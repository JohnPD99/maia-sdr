//! Spectrometer.
//!
//! Drain the FPGA spectrometer ring buffers, convert to f32, and broadcast
//! frames with a 32-byte telemetry footer. Includes loss accounting and
//! lightweight performance logging.

use crate::{app::AppState, fpga::InterruptWaiter};
use crate::telemetry::Telemetry;
use anyhow::Result;
use bytes::Bytes;
use std::sync::Mutex;
use std::time::Instant;
use tokio::sync::broadcast;
use tracing::{info, trace, warn};

// Convert scale: (u64fp -> power) -> f32
const BASE_SCALE: f32 = 4e6;
// Spectrometer ring has 8 buffers (indices 0..7)
const RING_LEN: u8 = 8;

/// Main spectrometer task.
#[derive(Debug)]
pub struct Spectrometer {
    state: AppState,
    sender: broadcast::Sender<Bytes>,
    interrupt: InterruptWaiter,
    telemetry: Telemetry,

    // --- loss accounting ---
    last_buf_idx: Option<u8>,
    lost_before_userspace: u64,

    // --- perf ---
    metrics: Perf,

    // --- debug toggles via env ---
    no_broadcast: bool,
    convert_outside_lock: bool,
}

/// Shared config container.
#[derive(Debug)]
pub struct SpectrometerConfig(Mutex<Config>);

#[derive(Debug, Clone)]
struct Config {
    samp_rate: f32,
}

#[derive(Debug)]
struct Perf {
    // counters in current reporting window
    produced_cnt: usize,
    drained_cnt:  usize,
    lost_cnt:     usize,
    sent_cnt:     usize,

    // time accounting (aggregate ms per window)
    lock_ms:    f64,
    convert_ms: f64,
    foot_ms:    f64,

    last_report: Instant,
}

impl Perf {
    fn new() -> Self {
        Self {
            produced_cnt: 0,
            drained_cnt:  0,
            lost_cnt:     0,
            sent_cnt:     0,
            lock_ms:      0.0,
            convert_ms:   0.0,
            foot_ms:      0.0,
            last_report:  Instant::now(),
        }
    }

    fn add_lock_ms(&mut self, dt_ms: f64)    { self.lock_ms += dt_ms; }
    fn add_convert_ms(&mut self, dt_ms: f64) { self.convert_ms += dt_ms; }
    fn add_foot_ms(&mut self, dt_ms: f64)    { self.foot_ms += dt_ms; }

    fn add_produced(&mut self, n: usize) { self.produced_cnt += n; }
    fn add_drained(&mut self, n: usize)  { self.drained_cnt += n; }
    fn add_lost(&mut self, n: usize)     { self.lost_cnt += n; }
    fn add_sent(&mut self, n: usize)     { self.sent_cnt += n; }

    /// Emit a 1-second summary if a second elapsed; then reset counters.
    fn maybe_report_and_reset(
        &mut self,
        no_broadcast: bool,
        convert_outside_lock: bool,
    ) {
        let now = Instant::now();
        let secs = (now - self.last_report).as_secs_f64();
        if secs < 1.0 {
            return;
        }
        let produced_fps = self.produced_cnt as f64 / secs;
        let drained_fps  = self.drained_cnt  as f64 / secs;
        let lost_fps     = self.lost_cnt     as f64 / secs;
        let sent_fps     = self.sent_cnt     as f64 / secs;

        info!(
            produced_fps = format_args!("{:.1}", produced_fps),
            drained_fps  = format_args!("{:.1}", drained_fps),
            lost_fps     = format_args!("{:.1}", lost_fps),
            sent_fps     = format_args!("{:.1}", sent_fps),
            lock_ms_per_s    = format_args!("{:.3}", self.lock_ms / secs),
            convert_ms_per_s = format_args!("{:.3}", self.convert_ms / secs),
            footer_bcast_ms_per_s = format_args!("{:.3}", self.foot_ms / secs),
            no_broadcast,
            convert_outside_lock,
            "spectrometer: 1s summary"
        );

        // reset for next window
        self.produced_cnt = 0;
        self.drained_cnt  = 0;
        self.lost_cnt     = 0;
        self.sent_cnt     = 0;
        self.lock_ms      = 0.0;
        self.convert_ms   = 0.0;
        self.foot_ms      = 0.0;
        self.last_report  = now;
    }
}

