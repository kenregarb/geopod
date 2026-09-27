LETAKKAN FILE GEOMETRI DI SINI
=============================

KEHAP PRIA: .geojson / .json (FeatureCollection) dengan properti `iddesa`
(or `kode_kelurahan`) dan `nama_desa`.

    XprContoh: peta_desa_202511673.geojson

Atau file SHP + DBF pendampingnya (wajib ada .dbf untuk atribut kode):
    idn_admin4.shp
    idn_admin4.dbf   <- dibutuhkan (kolom kode, mis. `iddesa`)

Setelah file diletakkan, jalankan:
    DATABASE_URL="postgres://..." ./seed_geojson.sh

Filter wilayah per kabupaten: SEED_MATCH_PREFIX="1673" (Kota Pagar Alam).