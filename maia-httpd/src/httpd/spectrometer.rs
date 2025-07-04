use super::json_error::JsonError;
use crate::app::AppState;
use anyhow::Result;
use axum::{Json, extract::State};
use maia_json::{PatchSpectrometer, Spectrometer};

// TODO: do not hardcode FFT size
const FFT_SIZE: u32 = 4096;

pub async fn spectrometer_json(state: &AppState) -> Result<Spectrometer> {
    let ad9361_samp_rate = state.ad9361_samp_rate().await?;
    let ip_core = state.ip_core().lock().unwrap();
    let samp_rate = ad9361_samp_rate;
    let integrations_exp = ip_core.spectrometer_integrations_exp();
    let num_integrations = 1u32 << integrations_exp;
    drop(ip_core);
    state
        .spectrometer_config()
        .set_samp_rate(samp_rate as f32);
    Ok(Spectrometer {
        input_sampling_frequency: samp_rate,
        output_sampling_frequency: samp_rate / (f64::from(FFT_SIZE) * f64::from(num_integrations)),
        integrations_exp: integrations_exp,
        fft_size: FFT_SIZE
    })
}

async fn get_spectrometer_json(state: &AppState) -> Result<Json<Spectrometer>, JsonError> {
    spectrometer_json(state)
        .await
        .map_err(JsonError::server_error)
        .map(Json)
}

pub async fn get_spectrometer(
    State(state): State<AppState>,
) -> Result<Json<Spectrometer>, JsonError> {
    get_spectrometer_json(&state).await
}

async fn update_spectrometer(state: &AppState, patch: &PatchSpectrometer) -> Result<(), JsonError> {
    match patch {
        PatchSpectrometer {
            integrations_exp: Some(n),
            ..
        } => state
            .ip_core()
            .lock()
            .unwrap()
            .set_spectrometer_integrations_exp(*n)
            .map_err(JsonError::client_error)?,
        _ => {
            // No parameters were specified. We don't do anything.
        }
    }
    Ok(())
}

pub async fn patch_spectrometer(
    State(state): State<AppState>,
    Json(patch): Json<PatchSpectrometer>,
) -> Result<Json<Spectrometer>, JsonError> {
    update_spectrometer(&state, &patch).await?;
    get_spectrometer_json(&state).await
}
