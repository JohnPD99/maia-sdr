//! Spectrometer.
//!
//! This module is used for the control of the spectrometer included in the Maia
//! SDR FPGA IP core.

use crate::{app::AppState, fpga::InterruptWaiter};
use crate::telemetry::Telemetry;                 // <-- added
use anyhow::Result;
use bytes::Bytes;
use std::sync::Mutex;
use tokio::sync::broadcast;

// Used to obtain values in dB which are positive
const BASE_SCALE: f32 = 4e6;

/// Spectrometer.
///
/// This struct waits for interrupts from the spectrometer in the FPGA IP core,
/// reads the spectrum data, transforms it from `u64` to `f32` format, and sends
/// it (serialized into [`Bytes`]) into a [`tokio::sync::broadcast::Sender`].
#[derive(Debug)]
pub struct Spectrometer {
    state: AppState,
    sender: broadcast::Sender<Bytes>,
    interrupt: InterruptWaiter,
    telemetry: Telemetry,                          // <-- added
}

/// Spectrometer configuration setter.
///
/// This struct gives shared access to getters and setters for the spectrometer
/// sample rate and mode. It is used to update the sample rate and mode from
/// other parts of the code.
#[derive(Debug)]
pub struct SpectrometerConfig(Mutex<Config>);

#[derive(Debug, Clone)]
struct Config {
    samp_rate: f32
}

impl Spectrometer {
    /// Creates a new spectrometer struct.
    ///
    /// The `interrupt` parameter should correspond to the [`InterruptWaiter`]
    /// corresponding to the spectrometer. Each spectra received from the FPGA
    /// is sent to the `sender`.
    pub fn new(
        state: AppState,
        interrupt: InterruptWaiter,
        sender: broadcast::Sender<Bytes>,
        telemetry: Telemetry,                      // <-- added
    ) -> Spectrometer {
        Spectrometer {
            state,
            interrupt,
            sender,
            telemetry,                             // <-- added
        }
    }

    /// Runs the spectrometer.
    ///
    /// This function only returns if there is an error. The function should be
    /// run concurrently with the rest of the application for the spectrometer
    /// to work.
    #[tracing::instrument(name = "spectrometer", skip_all)]
    pub async fn run(self) -> Result<()> {
        loop {
            self.interrupt.wait().await;
            let samp_rate = self.state.spectrometer_config().samp_rate();
            let mut ip_core = self.state.ip_core().lock().unwrap();
            let integrations_exp = ip_core.spectrometer_integrations_exp() as u32;
            let kurt_1 = ip_core.spectrometer_kurt_1() as u32;
            let kurt_2 = ip_core.spectrometer_kurt_2() as u32;
            let kurt_enable = ip_core.spectrometer_kurt_enable() as bool;
            let sweep_enable = ip_core.spectrometer_sweep_enable() as bool;
            let lpf_select = ip_core.spectrometer_lpf_select() as bool;
            let port_select = ip_core.spectrometer_port_select() as u32;
            let freq_profile = ip_core.spectrometer_freq_profile() as u32;
            let num_integrations = (1u32 << integrations_exp) as f32; 
            let scale = BASE_SCALE / (num_integrations * samp_rate);
            tracing::trace!(
                last_buffer = ip_core.spectrometer_last_buffer(),
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
                sweep_cnt = ip_core.spectrometer_sweep_cnt(), // <- optional
            );
            // TODO: potential optimization: do not hold the mutex locked while
            // we iterate over the buffers.

            let sweep_cnt = ip_core.spectrometer_sweep_cnt();


            for buffer in ip_core.get_spectrometer_buffers() {
                if self.sender.receiver_count() > 0 {
                    // Convert 4096 bins -> f32 -> bytesW
                    let mut payload = Self::buffer_u64fp_to_f32(buffer, scale);

                    let mut footer = self.telemetry.footer_bytes();
                    footer[6] = sweep_cnt; // mask to 0..31 if that’s your range
                    footer[7] = 0;

                    // Append footer
                    payload.extend_from_slice(&footer);

                    // Broadcast (ignore Err if no receivers)
                    let _ = self.sender.send(Bytes::from(payload));
                }
            }
        }
    }

    fn buffer_u64fp_to_f32(buffer: &[u64], scale: f32) -> Vec<u8> {
        let mut out = Vec::with_capacity(buffer.len() * 4); // 4096 bins * 4 bytes
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
    /// Creates a new spectrometer configuration object.
    fn new() -> SpectrometerConfig {
        SpectrometerConfig(Mutex::new(Config {
            samp_rate: 0.0
        }))
    }

    /// Returns the spectrometer sample rate.
    ///
    /// The units are samples per second.
    pub fn samp_rate(&self) -> f32 {
        self.0.lock().unwrap().samp_rate
    }

    /// Sets the spectrometer sample rate.
    ///
    /// Updates the spectrometer sample rate to the value give, in units of
    /// samples per second.
    pub fn set_samp_rate(&self, samp_rate: f32) {
        self.0.lock().unwrap().samp_rate = samp_rate;
    }
}

impl Default for SpectrometerConfig {
    fn default() -> SpectrometerConfig {
        SpectrometerConfig::new()
    }
}
