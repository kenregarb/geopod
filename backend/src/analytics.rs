use crate::db::AnalyticsRow;
use serde_json::{json, Value};

fn field_value(potensi: &Value, code: &str) -> Option<String> {
    let sections = potensi.get("sections")?.as_object()?;
    for sec in sections.values() {
        let fields = sec.get("fields")?.as_array()?;
        for f in fields {
            if f.get("k").and_then(Value::as_str) == Some(code) {
                let v = f.get("v").and_then(Value::as_str)?;
                return Some(v.to_string());
            }
        }
    }
    None
}

fn emptied(v: &str) -> bool {
    let t = v.trim();
    t.is_empty() || t == "–"
}

fn nonempty(v: &str) -> bool {
    !emptied(v)
}

fn parse_int(v: &str) -> i64 {
    v.trim().parse::<i64>().unwrap_or(0)
}

fn bencana_list(potensi: &Value) -> Vec<String> {
    let mut out = Vec::new();
    let Some(sections) = potensi.get("sections").and_then(Value::as_object) else {
        return out;
    };
    for sec in sections.values() {
        let Some(fields) = sec.get("fields").and_then(Value::as_array) else {
            continue;
        };
        for f in fields {
            let k = f.get("k").and_then(Value::as_str).unwrap_or("");
            if k.len() == 7 && k.starts_with("r601") && k.ends_with("k2") {
                let v = f.get("v").and_then(Value::as_str).unwrap_or("");
                let t = v.trim();
                if t != "Tidak ada" && nonempty(t) {
                    let label = f.get("l").and_then(Value::as_str).unwrap_or(k);
                    let name = label.split(':').next().unwrap_or(label).trim().to_string();
                    if !out.contains(&name) {
                        out.push(name);
                    }
                }
            }
        }
    }
    out
}

pub fn compute(rows: &[AnalyticsRow]) -> Value {
    let mut perdesaan = 0i64;
    let mut perkotaan = 0i64;
    let mut rw = 0i64;
    let mut rt = 0i64;
    let mut pln = 0i64;
    let mut non_pln = 0i64;
    let mut tanpa_listrik = 0i64;
    let mut bts = 0i64;
    let mut with_produk = 0i64;
    let mut with_angkutan = 0i64;
    let mut with_bencana = 0i64;
    let mut with_peringatan = 0i64;
    let mut imk_total = 0i64;
    let mut luas_total = 0.0f64;
    let mut items: Vec<Value> = Vec::with_capacity(rows.len());

    for row in rows {
        let potensi = row
            .potensi_desa
            .as_ref()
            .map(|j| j.0.clone())
            .unwrap_or_else(|| json!({}));
        let get = |code: &str| field_value(&potensi, code).unwrap_or_default();

        let kelas = get("r105");
        let is_perdesaan = kelas == "Perdesaan";
        let is_perkotaan = kelas == "Perkotaan";
        if is_perdesaan {
            perdesaan += 1;
        } else if is_perkotaan {
            perkotaan += 1;
        }

        let rwv = parse_int(&get("r304a"));
        let rtv = parse_int(&get("r304b"));
        let plnv = parse_int(&get("r501a1"));
        let non_plnv = parse_int(&get("r501a2"));
        let tanpa_listrik_v = parse_int(&get("r501b"));
        let bts_v = parse_int(&get("r804a"));
        rw += rwv;
        rt += rtv;
        pln += plnv;
        non_pln += non_plnv;
        tanpa_listrik += tanpa_listrik_v;
        bts += bts_v;

        let mut produk: Vec<String> = Vec::new();
        for code in ["r908b1", "r908b2"] {
            let v = get(code);
            if nonempty(&v) {
                produk.push(v);
            }
        }
        let bencana = bencana_list(&potensi);
        let angkutan = get("r801c1").starts_with("Ada");
        let imk_v = parse_int(&get("r907a"));
        let peringatan_v = get("r602a").trim().to_string();
        if !produk.is_empty() {
            with_produk += 1;
        }
        if angkutan {
            with_angkutan += 1;
        }
        if !bencana.is_empty() {
            with_bencana += 1;
        }
        if nonempty(&peringatan_v) && peringatan_v != "Tidak" {
            with_peringatan += 1;
        }
        imk_total += imk_v;
        if let Some(l) = row.luas_wilayah {
            luas_total += l;
        }

        items.push(json!({
            "kode_kelurahan": row.kode_kelurahan,
            "nama_kelurahan": row.nama_kelurahan,
            "nama_kecamatan": row.nama_kecamatan,
            "luas_wilayah": row.luas_wilayah,
            "klasifikasi": if kelas.is_empty() { "–" } else { &kelas },
            "rw": rwv,
            "rt": rtv,
            "pln": plnv,
            "non_pln": non_plnv,
            "tanpa_listrik": tanpa_listrik_v,
            "bts": bts_v,
            "produk_unggulan": produk,
            "bencana": bencana,
            "angkutan_umum": angkutan,
        }));
    }

    let total = rows.len() as i64;
    let lain = (total - perdesaan - perkotaan).max(0);

    json!({
        "tahun": 2025,
        "updated": "2025",
        "aggregates": {
            "total_kelurahan": total,
            "perdesaan": perdesaan,
            "perkotaan": perkotaan,
            "klasifikasi_lain": lain,
            "rw": rw,
            "rt": rt,
            "pln": pln,
            "non_pln": non_pln,
            "tanpa_listrik": tanpa_listrik,
            "bts": bts,
            "dengan_produk_unggulan": with_produk,
            "dengan_angkutan_umum": with_angkutan,
            "dengan_bencana": with_bencana,
            "dengan_peringatan_dini": with_peringatan,
            "imk": imk_total,
            "luas_wilayah": (luas_total * 100.0).round() / 100.0
        },
        "donuts": [
            {
                "id": "klasifikasi",
                "title": "Klasifikasi Wilayah",
                "entries": [
                    { "label": "Perdesaan", "value": perdesaan },
                    { "label": "Perkotaan", "value": perkotaan }
                ]
            },
            {
                "id": "produk",
                "title": "Produk Unggulan",
                "entries": [
                    { "label": "Dengan produk unggulan", "value": with_produk },
                    { "label": "Tanpa", "value": total - with_produk }
                ]
            },
            {
                "id": "peringatan",
                "title": "Fasilitas peringatan dini bencana alam",
                "entries": [
                    { "label": "Ada", "value": with_peringatan },
                    { "label": "Tidak ada", "value": total - with_peringatan }
                ]
            }
        ],
        "items": items
    })
}