impl Spectrometer {
    pub fn new(
        state: AppState,
        interrupt: InterruptWaiter,
        sender: broadcast::Sender<Bytes>,
        telemetry: Telemetry,
    ) -> Spectrometer {
        // env toggles
        let no_broadcast = std::env::var("NO_BCAST").map(|v| v == "1" || v.eq_ignore_ascii_case("true")).unwrap_or(false);
        let convert_outside_lock = std::env::var("CONVERT_OUTSIDE_LOCK").map(|v| v == "1" || v.eq_ignore_ascii_case("true")).unwrap_or(false);

        if no_broadcast || convert_outside_lock {
            info!(no_broadcast, convert_outside_lock, "spectrometer: debug toggles enabled");
        }

        Spectrometer {
            state,
            interrupt,
            sender,
            telemetry,
            last_buf_idx: None,
            lost_before_userspace: 0,
            metrics: Perf::new(),
            no_broadcast,
            convert_outside_lock,
        }
    }

    /// Main loop.
    ///
    /// Always appends a 32-byte footer per frame (flags indicate validity).
    /// Never reads new registers inside the per-buffer loop.
    #[tracing::instrument(name = "spectrometer", skip_all)]
    pub async fn run(mut self) -> Result<()> {
        loop {
            // Wait for IRQ (new data in the ring)
            self.interrupt.wait().await;

            // ---------- lock & snapshot ----------
            let t0 = Instant::now();
            let samp_rate = self.state.spectrometer_config().samp_rate();
            let mut ip_core = self.state.ip_core().lock().unwrap();

            let integrations_exp = ip_core.spectrometer_integrations_exp() as u32;
            let kurt_1          = ip_core.spectrometer_kurt_1() as u32;
            let kurt_2          = ip_core.spectrometer_kurt_2() as u32;
            let kurt_enable     = ip_core.spectrometer_kurt_enable() as bool;
            let sweep_enable    = ip_core.spectrometer_sweep_enable() as bool;
            let lpf_select      = ip_core.spectrometer_lpf_select() as bool;
            let port_select     = ip_core.spectrometer_port_select() as u32;
            let freq_profile    = ip_core.spectrometer_freq_profile() as u32;

            // producer index (0..7) and the *newest* sweep counter at IRQ time
            let idx_now: u8     = (ip_core.spectrometer_last_buffer() as u32 & 0xFF) as u8;
            let sweep_cnt_now: u8 = ip_core.spectrometer_sweep_cnt() as u8;

            let num_integrations = (1u32 << integrations_exp) as f32;
            let scale = BASE_SCALE / (num_integrations * samp_rate);

            // Drain the ring. Two modes:
            //  - convert inside lock (fastest)
            //  - OR copy raw u64 inside lock and convert later
            let mut drained_payloads: Vec<Vec<u8>> = Vec::with_capacity(8);
            let mut raw_buffers: Vec<Vec<u64>> = Vec::with_capacity(8);

            if self.convert_outside_lock {
                for buffer in ip_core.get_spectrometer_buffers() {
                    raw_buffers.push(buffer.to_vec()); // copy raw u64
                }
            } else {
                for buffer in ip_core.get_spectrometer_buffers() {
                    drained_payloads.push(Self::buffer_u64fp_to_f32(buffer, scale));
                }
            }
            let drained = if self.convert_outside_lock { raw_buffers.len() } else { drained_payloads.len() };

            drop(ip_core);
            let dt_lock = (Instant::now() - t0).as_secs_f64() * 1e3;
            self.metrics.add_lock_ms(dt_lock);

            // ---------- optional conversion outside lock ----------
            if self.convert_outside_lock && !raw_buffers.is_empty() {
                let t = Instant::now();
                for buf in raw_buffers.into_iter() {
                    drained_payloads.push(Self::buffer_u64fp_to_f32(&buf, scale));
                }
                let dt = (Instant::now() - t).as_secs_f64() * 1e3;
                self.metrics.add_convert_ms(dt);
            }

            // Nothing drained? Establish baseline + trace and continue.
            if drained == 0 {
                if self.last_buf_idx.is_none() {
                    self.last_buf_idx = Some(idx_now);
                }
                trace!(
                    last_buffer = idx_now,
                    samp_rate,
                    integrations_exp,
                    scale,
                    kurt_1,
                    kurt_2,
                    kurt_enable,
                    sweep_enable,
                    lpf_select,
                    port_select,
                    freq_profile,
                    drained,
                    "spectrometer irq snapshot (no frames)"
                );
                self.metrics.maybe_report_and_reset(self.no_broadcast, self.convert_outside_lock);
                continue;
            }

            // ---------- loss accounting (modulo-8) ----------
            let produced_mod: u8 = if let Some(prev) = self.last_buf_idx {
                (idx_now + RING_LEN - prev) % RING_LEN
            } else {
                0
            };
            self.last_buf_idx = Some(idx_now);

            self.metrics.add_produced(produced_mod as usize);
            self.metrics.add_drained(drained);

            let lost = produced_mod as isize - drained as isize;
            if lost > 0 {
                self.lost_before_userspace = self.lost_before_userspace.saturating_add(lost as u64);
                self.metrics.add_lost(lost as usize);
                warn!(
                    produced = produced_mod,
                    drained,
                    lost = lost,
                    total_lost = self.lost_before_userspace,
                    "DMA ring overrun: frames lost before userspace could drain"
                );
            } else {
                trace!(
                    last_buffer = idx_now,
                    samp_rate,
                    integrations_exp,
                    scale,
                    kurt_1,
                    kurt_2,
                    kurt_enable,
                    sweep_enable,
                    lpf_select,
                    port_select,
                    freq_profile,
                    drained,
                    "spectrometer irq snapshot"
                );
            }

            // ---------- build footer + broadcast ----------
            // first frame's sweep_cnt = newest - (drained - 1)
            let mut sweep_cnt = sweep_cnt_now.wrapping_sub(drained as u8).wrapping_add(1);
            let have_receivers = !self.no_broadcast && self.sender.receiver_count() > 0;

            let t_fb = Instant::now();
            let mut sent_this_irq = 0usize;
            for mut payload in drained_payloads {
                let mut footer = self.telemetry.footer_bytes();
                footer[6] = sweep_cnt; // always present
                footer[7] = 0;         // reserved
                sweep_cnt = sweep_cnt.wrapping_add(1);

                payload.extend_from_slice(&footer);

                if have_receivers {
                    let _ = self.sender.send(Bytes::from(payload));
                    sent_this_irq += 1;
                }
            }
            let dt_fb = (Instant::now() - t_fb).as_secs_f64() * 1e3;
            self.metrics.add_foot_ms(dt_fb);
            self.metrics.add_sent(sent_this_irq);

            // ---------- periodic report ----------
            self.metrics.maybe_report_and_reset(self.no_broadcast, self.convert_outside_lock);
        }
    }

    #[inline]
    fn buffer_u64fp_to_f32(buffer: &[u64], scale: f32) -> Vec<u8> {
        // 4096 bins * 4 bytes each
        let mut out = Vec::with_capacity(buffer.len() * 4);
        for &x in buffer {
            let exponent = (x >> 56) as u8;
            let value = x & ((1u64 << 56) - 1);
            let y = value << (2 * exponent);
            out.extend_from_slice(&(y as f32 * scale).to_ne_bytes());
        }
        out
    }
}

impl SpectrometerConfig {
    fn new() -> SpectrometerConfig {
        SpectrometerConfig(Mutex::new(Config { samp_rate: 0.0 }))
    }
    /// Returns the spectrometer sample rate (samples/sec).
    pub fn samp_rate(&self) -> f32 {
        self.0.lock().unwrap().samp_rate
    }
    /// Sets the spectrometer sample rate (samples/sec).
    pub fn set_samp_rate(&self, samp_rate: f32) {
        self.0.lock().unwrap().samp_rate = samp_rate;
    }
}

impl Default for SpectrometerConfig {
    fn default() -> SpectrometerConfig {
        SpectrometerConfig::new()
    }
}
