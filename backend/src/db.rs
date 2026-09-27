use chrono::{DateTime, Utc};
use serde::Serialize;
use sqlx::postgres::{PgPool, PgPoolOptions};
use sqlx::types::Json as SqlxJson;
use sqlx::FromRow;

use crate::error::{ApiError, ApiResult};

#[derive(FromRow, Serialize)]
pub struct KelurahanSummary {
    #[sqlx(rename = "kode_kelurahan")]
    pub kode_kelurahan: String,
    pub nama_kelurahan: Option<String>,
    pub nama_kecamatan: Option<String>,
    #[sqlx(rename = "luas")]
    pub luas_wilayah: Option<f64>,
}

#[derive(FromRow, Serialize)]
pub struct KelurahanDetail {
    pub kode_kelurahan: String,
    pub nama_kelurahan: Option<String>,
    pub nama_kecamatan: Option<String>,
    #[sqlx(rename = "luas")]
    pub luas_wilayah: Option<f64>,
    pub potensi_desa: Option<SqlxJson<serde_json::Value>>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(FromRow)]
pub struct AnalyticsRow {
    pub kode_kelurahan: String,
    pub nama_kelurahan: Option<String>,
    pub nama_kecamatan: Option<String>,
    #[sqlx(rename = "luas")]
    pub luas_wilayah: Option<f64>,
    pub potensi_desa: Option<SqlxJson<serde_json::Value>>,
}

pub async fn pool(db_url: &str) -> ApiResult<PgPool> {
    PgPoolOptions::new()
        .max_connections(5)
        .connect(db_url)
        .await
        .map_err(|e| ApiError::Internal(format!("koneksi database: {e}")))
}

pub async fn list(pool: &PgPool) -> ApiResult<Vec<KelurahanSummary>> {
    let rows = sqlx::query_as::<_, KelurahanSummary>(
        r#"
        SELECT kode_kelurahan,
               nama_kelurahan,
               nama_kecamatan,
               (luas_wilayah::float8) AS luas
        FROM kelurahan_attribute
        ORDER BY kode_kelurahan
        "#,
    )
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

pub async fn detail(pool: &PgPool, kode: &str) -> ApiResult<KelurahanDetail> {
    let row = sqlx::query_as::<_, KelurahanDetail>(
        r#"
        SELECT kode_kelurahan,
               nama_kelurahan,
               nama_kecamatan,
               (luas_wilayah::float8) AS luas,
               potensi_desa,
               updated_at
        FROM kelurahan_attribute
        WHERE kode_kelurahan = $1
        "#,
    )
    .bind(kode)
    .fetch_one(pool)
    .await?;
    Ok(row)
}

pub async fn analytics(pool: &PgPool) -> ApiResult<Vec<AnalyticsRow>> {
    let rows = sqlx::query_as::<_, AnalyticsRow>(
        r#"
        SELECT kode_kelurahan,
               nama_kelurahan,
               nama_kecamatan,
               (luas_wilayah::float8) AS luas,
               potensi_desa
        FROM kelurahan_attribute
        ORDER BY kode_kelurahan
        "#,
    )
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

pub async fn update_attribute(
    pool: &PgPool,
    kode: &str,
    nama_kelurahan: Option<&str>,
    nama_kecamatan: Option<&str>,
    potensi_desa: Option<&serde_json::Value>,
) -> ApiResult<()> {
    let result = sqlx::query(
        r#"
        UPDATE kelurahan_attribute
        SET nama_kelurahan = COALESCE($1, nama_kelurahan),
            nama_kecamatan = COALESCE($2, nama_kecamatan),
            potensi_desa = COALESCE($3, potensi_desa),
            updated_at = NOW()
        WHERE kode_kelurahan = $4
        "#,
    )
    .bind(nama_kelurahan)
    .bind(nama_kecamatan)
    .bind(potensi_desa.map(|v| SqlxJson(v.clone())))
    .bind(kode)
    .execute(pool)
    .await?;
    if result.rows_affected() == 0 {
        return Err(ApiError::NotFound);
    }
    Ok(())
}

pub async fn geometry(pool: &PgPool, kode: &str) -> ApiResult<serde_json::Value> {
    let geom: Option<String> = sqlx::query_scalar(
        r#"
        SELECT ST_AsGeoJSON(geom)::text
        FROM kelurahan_geom
        WHERE kode_kelurahan = $1
        "#,
    )
    .bind(kode)
    .fetch_optional(pool)
    .await?;
    let Some(text) = geom else {
        return Err(ApiError::NotFound);
    };
    serde_json::from_str(&text)
        .map_err(|e| ApiError::Internal(format!("parsing geometri dari DB: {e}")))
}

pub async fn update_geometry(
    pool: &PgPool,
    kode: &str,
    geometry_json: &str,
) -> ApiResult<()> {
    let result = sqlx::query(
        r#"
        UPDATE kelurahan_geom
        SET geom = ST_SetSRID(ST_GeomFromGeoJSON($1), 4326),
            updated_at = NOW()
        WHERE kode_kelurahan = $2
        "#,
    )
    .bind(geometry_json)
    .bind(kode)
    .execute(pool)
    .await?;
    if result.rows_affected() == 0 {
        return Err(ApiError::NotFound);
    }

    sqlx::query(
        r#"
        UPDATE kelurahan_attribute
        SET luas_wilayah = ROUND(
                (ST_Area((SELECT geom FROM kelurahan_geom WHERE kode_kelurahan = $1), TRUE)
                 / 10000.0)::numeric, 2
            )
        WHERE kode_kelurahan = $1
        "#,
    )
    .bind(kode)
    .execute(pool)
    .await?;
    Ok(())
}