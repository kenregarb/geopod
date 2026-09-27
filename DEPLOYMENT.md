# Deployment Geopod v2

Panduan men-deploy aplikasi Geopod v2 di server VPS (Linux) dengan **podman** + **podman-compose**.
Target spesifikasi: VPS 1 vCPU / 1 GB RAM / 20 GB disk.

---

## 1. Prasyarat Server

```sh
# Debian/Ubuntu
sudo apt update
sudo apt install -y podman podman-compose
```

Catatan Windows: podman dipakai **di VPS**, bukan di mesin pengembangan. Di mesin
Windows cukup `git`, `node`+`pnpm`, dan Rust (lihat `DEVELOPER_TUTORIAL.md`).

---

## 2. Menyiapkan Folder Proyek

Kirim seluruh folder proyek ke VPS (mis. ke `/srv/geopodv2`), pastikan berisi:

```
podman-compose.yml
.env                          (lihat langkah 4)
seed_geojson.sh
deploy/
  nginx/nginx.conf
  martin/martin.yaml
  postgres/schema.sql
  seed/                       (seed_geojson.py, import_podes_xlsx.py, Dockerfile.seed)
frontend/dist/                (hasil build vite, langkah 3)
geojson_seed/                 (peta_desa_202511673.geojson, dll.)
podes_seed/                   (datageopod.xlsx)
```

---

## 3. Build Frontend (di mesin pengembangan)

```sh
cd frontend
pnpm install
pnpm build          # hasil: frontend/dist/
```

Salin `frontend/dist` ke VPS menjadi `frontend/dist` (mount nginx memakai folder ini).

---

## 4. Konfigurasi `.env`

```sh
cp .env.example .env
nano .env
```

Variabel yang WAJIB diganti:

| Variabel               | Keterangan                                     |
| ---------------------- | ---------------------------------------------- |
| `JWT_SECRET`           | string acak panjang, mis. `openssl rand -hex 32` |
| `APP_ADMIN_PASSWORD`   | password login dashboard admin                 |
| `POSTGRES_PASSWORD`    | password database (idealnya acak juga)         |

Kontainer `geodb`, `martin`, dan `backend` membaca variabel ini dari `.env`.
Seeding memakai `DATABASE_URL` yang diexport manual (langkah 6).

---

## 5. Menjalankan Stack

```sh
podman-compose up -d
podman-compose ps          # pastikan 4 kontainer sehat (geodb punya healthcheck)
```

Port publik: **3333**.

- Peta publik : `http://<IP-SERVER> param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' } /`
- Dashboard admin: `http://<IP-SERVER> param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' } /admin` (otomatis ke `/admin/login`)

Firewall: buka port 3333, mis. `sudo ufw allow 3333/tcp`.

---

## 6. Seeding Data

Geometri harus masuk **dulu** karena `kelurahan_attribute` memiliki foreign key
ke `kelurahan_geom`.

```sh
# Dari folder proyek di VPS, setelah geodb sehat:
export DATABASE_URL="postgres://geopod:geopod@localhost:5432/geopod_db"
./seed_geojson.sh
```

Script ini (a) membangun image seed, (b) mengimpor semua `.geojson/.json` dan
`.shp`+`.dbf` di `geojson_seed/`, (c) mengimpor semua `.xlsx` di `podes_seed/`
(dengan kode `iddesa` sebagai `kode_kelurahan`).

Filter hanya Kota Pagar Alam (opsional):

```sh
export SEED_MATCH_PREFIX="1673"
```

Jika `.shp` tanpa `.dbf`, script melewatinya dengan peringatan â€” sediakan `.dbf`
pendamping atau pakai `.geojson` (contoh `peta_desa_202511673.geojson` sudah
memuat properti `iddesa`).

Verifikasi:

```sh
podman exec geopod-geodb psql -U gepod -d gepod_db -c "SELECT count(*) FROM kelurahan_geom;"
podman exec geopod-geodb psql -U gepod -d gepod_db -c "SELECT kode_kelurahan, nama_kelurahan, luas_wilayah FROM kelurahan_attribute LIMIT 5;"
```

Uji tile (nginx menulis ulang `/tiles/` ke Martin):

```sh
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost param($m) if ($m.Value -eq ':3333') { ':3433' } else { '3433:' } /tiles/8/237/128.pbf
# harapan: 200 application/vnd.mapbox-vector-tile
```

---

## 7. Operasional Harian

### Memperbarui data Podes
Ganti `podes_seed/datageopod.xlsx`, jalankan ulang `./seed_geojson.sh`
(impor *upsert*, idempoten).

### Mengubah data lewat dashboard
Login `/admin`:

- **Atribut** â€” ubah nama kelurahan, kecamatan, atau data Podes (JSON) per kelurahan.
- **Geometri** â€” tempel GeoJSON `Polygon`/`MultiPolygon`; luas wilayah dihitung ulang otomatis.
- **Cache** â€” bersihkan cache nginx (90 hari) setelah perubahan agar peta & API langsung terlihat baru.

### Backup database
```sh
podman exec geopod-geodb pg_dump -U gepod -d gepod_db | gzip > gepod-$(date +%F).sql.gz
```
Restore: `gunzip -c gepod-*.sql.gz | podman exec -i geopod-geodb psql -U gepod -d gepod_db`.

---

## 8. Keamanan & Proteksi

- **Rate limit nginx**: tile 35 r/s, API 7 r/s, login 3 r/m (dengan burst). Melebihi ->
  HTTP 429.
- **Cache respons**: GET tile & API di-cache nginx hingga 90 hari (anti-scraping &
  hemat CPU). Perubahan data perlu purge cache.
- **Auth**: cookie `gp_token` HttpOnly + SameSite=Lax; jwt HS256; password admin
  diverifikasi dengan Argon2 (hash dibuat saat kontainer start dari `APP_ADMIN_PASSWORD`).
- **Deny file mentah**: `.geojson/.json/.dbf/.shp/.shx` diblokir di nginx.
- **Max zoom tile 14** membatasi detail koordinat pada zoom tinggi.
- Ganti `JWT_SECRET` dan ganti `APP_ADMIN_PASSWORD` setelah deploy pertama.

---

## 9. Troubleshooting

| Gejala                          | Penyebab umum / solusi                                                    |
| ------------------------------- | ------------------------------------------------------------------------- |
| `geodb` restart terus           | healthcheck gagal; cek log `podman logs geopod-geodb`                     |
| Tile 404 / peta kosong          | Belum seed geometri atau salah `id_column` Martin                         |
| API 429 saat tes                | Normal: rate limit; login memakai lokasi `3r/m`                           |
| Login gagal                    | `APP_ADMIN_PASSWORD` salah / kosong; hash dibuat saat container start     |
| `curl` tile 200 tapi peta kosong | Pastikan `frontend/dist` ter-build dan ter-mount; cek console browser     |
| .dbf belum ada                  | Seeder men-skip SHP itu; gunakan GeoJSON atau tunggu `.dbf` diberikan     |