//! WebSocket client for waterfall data (+ optional 32-byte telemetry footer).

use std::cell::RefCell;
use std::rc::Rc;
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use wasm_bindgen::closure::Closure;
use web_sys::{CloseEvent, MessageEvent, WebSocket, Window};

use crate::waterfall::Waterfall;
use crate::ui::Ui;
use wasm_bindgen_futures::spawn_local;

/// WebSocket client for waterfall data.
///
/// Receives binary frames:
/// - Legacy: 4096 * 4 bytes (Float32Array) — spectrum only
/// - New:    4096 * 4 + 32 bytes          — spectrum + telemetry footer
pub struct WebSocketClient {}

struct WebSocketData {
    url: String,
    // Closure that handles onmessage
    onmessage: JsValue,
    // Closure that handles onclose. It is inside a RefCell<Option<>> because
    // the closure is self-referential, in the sense that to try a reconnection,
    // the onclose closure needs access to the onclose closure, in order to
    // assign it to the onclose of the new websocket.
    onclose: RefCell<Option<JsValue>>,
}

impl WebSocketClient {
    /// Starts the WebSocket client.
    ///
    /// The client is given shared mutable access to the [`Waterfall`].
    /// `ui` is used for telemetry overlay and recording.
    pub fn start(
        window: &Window,
        waterfall: Rc<RefCell<Waterfall>>,
        ui: Ui,
    ) -> Result<(), JsValue> {
        let location = window.location();
        let protocol = if location.protocol()? == "https:" { "wss" } else { "ws" };
        let hostname = location.hostname()?;
        let port = location.port()?;

        let url = if port.is_empty() {
            format!("{protocol}://{hostname}/waterfall")
        } else {
            format!("{protocol}://{hostname}:{port}/waterfall")
        };
        let data = Rc::new(WebSocketData {
            url,
            onmessage: onmessage(waterfall, ui).into_js_value(),
            onclose: RefCell::new(None),
        });
        data.setup_onclose();
        // initiate first connection
        data.connect()?;
        Ok(())
    }
}

fn onmessage(
    waterfall: Rc<RefCell<Waterfall>>,
    ui: Ui,
) -> Closure<dyn Fn(MessageEvent)> {
    Closure::new(move |event: MessageEvent| {
        // Expect an ArrayBuffer
        let abuf = match event.data().dyn_into::<js_sys::ArrayBuffer>() {
            Ok(x) => x,
            Err(e) => {
                web_sys::console::error_1(&e);
                return;
            }
        };

        // Layout:
        // - first 4096 f32 => spectrum
        // - optional last 32 bytes => telemetry footer
        const BINS: usize = 4096;
        const BYTES_BINS: usize = BINS * 4;
        const FOOTER: usize = 32;

        let total = abuf.byte_length() as usize;
        if total != BYTES_BINS && total != BYTES_BINS + FOOTER {
            web_sys::console::warn_1(
                &format!(
                    "unexpected WS frame size: {} (expected {} or {})",
                    total, BYTES_BINS, BYTES_BINS + FOOTER
                ).into()
            );
            return;
        }

        // ----- Extract optional footer bytes up-front -----
        let has_footer = total == BYTES_BINS + FOOTER;
        let footer_opt: Option<Vec<u8>> = if has_footer {
            let u8_view = js_sys::Uint8Array::new(&abuf)
                .subarray(BYTES_BINS as u32, (BYTES_BINS + FOOTER) as u32);
            Some(u8_view.to_vec())
        } else {
            None
        };

        // Spectrum view: first 4096 floats
        let f32_view = js_sys::Float32Array::new(&abuf).subarray(0, BINS as u32);
        waterfall.borrow_mut().put_waterfall_spectrum(&f32_view);

        // If recording is enabled, append this frame to disk (non-blocking)
        if ui.is_recording_enabled() {
            // Copy out of the JS view
            let mut frame = vec![0f32; BINS];
            f32_view.copy_to(&mut frame[..]);

            // Move data into the async task
            let footer_for_write = footer_opt.clone();
            let saver = ui.saver(); // Rc<SaveTarget>

            spawn_local(async move {
                if let Err(e) = saver
                    .write_frame_plus_footer(&frame, footer_for_write.as_deref())
                    .await
                {
                    web_sys::console::error_1(&e);
                }
            });
        }

        // Apply telemetry overlay to UI (if present)
        if let Some(ref footer) = footer_opt {
            ui.apply_telemetry_footer(footer);
        }
    })
}

impl WebSocketData {
    fn connect(&self) -> Result<(), JsValue> {
        let ws = WebSocket::new(&self.url)?;
        ws.set_binary_type(web_sys::BinaryType::Arraybuffer);
        ws.set_onmessage(Some(self.onmessage.unchecked_ref()));
        // by this point onclose shouldn't be None
        ws.set_onclose(Some(
            self.onclose.borrow().as_ref().unwrap().unchecked_ref(),
        ));
        Ok(())
    }

    fn setup_onclose(self: &Rc<Self>) {
        let data = Rc::clone(self);
        let closure = Closure::<dyn Fn(CloseEvent)>::new(move |_: CloseEvent| {
            // Simple reconnect loop; consider adding backoff if desired
            if let Err(e) = data.connect() {
                web_sys::console::error_1(&e);
            }
        });
        *self.onclose.borrow_mut() = Some(closure.into_js_value());
    }
}
