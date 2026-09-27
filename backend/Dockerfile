# ============================================================
# GEOPOD v2 - Backend (Rust/Axum) multi-stage
# ============================================================
FROM rust:1.98-slim-bullseye AS builder
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
RUN mkdir -p src && echo 'fn main() {}' > src/main.rs \
    && cargo build --release \
    && rm -f src/main.rs target/release/deps/geopod_backend*
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/target/release/geopod-backend /app/geopod-backend
ENV BIND_ADDR=0.0.0.0:3001
EXPOSE 3001
CMD ["/app/geopod-backend"]