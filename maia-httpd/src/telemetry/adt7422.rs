//! Two ADT7422 sensors on one I²C bus (e.g. /dev/i2c-1 at 0x48 and 0x49).
//!
//! - We set 16-bit resolution once per device (config reg 0x03, bit7 = 1).
//! - Then we poll both sensors on a background blocking thread per sensor.
//! - The current readings live in an `Arc<RwLock<Temps>>` and `snapshot()` is
//!   just a read lock (non-blocking on the async runtime).
//!
//! NOTE: ADT7422 conversion time in 16-bit mode is ~240 ms typical. Polling
//! faster (e.g. 20 ms) will usually return the same code until the next
//! conversion completes. If you truly need <100 ms update rates, consider
//! 13-bit mode (bit7 = 0), which is ~60 ms typical, at the expense of
//! resolution.

use std::{
    fs::OpenOptions,
    os::fd::{AsRawFd, RawFd},
    sync::{Arc, RwLock},
    thread,
    time::Duration,
};

#[derive(Debug, Clone, Copy, Default)]
pub struct Temps {
    /// Temperature from sensor at `addr0` (e.g. 0x48), in centi-°C.
    pub t0_c_centi: i16,
    /// Temperature from sensor at `addr1` (e.g. 0x49), in centi-°C.
    pub t1_c_centi: i16,
    /// `true` once at least one successful read has occurred.
    pub valid: bool,
}

#[derive(Clone, Default)]
pub struct Adt7422Reader {
    shared: Arc<RwLock<Temps>>,
}

impl Adt7422Reader {
    pub fn new() -> Self {
        Self::default()
    }

    /// Spawn two background polling loops (one per I²C address).
    ///
    /// `i2c_path` like `/dev/i2c-1`, `addr0`/`addr1` like `0x48/0x49`,
    /// `poll_ms` is the sleep between read attempts.
    pub fn spawn(&self, i2c_path: &str, addr0: u16, addr1: u16, poll_ms: u64) {
        let shared0 = self.shared.clone();
        let path0 = i2c_path.to_string();
        tokio::task::spawn_blocking(move || poll_loop(&path0, addr0, 0, shared0, poll_ms));

        let shared1 = self.shared.clone();
        let path1 = i2c_path.to_string();
        tokio::task::spawn_blocking(move || poll_loop(&path1, addr1, 1, shared1, poll_ms));
    }

    /// Snapshot the latest values (lock-poison safe).
    pub fn snapshot(&self) -> Temps {
        match self.shared.read() {
            Ok(g) => *g,
            Err(e) => *e.into_inner(), // recover if lock is poisoned
        }
    }
}

fn poll_loop(path: &str, addr: u16, index: usize, shared: Arc<RwLock<Temps>>, poll_ms: u64) {
    loop {
        // Open the I²C character device; keep it open until an error occurs.
        let file = match OpenOptions::new().read(true).write(true).open(path) {
            Ok(f) => f,
            Err(e) => {
                tracing::warn!("ADT7422 open {path}: {e}");
                thread::sleep(Duration::from_secs(1));
                continue;
            }
        };
        let fd = file.as_raw_fd();

        // Configure 16-bit resolution (config reg 0x03, bit7 = 1). Best-effort.
        let _ = i2c_write(fd, addr, &[0x03, 0x80]);

        // Inner read loop: read current temperature, publish, sleep.
        loop {
            match read_adt7422_centi(fd, addr) {
                Ok(cdeg) => {
                    let mut w = shared.write().expect("Temps lock poisoned");
                    if index == 0 {
                        w.t0_c_centi = cdeg;
                    } else {
                        w.t1_c_centi = cdeg;
                    }
                    w.valid = true;
                }
                Err(e) => {
                    tracing::warn!("ADT7422 read addr 0x{addr:02x}: {e}");
                    break; // reopen the device
                }
            }
            thread::sleep(Duration::from_millis(poll_ms));
        }

        // Backoff a little before trying to reopen.
        thread::sleep(Duration::from_millis(200));
    }
}

// --- I²C helpers via I2C_RDWR ioctl -----------------------------------------

const I2C_RDWR: u64 = 0x0707;
const I2C_M_RD: u16 = 0x0001;

#[repr(C)]
struct I2cMsg {
    addr: u16,
    flags: u16,
    len: u16,
    buf: *mut u8,
}

#[repr(C)]
struct I2cRdwrIoctlData {
    msgs: *mut I2cMsg,
    nmsgs: u32,
}

fn i2c_write(fd: RawFd, addr: u16, wr: &[u8]) -> std::io::Result<()> {
    unsafe {
        let mut m = I2cMsg {
            addr,
            flags: 0,
            len: wr.len() as u16,
            buf: wr.as_ptr() as *mut u8,
        };
        let mut data = I2cRdwrIoctlData {
            msgs: &mut m,
            nmsgs: 1,
        };
        let r = libc::ioctl(fd, I2C_RDWR as _, &mut data);
        if r < 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(())
}

fn i2c_write_read(fd: RawFd, addr: u16, wr: &[u8], rd: &mut [u8]) -> std::io::Result<()> {
    unsafe {
        let w = I2cMsg {
            addr,
            flags: 0,
            len: wr.len() as u16,
            buf: wr.as_ptr() as *mut u8,
        };
        let r = I2cMsg {
            addr,
            flags: I2C_M_RD,
            len: rd.len() as u16,
            buf: rd.as_mut_ptr(),
        };
        let mut msgs = [w, r];
        let mut data = I2cRdwrIoctlData {
            msgs: msgs.as_mut_ptr(),
            nmsgs: 2,
        };
        let rc = libc::ioctl(fd, I2C_RDWR as _, &mut data);
        if rc < 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(())
}

/// One temperature read; returns centi-°C (i16).
///
/// ADT7422 temperature register at 0x00/0x01 is big-endian 16-bit. In 16-bit
/// mode (cfg bit7=1), the LSB weight is 1/128 °C. We convert to centi-°C.
fn read_adt7422_centi(fd: RawFd, addr: u16) -> std::io::Result<i16> {
    let mut buf = [0u8; 2];
    // Register pointer 0x00 (MSB). Auto-increment fetches MSB+LSB.
    i2c_write_read(fd, addr, &[0x00], &mut buf)?;

    let raw = i16::from_be_bytes(buf); // sign-extended
    // centi-°C = raw(°C) * 100 = raw * (100 / 128)
    Ok(((raw as i32) * 100 / 128) as i16)
}
