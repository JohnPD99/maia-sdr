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
    let kurt_1 = ip_core.spectrometer_kurt_1();
    let kurt_2 = ip_core.spectrometer_kurt_2();
    let kurt_enable = ip_core.spectrometer_kurt_enable();
    drop(ip_core);
    state
        .spectrometer_config()
        .set_samp_rate(samp_rate as f32);
    Ok(Spectrometer {
        input_sampling_frequency: samp_rate,
        output_sampling_frequency: samp_rate / (f64::from(FFT_SIZE) * f64::from(num_integrations)),
        integrations_exp: integrations_exp,
        fft_size: FFT_SIZE,
        kurt_1:kurt_1,
        kurt_2:kurt_2,
        kurt_enable:kurt_enable
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
    
    let mut ip_core = state.ip_core().lock().unwrap();

    if let Some(n) = patch.integrations_exp {
        ip_core
            .set_spectrometer_integrations_exp(n)
            .map_err(JsonError::client_error)?;
    }

    if let Some(k1) = patch.kurt_1 {
        ip_core
            .set_spectrometer_kurt_1(k1)
            .map_err(JsonError::client_error)?;
    }

    if let Some(k2) = patch.kurt_2 {
        ip_core
            .set_spectrometer_kurt_2(k2)
            .map_err(JsonError::client_error)?;
    }

    if let Some(ken) = patch.kurt_enable {
        ip_core
            .set_spectrometer_kurt_enable(ken)
            .map_err(JsonError::client_error)?;
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
