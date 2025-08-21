// src/file_writer.rs

use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use wasm_bindgen_futures::{JsFuture, spawn_local};
use js_sys::{Object, Uint8Array};
use serde::Serialize;

use futures::{channel::mpsc, channel::oneshot, SinkExt, StreamExt};
use std::cell::{Cell, RefCell};
use web_sys::TextEncoder;

/// Bounded queue to protect memory if the producer outpaces disk/browser I/O.
const QUEUE_CAP_FRAMES: usize = 256;

/// Target batch size for each underlying write to reduce overhead (~256 KiB).
const BATCH_TARGET_BYTES: usize = 256 * 1024;

#[wasm_bindgen]
extern "C" {
    // File System Access API (Chromium-based browsers)
    #[wasm_bindgen(js_namespace = ["window"], js_name = showSaveFilePicker)]
    fn show_save_file_picker(options: JsValue) -> js_sys::Promise;

    type FileSystemFileHandle;
    #[wasm_bindgen(method, js_name = createWritable)]
    fn create_writable(this: &FileSystemFileHandle) -> js_sys::Promise;

    type FileSystemWritableFileStream;
    #[wasm_bindgen(method)]
    fn write(this: &FileSystemWritableFileStream, data: &JsValue) -> js_sys::Promise;
    #[wasm_bindgen(method)]
    fn close(this: &FileSystemWritableFileStream) -> js_sys::Promise;
}

pub struct SaveTarget {
    // Keep handle/sink as opaque JS objects; cast when used.
    handle: RefCell<Option<Object>>,  // FileSystemFileHandle
    sink:   RefCell<Option<Object>>,  // FileSystemWritableFileStream

    // True while recording (accepting frames).
    enabled: Cell<bool>,

    // Channel to the writer task (Vec<u8> are ready-to-write chunks).
    tx: RefCell<Option<mpsc::Sender<Vec<u8>>>>,

    // One-shot to signal writer completion (flush+close done).
    done_rx: RefCell<Option<oneshot::Receiver<()>>>,
}

impl Default for SaveTarget {
    fn default() -> Self {
        Self {
            handle: RefCell::new(None),
            sink: RefCell::new(None),
            enabled: Cell::new(false),
            tx: RefCell::new(None),
            done_rx: RefCell::new(None),
        }
    }
}

impl SaveTarget {
    pub fn new() -> Self { Self::default() }

    /// Open a file picker with a suggested name.
    pub async fn browse(&self, suggested_name: &str) -> Result<(), JsValue> {
        let opts = Object::new();
        js_sys::Reflect::set(&opts, &"suggestedName".into(), &suggested_name.into())?;
        let handle_val = JsFuture::from(show_save_file_picker(opts.into())).await?;
        *self.handle.borrow_mut() = Some(handle_val.unchecked_into());
        Ok(())
    }

    /// Create a writable stream and write the JSON header (+ newline).
    /// Also starts the background writer task that drains the queue.
    pub async fn start_with_header<T: Serialize>(&self, header: &T) -> Result<(), JsValue> {
        let handle: FileSystemFileHandle = self
            .handle
            .borrow()
            .as_ref()
            .ok_or_else(|| JsValue::from_str("No file chosen"))?
            .clone()
            .unchecked_into();

        let sink_val = JsFuture::from(handle.create_writable()).await?;
        let sink: FileSystemWritableFileStream = sink_val.unchecked_into();
        *self.sink.borrow_mut() = Some(sink.clone().unchecked_into());

        // Header = JSON + newline
        let json = serde_json::to_string(header).unwrap() + "\n";
        let enc = TextEncoder::new()?.encode_with_input(&json);
        JsFuture::from(sink.write(&Uint8Array::from(enc.as_ref()).into())).await?;

        // Channel for frames
        let (tx, mut rx) = mpsc::channel::<Vec<u8>>(QUEUE_CAP_FRAMES);
        *self.tx.borrow_mut() = Some(tx);
        self.enabled.set(true);

        // Completion signal
        let (done_tx, done_rx) = oneshot::channel::<()>();
        *self.done_rx.borrow_mut() = Some(done_rx);

        // Background writer: drain queue, batch, write, close, signal done.
        // Move `sink` into the task to avoid cloning/casting issues.
        spawn_local(async move {
            let mut pending: Vec<Vec<u8>> = Vec::new();
            let mut pending_bytes: usize = 0;

            async fn flush(
                sink: &FileSystemWritableFileStream,
                batch: &mut Vec<Vec<u8>>,
                bytes: &mut usize,
            ) -> Result<(), JsValue> {
                if batch.is_empty() { return Ok(()); }

                if batch.len() == 1 {
                    // Single buffer: zero-copy view into WASM memory; keep Vec alive until await completes.
                    let buf = &batch[0];
                    let view = unsafe { Uint8Array::view(buf.as_slice()) };
                    JsFuture::from(sink.write(&view.into())).await?;
                } else {
                    // Concatenate once, then single write.
                    let mut cat = Vec::with_capacity(*bytes);
                    for b in batch.iter() { cat.extend_from_slice(b); }
                    let view = unsafe { Uint8Array::view(cat.as_slice()) };
                    JsFuture::from(sink.write(&view.into())).await?;
                }
                batch.clear();
                *bytes = 0;
                Ok(())
            }

            while let Some(buf) = rx.next().await {
                pending_bytes += buf.len();
                pending.push(buf);

                if pending_bytes >= BATCH_TARGET_BYTES {
                    let _ = flush(&sink, &mut pending, &mut pending_bytes).await;
                }
            }

            // Final flush
            let _ = flush(&sink, &mut pending, &mut pending_bytes).await;

            // Close the file here so we know all writes are done.
            let _ = JsFuture::from(sink.close()).await;

            // Signal completion (ignore if receiver dropped)
            let _ = done_tx.send(());
        });

        Ok(())
    }

