//! Synthetic fixture evidence, NOT a SemanticEngine/SharedEncoder loader test.
//! cargo run --release --features semantic --example source_pack_probe -- PACK [SECOND_PACK]
pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[path = "../src/semantic_federation.rs"]
mod semantic_federation;

#[cfg(feature = "semantic")]
mod probe {
    use super::{semantic_federation, Result};
    use rusqlite::{params, Connection, OpenFlags};
    use serde_json::{json, Value};
    use sha2::{Digest, Sha256};
    use std::{collections::BTreeSet, path::{Path, PathBuf}};
    use usearch::{Index, MetricKind, ScalarKind};

    fn require(ok: bool, message: &str) -> Result<()> {
        if ok { Ok(()) } else { Err(message.into()) }
    }
    fn text<'a>(v: &'a Value, field: &str) -> Result<&'a str> {
        v[field].as_str().filter(|s| !s.trim().is_empty())
            .ok_or_else(|| format!("missing/nontext {field}").into())
    }
    fn readonly(path: &Path) -> Result<Connection> {
        let c = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
        c.execute_batch("PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;")?;
        Ok(c)
    }
    fn artifact(root: &Path, binding: &Value) -> Result<PathBuf> {
        let name = text(binding, "path")?;
        require(!name.contains(['\\', ':']) && !name.starts_with('/')
            && name.split('/').all(|s| !s.is_empty() && s != "." && s != ".."), "artifact path escape")?;
        let path = root.join(name).canonicalize()?;
        require(path.starts_with(root.canonicalize()?), "artifact path escape")?;
        // Bound fixture size before hashing; never scan a full pack.
        let size = std::fs::metadata(&path)?.len();
        require(size > 0 && size <= 32 * 1024 * 1024 && binding["size"].as_u64() == Some(size), "fixture artifact size mismatch/too large")?;
        let digest = format!("{:x}", Sha256::digest(std::fs::read(&path)?));
        require(binding["sha256"].as_str() == Some(digest.as_str()), "artifact digest mismatch")?;
        Ok(path)
    }
    fn typed_key(v: &Value) -> Result<(String, String, String)> {
        let k = &v["entry"];
        let kind = text(k, "kind")?;
        require(matches!(kind, "subject" | "character" | "person" | "episode" | "page" | "tag"), "invalid entry kind")?;
        Ok((kind.into(), text(k, "namespace")?.into(), text(k, "value")?.into()))
    }
    fn closure(base: &Connection, hit: &Value) -> Result<()> {
        let (kind, namespace, value) = typed_key(hit)?;
        let did = hit["document_id"].as_i64().ok_or("invalid document_id")?;
        let source = text(hit, "source_id")?;
        let evidence = text(hit, "evidence_id")?;
        text(hit, "chunk_id")?;
        let count: i64 = base.query_row(
            "SELECT count(*) FROM documents d JOIN entries e ON e.id=d.entry_id JOIN sources s ON s.source_id=d.source_id WHERE d.id=?1 AND e.kind=?2 AND e.namespace=?3 AND e.value=?4 AND e.conflicted=0 AND d.status IN ('source_backed','generated_from_evidence') AND d.source_id=?5 AND d.evidence_id=?6 AND EXISTS(SELECT 1 FROM entry_evidence v JOIN sources vs ON vs.source_id=v.source_id WHERE v.entry_id=e.id AND v.status='source_backed' AND length(trim(v.evidence_id))>0)",
            params![did, kind, namespace, value, source, evidence], |r| r.get(0))?;
        require(count == 1, "mapping document/typed entry/source evidence closure mismatch")
    }
    fn branch(input: &Path, query: &[f32]) -> Result<(String, Value, Value, usize)> {
        let manifest_path = if input.is_dir() { input.join("manifest.json") } else { input.to_owned() }.canonicalize()?;
        require(std::fs::metadata(&manifest_path)?.len() <= 1_000_000, "manifest too large")?;
        let m: Value = serde_json::from_slice(&std::fs::read(&manifest_path)?)?;
        require(m["schema"] == "sakura-source-pack-v1" && m["requires_model"] == "bge-m3", "source schema/model mismatch")?;
        require(m["text_projection"]["synthetic_test_encoder"] == true, "only synthetic encoder fixtures are accepted")?;
        require(m["text_projection"]["model_revision"] == "5617a9f61b028005a4858fdac845db406aefb181", "frozen revision mismatch")?;
        require(m["capabilities"].as_array().is_some_and(|a| a.iter().any(|v| v == "semantic")), "missing semantic capability")?;
        let id = text(&m, "pack_id")?.to_owned();
        let s = &m["semantic"];
        let rows = usize::try_from(s["rows"].as_u64().ok_or("missing rows")?)?;
        require((1..=4096).contains(&rows), "only tiny fixtures (1..4096 rows) are accepted")?;
        require(s["dimension"] == 1024 && s["metric"] == "cos" && s["dtype"] == "i8" && s["connectivity"] == 16 && s["expansion_add"] == 256 && s["expansion_search"] == 2048 && s["entry_depth"] == 100 && s["chunk_depth"].as_u64().is_some_and(|n| (512..=65536).contains(&n)), "semantic contract mismatch")?;
        let contract = json!({"revision":m["text_projection"]["model_revision"],"dimension":s["dimension"],"pooling":"cls","normalize":true,"query_prefix":"","dtype":"float32","output":"embeddings","ann":{"metric":s["metric"],"dtype":s["dtype"],"connectivity":s["connectivity"]}});
        let root = manifest_path.parent().ok_or("manifest parent")?;
        require(m["artifacts"]["snapshot"]["identity"] == "knowledge.sqlite", "snapshot identity mismatch")?;
        let base = readonly(&artifact(root, &m["artifacts"]["snapshot"])?)?;
        let declared: BTreeSet<String> = m["source_ids"].as_array().ok_or("missing source_ids")?.iter()
            .map(|v| v.as_str().filter(|s| !s.trim().is_empty()).map(str::to_owned).ok_or("invalid source_id"))
            .collect::<std::result::Result<_, _>>()?;
        require(declared.len() == m["source_ids"].as_array().unwrap().len(), "duplicate source_ids")?;
        let actual: BTreeSet<String> = base.prepare("SELECT source_id FROM sources")?.query_map([], |r| r.get(0))?.collect::<rusqlite::Result<_>>()?;
        require(actual == declared, "source_ids mismatch")?;
        let mapping = readonly(&artifact(root, &m["artifacts"]["mapping"])?)?;
        let mut stmt = mapping.prepare("SELECT position,original_position,chunk_id,document_id,kind,namespace,value,source_id,evidence_id FROM chunks ORDER BY position")?;
        let mapped = stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?, json!({"chunk_id":r.get::<_, String>(2)?,"document_id":r.get::<_, i64>(3)?,"entry":{"kind":r.get::<_, String>(4)?,"namespace":r.get::<_, String>(5)?,"value":r.get::<_, String>(6)?},"source_id":r.get::<_, String>(7)?,"evidence_id":r.get::<_, String>(8)?}))))?.collect::<rusqlite::Result<Vec<_>>>()?;
        require(mapped.len() == rows, "mapping row count mismatch")?;
        let mut originals = BTreeSet::new();
        let mut chunks = BTreeSet::new();
        for (i, (position, original, hit)) in mapped.iter().enumerate() {
            require(*position == i as i64 && *original >= 0 && originals.insert(*original) && chunks.insert(text(hit, "chunk_id")?.to_owned()), "mapping key identity mismatch")?;
            closure(&base, hit)?;
        }
        let index_path = artifact(root, &m["artifacts"]["index"])?;
        let ip = index_path.to_str().ok_or("non UTF-8 index path")?;
        let metadata = Index::metadata(ip)?;
        require(metadata.dimensions == 1024 && metadata.metric == MetricKind::Cos, "index metadata mismatch")?;
        let index = Index::new(&metadata.into())?;
        index.view(ip)?;
        require(index.size() == rows && index.dimensions() == 1024 && index.metric_kind() == MetricKind::Cos && index.scalar_kind() == ScalarKind::I8 && index.connectivity() == 16, "native Cos/I8/M16 contract mismatch")?;
        for i in 0..rows { require(index.contains(i as u64), "native local key coverage mismatch")?; }
        index.change_expansion_search(2048);
        let matches = index.search(query, rows.min(s["chunk_depth"].as_u64().unwrap() as usize))?;
        require(!matches.keys.is_empty() && matches.keys.len() == matches.distances.len(), "empty/malformed native hits")?;
        let mut hits = Vec::new();
        let mut seen = BTreeSet::new();
        for (key, distance) in matches.keys.iter().zip(&matches.distances) {
            require(distance.is_finite() && seen.insert(*key), "nonfinite/duplicate native hit")?;
            let mut hit = mapped.get(usize::try_from(*key)?).ok_or("unmapped native key")?.2.clone();
            hit["distance"] = json!(distance);
            closure(&base, &hit)?;
            hits.push(hit);
        }
        Ok((id, json!({"dense_hits":hits,"lexical_hits":[],"trusted_pins":[],"candidates":[]}), contract, rows))
    }
    pub fn run() -> Result<()> {
        let args: Vec<_> = std::env::args_os().skip(1).collect();
        require((1..=2).contains(&args.len()), "source_pack_probe PACK [SECOND_PACK]")?;
        // The only mocked boundary is the expensive query encoder.
        let mut query = vec![0.0f32; 1024];
        query[0] = 1.0;
        let mut parts = Vec::new();
        let mut contracts = Vec::new();
        let mut counts = Vec::new();
        let mut ids = BTreeSet::new();
        for arg in args {
            let path = Path::new(&arg);
            let first = branch(path, &query)?;
            let reload = branch(path, &query)?;
            require(first == reload, "native readonly reload changed branch")?;
            require(ids.insert(first.0.clone()), "duplicate participating pack_id")?;
            counts.push(json!({"pack_id":first.0,"rows":first.3,"hits":first.1["dense_hits"].as_array().unwrap().len()}));
            contracts.push(first.2);
            parts.push((first.0, first.1));
        }
        semantic_federation::compatible(&contracts)?;
        let fused = semantic_federation::fuse(&parts, 100)?;
        let reversed: Vec<_> = parts.iter().rev().cloned().collect();
        require(fused == semantic_federation::fuse(&reversed, 100)?, "federation is branch order dependent")?;
        let mut keys = BTreeSet::new();
        for row in &fused {
            let key = typed_key(row)?;
            require(keys.insert(key.clone()), "federation duplicated full typed key")?;
            let mut expected_packs = BTreeSet::new();
            let mut expected_proofs = BTreeSet::new();
            for (pack, part) in &parts {
                for hit in part["dense_hits"].as_array().unwrap() {
                    if typed_key(hit)? == key {
                        expected_packs.insert(pack.clone());
                        expected_proofs.insert(json!({"backend":"dense","source_pack":pack,"hit":hit}).to_string());
                        require(row["citations"].as_array().unwrap().contains(&json!({"document_id":hit["document_id"],"source_id":hit["source_id"],"evidence_id":hit["evidence_id"]})), "missing citation")?;
                    }
                }
            }
            let packs: BTreeSet<_> = row["source_packs"].as_array().ok_or("missing source_packs")?.iter().map(|v| v.as_str().unwrap_or("").to_owned()).collect();
            let proofs: BTreeSet<_> = row["provenance"].as_array().ok_or("missing provenance")?.iter().map(Value::to_string).collect();
            require(packs == expected_packs && proofs == expected_proofs, "full typed key lost/changed source_pack proofs")?;
        }
        require(!fused.is_empty(), "empty federation")?;
        println!("{}", json!({"validation":"PASS","scope":"native synthetic fixture; not SemanticEngine loader or real encoder evidence","query":"synthetic unit axis0","reload":"PASS","rows_hits":counts,"branches":parts,"fused":fused,"participating_ids":ids}));
        Ok(())
    }
}

#[cfg(feature = "semantic")]
fn main() -> Result<()> { probe::run() }
#[cfg(not(feature = "semantic"))]
fn main() -> Result<()> { Err("source_pack_probe requires --features semantic".into()) }
