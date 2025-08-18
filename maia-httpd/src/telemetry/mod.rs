//! Telemetry aggregation and 32-byte footer packing.
//! Hot path (websocket) remains async & non-blocking; we only snapshot locks.

mod neom8;
mod adt7422;

pub use neom8::{NeoM8Reader, GpsFix};
pub use adt7422::{Adt7422Reader, Temps};

use bytes::BufMut;

/// Binary footer (little-endian), appended after 4096 f32 bins:
/// [0..3]   b"TLM1"
/// [4]      version = 1
/// [5]      flags: bit0=gps.valid, bit1=temps.valid
/// [6..7]   reserved = 0
/// [8..9]   t0_c_centi (i16)
/// [10..11] t1_c_centi (i16)
/// [12..15] lat_e7 (i32)
/// [16..19] lon_e7 (i32)
/// [20..23] alt_mm (i32)
/// [24..31] unix_ms (i64)
pub const FOOTER_SIZE: usize = 32;

#[derive(Clone)]
pub struct Telemetry {
    gps: NeoM8Reader,
    temps: Adt7422Reader,
}

impl core::fmt::Debug for Telemetry {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("Telemetry").finish()
    }
}


impl Telemetry {
    pub fn new() -> Self {
        Self {
            gps: NeoM8Reader::new(),
            temps: Adt7422Reader::new(),
        }
    }

    /// Start background readers on Tokio’s blocking pool.
    pub fn spawn_inputs(
        &self,
        gps_tty: &str,   // e.g. "/dev/ttyPS0"
        gps_baud: u32,   // e.g. 9600 / 38400
        i2c_path: &str,  // e.g. "/dev/i2c-1"
        addr0: u16,      // 0x48
        addr1: u16,      // 0x49
        temp_poll_ms: u64,    // e.g. 20
    ) {
        self.gps.spawn(gps_tty, gps_baud);
        self.temps.spawn(i2c_path, addr0, addr1, temp_poll_ms);
    }

    /// Build the 32-byte footer from the latest samples.
    pub fn footer_bytes(&self) -> [u8; FOOTER_SIZE] {
        let gps = self.gps.snapshot();
        let tp = self.temps.snapshot();

        let flags = (gps.valid as u8) | ((tp.valid as u8) << 1);
        let unix_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as i64;

        let mut out = [0u8; FOOTER_SIZE];
        {
            // &mut [u8] implements BufMut; write fields in little-endian
            let mut w = &mut out[..];
            w.put_slice(b"TLM1");         // magic
            w.put_u8(1);                  // version
            w.put_u8(flags);              // flags
            w.put_u16_le(0);              // reserved
            w.put_i16_le(tp.t0_c_centi);  // temp0 (centi °C)
            w.put_i16_le(tp.t1_c_centi);  // temp1 (centi °C)
            w.put_i32_le(gps.lat_e7);     // latitude * 1e7
            w.put_i32_le(gps.lon_e7);     // longitude * 1e7
            w.put_i32_le(gps.alt_mm);     // altitude mm
            w.put_i64_le(unix_ms);        // unix ms
        }
        out
    }
}
