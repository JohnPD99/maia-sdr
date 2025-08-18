//! NEO-M8 NMEA reader on a serial TTY (e.g. `/dev/ttyPS0`).
//!
//! Spawns a blocking thread via `tokio::task::spawn_blocking` that:
//!   * Opens the TTY
//!   * Puts it into raw mode with the requested baud
//!   * Reads NMEA lines and parses minimal `GGA`/`GLL`
//! Latest fix is stored in an `Arc<RwLock<...>>` and can be snapshotted quickly
//! from async code with [`NeoM8Reader::snapshot`].

use std::{
    io::{BufRead, BufReader},
    os::fd::AsRawFd,
    sync::{Arc, RwLock},
    time::Duration,
};

#[derive(Debug, Clone, Copy, Default)]
pub struct GpsFix {
    pub lat_e7: i32, // degrees * 1e7
    pub lon_e7: i32, // degrees * 1e7
    pub alt_mm: i32, // millimeters (MSL from GGA)
    pub valid: bool, // true if fix is valid ("A" in GLL, quality>=1 in GGA)
}

#[derive(Clone, Default)]
pub struct NeoM8Reader {
    shared: Arc<RwLock<GpsFix>>,
}

impl NeoM8Reader {
    pub fn new() -> Self {
        Self::default()
    }

    /// Start the background reader on Tokio’s blocking pool.
    ///
    /// This function never blocks the caller; it continuously reconnects on errors.
    pub fn spawn(&self, tty_path: &str, baud: u32) {
        let shared = self.shared.clone();
        let path = tty_path.to_string();

        tokio::task::spawn_blocking(move || loop {
            // Open TTY (need write to send UBX config)
            let file = match std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
            {
                Ok(f) => f,
                Err(e) => {
                    tracing::warn!("NEO-M8: open {path}: {e}");
                    std::thread::sleep(Duration::from_secs(2));
                    continue;
                }
            };


            // Configure raw 8N1 at the requested baud
            if let Err(e) = set_serial_raw(file.as_raw_fd(), baud) {
                tracing::warn!("NEO-M8: termios failed: {e}");
            }

            // Configure module for 10 Hz, GGA-only (ignore errors; we'll still try to read)
            if let Err(e) = configure_m8_to_10hz_gga_only(&file) {
                tracing::warn!("NEO-M8: UBX config failed: {e}");
            }
            // Give the module a brief moment to apply settings
            std::thread::sleep(Duration::from_millis(100));

            // Read lines until EOF / error, then reopen
            let mut reader = BufReader::new(file);
            let mut line = String::new();
            loop {
                line.clear();
                match reader.read_line(&mut line) {
                    Ok(0) => break, // EOF
                    Ok(_) => {
                        if let Some(fix) = parse_nmea(&line) {
                            if let Ok(mut w) = shared.write() {
                                *w = fix;
                            }
                        }
                    }
                    Err(e) => {
                        tracing::warn!("NEO-M8: read error: {e}");
                        break;
                    }
                }
            }

            // Backoff before retry
            std::thread::sleep(Duration::from_millis(500));
        });
    }

    /// Fetch a copy of the last known fix (non-blocking fast path).
    pub fn snapshot(&self) -> GpsFix {
        *self.shared.read().unwrap_or_else(|e| e.into_inner())
    }
}

// --- Serial raw config (termios) ---------------------------------------------

