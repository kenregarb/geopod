# Developer Tutorial â€” Geopod v2

Panduan memahami dan mengembangkan Geopod v2 untuk pengembang (Bahasa Indonesia).

Aplikasi: profil 35 kelurahan Kota Pagar Alam berbasis data Potensi Desa (Podes) 2025,
tampil sebagai peta interaktif + detail tab per kelurahan, dengan dashboard admin.

---

## 1. Arsitektur

```
Browser (MapLibre GL)
   â”‚  GET /tiles/{z}/{x}/{y}.pbf       GET /api/...
   â–¼
nginx ( param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' } )  â”€â”€ rate limit + proxy cache 90 hari + SPA
   â”‚
   â”œâ”€â”€ /tiles/*  â”€â”€â–º Martin (:3000) â”€â”€â–º PostgreSQL + PostGIS (`kelurahan_geom`)
   â”‚                    vector tile (layer `kelurahan`, maxzoom 14)
   â””â”€â”€ /api/*    â”€â”€â–º Backend Axum (:3001) â”€â”€â–º PostgreSQL (`kelurahan_attribute`, JSONB)

Seeder Python (container terpisah): geometri â†’ PostGIS ; Excel Podes â†’ JSONB
```

Alur data Podes: `datageopod.xlsx` â†’ `import_podes_xlsx.py` â†’ JSONB `potensi_desa`
â†’ API `GET /api/kelurahan/:kode` â†’ modal 4 tab di frontend.

---

## 2. Struktur Proyek

```
geopodv2/
â”œâ”€â”€ podman-compose.yml          # stack: geodb, martin, backend, nginx ( param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' } )
â”œâ”€â”€ .env.example                # template konfigurasi
â”œâ”€â”€ seed_geojson.sh             # wrapper seeding (build + run container)
â”œâ”€â”€ deploy/
â”‚   â”œâ”€â”€ nginx/nginx.conf        # rate limit + cache + deny file mentah + SPA
â”‚   â”œâ”€â”€ martin/martin.yaml      # layer vector tile `kelurahan`
â”‚   â”œâ”€â”€ postgres/schema.sql     # kelurahan_geom + kelurahan_attribute + trigger
â”‚   â””â”€â”€ seed/                   # seed_geojson.py, import_podes_xlsx.py, Dockerfile.seed
â”œâ”€â”€ geojson_seed/               # sumber geometri (GeoJSON / SHP+DBF)
â”œâ”€â”€ podes_seed/                 # sumber atribut (datageopod.xlsx)
â”œâ”€â”€ frontend/                   # Vite + TypeScript strict + Tailwind v4 + MapLibre GL
â”‚   â””â”€â”€ src/
â”‚       â”œâ”€â”€ main.ts             # entry + router
â”‚       â”œâ”€â”€ router.ts           # router pathname sederhana (tanpa lib)
â”‚       â”œâ”€â”€ types.ts            # kontrak data API
â”‚       â”œâ”€â”€ lib/                # http, dom helper, cache in-memory
â”‚       â”œâ”€â”€ meta/tabConfig.ts   # â­ definisi 4 tab & mapping section Podes
â”‚       â”œâ”€â”€ api/                # public.ts, admin.ts
â”‚       â”œâ”€â”€ components/         # MapView.ts, KelurahanModal.ts
â”‚       â””â”€â”€ pages/              # PublicMapPage, AdminLoginPage, AdminDashboardPage
â””â”€â”€ backend/                    # Rust Axum
    â”œâ”€â”€ Dockerfile              # multi-stage
    â””â”€â”€ src/
        â”œâ”€â”€ main.rs             # bootstrap + routes
        â”œâ”€â”€ config.rs           # env config
        â”œâ”€â”€ auth.rs             # Argon2 + JWT + cookie
        â”œâ”€â”€ db.rs               # query sqlx/PostGIS
        â”œâ”€â”€ handlers.rs         # handlers HTTP
        â”œâ”€â”€ state.rs            # AppState
        â””â”€â”€ error.rs            # ApiError
```

