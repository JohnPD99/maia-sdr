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
            // Open TTY (read-only is enough for NMEA)
            let file = match std::fs::OpenOptions::new().read(true).open(&path) {
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

// --- Minimal NMEA parsing (GGA + GLL) ---------------------------------------

fn parse_nmea(s: &str) -> Option<GpsFix> {
    if !s.starts_with('$') {
        return None;
    }
    let core = s.trim_end().trim_start_matches('$');
    let payload = core.split('*').next()?; // ignore checksum
    let fields: Vec<&str> = payload.split(',').collect();
    if fields.is_empty() {
        return None;
    }
    let msg = fields[0];
    if msg.len() < 5 {
        return None;
    }
    match &msg[2..] {
        "GGA" => parse_gga(&fields),
        "GLL" => parse_gll(&fields),
        _ => None,
    }
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

fn parse_gll(f: &[&str]) -> Option<GpsFix> {
    // $..GLL,lat,N,lon,E,UTC,status[,FAA]
    if f.len() < 7 {
        return None;
    }
    let (lat, lon) = parse_lat_lon(*f.get(1)?, *f.get(2)?, *f.get(3)?, *f.get(4)?)?;
    let status = *f.get(6)?;
    Some(GpsFix {
        lat_e7: (lat * 1e7).round() as i32,
        lon_e7: (lon * 1e7).round() as i32,
        alt_mm: 0,
        valid: status == "A",
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
