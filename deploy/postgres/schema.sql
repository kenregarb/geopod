-- GEOPOD v2 initial schema
-- Database: PostGIS 16 + PostGIS 3.4

CREATE EXTENSION IF NOT EXISTS postgis;

-- ===================== GEOMETRI KELURAHAN =====================
-- Menyimpan geometri spasial kelurahan (Polygon/MultiPolygon/Point/MultiPoint).
-- Kolom `geom` bertipe generic GEOMETRY sehingga mendukung polygon maupun point.
CREATE TABLE IF NOT EXISTS kelurahan_geom (
    id SERIAL PRIMARY KEY,
    kode_kelurahan VARCHAR(20) UNIQUE NOT NULL,
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kelurahan_geom_kode ON kelurahan_geom (kode_kelurahan);
CREATE INDEX IF NOT EXISTS idx_kelurahan_geom_gist ON kelurahan_geom USING GIST (geom);

-- ===================== ATRIBUT & POTENSI DESA =====================
-- potensi_desa (JSONB) menampung seluruh data atribut Podes dinamis,
-- diorganisasi per section (keterangan_tempat, umum_kelurahan, dst).
CREATE TABLE IF NOT EXISTS kelurahan_attribute (
    id SERIAL PRIMARY KEY,
    kode_kelurahan VARCHAR(20) UNIQUE NOT NULL
        REFERENCES kelurahan_geom (kode_kelurahan) ON DELETE CASCADE,
    nama_kelurahan VARCHAR(100),
    nama_kecamatan VARCHAR(100),
    luas_wilayah NUMERIC(10, 2),
    potensi_desa JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kelurahan_attribute_kode ON kelurahan_attribute (kode_kelurahan);
CREATE INDEX IF NOT EXISTS idx_kelurahan_attribute_gin_podes ON kelurahan_attribute USING GIN (potensi_desa);

-- ===================== TRIGGER updated_at =====================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_kelurahan_geom_updated') THEN
        CREATE TRIGGER trg_kelurahan_geom_updated
        BEFORE UPDATE ON kelurahan_geom
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_kelurahan_attribute_updated') THEN
        CREATE TRIGGER trg_kelurahan_attribute_updated
        BEFORE UPDATE ON kelurahan_attribute
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;