---

## 3. Database

Dua tabel inti (`deploy/postgres/schema.sql`):

```sql
kelurahan_geom PK/(UNIQUE kode_kelurahan)
  - geom GEOMETRY(Geometry,4326) + GIST index
  - kode_kelurahan = iddesa 10 digit (mis. 1673040001)

kelurahan_attribute FK->kelurahan_geom
  - nama_kelurahan, nama_kecamatan, luas_wilayah NUMERIC(10,2)  -- hektare, dihitung ST_Area(geom,TRUE)/10000
  - potensi_desa JSONB NOT NULL DEFAULT '{}' + GIN index
  - kolom lain TIDAK ada (keputusan: hanya tampilkan yang ada di DB)
```

Struktur JSONB `potensi_desa`:

```json
{
  "meta":     { "tahun": "2025", "iddesa": "...", "nama_prov": "...", "nama_kab": "...", "nama_kec": "...", "nama_desa": "..." },
  "sections": {
    "keterangan_tempat":      { "label": "...", "fields": [{ "k": "r101", "l": "Provinsi", "v": "16" }, ...] },
    "umum_kelurahan":         { "label": "...", "fields": [...] },
    "perumahan_lingkungan":   { "label": "...", "fields": [...] },
    "bencana_mitigasi":       { "label": "...", "fields": [...] },
    "pendidikan_kesehatan":   { "label": "...", "fields": [...] },
    "angkutan_komunikasi":    { "label": "...", "fields": [...] },
    "ekonomi":                { "label": "...", "fields": [...] },
    "keamanan":               { "label": "...", "fields": [...] },
    "keuangan_aset":          { "label": "...", "fields": [...] },
    "aparatur":               { "label": "...", "fields": [...] }
  }
}
```

Nilai kosong ditapis di seeder; nilai mentah (`"1"`, `"B"`, dst.) dibiarkan apa
adanya karena kode interpretasinya ada di `datageopod.xlsx` (sheet `dict`).

---

## 4. Seeding

### 4.1 Geometri â€” `deploy/seed/seed_geojson.py`
- Baca GeoJSON/JSON `FeatureCollection` atau **SHP biner** (parse native: Polygon
  type 5 & PolygonZ, tanpa GDAL) + DBF pendamping.
- Kolom kode dideteksi otomatis: `iddesa`, `kode_kelurahan`, ... (env `SEED_CODE_FIELD`).
- Upsert `kelurahan_geom` (ON CONFLICT) + baris `kelurahan_attribute` + hitung `luas_wilayah`.
- Env: `DATABASE_URL`, `SEED_MATCH_PREFIX`, `SEED_CODE_FIELD`, `SEED_NAME_FIELD`.

### 4.2 Atribut â€” `deploy/seed/import_podes_xlsx.py`
- Baca sheet `ALL` (header = kode `r1xx`â€“`r12xx`) + sheet `dict` (kodeâ†’label, arah
  dideteksi) + sheet section per topik menggunakan `openpyxl`.
- Kode kolom dikelompokkan ke section; `iddesa`/`D_R` tidak dimasukkan sebagai field.
- Upsert `kelurahan_attribute.potensi_desa`; kelurahan tanpa geometri dilewati (FK).
- CLI punya mode `--dry-run` untuk memeriksa hasil tanpa DB:
  `python import_podes_xlsx.py --src podes_seed/datageopod.xlsx --dry-run`

### 4.3 Menjalankan
```sh
export DATABASE_URL="postgres://geopod:geopod@localhost:5432/geopod_db"
./seed_geojson.sh
```
Image seed dibangun dari `deploy/seed/Dockerfile.seed` (`python:3.12-slim` +
`psycopg2-binary` + `openpyxl`), dijalankan di network compose (`geopodv2_geopod`).

---

## 5. Backend (Rust/Axum)

