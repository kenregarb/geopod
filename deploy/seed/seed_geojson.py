#!/usr/bin/env python3
"""GEOPOD v2 - Seeder geometri (GeoJSON / SHP+DBF) ke PostGIS.

Membaca seluruh file .geojson/.json (FeatureCollection) dan/atau .shp (bila
file .dbf pendampingnya ada) dari folder sumber, lalu meng-insert/update
geometri ke tabel `kelurahan_geom` (ON CONFLICT kode_kelurahan DO UPDATE).

Support geometry: Polygon, MultiPolygon, Point, MultiPoint (via GeoJSON).
SHP di-parse secara native (tanpa GDAL) sehingga image container tetap ringan.

Penggunaan:
    python seed_geojson.py --src ./geojson_seed
    python seed_geojson.py --src ./geojson_seed --shp idn_admin4.shp --match-prefix 1673

Env:
    DATABASE_URL / GEOPOD_DB_URL  : koneksi Postgres (wajib)
    SEED_CODE_FIELD               : nama properti kode (default: otomatis)
    SEED_NAME_FIELD               : nama properti nama (default: otomatis)
    SEED_MATCH_PREFIX             : filter kode diawali awalan (mis. "1673")
"""
import argparse
import json
import os
import struct
import sys
from pathlib import Path

CODE_CANDIDATES = ["iddesa", "kode_kelurahan", "kode_desa", "kode_des", "KODE", "ID", "id"]
NAME_CANDIDATES = ["nama_kelurahan", "nama_desa", "nmdesa", "NAME", "NAMA", "name"]


# ---------------------------------------------------------------------------
# Koneksi database
# ---------------------------------------------------------------------------
def connect():
    try:
        import psycopg2  # noqa
        import psycopg2.extras  # noqa
    except ImportError as e:
        sys.exit(f"[seed] psycopg2 tidak terpasang di container: {e}")
    url = os.environ.get("DATABASE_URL") or os.environ.get("GEOPOD_DB_URL")
    if not url:
        sys.exit("[seed] Set DATABASE_URL / GEOPOD_DB_URL.")
    return psycopg2.connect(url)


