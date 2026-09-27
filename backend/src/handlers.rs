use axum::{
    extract::{Path, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::IntoResponse,
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::auth;
use crate::db;
use crate::error::{ApiError, ApiResult};
use crate::state::AppState;

#[derive(Deserialize)]
pub struct LoginBody {
    username: String,
    password: String,
}

#[derive(Deserialize)]
pub struct UpdateBody {
    nama_kelurahan: Option<String>,
    nama_kecamatan: Option<String>,
    potensi_desa: Option<Value>,
}

#[derive(Deserialize)]
pub struct GeometryBody {
    geometry: Value,
}

fn extract_cookie(headers: &HeaderMap, name: &str) -> Option<String> {
    for value in headers.get_all(header::COOKIE) {
        let Ok(text) = value.to_str() else {
            continue;
        };
        for part in text.split(';') {
            let Some((k, v)) = part.split_once('=') else {
                continue;
            };
            if k.trim() == name {
                return Some(v.trim().to_string());
            }
        }
    }
    None
}

fn require_admin(state: &AppState, headers: &HeaderMap) -> ApiResult<String> {
    let token = extract_cookie(headers, auth::COOKIE_NAME)
        .ok_or(ApiError::Unauthorized)?;
    let claims = auth::verify_token(&state.cfg.jwt_secret, &token)?;
    Ok(claims.sub)
}

fn is_supported_geometry(v: &Value) -> bool {
    match v.get("type").and_then(Value::as_str) {
        Some("Polygon") | Some("MultiPolygon") => true,
        _ => false,
    }
}

pub async fn login(
    State(state): State<AppState>,
    Json(body): Json<LoginBody>,
) -> ApiResult<axum::response::Response> {
    if body.username != state.cfg.admin_username
        || !auth::verify_password(&body.password, &state.cfg.admin_password_hash)
    {
        return Err(ApiError::Unauthorized);
    }
    let token = auth::sign_token(&state.cfg.jwt_secret, &body.username)?;
    let cookie = auth::cookie_header(&token, state.cfg.secure_cookie);
    let mut response = Json(json!({ "message": "Login berhasil." })).into_response();
    response
        .headers_mut()
        .insert(header::SET_COOKIE, HeaderValue::from_str(&cookie).unwrap());
    Ok(response)
}

pub async fn logout() -> impl IntoResponse {
    let mut response = StatusCode::NO_CONTENT.into_response();
    response.headers_mut().insert(
        header::SET_COOKIE,
        HeaderValue::from_str(&auth::clear_cookie()).unwrap(),
    );
    response
}

pub async fn me(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> ApiResult<impl IntoResponse> {
    let username = require_admin(&state, &headers)?;
    Ok(Json(json!({ "username": username })))
}

pub async fn list_kelurahan(
    State(state): State<AppState>,
) -> ApiResult<impl IntoResponse> {
    let items = db::list(&state.db).await?;
    Ok(Json(json!({ "items": items })))
}

pub async fn city_analytics(
    State(state): State<AppState>,
) -> ApiResult<impl IntoResponse> {
    let rows = db::analytics(&state.db).await?;
    let payload = crate::analytics::compute(&rows);
    Ok(Json(payload))
}

pub async fn get_kelurahan(
    State(state): State<AppState>,
    Path(kode): Path<String>,
) -> ApiResult<impl IntoResponse> {
    let row = db::detail(&state.db, &kode).await?;
    Ok(Json(row))
}

pub async fn update_kelurahan(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(kode): Path<String>,
    Json(body): Json<UpdateBody>,
) -> ApiResult<impl IntoResponse> {
    require_admin(&state, &headers)?;
    db::update_attribute(
        &state.db,
        &kode,
        body.nama_kelurahan.as_deref(),
        body.nama_kecamatan.as_deref(),
        body.potensi_desa.as_ref(),
    )
    .await?;
    let row = db::detail(&state.db, &kode).await?;
    Ok(Json(row))
}

pub async fn get_kelurahan_geometry(
    State(state): State<AppState>,
    Path(kode): Path<String>,
) -> ApiResult<impl IntoResponse> {
    let geometry = db::geometry(&state.db, &kode).await?;
    Ok(Json(json!({ "geometry": geometry })))
}

pub async fn update_kelurahan_geometry(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(kode): Path<String>,
    Json(body): Json<GeometryBody>,
) -> ApiResult<impl IntoResponse> {
    require_admin(&state, &headers)?;
    if !is_supported_geometry(&body.geometry) {
        return Err(ApiError::BadRequest(
            "Geometri harus bertipe Polygon atau MultiPolygon.".to_string(),
        ));
    }
    let geometry_json = body.geometry.to_string();
    db::update_geometry(&state.db, &kode, &geometry_json).await?;
    let row = db::detail(&state.db, &kode).await?;
    Ok(Json(row))
}

pub async fn purge_cache(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> ApiResult<impl IntoResponse> {
    require_admin(&state, &headers)?;
    let dir = state.cfg.cache_dir.clone();
    let removed = tokio::task::spawn_blocking(move || purge_dir(&dir))
        .await
        .map_err(|e| ApiError::Internal(format!("spawn purge: {e}")))?
        .map_err(|e| ApiError::Internal(format!("purge cache: {e}")))?;
    Ok(Json(json!({
        "purged": true,
        "message": format!("{removed} file cache dihapus.")
    })))
}

fn purge_dir(dir: &std::path::Path) -> std::io::Result<usize> {
    let mut removed = 0usize;
    if !dir.exists() {
        return Ok(0);
    }
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            removed += purge_dir(&path)?;
        } else {
            let _ = std::fs::remove_file(&path);
            removed += 1;
        }
    }
    Ok(removed)
}