### 5.1 Kredensial & Auth
- `JWT_SECRET` (HS256), `APP_ADMIN_USERNAME`, `APP_ADMIN_PASSWORD`.
- Saat start, password di-hash Argon2 (PHC). Login membandingkan hash.
- Token JWT valid 12 jam di cookie `gp_token` (HttpOnly, SameSite=Lax, `Secure`
  hanya jika `APP_ENV=production`).

### 5.2 Endpoints

| Method | Path                              | Auth | Keterangan                          |
| ------ | --------------------------------- | ---- | ----------------------------------- |
| GET    | `/api/kelurahan`                  | -    | daftar singkat `{ items: [...] }`   |
| GET    | `/api/kelurahan/:kode`            | -    | detail + `potensi_desa` JSONB       |
| POST   | `/api/auth/login`                 | -    | set cookie, body `{username,password}` |
| POST   | `/api/auth/logout`                | -    | hapus cookie (`204`)                |
| GET    | `/api/auth/me`                    | admin| username saat ini (401 bila belum)  |
| PUT    | `/api/kelurahan/:kode`            | admin| update nama/kecamatan/`potensi_desa` |
| PUT    | `/api/kelurahan/:kode/geometry`   | admin| body `{geometry}` Polygon/MultiPolygon; luas dihitung ulang |
| POST   | `/api/cache/purge`                | admin| hapus file `CACHE_DIR`              |

Aturan frontend terkait auth: semua fetch memakai `credentials: 'include'`;
tidak ada token di localStorage (anti-XSS).

### 5.3 Menjalankan di mesin dev
```sh
cd backend
cargo check                 # cepat
cargo build --release
```
Butuh Postgres berdiri dan env sesuai (lihat `.env.example` / `DEVELOPER_TUTORIAL`).

---

## 6. Frontend

Stack: Vite + **TypeScript strict** + **Tailwind v4** (`@tailwindcss/vite`) + **MapLibre GL**.
Package manager: **pnpm**.

### 6.1 Menjalankan dev
```sh
cd frontend
pnpm install
pnpm dev          # :5173; /api dan /tiles di-proxy ke localhost param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' }  (stack harus jalan)
pnpm build        # tsc --noEmit && vite build -> dist/
```

### 6.2 Konvensi kode (disepakati)
- **Hanya arrow function** (`const fn = () => {}`); dilarang kata kunci `class`/`function`.
- **No localStorage/sessionStorage**; memori cache pakai `Map` (`src/lib/cache.ts`).
- Semua fetch `credentials: 'include'`.
- Type-only import memakai `import type`.

### 6.3 Peta (`components/MapView.ts`)
- Tile vector dari `/tiles/{z}/{x}/{y}.pbf` (via nginx â†’ Martin â†’ PostGIS).
- **Basemap 100% offline** (sejak keputusan di sesi 2026-09): tidak ada lagi tile
  raster eksternal. Penampil: `basemap-bg` (background) + `sekitar` (GeoJSON
  `frontend/src/data/sekitar.geojson`, boundary kelurahan sekitar dari
  `idn_admin4.shp`) + `kelurahan` (Pagar Alam 35). Alasannya: OSM memblokir IP
  datacenter ("Access blocked"), CARTO mewajibkan API key (watermark
  "API key required", raster sedang di-retire). Blok `location /basemap/` di
  nginx dikomentari + ditutup `return 404`; template upstream (OSM/CARTO/Esri)
  disertakan sebagai komentar untuk aktifkan kembali.
- `maxBounds` dibatasi jendela konteks supaya tidak pan ke area kosong.
- `fallback2d` (non-WebGL) menggambar garis konteks pucat + poligon kelurahan.
- Layer `kelurahan` dengan `promoteId: 'kode_kelurahan'` agar `feature-state`
  (hover/selected) bekerja.
