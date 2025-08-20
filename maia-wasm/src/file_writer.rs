// src/file_writer.rs
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use wasm_bindgen_futures::JsFuture;
use js_sys::{Object, Uint8Array};
use serde::Serialize;

// Serialize writes across tasks
use futures::lock::Mutex;
use std::cell::{Cell, RefCell};
use std::sync::Arc;

#[wasm_bindgen]
extern "C" {
    // File System Access API (Chromium)
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
    // Interior mutability so methods can take &self
    handle: RefCell<Option<js_sys::Object>>,  // FileSystemFileHandle
    sink:   RefCell<Option<js_sys::Object>>,  // FileSystemWritableFileStream
    enabled: Cell<bool>,                      // true while recording
    // Serialize all writes
    write_lock: Arc<Mutex<()>>,
}

impl Default for SaveTarget {
    fn default() -> Self {
        Self {
            handle: RefCell::new(None),
            sink: RefCell::new(None),
            enabled: Cell::new(false),
            write_lock: Arc::new(Mutex::new(())),
        }
    }
}

impl SaveTarget {
    pub fn new() -> Self { Self::default() }

    /// Open a file picker with a suggested name.
    pub async fn browse(&self, suggested_name: &str) -> Result<(), JsValue> {
        let o = Object::new();
        js_sys::Reflect::set(&o, &"suggestedName".into(), &suggested_name.into())?;
        let handle_val = JsFuture::from(show_save_file_picker(o.into())).await?;
        *self.handle.borrow_mut() = Some(handle_val.unchecked_into());
        Ok(())
    }

    /// Create a writable stream and write the JSON header (+ newline).
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
        let enc = web_sys::TextEncoder::new()?.encode_with_input(&json);

        let _g = self.write_lock.lock().await;
        JsFuture::from(sink.write(&Uint8Array::from(enc.as_ref()).into())).await?;
        self.enabled.set(true);
        Ok(())
    }

    /// Append one frame: [u32 LE length][f32 little-endian bytes]
    pub async fn write_frame(&self, frame: &[f32]) -> Result<(), JsValue> {
        if !self.enabled.get() { return Ok(()); }
        let sink: FileSystemWritableFileStream = self
            .sink
            .borrow()
            .as_ref()
            .ok_or_else(|| JsValue::from_str("Sink not open"))?
            .clone()
            .unchecked_into();

        // Build a single buffer for atomic-ish write
        let mut buf = Vec::with_capacity(4 + frame.len() * 4);

        // length prefix
        let len = frame.len() as u32;
        buf.extend_from_slice(&len.to_le_bytes());

        // floats (little-endian as bytes)
        let bytes: &[u8] = unsafe {
            core::slice::from_raw_parts(frame.as_ptr() as *const u8, frame.len() * 4)
        };
        buf.extend_from_slice(bytes);

        let _g = self.write_lock.lock().await;
        JsFuture::from(sink.write(&Uint8Array::from(buf.as_slice()).into())).await?;
        Ok(())
    }

    /// v2 record: [u32 bins][f32*bins][u32 tail_len][tail_bytes]
    pub async fn write_frame_plus_footer(&self, frame: &[f32], footer: Option<&[u8]>) -> Result<(), JsValue> {
        if !self.enabled.get() { return Ok(()); }
        let sink: FileSystemWritableFileStream = self
            .sink
            .borrow()
            .as_ref()
            .ok_or_else(|| JsValue::from_str("Sink not open"))?
            .clone()
            .unchecked_into();

        let bins = frame.len() as u32;
        let tail_len: u32 = footer.map(|f| f.len() as u32).unwrap_or(0);
        let floats_bytes_len = frame.len() * 4;

        let total = 4 /*bins*/ + floats_bytes_len + 4 /*tail_len*/ + tail_len as usize;
        let mut buf = Vec::with_capacity(total);

        // 1) bins
        buf.extend_from_slice(&bins.to_le_bytes());

        // 2) floats
        let bytes: &[u8] = unsafe {
            core::slice::from_raw_parts(frame.as_ptr() as *const u8, floats_bytes_len)
        };
        buf.extend_from_slice(bytes);

        // 3) footer length
        buf.extend_from_slice(&tail_len.to_le_bytes());

        // 4) footer bytes (if any)
        if let Some(f) = footer {
            buf.extend_from_slice(f);
        }

        let _g = self.write_lock.lock().await;
        JsFuture::from(sink.write(&Uint8Array::from(buf.as_slice()).into())).await?;
        Ok(())
    }

    /// Close the stream (non-consuming). Safe even if called when not open.
    pub async fn stop(&self) -> Result<(), JsValue> {
        // Ensure no writes are in-flight before closing
        let _g = self.write_lock.lock().await;

        if let Some(sink_obj) = self.sink.borrow_mut().take() {
            let sink: FileSystemWritableFileStream = sink_obj.unchecked_into();
            let _ = JsFuture::from(sink.close()).await?;
        }
        self.enabled.set(false);
        Ok(())
    }

    /// Expose enabled state for the UI.
    pub fn is_enabled(&self) -> bool { self.enabled.get() }
}
