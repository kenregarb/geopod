use std::error::Error;
use std::path::PathBuf;

use crate::auth;

pub struct Config {
    pub bind_addr: String,
    pub db_url: String,
    pub jwt_secret: String,
    pub admin_username: String,
    pub admin_password_hash: String,
    pub cache_dir: PathBuf,
    pub secure_cookie: bool,
}

fn env(name: &str, default: &str) -> String {
    std::env::var(name).unwrap_or_else(|_| default.to_string())
}

impl Config {
    pub fn from_env() -> Result<Self, Box<dyn Error>> {
        let app_env = env("APP_ENV", "production");
        let admin_password = env("APP_ADMIN_PASSWORD", "");
        let jwt_secret = env("JWT_SECRET", "");
        let db_url = env("DATABASE_URL", "");
        if admin_password.is_empty() {
            tracing::warn!("APP_ADMIN_PASSWORD kosong; login admin tidak akan pernah berhasil.");
        }
        if jwt_secret.is_empty() {
            tracing::warn!("JWT_SECRET kosong; gunakan nilai acak panjang.");
        }
        if db_url.is_empty() {
            return Err("DATABASE_URL tidak diset.".into());
        }
        Ok(Config {
            bind_addr: env("BIND_ADDR", "0.0.0.0:3001"),
            db_url,
            jwt_secret,
            admin_username: env("APP_ADMIN_USERNAME", "admin"),
            admin_password_hash: auth::hash_password(&admin_password)?,
            cache_dir: PathBuf::from(env("CACHE_DIR", "/var/cache/nginx/geopod_cache")),
            secure_cookie: app_env == "production",
        })
    }
}