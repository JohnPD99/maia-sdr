// src/file_writer.rs
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use wasm_bindgen_futures::JsFuture;
use js_sys::{Object, Uint8Array};
use serde::Serialize;

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

#[derive(Default)]
pub struct SaveTarget {
    handle: Option<js_sys::Object>,  // FileSystemFileHandle
    sink:   Option<js_sys::Object>,  // FileSystemWritableFileStream
    pub enabled: bool,               // true while recording
}

impl SaveTarget {
    pub fn new() -> Self { Self::default() }

    pub async fn browse(&mut self, suggested_name: &str) -> Result<(), JsValue> {
        let o = Object::new();
        js_sys::Reflect::set(&o, &"suggestedName".into(), &suggested_name.into())?;
        let handle_val = JsFuture::from(show_save_file_picker(o.into())).await?;
        self.handle = Some(handle_val.unchecked_into());
        Ok(())
    }

    pub async fn start_with_header<T: Serialize>(&mut self, header: &T) -> Result<(), JsValue> {
        let handle: FileSystemFileHandle = self.handle.as_ref()
            .ok_or_else(|| JsValue::from_str("No file chosen"))?
            .clone().unchecked_into();

        let sink_val = JsFuture::from(handle.create_writable()).await?;
        let sink: FileSystemWritableFileStream = sink_val.unchecked_into();
        self.sink = Some(sink.clone().unchecked_into());

        // Header = JSON + newline
        let json = serde_json::to_string(header).unwrap() + "\n";
        let enc = web_sys::TextEncoder::new()?.encode_with_input(&json);
        JsFuture::from(sink.write(&Uint8Array::from(enc.as_ref()).into())).await?;

        self.enabled = true;
        Ok(())
    }

    /// Append one frame: [u32 LE length][f32 little-endian bytes]
    pub async fn write_frame(&self, frame: &[f32]) -> Result<(), JsValue> {
        if !self.enabled { return Ok(()); }
        let sink: FileSystemWritableFileStream = self.sink.as_ref()
            .ok_or_else(|| JsValue::from_str("Sink not open"))?
            .clone().unchecked_into();

        let len = frame.len() as u32;
        let mut prefix = [0u8; 4];
        prefix.copy_from_slice(&len.to_le_bytes());
        JsFuture::from(sink.write(&Uint8Array::from(prefix.as_slice()).into())).await?;

        let bytes: &[u8] = unsafe { core::slice::from_raw_parts(frame.as_ptr() as *const u8, frame.len()*4) };
        JsFuture::from(sink.write(&Uint8Array::from(bytes).into())).await?;
        Ok(())
    }

    pub async fn stop(mut self) -> Result<(), JsValue> {
        if let Some(sink_obj) = self.sink.take() {
            let sink: FileSystemWritableFileStream = sink_obj.unchecked_into();
            let _ = JsFuture::from(sink.close()).await?;
        }
        Ok(())
    }

     /// Expose enabled state via Ui
    pub fn is_enabled(&self) -> bool { self.enabled }

    /// Clone the writable stream object so callers can write without borrowing `self`.
    pub fn clone_sink_object(&self) -> Option<js_sys::Object> {
        self.sink.clone()
    }

    /// Write a frame given a writable sink object (no RefCell involved).
    pub async fn write_frame_with_sink(
        sink_obj: js_sys::Object,
        frame: &[f32],
    ) -> Result<(), JsValue> {
        // SAFETY: same as your write_frame()
        let sink: FileSystemWritableFileStream = sink_obj.unchecked_into();

        let len = frame.len() as u32;
        let mut prefix = [0u8; 4];
        prefix.copy_from_slice(&len.to_le_bytes());
        JsFuture::from(sink.write(&Uint8Array::from(prefix.as_slice()).into())).await?;

        let bytes: &[u8] = unsafe {
            core::slice::from_raw_parts(frame.as_ptr() as *const u8, frame.len() * 4)
        };
        JsFuture::from(sink.write(&Uint8Array::from(bytes).into())).await?;
        Ok(())
    }
}