fn set_serial_raw(fd: std::os::fd::RawFd, baud: u32) -> std::io::Result<()> {
    unsafe {
        let mut t: libc::termios = std::mem::zeroed();
        if libc::tcgetattr(fd, &mut t) != 0 {
            return Err(std::io::Error::last_os_error());
        }

        // Raw 8N1
        t.c_iflag = 0;
        t.c_oflag = 0;
        t.c_lflag = 0;
        t.c_cflag |= libc::CREAD | libc::CLOCAL;
        t.c_cflag &= !(libc::PARENB | libc::CSTOPB | libc::CSIZE);
        t.c_cflag |= libc::CS8;

        // Blocking reads, return on every byte
        t.c_cc[libc::VMIN as usize] = 1;
        t.c_cc[libc::VTIME as usize] = 0;

        // Baud rate
        let speed = match baud {
            9600 => libc::B9600,
            19200 => libc::B19200,
            38400 => libc::B38400,
            57600 => libc::B57600,
            115200 => libc::B115200,
            _ => libc::B9600,
        };
        if libc::cfsetispeed(&mut t, speed) != 0 {
            return Err(std::io::Error::last_os_error());
        }
        if libc::cfsetospeed(&mut t, speed) != 0 {
            return Err(std::io::Error::last_os_error());
        }

        if libc::tcsetattr(fd, libc::TCSANOW, &t) != 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(())
}

// --- Minimal NMEA parsing (GGA) ---------------------------------------

fn parse_nmea(s: &str) -> Option<GpsFix> {
    if !s.starts_with('$') {
        return None;
    }
    // Fast pre-filter: "$xxGGA,..."
    if s.as_bytes().get(3..6) != Some(b"GGA") {
        return None;
    }

    let core = s.trim_end().trim_start_matches('$');
    let payload = core.split('*').next()?; // ignore checksum for now
    let fields: Vec<&str> = payload.split(',').collect();
    if fields.len() < 10 { // $..GGA,UTC,lat,N,lon,E,quality,nsat,hdop,alt,M,...
        return None;
    }
    parse_gga(&fields)
}


fn parse_gga(f: &[&str]) -> Option<GpsFix> {
    // $..GGA,UTC,lat,N,lon,E,quality,nsat,hdop,alt,M,...
    if f.len() < 10 {
        return None;
    }
    let quality = f.get(6)?.parse::<u8>().ok()?;
    let (lat, lon) = parse_lat_lon(*f.get(2)?, *f.get(3)?, *f.get(4)?, *f.get(5)?)?;
    let alt_m = f.get(9)?.parse::<f32>().ok()?;

    Some(GpsFix {
        lat_e7: (lat * 1e7).round() as i32,
        lon_e7: (lon * 1e7).round() as i32,
        alt_mm: (alt_m * 1000.0).round() as i32,
        valid: quality >= 1,
    })
}

fn parse_lat_lon(lat: &str, ns: &str, lon: &str, ew: &str) -> Option<(f64, f64)> {
    let lat = ddmm_to_deg(lat)? * if ns == "S" { -1.0 } else { 1.0 };
    let lon = ddmm_to_deg(lon)? * if ew == "W" { -1.0 } else { 1.0 };
    Some((lat, lon))
}

fn ddmm_to_deg(s: &str) -> Option<f64> {
    // ddmm.mmmm (lat) or dddmm.mmmm (lon)
    let v: f64 = s.parse().ok()?;
    let deg = (v / 100.0).floor();
    let min = v - deg * 100.0;
    Some(deg + min / 60.0)
}

fn ubx_checksum(data: &[u8]) -> (u8, u8) {
    let mut ck_a: u8 = 0;
    let mut ck_b: u8 = 0;
    for &b in data {
        ck_a = ck_a.wrapping_add(b);
        ck_b = ck_b.wrapping_add(ck_a);
    }
    (ck_a, ck_b)
}

fn ubx_packet(class: u8, id: u8, payload: &[u8]) -> Vec<u8> {
    let len = payload.len() as u16;
    let mut body = vec![class, id, (len & 0xFF) as u8, (len >> 8) as u8];
    body.extend_from_slice(payload);
    let (a, b) = ubx_checksum(&body);
    let mut pkt = vec![0xB5, 0x62];
    pkt.extend_from_slice(&body);
    pkt.push(a);
    pkt.push(b);
    pkt
}

/// Send UBX to set 10 Hz navigation and GGA-only on UART1.
/// Safe to call after termios; idempotent across reconnects.
fn configure_m8_to_10hz_gga_only(file: &std::fs::File) -> std::io::Result<()> {
    use std::io::Write;
    let mut w = std::io::BufWriter::new(file);

    // 1) CFG-RATE: measRate=100 ms (10 Hz), navRate=1, timeRef=GPS(1)
    let cfg_rate = ubx_packet(0x06, 0x08, &[0x64, 0x00, 0x01, 0x00, 0x01, 0x00]);

    // 2) Enable NMEA-GxGGA on UART1: rateUART1 = 1
    //    Payload (u-blox 8): [msgClass, msgId, rateUSB, rateUART1, rateUART2, rateSPI, rateI2C, rateReserved]
    let cfg_msg_gga = ubx_packet(0x06, 0x01, &[0xF0, 0x00, 0, 1, 0, 0, 0, 0]);

    // 3) Disable common NMEA sentences on UART1 (set UART1 rate to 0)
    let off = |id: u8| ubx_packet(0x06, 0x01, &[0xF0, id, 0, 0, 0, 0, 0, 0]);
    let cfg_msg_gll_off = off(0x01);
    let cfg_msg_gsa_off = off(0x02);
    let cfg_msg_gsv_off = off(0x03);
    let cfg_msg_rmc_off = off(0x04);
    let cfg_msg_vtg_off = off(0x05);

    // Write with tiny pacing
    for pkt in [
        &cfg_rate,
        &cfg_msg_gga,
        &cfg_msg_gll_off,
        &cfg_msg_gsa_off,
        &cfg_msg_gsv_off,
        &cfg_msg_rmc_off,
        &cfg_msg_vtg_off,
    ] {
        w.write_all(pkt)?;
        w.flush()?;
        std::thread::sleep(std::time::Duration::from_millis(40));
    }

    Ok(())
}