    /// Append one frame: [u32 LE length][f32 little-endian bytes].
    /// Fast path: enqueue bytes; writer task does the actual I/O.
    pub async fn write_frame(&self, frame: &[f32]) -> Result<(), JsValue> {
        self.enqueue_frame_as_v1(frame).await
    }

    /// v2 record: [u32 bins][f32*bins][u32 tail_len][tail_bytes]
    pub async fn write_frame_plus_footer(&self, frame: &[f32], footer: Option<&[u8]>) -> Result<(), JsValue> {
        self.enqueue_frame_as_v2(frame, footer).await
    }

    /// Stop recording: stop accepting frames, close the channel, wait for the writer
    /// to flush and close the file, then release our sink reference.
    pub async fn stop(&self) -> Result<(), JsValue> {
        // Stop accepting frames and drop the Sender to end the writer loop.
        self.enabled.set(false);
        self.tx.borrow_mut().take();

        // Wait for writer completion (flush+close).
        if let Some(rx) = self.done_rx.borrow_mut().take() {
            let _ = rx.await; // ignore error if task already finished/dropped
        }

        // Drop our sink handle (writer task already closed it).
        self.sink.borrow_mut().take();
        Ok(())
    }

    /// Expose enabled state for the UI.
    pub fn is_enabled(&self) -> bool { self.enabled.get() }

    // -------------------- internal helpers --------------------

    async fn enqueue_frame_as_v1(&self, frame: &[f32]) -> Result<(), JsValue> {
        let mut out = Vec::with_capacity(4 + frame.len() * 4);

        // length prefix (bins)
        let len = frame.len() as u32;
        out.extend_from_slice(&len.to_le_bytes());

        // floats (little-endian as bytes)
        let bytes: &[u8] = unsafe {
            core::slice::from_raw_parts(frame.as_ptr() as *const u8, frame.len() * 4)
        };
        out.extend_from_slice(bytes);

        self.enqueue_bytes(out).await
    }

    async fn enqueue_frame_as_v2(&self, frame: &[f32], footer: Option<&[u8]>) -> Result<(), JsValue> {
        let bins = frame.len() as u32;
        let tail_len: u32 = footer.map(|f| f.len() as u32).unwrap_or(0);
        let floats_bytes_len = frame.len() * 4;
        let total = 4 /*bins*/ + floats_bytes_len + 4 /*tail_len*/ + tail_len as usize;

        let mut out = Vec::with_capacity(total);

        // 1) bins
        out.extend_from_slice(&bins.to_le_bytes());

        // 2) floats
        let bytes: &[u8] = unsafe {
            core::slice::from_raw_parts(frame.as_ptr() as *const u8, floats_bytes_len)
        };
        out.extend_from_slice(bytes);

        // 3) footer length
        out.extend_from_slice(&tail_len.to_le_bytes());

        // 4) footer bytes (if any)
        if let Some(f) = footer { out.extend_from_slice(f); }

        self.enqueue_bytes(out).await
    }

    async fn enqueue_bytes(&self, buf: Vec<u8>) -> Result<(), JsValue> {
        if !self.enabled.get() { return Ok(()); }

        // Clone the Sender so we don't hold a RefCell borrow across an await.
        let sender_opt = self.tx.borrow().as_ref().cloned();
        let mut sender = match sender_opt {
            Some(s) => s,
            None => return Err(JsValue::from_str("Writer not started")),
        };

        // Try non-blocking first
        match sender.try_send(buf) {
            Ok(_) => Ok(()),
            Err(e) => {
                // futures::channel::mpsc::TrySendError is a struct (not enum variants in this version)
                let is_full = e.is_full();
                let buf = e.into_inner();
                if is_full {
                    // Queue is full -> backpressure by awaiting room.
                    sender
                        .send(buf)
                        .await
                        .map_err(|_| JsValue::from_str("Writer channel closed"))
                } else {
                    // Closed
                    Err(JsValue::from_str("Writer channel closed"))
                }
            }
        }
    }
}
