use std::sync::Arc;

use sqlx::postgres::PgPool;

use crate::config::Config;

#[derive(Clone)]
pub struct AppState {
    pub cfg: Arc<Config>,
    pub db: PgPool,
}