# ---------------------------------------------------------------------------
# Helper nilai
# ---------------------------------------------------------------------------
def norm_code(v):
    """Normalisasi kode dari angka/DNA/string menjadi string kulat bersih."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            return str(int(v))
        return str(v)
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def pick(props, candidates):
    for k in candidates:
        if k in props and props[k] not in (None, ""):
            return norm_code(props[k])
    return None


# ---------------------------------------------------------------------------
# Parser SHP biner mini (Polygon / MultiPolygon / Point / MultiPoint)
# ---------------------------------------------------------------------------
def shp_read_int32(buf, off):
    """Integer pada konten geometri SHP selalu little-endian."""
    return struct.unpack_from("<i", buf, off)[0]


def shp_read_double(buf, off):
    """Double pada konten geometri SHP selalu little-endian."""
    return struct.unpack_from("<d", buf, off)[0]


def ring_geo(points, close=True):
    pts = list(points)
    if close and len(pts) > 1 and pts[0] != pts[-1]:
        pts.append(pts[0])
    return [[round(x, 6), round(y, 6)] for x, y in pts]


def ring_area(pts):
    """Luas bertanda (shoelace). Orientasi CW bernilai negatif, CCW positif."""
    if len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def parse_polygon(buf, off, num_parts, num_points, point_off):
    parts = [
        shp_read_int32(buf, point_off + i * 4)
        for i in range(num_parts)
    ]
    parts.append(num_points)
    rings = []
    for i in range(num_parts):
        start, end = parts[i], parts[i + 1]
        coords = []
        for j in range(start, end):
            x = shp_read_double(buf, point_off + num_parts * 4 + j * 16)
            y = shp_read_double(buf, point_off + num_parts * 4 + j * 16 + 8)
            coords.append((x, y))
        rings.append(ring_geo(coords))

    if num_parts == 1:
        return {"type": "Polygon", "coordinates": [rings[0]]}

    # Klasifikasi ring: outer (orientasi utama) mulai polygon baru,
    # ring berlawanan menjadi hole dari polygon terakhir.
    first = ring_area(rings[0])
    outer_sign = -1 if first <= 0 else 1
    polygons = []
    current = None
    for r in rings:
        if ring_area(r) * outer_sign >= 0:
            if current is not None:
                polygons.append(current)
            current = [r]
        else:
            if current is not None:
                current.append(r)
    if current is not None:
        polygons.append(current)

    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def parse_shp_geometry_buf(buf):
    """Mengembalikan geometry GeoJSON dict dari konten satu record SHP."""
    shape_type = shp_read_int32(buf, 0)
    if shape_type == 1:  # Point
        return {"type": "Point", "coordinates": [round(shp_read_double(buf, 4), 6),
                                                 round(shp_read_double(buf, 12), 6)]}
    if shape_type == 3:  # PolyLine -> tidak dipakai, lewati
        return None
    if shape_type == 5:  # Polygon
        num_parts = shp_read_int32(buf, 36)
        num_points = shp_read_int32(buf, 40)
        point_off = 44
        return parse_polygon(buf, 44, num_parts, num_points, point_off)
    if shape_type == 8:  # MultiPoint
        num_points = shp_read_int32(buf, 36)
        coords = []
        for j in range(num_points):
            x = shp_read_double(buf, 40 + j * 16)
            y = shp_read_double(buf, 40 + j * 16 + 8)
            coords.append([round(x, 6), round(y, 6)])
        return {"type": "MultiPoint", "coordinates": coords}
    if shape_type in (11,):  # PointZ
        return {"type": "Point", "coordinates": [round(shp_read_double(buf, 4), 6),
                                                 round(shp_read_double(buf, 12), 6)]}
    if shape_type in (13, 15, 18, 25, 28, 31):  # zi/z/m polygon/polyline/polygon
        num_parts = shp_read_int32(buf, 36)
        num_points = shp_read_int32(buf, 40)
        return parse_polygon(buf, 44, num_parts, num_points, 44)
    return None


def iter_shp_features(shp_path):
    """Streaming reader SHP agar hemat RAM (file besar seperti idn_admin4.shp)."""
    with shp_path.open("rb") as fp:
        header = fp.read(100)
        if len(header) < 100:
            return
        shape_type = struct.unpack_from("<i", header, 32)[0]
        if shape_type != 5:
            sys.stderr.write(f"[seed] {shp_path.name}: hanya mendukung Polygon/MultiPolygon (shape type 5).\n")
            return

        rec_num = 0
        while True:
            rec_header = fp.read(8)
            if len(rec_header) < 8:
                break
            rec_num = struct.unpack_from(">i", rec_header, 0)[0]
            content_words = struct.unpack_from(">i", rec_header, 4)[0]
            content_len = content_words * 2
            content = fp.read(content_len)
            if len(content) < content_len:
                break
            geom = parse_shp_geometry_buf(content)
            if geom is not None:
                yield (rec_num, geom)


# ---------------------------------------------------------------------------
# Parser DBF mini (dengan/tanpa deletion-flag byte)
# ---------------------------------------------------------------------------
def parse_dbf(dbf_path):
    b = dbf_path.read_bytes()
    if len(b) < 33:
        return []
    num_records = struct.unpack_from("<I", b, 4)[0]
    header_len = struct.unpack_from("<H", b, 8)[0]
    record_len = struct.unpack_from("<H", b, 10)[0]
    fields = []
    off = 32
    while off + 32 <= header_len - 1:
        raw_name = b[off:off + 11].split(b"\x00")[0].decode("latin1").strip()
        ftype = chr(b[off + 11])
        flen = b[off + 16]
        if not raw_name:
            break
        fields.append((raw_name, ftype, flen))
        off += 32

    sum_len = sum(f[2] for f in fields)
    flag_size = 0 if sum_len == record_len else 1

    rows = []
    rec = header_len
    for _ in range(num_records):
        if rec + record_len > len(b):
            break
        p = rec + flag_size
        row = {}
        for (name, ftype, flen) in fields:
            raw = b[p:p + flen].decode("latin1").strip().rstrip("\x00").strip()
            v = raw
            if ftype in ("N", "F"):
                v = raw
            row[name.lower()] = v
            p += flen
        rows.append(row)
        rec += record_len
    return rows


def shp_features_with_attrs(shp_path, dbf_path, code_field=None, name_field=None, match_prefix=None):
    rows = parse_dbf(dbf_path)
    fields = rows[0].keys() if rows else []
    code_key = None
    for cand in (code_field,) if code_field else CODE_CANDIDATES:
        if cand.lower() in fields:
            code_key = cand.lower()
            break
    name_key = None
    for cand in (name_field,) if name_field else NAME_CANDIDATES:
        if cand.lower() in fields:
            name_key = cand.lower()
            break
    if code_key is None:
        sys.stderr.write(f"[seed] DBF {dbf_path.name}: tidak ada kolom kode dikenal "
                         f"({', '.join(sorted(fields))}).\n")
        return

    for i, (rec_num, geom) in enumerate(iter_shp_features(shp_path)):
        attrs = rows[i] if i < len(rows) else {}
        code = norm_code(attrs.get(code_key))
        if code is None:
            continue
        if match_prefix and not code.startswith(match_prefix):
            continue
        name = norm_code(attrs.get(name_key)) if name_key else None
        yield code, name, geom


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------
def geojson_features(path, code_field=None, name_field=None, match_prefix=None):
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", []) if isinstance(data, dict) else []
    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        if not geom:
            continue
        code = pick(props, [code_field] if code_field else CODE_CANDIDATES)
        if code is None:
            continue
        if match_prefix and not code.startswith(match_prefix):
            continue
        name = pick(props, [name_field] if name_field else NAME_CANDIDATES)
        gtype = geom.get("type")
        if gtype == "GeometryCollection":
            sys.stderr.write(f"[seed] lewati GeometryCollection: {path.name}\n")
            continue
        yield code, name, geom


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def upsert(conn, code, name, geom):
    geom_json = json.dumps(geom)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kelurahan_geom (kode_kelurahan, geom)
            VALUES (%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
            ON CONFLICT (kode_kelurahan)
            DO UPDATE SET geom = EXCLUDED.geom, updated_at = NOW()
            """,
            (code, geom_json),
        )
        cur.execute(
            """
            INSERT INTO kelurahan_attribute (kode_kelurahan, nama_kelurahan)
            VALUES (%s, %s)
            ON CONFLICT (kode_kelurahan)
            DO UPDATE SET nama_kelurahan = EXCLUDED.nama_kelurahan
            """,
            (code, name),
        )
        cur.execute(
            """
            UPDATE kelurahan_attribute
            SET luas_wilayah = ROUND(
                    (ST_Area((SELECT geom FROM kelurahan_geom WHERE kode_kelurahan = %s), TRUE)
                     / 10000.0)::numeric, 2
                )
            WHERE kode_kelurahan = %s
            """,
            (code, code),
        )
    conn.commit()


