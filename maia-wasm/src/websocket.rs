//! WebSocket client for waterfall data (+ optional 32-byte telemetry footer).

use std::cell::RefCell;
use std::rc::Rc;
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use wasm_bindgen::closure::Closure;
use web_sys::{CloseEvent, MessageEvent, WebSocket, Window};

use crate::waterfall::Waterfall;
use crate::ui::Ui; // <-- added

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
    /// `ui` is used to apply an optional 32-byte telemetry footer overlay.
    pub fn start(
        window: &Window,
        waterfall: Rc<RefCell<Waterfall>>,
        ui: Ui, // <-- added
    ) -> Result<(), JsValue> {
        let location = window.location();
        let protocol = if location.protocol()? == "https:" { "wss" } else { "ws" };
        let hostname = location.hostname()?;
        let port = location.port()?;
        let data = Rc::new(WebSocketData {
            url: format!("{protocol}://{hostname}:{port}/waterfall"),
            onmessage: onmessage(waterfall, ui).into_js_value(), // <-- pass ui
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
    ui: Ui, // <-- added
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
                &format!("unexpected WS frame size: {} (expected {} or {})",
                         total, BYTES_BINS, BYTES_BINS + FOOTER).into()
            );
            return;
        }

        // Spectrum view: first 4096 floats
        let f32_view = js_sys::Float32Array::new(&abuf).subarray(0, BINS as u32);
        waterfall.borrow_mut().put_waterfall_spectrum(&f32_view);

        // Optional 32-byte footer: last bytes
        if total == BYTES_BINS + FOOTER {
            let u8_view = js_sys::Uint8Array::new(&abuf)
                .subarray(BYTES_BINS as u32, (BYTES_BINS + FOOTER) as u32);
            let mut footer = [0u8; FOOTER];
            u8_view.copy_to(&mut footer);
            ui.apply_telemetry_footer(&footer);
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
            data.connect().unwrap();
        });
        *self.onclose.borrow_mut() = Some(closure.into_js_value());
    }
}
