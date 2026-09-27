mod analytics;
mod auth;
mod config;
mod db;
mod error;
mod handlers;
mod state;

use std::sync::Arc;

use axum::{
    routing::{get, post, put},
    Router,
};
use tower_http::{catch_panic::CatchPanicLayer, trace::TraceLayer};

use state::AppState;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let cfg = match config::Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            tracing::error!("konfigurasi tidak valid: {e}");
            std::process::exit(1);
        }
    };

    let pool = match db::pool(&cfg.db_url).await {
        Ok(p) => p,
        Err(e) => {
            tracing::error!("gagal koneksi database: {e}");
            std::process::exit(1);
        }
    };
    tracing::info!("database terhubung.");

    let bind_addr = cfg.bind_addr.clone();
    let app_state = AppState {
        cfg: Arc::new(cfg),
        db: pool,
    };

    let app = Router::new()
        .route("/api/auth/login", post(handlers::login))
        .route("/api/auth/logout", post(handlers::logout))
        .route("/api/auth/me", get(handlers::me))
        .route("/api/kelurahan", get(handlers::list_kelurahan))
        .route("/api/podes/analitik", get(handlers::city_analytics))
        .route(
            "/api/kelurahan/:kode",
            get(handlers::get_kelurahan).put(handlers::update_kelurahan),
        )
        .route(
            "/api/kelurahan/:kode/geometry",
            get(handlers::get_kelurahan_geometry).put(handlers::update_kelurahan_geometry),
        )
        .route("/api/cache/purge", post(handlers::purge_cache))
        .layer(TraceLayer::new_for_http())
        .layer(CatchPanicLayer::new())
        .with_state(app_state);

    let listener = tokio::net::TcpListener::bind(&bind_addr)
        .await
        .expect("gagal bind 3001");
    tracing::info!("backend siap di http://{bind_addr}");
    axum::serve(listener, app).await.expect("server error");
}