def main():
    ap = argparse.ArgumentParser(description="Seeder geometri Geopod v2")
    ap.add_argument("--src", required=True, help="Folder berisi .geojson/.json/.shp")
    ap.add_argument("--shp", help="Path spesifik ke file .shp (boleh kosong; otomatis di-scan)")
    ap.add_argument("--code-field", default=os.environ.get("SEED_CODE_FIELD"))
    ap.add_argument("--name-field", default=os.environ.get("SEED_NAME_FIELD"))
    ap.add_argument("--match-prefix", default=os.environ.get("SEED_MATCH_PREFIX"))
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        sys.exit(f"[seed] Folder sumber tidak ada: {src}")

    conn = connect()
    ok = skipped = 0

    # 1) GeoJSON/JSON
    for f in sorted(src.glob("*")):
        if f.suffix.lower() not in (".geojson", ".json"):
            continue
        try:
            for code, name, geom in geojson_features(f, args.code_field, args.name_field, args.match_prefix):
                upsert(conn, code, name, geom)
                ok += 1
        except Exception as e:  # noqa
            sys.stderr.write(f"[seed] ERROR {f.name}: {e}\n")
            skipped += 1

    # 2) SHP (butuh .dbf pendamping)
    shp_files = [Path(args.shp)] if args.shp else list(src.glob("*.shp"))
    for shp in shp_files:
        if not shp:
            continue
        dbf = shp.with_suffix(".dbf")
        if not dbf.exists():
            sys.stderr.write(f"[seed] SHP {shp.name} tanpa .dbf -> dilewati (atribut kode tidak tersedia).\n")
            skipped += 1
            continue
        try:
            for code, name, geom in shp_features_with_attrs(
                shp, dbf, args.code_field, args.name_field, args.match_prefix
            ):
                upsert(conn, code, name, geom)
                ok += 1
        except Exception as e:  # noqa
            sys.stderr.write(f"[seed] ERROR {shp.name}: {e}\n")
            skipped += 1

    conn.close()
    print(f"[seed] Selesai: {ok} fitur di-import, {skipped} dilewati/error.")


if __name__ == "__main__":
    main()