- Klik kelurahan â†’ `openKelurahanModal(kode)`.
- Geometri kelurahan ditarik dari `idn_admin4.shp` (dataset batas admin nasional):
  ekstrak subset via `deploy/seed/extract_admin4.py` lalu import via
  `deploy/seed/import_admin4.py` (properti `iddesa` = `adm4_pcode` tanpa prefiks
  `ID`). 35 fitur Kota Pagar Alam cocok 1:1 dengan `iddesa` di datageopod.xlsx.
- Konteks sekitar: `extract_admin4.py --bbox "103.05,-4.38,103.52,-3.71" --exclude-adm2 ID1673 --out frontend/src/data/sekitar.geojson`
  (230 desa sekitar; jendela bbox harus sesuai `maxBounds` MapView).

### 6.4 Modal per sheet (`components/KelurahanModal.ts` + `meta/tabConfig.ts`)
- Data detail diambil lazy saat modal dibuka, disimpan di cache in-memory.
- `PODES_TABS` memetakan 1 tab = 1 sheet xlsx (10 sheet), urut sesuai nomor sheet;
  label tab & judul card memakai judul sheet asli dari workbook
  (`deploy/seed/import_podes_xlsx.py` membaca `ws.title` langsung):

| Tab (judul sheet asli) | Section key |
| --- | --- |
| I. KETERANGAN TEMPAT | keterangan_tempat |
| III. KETERANGAN UMUM KELURAHAN | umum_kelurahan |
| V. PERUMAHAN DAN LINGKUNGAN HID | perumahan_lingkungan |
| VI. BENCANA ALAM DAN MITIGASI | bencana_mitigasi |
| VII. PENDIDIKAN DAN KESEHATAN | pendidikan_kesehatan |
| VIII. ANGKUTAN, KOMUNIKASI INFO | angkutan_komunikasi |
| IX. EKONOMI | ekonomi |
| X. KEAMANAN | keamanan |
| XI. KEUANGAN DAN ASET DESA | keuangan_aset |
| XII. KETERANGAN APARATUR PEMERI | aparatur |

> Label item (`l`) mengikuti sheet `dict`; nilai (`v`) diambil mentah dari sheet
> (kode Podes 0/1/2/…, tidak didekode). Ubah judul tab di `src/meta/tabConfig.ts`.
> Frontend hanya menampilkan field yang benar-benar ada di JSONB (tanpa paksaan).

### 6.5 Dashboard admin (`pages/AdminDashboardPage.ts`)
- Guard `GET /api/auth/me`; 401 â†’ redireksi ke `/admin/login`.
- Tab Atribut (tabel + modal edit), Geometri (tempel GeoJSON), Cache (purge).
- Setelah mengedit, `invalidateAll()` membersihkan cache frontend.

---

## 7. Properti Anti-Scraping

| Mekanisme | Lokasi |
| --- | --- |
| Rate limit `limit_req_zone` (tiles/api/login) | `deploy/nginx/nginx.conf` |
| Proxy cache 90 hari (GET tile & api) | `deploy/nginx/nginx.conf` + purge via `POST /api/cache/purge` |
| Deny berkas mentah (`.geojson .json .dbf .shp .shx`) | `deploy/nginx/nginx.conf` |
| Max zoom tile = 14 | `deploy/martin/martin.yaml` |
| Auth HttpOnly cookie | `backend/src/auth.rs` |

---

## 8. Checklist Perubahan Umum

1. **Tambah tab baru** â†’ edit `src/meta/tabConfig.ts`.
2. **Tambah kolom/field** â†’ cukup tambahkan di sheet Excel + seeder; JSONB otomatis.
3. **Ubah password admin** â†’ ganti `APP_ADMIN_PASSWORD` di `.env`, restart backend.
4. **Data berubah tapi peta lama** â†’ purge cache (menu Cache / `POST /api/cache/purge`).
5. **Ganti sumber geometri** â†’ letakkan file di `geojson_seed/`, isi `SEED_CODE_FIELD`
   bila kolom kode bukan `iddesa`.
6. **Perbarui tile config** â†’ `deploy/martin/martin.yaml`, restart martin.