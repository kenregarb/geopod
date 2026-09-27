#!/usr/bin/env bash
# ============================================================
# GEOPOD v2 - seed_geojson.sh
# Seeding otomatis geometri (GeoJSON/SHP+DBF) + atribut Podes (Excel).
#
# Cara pakai (di VPS, root proyek):
#   1) Letakkan file .geojson di ./geojson_seed/   (atau .shp + .dbf)
#   2) (Opsional) Letakkan datageopod.xlsx di ./podes_seed/
#   3) Export DATABASE_URL dulu, lalu jalankan:
#        DATABASE_URL="postgres://geopod:geopod@localhost:5432/geopod_db" ./seed_geojson.sh
#
# Env opsional:
#   GEOPOD_NET        nama network podman-compose (default: geopodv2_geopod)
#   GEOJSON_DIR       folder sumber geometri (default: ./geojson_seed)
#   PODES_DIR         folder sumber xlsx Podes (default: ./podes_seed)
#   SEED_MATCH_PREFIX filter kode (mis. "1673" hanya Kota Pagar Alam)
#   SEED_CODE_FIELD   nama kolom/properti kode bila bukan iddesa
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${GEOPOD_SEED_IMAGE:-geopod-seed:latest}"
NET="${GEOPOD_NET:-geopodv2_geopod}"
GEOJSON_DIR="${GEOJSON_DIR:-$(pwd)/geojson_seed}"
PODES_DIR="${PODES_DIR:-$(pwd)/podes_seed}"

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "[geopod] ERROR: export DATABASE_URL terlebih dahulu." >&2
    exit 1
fi

echo "[geopod] build image seed..."
podman build -t "$IMAGE" -f deploy/seed/Dockerfile.seed deploy/seed

echo "[geopod] seed geometri (GeoJSON/SHP) dari ${GEOJSON_DIR}..."
podman run --rm \
    --network "$NET" \
    -v "$GEOJSON_DIR:/data:ro" \
    -e DATABASE_URL="$DATABASE_URL" \
    -e SEED_CODE_FIELD="${SEED_CODE_FIELD:-}" \
    -e SEED_NAME_FIELD="${SEED_NAME_FIELD:-}" \
    -e SEED_MATCH_PREFIX="${SEED_MATCH_PREFIX:-}" \
    "$IMAGE" /app/seed_geojson.py --src /data

if compgen -G "$PODES_DIR"/*.xlsx > /dev/null 2>&1; then
    for f in "$PODES_DIR"/*.xlsx; do
        echo "[geopod] import atribut Podes: ${f}..."
        podman run --rm \
            --network "$NET" \
            -v "$f:/data/input.xlsx:ro" \
            -e DATABASE_URL="$DATABASE_URL" \
            "$IMAGE" /app/import_podes_xlsx.py --src /data/input.xlsx
    done
else
    echo "[geopod] tidak ada file .xlsx di ${PODES_DIR} -> impor atribut dilewati."
fi

echo "[geopod] seeding selesai."