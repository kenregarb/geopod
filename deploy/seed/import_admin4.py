#!/usr/bin/env python3
"""GEOPOD v2 - Import geometri admin4 (dari hasil ekstraksi idn_admin4.shp).

Meng-update/upsert geometri ke `kelurahan_geom` berdasarkan properti `iddesa`,
menghitung ulang luas_wilayah, lalu melaporkan kecocokan terhadap
`kelurahan_attribute`. Tidak mengubah nama kelurahan yang sudah ada.

Pemakaian:
    python import_admin4.py --src /data/pagaralam_admin4.geojson

Env: DATABASE_URL / GEOPOD_DB_URL
"""
import argparse
import json
import os
import sys
from pathlib import Path


def connect():
    try:
        import psycopg2  # noqa
    except ImportError as e:
        sys.exit(f"[admin4] psycopg2 tidak terpasang di container: {e}")
    url = os.environ.get("DATABASE_URL") or os.environ.get("GEOPOD_DB_URL")
    if not url:
        sys.exit("[admin4] Set DATABASE_URL / GEOPOD_DB_URL.")
    return psycopg2.connect(url)


def norm(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else str(v)
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    args = ap.parse_args()
    path = Path(args.src)
    if not path.exists():
        sys.exit(f"[admin4] File tidak ada: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    feats = data.get("features", []) if isinstance(data, dict) else []
    items = [(norm(f.get("properties", {}).get("iddesa")), f.get("geometry")) for f in feats]
    items = [(c, g) for c, g in items if c and g]

    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT kode_kelurahan FROM kelurahan_attribute")
        attr_codes = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT kode_kelurahan FROM kelurahan_geom")
        geom_codes = {r[0] for r in cur.fetchall()}

        ok = 0
        for code, geom in items:
            cur.execute(
                """
                INSERT INTO kelurahan_geom (kode_kelurahan, geom)
                VALUES (%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                ON CONFLICT (kode_kelurahan)
                DO UPDATE SET geom = EXCLUDED.geom, updated_at = NOW()
                """,
                (code, json.dumps(geom)),
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
            ok += 1
        conn.commit()

        got_codes = {c for c, _ in items}
        orphan = sorted(got_codes - attr_codes)
        no_geom = sorted(attr_codes - geom_codes | (attr_codes - got_codes))
        cur.execute(
            "SELECT count(*) FROM kelurahan_geom WHERE NOT ST_IsValid(geom)"
        )
        invalid = cur.fetchone()[0]
    conn.close()

    print(f"[admin4] diimpor: {ok} geometri")
    print(f"[admin4] iddesa di file tanpa atribut (calon yatim): {orphan}")
    print(f"[admin4] iddesa atribut tanpa geometri setelah ini: {sorted(no_geom)}")
    print(f"[admin4] geometri invalid: {invalid}")


if __name__ == "__main__":
    main()