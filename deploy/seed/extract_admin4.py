#!/usr/bin/env python3
"""GEOPOD v2 - Ekstrak subset admin-4 (desa/kelurahan) dari idn_admin4.shp ke GeoJSON.

Dua mode:
1. Kelurahan satu kabupaten/kota (default): filter `--adm2` (mis. ID1673 = Kota
   Pagar Alam). Digunakan untuk mengisi `kelurahan_geom` via import_admin4.py.
2. Konteks wilayah (basemap offline): filter `--bbox "w,s,e,n"` berdasarkan
   centro id (center_lon/lat), dengan `--exclude-adm2` untuk membuang kelurahan
   yang sudah digambar terpisah (mis. ID1673). Digunakan sebagai layer konteks
   ringan di sekitar Pagar Alam.

Properti `iddesa` diambil dari adm4_pcode (tanpa prefiks "ID") agar cocok dengan
kode kelurahan pada datageopod.xlsx. Geometri dibangun ulang dari ring + orientasi
(hole) sehingga menghasilkan Polygon/MultiPolygon GeoJSON yang valid.

Kebutuhan: pyshp (jalankan di host; container seed tidak memerlukan pyshp).

Pemakaian:
    python extract_admin4.py --shp D:\\datageopodv2\\idn_admin4.shp --adm2 ID1673 --out D:\\datageopodv2\\pagaralam_admin4.geojson
    python extract_admin4.py --shp D:\\datageopodv2\\idn_admin4.shp --bbox "103.05,-4.38,103.52,-3.71" --exclude-adm2 ID1673 --out frontend\\src\\data\\sekitar.geojson
"""
import argparse
import json
import sys
from pathlib import Path


def ring_geo(points, close=True):
    pts = list(points)
    if close and len(pts) > 1 and pts[0] != pts[-1]:
        pts.append(pts[0])
    return [[round(x, 6), round(y, 6)] for x, y in pts]


def ring_area(pts):
    if len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def build_geometry(shape):
    """Konversi shape SHP (pyshp) menjadi dict geometry GeoJSON (valid)."""
    parts = list(shape.parts) + [len(shape.points)]
    rings = [ring_geo(shape.points[parts[i]:parts[i + 1]]) for i in range(len(shape.parts))]

    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": [rings[0]]}

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


def main():
    ap = argparse.ArgumentParser(description="Ekstrak admin-4 dari idn_admin4.shp ke GeoJSON")
    ap.add_argument("--shp", required=True, help="Path ke idn_admin4.shp")
    ap.add_argument("--adm2", default="ID1673", help="Kode adm2 untuk difilter (mode kelurahan)")
    ap.add_argument("--bbox", help="lonMin,latMin,lonMax,latMax untuk seleksi konteks by centroid")
    ap.add_argument("--exclude-adm2", default="ID1673", help="adm2 yang dikecualikan pada mode bbox")
    ap.add_argument("--out", required=True, help="Path output .geojson")
    args = ap.parse_args()

    shp_path = Path(args.shp)
    if not shp_path.exists():
        sys.exit(f"[extract] file tidak ada: {shp_path}")

    try:
        import shapefile  # pyshp
    except ImportError as e:
        sys.exit(f"[extract] pyshp tidak terpasang di host: {e}")

    bbox = None
    if args.bbox:
        try:
            w, s, e, n = [float(v) for v in args.bbox.replace(" ", "").split(",")]
            bbox = (w, s, e, n)
        except ValueError:
            sys.exit("[extract] --bbox harus 'lonMin,latMin,lonMax,latMax'.")
        if w >= e or s >= n:
            sys.exit("[extract] --bbox tidak valid (lonMin<lonMax, latMin<latMax).")

    reader = shapefile.Reader(str(shp_path))
    feats = []
    for sr in reader.iterShapeRecords():
        rec = sr.record.as_dict()
        if bbox is not None:
            lon = rec.get("center_lon")
            lat = rec.get("center_lat")
            if lon is None or lat is None:
                continue
            if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                continue
            if str(rec.get("adm2_pcode", "")).lower() == args.exclude_adm2.lower():
                continue
        else:
            if str(rec.get("adm2_pcode", "")).lower() != args.adm2.lower():
                continue
        iddesa = str(rec.get("adm4_pcode", "")).removeprefix("ID")
        if not iddesa:
            continue
        geom = build_geometry(sr.shape)
        props = {
            "iddesa": iddesa,
            "kecamatan": rec.get("adm3_name"),
        }
        if bbox is not None:
            props["kabupaten"] = rec.get("adm2_name")
        else:
            props["nama_kelurahan"] = rec.get("adm4_name")
        feats.append({
            "type": "Feature",
            "properties": props,
            "geometry": geom,
        })
    reader.close()

    if not feats:
        where = f"bbox={args.bbox} (kecuali adm2={args.exclude_adm2})" if bbox else f"adm2={args.adm2}"
        sys.exit(f"[extract] tidak ada fitur untuk {where}; output tidak dibuat.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[extract] {len(feats)} fitur -> {out}")
    print(f"[extract] iddesa pertama: {sorted(f['properties']['iddesa'] for f in feats)[:3]} ...")


if __name__ == "__main__":
    main()