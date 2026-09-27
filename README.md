# GEOPOD v2

GIS profil 35 kelurahan Kota Pagar Alam (Sumatera Selatan) berbasis data Potensi Desa (Podes) 2025.

- Peta interaktif (MapLibre GL) dengan vector tile (Martin + PostGIS).
- Data atribut Podes ditampilkan per kelurahan dalam modal dengan 4 tab.
- Dashboard admin untuk kelola atribut & geometri (auth cookie HttpOnly).
- Proteksi anti-scraping: rate limit + proxy cache 90 hari (nginx).

## Struktur

```
â”œâ”€â”€ podman-compose.yml     # stack: geodb, martin, backend, nginx (port 3333)
â”œâ”€â”€ .env.example           # contoh konfigurasi
â”œâ”€â”€ deploy/
â”‚   â”œâ”€â”€ postgres/schema.sql
â”‚   â”œâ”€â”€ martin/martin.yaml
â”‚   â”œâ”€â”€ nginx/nginx.conf
â”‚   â””â”€â”€ seed/              # seed_geojson.py, import_podes_xlsx.py, Dockerfile.seed
â”œâ”€â”€ geojson_seed/          # sumber geometri (.geojson / .shp+.dbf)
â”œâ”€â”€ podes_seed/            # sumber atribut (datageopod.xlsx)
â”œâ”€â”€ frontend/              # Vite + TS + Tailwind v4 + MapLibre GL
â””â”€â”€ backend/               # Rust Axum (API + auth)
```

## Menjalankan (VPS, memakai podman)

```sh
cp .env.example .env            # sesuaikan JWT_SECRET & APP_ADMIN_PASSWORD
podman-compose up -d

# seed data (geometri dulu, lalu atribut)
export DATABASE_URL="postgres://geopod:geopod@localhost:5432/geopod_db"
./seed_geojson.sh

# akses
#   Publik   : http://<ip-server> param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' } /
#   Admin    : http://<ip-server> param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' } /admin  (login /admin)
```

## Prasyarat pengembangan (Windows)

- Node.js >= 20, pnpm
- Rust (cargo) untuk backend
- podman + podman-compose untuk kustomisasi stack

Dokumentasi lengkap ada di `DEPLOYMENT.md` dan `DEVELOPER_TUTORIAL.md` (fase dokumentasi).