//! Local-only semantic retrieval. Activation verifies current product bindings.
use ort::{ep, session::Session, value::Tensor};
use rusqlite::{params, Connection, OpenFlags, OptionalExtension};
use serde_json::{json, Value};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    rc::Rc,
    time::Instant,
};
use tokenizers::Tokenizer;
use usearch::{Index, MetricKind, ScalarKind};
pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[path = "semantic_evidence.rs"]
mod semantic_evidence;
#[path = "embedding_cache.rs"]
mod embedding_cache;
pub(crate) use semantic_evidence::{close_public_evidence, qualify_public_record};
const ROWS: usize = 52664;
const WARNING: &str =
    "Retrieval relevance is not verified identity or permission to promote identity.";
const DLL_SHA: &str = "4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847";
const LEX_SHA: &str = "c664b3c81181942d202321fe81448d2cfc4e00ab658b864732e758ce7a1829b3";
// Legacy manifest identity is relative metadata, not a build-machine location.
const CANONICAL_PATH: &str = "configs/p4-full-semantic-v1.json";
const CURRENT_ASSETS: &str = include_str!("../../configs/p4-current-assets.json");
const FULL_DECLARATION: &str = include_str!("../../configs/p4-full-semantic-v1.json");
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct EntryKey {
    pub kind: String,
    pub namespace: String,
    pub value: String,
}
impl EntryKey {
    fn parse(v: &Value) -> Result<Self> {
        let k = Self {
            kind: text(v, "kind")?.into(),
            namespace: text(v, "namespace")?.into(),
            value: text(v, "value")?.into(),
        };
        Self::from_parts(k.kind, k.namespace, k.value)
    }
    fn from_parts(kind: String, namespace: String, value: String) -> Result<Self> {
        let k = Self { kind, namespace, value };
        for (name, value) in [("kind", &k.kind), ("namespace", &k.namespace), ("value", &k.value)] {
            require(!value.trim().is_empty(), &format!("missing/nontext {name}"))?;
        }
        require(
            matches!(
                k.kind.as_str(),
                "subject" | "character" | "person" | "episode" | "page" | "tag"
            ),
            "invalid EntryKey kind",
        )?;
        require(
            k.namespace.chars().count() <= 1024 && k.value.chars().count() <= 1024,
            "invalid EntryKey length",
        )?;
        Ok(k)
    }
    fn json(&self) -> Value {
        json!({"kind":self.kind,"namespace":self.namespace,"value":self.value})
    }
}
#[derive(Clone, Debug)]
pub struct RetrieveOptions {
    pub limit: usize,
    pub kind: Option<String>,
    pub namespace: Option<String>,
    pub include_vector: bool,
}
impl Default for RetrieveOptions {
    fn default() -> Self {
        Self {
            limit: 100,
            kind: None,
            namespace: None,
            include_vector: false,
        }
    }
}
impl RetrieveOptions {
    pub fn validate(&self) -> Result<()> {
        require((1..=100).contains(&self.limit), "limit must be 1..100")?;
        if let Some(k) = &self.kind {
            EntryKey::parse(&json!({"kind":k,"namespace":"x","value":"x"}))?;
        }
        if let Some(ns) = &self.namespace {
            require(
                !ns.trim().is_empty() && ns.chars().count() <= 1024,
                "invalid namespace",
            )?;
        }
        Ok(())
    }
    fn accepts(&self, k: &EntryKey) -> bool {
        self.kind.as_ref().is_none_or(|v| v == &k.kind)
            && self.namespace.as_ref().is_none_or(|v| v == &k.namespace)
    }
}
pub fn fixed_contract() -> Value {
    json!({"lexical_mode":"pilot_sidecar","revision":"5617a9f61b028005a4858fdac845db406aefb181","dimension":1024,"pooling":"cls","normalize":true,"query_prefix":"","dtype":"float32","output":"embeddings","provider":"CPUExecutionProvider","ort_version":"1.24.1","intra_threads":8,"inter_threads":1,"sequential":true,"ann":{"rows":52664,"metric":"cos","dtype":"f32","connectivity":16,"expansion_add":256,"expansion_search":128,"chunk_depth":512,"entry_depth":100},"bm25_document_depth":100,"rrf_k":60,"ties":"kind,namespace,value","pins":"trusted_exact_alias"})
}
fn shared_encoder_contract(model_id: &str) -> Result<Value> {
    let mut contract = fixed_contract();
    match model_id {
        "bge-m3" => {},
        "embeddinggemma-2" => {
            contract["revision"] = json!("daa72c51243991dfcaf9f9137d2c573d8f7790c0");
            contract["dimension"] = json!(768);
            contract["pooling"] = json!("mean");
            contract["query_prefix"] = json!("task: search result | query: ");
            contract["document_template"] = json!("title: {title} | text: {text}");
            contract["untitled_document"] = json!("none");
            contract["pad_token_id"] = json!(0);
        },
        _ => return Err("unsupported shared model".into()),
    }
    for field in ["lexical_mode", "ann", "bm25_document_depth", "rrf_k", "ties", "pins"] {
        contract.as_object_mut().unwrap().remove(field);
    }
    Ok(contract)
}
/// The exact shared Python declaration, embedded rather than read at runtime.
pub fn full_declaration() -> Value {
    serde_json::from_str(FULL_DECLARATION).expect("embedded FULL declaration must be JSON")
}
/// Runtime projection; the positive chunk count belongs to the activated pack.
pub fn full_contract(full_chunk_count: usize) -> Result<Value> {
    require(
        full_chunk_count > 0 && full_chunk_count <= i64::MAX as usize,
        "invalid full_chunk_count",
    )?;
    let declaration = full_declaration();
    require(
        declaration["schema"] == "p4-full-semantic-contract-v1",
        "invalid FULL declaration",
    )?;
    let d = &declaration["declarative_contract"];
    let mut c = fixed_contract();
    for n in [
        "revision",
        "dimension",
        "pooling",
        "normalize",
        "query_prefix",
        "dtype",
    ] {
        c[n] = d["encoder"][n].clone();
    }
    for n in [
        "provider",
        "ort_version",
        "intra_threads",
        "inter_threads",
        "sequential",
        "lexical_mode",
    ] {
        c[n] = d["runtime"][n].clone();
    }
    for n in [
        "metric",
        "dtype",
        "connectivity",
        "expansion_add",
        "expansion_search",
        "chunk_depth",
        "entry_depth",
    ] {
        c["ann"][n] = d["ann"][n].clone();
    }
    for n in ["bm25_document_depth", "rrf_k", "ties", "pins"] {
        c[n] = d["hybrid"][n].clone();
    }
    c["schema"] = declaration["schema"].clone();
    c["ann"]["rows"] = json!(full_chunk_count);
    c["full_chunk_count"] = json!(full_chunk_count);
    Ok(c)
}
fn portable_contract(full_chunk_count: usize) -> Result<Value> {
    let mut c = full_contract(full_chunk_count)?;
    c["ann"]["dtype"] = json!("i8");
    c["ann_storage"] = json!("i8");
    Ok(c)
}
fn portable_declaration() -> Value {
    let mut d = full_declaration();
    d["declarative_contract"]["ann"]["dtype"] = json!("i8");
    d
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Mode {
    Pilot,
    Full,
}
fn is_portable(v: &Value) -> bool {
    v["pack_version"] == "portable-cpu-i8-v1"
}
fn mode(v: &Value) -> Result<Mode> {
    match v["contract"]["lexical_mode"].as_str() {
        Some("pilot_sidecar") => Ok(Mode::Pilot),
        Some("full_snapshot_fts") => Ok(Mode::Full),
        _ => Err("unsupported lexical mode".into()),
    }
}
fn row_count(v: &Value) -> Result<usize> {
    if mode(v)? == Mode::Pilot {
        return Ok(ROWS);
    }
    let n = usize::try_from(
        v["full_chunk_count"]
            .as_u64()
            .ok_or("missing full_chunk_count")?,
    )?;
    require(n > 0 && n <= i64::MAX as usize, "invalid full_chunk_count")?;
    Ok(n)
}
fn require(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}
fn text<'a>(v: &'a Value, n: &str) -> Result<&'a str> {
    v[n].as_str()
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| format!("missing/nontext {n}").into())
}
fn digest(v: &Value) -> bool {
    v.as_str().is_some_and(|s| {
        s.len() == 64
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}
fn ms(t: Instant) -> f64 {
    t.elapsed().as_secs_f64() * 1000.0
}
fn readonly(path: &Path) -> Result<Connection> {
    let c = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    c.execute_batch("PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;")?;
    c.set_limit(rusqlite::limits::Limit::SQLITE_LIMIT_LENGTH, 2_000_000);
    Ok(c)
}
fn validate_binding(v: &Value) -> Result<()> {
    text(v, "path")?;
    require(
        digest(&v["sha256"]) && v["size"].as_u64().is_some_and(|s| s > 0),
        "invalid artifact binding",
    )
}
fn artifact(root: &Path, v: &Value) -> Result<PathBuf> {
    validate_binding(v)?;
    let p = root.join(text(v, "path")?);
    let m = std::fs::metadata(&p)?;
    require(
        m.is_file() && Some(m.len()) == v["size"].as_u64(),
        "artifact file size mismatch",
    )?;
    Ok(std::fs::canonicalize(p)?)
}
fn validate_portable_path(path: &str) -> Result<()> {
    // Reject Windows escapes even when validation runs on Unix.
    require(!path.contains('\\') && !path.contains(':') && !path.starts_with('/')
        && path.split('/').all(|p| !p.is_empty() && p != "." && p != ".."),
        "portable path must be a normal relative path")
}
fn portable_artifact(root: &Path, binding: &Value) -> Result<PathBuf> {
    validate_binding(binding)?;
    validate_portable_path(text(binding, "path")?)?;
    reject_path_links(&root.join(text(binding, "path")?))?;
    let path = artifact(root, binding)?;
    require(path.starts_with(std::fs::canonicalize(root)?), "portable artifact escape")?;
    let mut file = std::io::BufReader::new(std::fs::File::open(&path)?);
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut digest = Sha256::new();
    let mut buffer = vec![0u8; 1024 * 1024];
    loop { let n=file.read(&mut buffer)?; if n==0 {break;} digest.update(&buffer[..n]); }
    require(format!("{:x}",digest.finalize()) == text(binding, "sha256")?, "portable artifact digest mismatch")?;
    Ok(path)
}
fn portable_paths(root: &Path, manifest: &Value) -> Result<BTreeMap<String, PathBuf>> {
    let mut paths = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for (name, binding) in std::iter::once(("snapshot", &manifest["snapshot"]))
        .chain(manifest["artifacts"].as_object().ok_or("invalid artifacts")?.iter()
            .filter(|(name,_)| name.as_str() != "external_data").map(|(name,b)| (name.as_str(),b))) {
        let path = portable_artifact(root, binding)?;
        require(seen.insert(path.clone()), "duplicate portable artifact")?;
        paths.insert(name.to_owned(),path);
    }
    for binding in manifest["artifacts"]["external_data"].as_array().ok_or("external tensors")? {
        require(seen.insert(portable_artifact(root,binding)?), "duplicate portable tensor")?;
    }
    Ok(paths)
}
// Check components before canonicalization; junctions are reparse points.
fn reject_path_links(path: &Path) -> Result<()> {
    let absolute = if path.is_absolute() {
        path.to_owned()
    } else {
        std::env::current_dir()?.join(path)
    };
    let mut current = PathBuf::new();
    for component in absolute.components() {
        current.push(component.as_os_str());
        let metadata = std::fs::symlink_metadata(&current)?;
        require(
            !metadata.file_type().is_symlink(),
            "FULL path symlink forbidden",
        )?;
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            require(
                metadata.file_attributes() & 0x400 == 0,
                "FULL path reparse point forbidden",
            )?;
        }
    }
    Ok(())
}
fn controlled_path(repository: &Path, path: &Path) -> Result<PathBuf> {
    reject_path_links(repository)?;
    reject_path_links(path)?;
    let resolved = std::fs::canonicalize(path)?;
    require(
        resolved.starts_with(std::fs::canonicalize(repository)?),
        "FULL artifact repository escape",
    )?;
    Ok(resolved)
}
fn full_artifact(
    repository: &Path,
    root: &Path,
    kind: &str,
    binding: &Value,
    proof: Option<&(PathBuf, u64, String)>,
) -> Result<PathBuf> {
    validate_binding(binding)?;
    reject_path_links(&root.join(text(binding, "path")?))?;
    let resolved = artifact(root, binding)?;
    let _ = (kind, proof); // Signature retained for compatibility with owned pack paths.
    require(
        resolved.starts_with(std::fs::canonicalize(repository)?),
        "FULL artifact must remain inside project",
    )?;
    Ok(resolved)
}
// Current asset specification is shared with Python activation, not pilot receipts.
fn approved_full_dll(repository: &Path) -> Result<(PathBuf, u64, String)> {
    let assets: Value = serde_json::from_str(CURRENT_ASSETS)?;
    require(
        assets["schema"] == "product_asset_spec_v1",
        "invalid current assets",
    )?;
    let binding = &assets["ort_dll"];
    validate_binding(binding)?;
    let path = PathBuf::from(text(binding, "path")?);
    require(!path.is_absolute(), "DLL path must be project-relative")?;
    controlled_path(repository, &repository.join(&path))?;
    Ok((
        artifact(repository, binding)?,
        binding["size"].as_u64().ok_or("DLL size")?,
        text(binding, "sha256")?.into(),
    ))
}
fn full_paths(
    repository: &Path,
    root: &Path,
    manifest: &Value,
    proof: Option<&(PathBuf, u64, String)>,
) -> Result<BTreeMap<String, PathBuf>> {
    controlled_path(repository, root)?;
    let artifacts = manifest["artifacts"]
        .as_object()
        .ok_or("invalid artifacts")?;
    let mut expected: BTreeSet<_> = [
        "model",
        "tokenizer",
        "ort_dll",
        "index",
        "mapping",
        "corpus",
        "external_data",
    ]
    .into_iter()
    .collect();
    if manifest["pack_version"] == "p4-full-prepared-lexical-v1" { expected.insert("lexical_membership"); }
    require(
        artifacts
            .keys()
            .map(String::as_str)
            .collect::<BTreeSet<_>>()
            == expected,
        "FULL artifact closed set mismatch",
    )?;
    let owned_proof;
    let dll_path = root.join(text(&artifacts["ort_dll"], "path")?);
    reject_path_links(&dll_path)?;
    let proof = if proof.is_none()
        && !std::fs::canonicalize(&dll_path)?.starts_with(std::fs::canonicalize(repository)?)
    {
        owned_proof = approved_full_dll(repository)?;
        Some(&owned_proof)
    } else {
        proof
    };
    if manifest["pack_version"] == "p4-full-existing-assets-v1" || manifest["pack_version"] == "p4-full-prepared-lexical-v1" {
        let assets: Value = serde_json::from_str(CURRENT_ASSETS)?;
        for role in ["index", "mapping", "corpus"] {
            let expected = &assets["existing_full_assets"][role];
            validate_binding(expected)?;
            let actual = &artifacts[role];
            require(actual["size"] == expected["size"] && actual["sha256"] == expected["sha256"] &&
                controlled_path(repository, &root.join(text(actual, "path")?))? ==
                controlled_path(repository, &repository.join(text(expected, "path")?))?,
                "existing FULL product role mismatch")?;
        }
    }
    let mut seen = BTreeSet::new();
    let mut paths = BTreeMap::new();
    let snapshot = full_artifact(repository, root, "snapshot", &manifest["snapshot"], proof)?;
    seen.insert(snapshot.clone());
    paths.insert("snapshot".into(), snapshot);
    for (kind, binding) in artifacts {
        if kind == "external_data" {
            continue;
        }
        let path = if kind == "lexical_membership" {
            require(manifest["pack_version"] == "p4-full-prepared-lexical-v1", "run explicit prepare-lexical")?;
            artifact(root, binding)?
        } else { full_artifact(repository, root, kind, binding, proof)? };
        require(
            seen.insert(path.clone()),
            "duplicate resolved FULL artifact path",
        )?;
        paths.insert(kind.clone(), path);
    }
    let external = artifacts["external_data"]
        .as_array()
        .ok_or("external_data must be an array")?;
    require(!external.is_empty(), "missing external tensors")?;
    for binding in external {
        require(
            seen.insert(full_artifact(
                repository,
                root,
                "external_data",
                binding,
                proof,
            )?),
            "duplicate resolved FULL artifact path",
        )?;
    }
    Ok(paths)
}
fn lexical_config() -> Value {
    json!({"version":"p4-pilot-lexical-v1","fts_schema":"CREATE VIRTUAL TABLE search_fts USING fts5(text, document_id UNINDEXED, entry_id UNINDEXED)","tokenizer":"FTS5 default unicode61 remove_diacritics=1","text":"search_text((title + SPACE + original)[:100000])","query":"model.match_query: NFKC/casefold, CJK bigrams, quoted OR","document_depth":100,"depth_before_entry_dedup":true,"ties":"score ASC, kind ASC, namespace ASC, value ASC, document_id ASC","pins":"verbatim value or source_backed alias; trusted nonconflicted pilot entries only; typed-key order","pin_depth":"all pins retained separately; final ranking capped at 100","identity_assertions":"none; ambiguity is never collapsed"})
}
// Use the shipped contract bytes, never the absolute compilation-machine checkout.
fn canonical_bytes() -> Result<Vec<u8>> {
    Ok(FULL_DECLARATION.as_bytes().to_vec())
}
fn verify_canonical_bytes(manifest: &Value, actual: &[u8]) -> Result<()> {
    require(
        serde_json::from_slice::<Value>(actual)? == full_declaration(),
        "canonical declaration mismatch",
    )?;
    let expected = json!({"schema":"p4-full-semantic-contract-v1", "path":CANONICAL_PATH,
        "size":actual.len(), "sha256":sha256(actual)});
    require(
        manifest["canonical_contract"] == expected,
        "canonical binding mismatch",
    )
}
// SHA-256 for the small canonical file; no artifact-sized allocation or subprocess.
fn sha256(bytes: &[u8]) -> String {
    sha256_reader(&mut std::io::Cursor::new(bytes)).expect("in-memory SHA256 read")
}
// Stream large portable tensors/snapshots without allocating their full contents.
fn sha256_reader(reader: &mut impl std::io::Read) -> Result<String> {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h = [
        0x6a09e667u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut length = 0u64;
    let mut final_blocks = Vec::new();
    let mut finished = false;
    loop {
        let mut block = [0u8; 64];
        if finished {
            if final_blocks.is_empty() { break; }
            block.copy_from_slice(&final_blocks.drain(..64).collect::<Vec<_>>());
        } else {
            let mut used = 0;
            while used < 64 {
                let n = reader.read(&mut block[used..])?;
                if n == 0 { break; }
                used += n;
            }
            length += used as u64;
            if used < 64 {
                final_blocks.extend_from_slice(&block[..used]);
                final_blocks.push(0x80);
                while final_blocks.len() % 64 != 56 { final_blocks.push(0); }
                final_blocks.extend_from_slice(&length.wrapping_mul(8).to_be_bytes());
                finished = true;
                continue;
            }
        }
        let mut w = [0u32; 64];
        for (i, word) in block.as_chunks::<4>().0.iter().enumerate() {
            w[i] = u32::from_be_bytes(*word);
        }
        for i in 16..64 {
            let x = w[i - 15];
            let y = w[i - 2];
            let s0 = x.rotate_right(7) ^ x.rotate_right(18) ^ (x >> 3);
            let s1 = y.rotate_right(17) ^ y.rotate_right(19) ^ (y >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (state, value) in h.iter_mut().zip([a, b, c, d, e, f, g, hh]) {
            *state = state.wrapping_add(value);
        }
    }
    Ok(h.iter().map(|word| format!("{word:08x}")).collect())
}
fn validate_manifest(v: &Value) -> Result<()> {
    let m = mode(v)?;
    let portable = is_portable(v);
    let schema = if portable { "p4-rust-semantic-portable-pack-v1" } else { match m {
        Mode::Pilot => "p4-rust-semantic-pack-v1",
        Mode::Full => "p4-rust-semantic-full-pack-v1",
    }};
    require(v["schema"] == schema, "unsupported pack schema")?;
    text(v, "pack_version")?;

    text(&v["snapshot"], "identity")?;
    validate_binding(&v["snapshot"])?;
    let expected = if m == Mode::Pilot {
        fixed_contract()
    } else if portable {
        portable_contract(row_count(v)?)?
    } else {
        full_contract(row_count(v)?)?
    };
    require(v["contract"] == expected, "semantic contract mismatch")?;
    require(
        v.get("full_declaration").is_none(),
        "private FULL declaration wrapper is forbidden",
    )?;
    if m == Mode::Full && !portable {
        require(
            v["object_type"] == "runtime_pack",
            "FULL runtime pack required",
        )?;
        verify_canonical_bytes(v, &canonical_bytes()?)?;
        let d = full_declaration();
        require(
            v["declarative_contract"] == d["declarative_contract"],
            "FULL declarative contract mismatch",
        )?;
        let s = &d["snapshot"];
        require(
            v["snapshot"]["sha256"] == s["sha256"]
                && v["snapshot"]["size"] == s["size"]
                && v["snapshot"]["identity"] == s["path"],
            "FULL snapshot binding mismatch",
        )?;
        require(
            v["artifacts"].get("lexical").is_none() && v.get("lexical_metadata").is_none(),
            "FULL must not bind a pilot lexical sidecar",
        )?;
    } else if !portable {
        for n in [
            "canonical_contract",
            "declarative_contract",
            "full_chunk_count",
        ] {
            require(v.get(n).is_none(), "pilot must not carry FULL fields")?;
        }
    }
    if portable {
        require(v["object_type"] == "runtime_pack", "portable runtime pack required")?;
        require(m == Mode::Full, "portable FULL lexical mode required")?;
        require(v.get("lexical_metadata").is_none(), "portable pilot metadata forbidden")?;
        let source = &v["source_snapshot"];
        validate_binding(source)?;
        let original = &full_declaration()["snapshot"];
        require(source == original, "portable source snapshot binding mismatch")?;
        let artifacts = v["artifacts"].as_object().ok_or("invalid artifacts")?;
        let expected: BTreeSet<_> = ["model", "tokenizer", "ort_dll", "index", "mapping", "lexical_membership", "external_data"].into_iter().collect();
        require(artifacts.keys().map(String::as_str).collect::<BTreeSet<_>>() == expected, "portable artifact closed set mismatch")?;
        require(v["declarative_contract"] == portable_declaration()["declarative_contract"], "portable declarative contract mismatch")?;
        for (name, binding) in artifacts {
            if name != "external_data" {
                validate_binding(binding)?;
                validate_portable_path(text(binding, "path")?)?;
            }
        }
        for binding in artifacts["external_data"].as_array().ok_or("external_data must be an array")? {
            validate_binding(binding)?;
            validate_portable_path(text(binding, "path")?)?;
        }
    } else {
        for n in [
        "model",
        "tokenizer",
        "ort_dll",
        "index",
        "mapping",
        "corpus",
    ] {
        validate_binding(&v["artifacts"][n])?;
        }
    }
    let external = v["artifacts"]["external_data"]
        .as_array()
        .ok_or("external_data must be an array")?;
    require(!external.is_empty(), "missing external tensors")?;
    let mut names = BTreeSet::new();
    for t in external {
        validate_binding(t)?;
        require(names.insert(text(t, "path")?), "duplicate external tensor")?;
    }
    if !portable { require(
        v["artifacts"]["ort_dll"]["sha256"] == DLL_SHA
            && v["artifacts"]["ort_dll"]["size"] == 15355936_u64,
        "unpinned ORT DLL",
    )?; }
    if m == Mode::Full && !portable {
        let artifacts = v["artifacts"].as_object().ok_or("invalid artifacts")?;
        let mut expected: BTreeSet<_> = [
            "model",
            "tokenizer",
            "ort_dll",
            "index",
            "mapping",
            "corpus",
            "external_data",
        ]
        .into_iter()
        .collect();
        if v["pack_version"] == "p4-full-prepared-lexical-v1" {
            expected.insert("lexical_membership");
            validate_binding(&artifacts["lexical_membership"])?;
            require(artifacts["lexical_membership"]["path"] == "lexical-membership.sqlite", "local membership required")?;
        }
        require(
            artifacts
                .keys()
                .map(String::as_str)
                .collect::<BTreeSet<_>>()
                == expected,
            "FULL artifact closed set mismatch",
        )?;
        for name in [
            "model",
            "tokenizer",
            "ort_dll",
            "index",
            "mapping",
            "corpus",
        ] {
            require(
                names.insert(text(&artifacts[name], "path")?),
                "duplicate artifact path",
            )?;
        }
        return Ok(());
    }
    if portable {
        let mut paths = BTreeSet::new();
        validate_portable_path(text(&v["snapshot"], "identity")?)?;
        for binding in std::iter::once(&v["snapshot"])
            .chain(v["artifacts"].as_object().unwrap().iter().filter(|(name,_)| name.as_str() != "external_data").map(|(_,b)| b))
            .chain(external.iter()) {
            let path = text(binding, "path")?;
            validate_portable_path(path)?;
            require(paths.insert(path), "duplicate portable artifact path")?;
        }
        let l = &v["lexical_membership"];
        require(l["version"] == "p4-full-membership-v1" && l["rows"].as_u64().is_some_and(|n| n > 0)
            && l["snapshot_sha256"] == v["snapshot"]["sha256"]
            && l["snapshot_size"] == v["snapshot"]["size"]
            && l["snapshot_identity"] == v["snapshot"]["identity"], "portable membership binding mismatch")?;
        return Ok(());
    }
    validate_binding(&v["artifacts"]["lexical"])?;
    require(
        v["artifacts"]["lexical"]["sha256"] == LEX_SHA,
        "unpinned lexical sidecar",
    )?;
    let l = &v["lexical_metadata"];
    require(
        l["version"] == "p4-pilot-lexical-v1"
            && l["document_count"] == 50000
            && l["snapshot"]["sha256"] == v["snapshot"]["sha256"]
            && l["snapshot"]["size"] == v["snapshot"]["size"]
            && l["corpus"]["sha256"] == v["artifacts"]["corpus"]["sha256"]
            && l["corpus"]["size"] == v["artifacts"]["corpus"]["size"],
        "lexical manifest binding mismatch",
    )?;
    for (n, x) in lexical_config().as_object().unwrap() {
        require(l["config"][n] == *x, "lexical configuration mismatch")?;
    }
    require(
        digest(&l["config"]["model_sha256"])
            && digest(&l["config_sha256"])
            && digest(&l["binding_sha256"]),
        "invalid lexical configuration binding",
    )?;
    require(
        l["config"]["unicode_version"] == "16.0.0",
        "lexical Unicode version mismatch",
    )?;
    text(&l["config"], "sqlite_version")?;
    Ok(())
}
fn external_paths(root: &Path, v: &Value) -> Result<()> {
    let mut p = BTreeSet::new();
    for t in v["artifacts"]["external_data"]
        .as_array()
        .ok_or("external_data must be an array")?
    {
        require(
            p.insert(artifact(root, t)?),
            "duplicate external tensor path",
        )?;
    }
    require(!p.is_empty(), "missing external tensors")
}
fn snapshot_path(base: &Path, root: &Path, v: &Value) -> Result<PathBuf> {
    let p = artifact(root, v)?;
    require(std::fs::canonicalize(base)? == p, "snapshot path mismatch")?;
    // Driver identity is repository-relative filename, not build_meta.snapshot.
    let id = Path::new(text(v, "identity")?);
    require(
        !id.is_absolute()
            && id
                .components()
                .all(|c| matches!(c, std::path::Component::Normal(_)))
            && p.ends_with(id),
        "snapshot identity mismatch",
    )?;
    Ok(p)
}
#[cfg(windows)]
fn runtime_version(dll: &Path) -> Result<String> {
    use std::{
        ffi::{c_void, CStr},
        os::windows::ffi::OsStrExt,
    };
    #[link(name = "kernel32")]
    extern "system" {
        fn GetModuleHandleW(name: *const u16) -> *mut c_void;
        fn GetProcAddress(module: *mut c_void, name: *const u8) -> *mut c_void;
    }
    let name: Vec<u16> = dll.as_os_str().encode_wide().chain(Some(0)).collect();
    // ORT retains the explicit module. Never search/load a second DLL.
    unsafe {
        let m = GetModuleHandleW(name.as_ptr());
        require(!m.is_null(), "explicit ORT DLL not loaded")?;
        let s = GetProcAddress(m, c"OrtGetApiBase".as_ptr().cast());
        require(!s.is_null(), "missing OrtGetApiBase")?;
        let get: unsafe extern "system" fn() -> *const ort::sys::OrtApiBase =
            std::mem::transmute(s);
        let b = get().as_ref().ok_or("null OrtApiBase")?;
        let v = (b.GetVersionString)();
        require(!v.is_null(), "null runtime version")?;
        Ok(CStr::from_ptr(v).to_str()?.into())
    }
}
#[cfg(target_os = "linux")]
fn runtime_version(library: &Path) -> Result<String> {
    use std::{ffi::{c_char, c_int, c_void, CStr, CString}, os::unix::ffi::OsStrExt};
    #[link(name = "dl")]
    extern "C" {
        fn dlopen(filename: *const c_char, flags: c_int) -> *mut c_void;
        fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
        fn dlclose(handle: *mut c_void) -> c_int;
    }
    let name = CString::new(library.as_os_str().as_bytes())?;
    // Probe only the exact module retained by ort::init_from. RTLD_NOLOAD
    // forbids loading another library or searching a system runtime.
    unsafe {
        let module = dlopen(name.as_ptr(), 2 /* RTLD_NOW */ | 4 /* RTLD_NOLOAD */);
        require(!module.is_null(), "explicit ORT library not loaded")?;
        let result = (|| -> Result<String> {
            let symbol = dlsym(module, c"OrtGetApiBase".as_ptr());
            require(!symbol.is_null(), "missing OrtGetApiBase")?;
            let get: unsafe extern "C" fn() -> *const ort::sys::OrtApiBase =
                std::mem::transmute(symbol);
            let base = get().as_ref().ok_or("null OrtApiBase")?;
            let version = (base.GetVersionString)();
            require(!version.is_null(), "null runtime version")?;
            Ok(CStr::from_ptr(version).to_str()?.into())
        })();
        dlclose(module); // Release only our NOLOAD reference; ORT retains its own.
        result
    }
}
#[cfg(not(any(windows, target_os = "linux")))]
fn runtime_version(_: &Path) -> Result<String> {
    Err("semantic runtime supports Windows and Linux only".into())
}

fn shared_runtime_path(manifest: &Value, bin_dir: &Path) -> Result<PathBuf> {
    if let Some(libraries) = manifest.get("ort_libraries") {
        let libraries = libraries.as_object().ok_or("ort_libraries must be an object")?;
        let platform = format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH);
        let binding = libraries.get(&platform).ok_or("ORT library missing for current platform")?;
        return portable_artifact(bin_dir, binding);
    }
    #[cfg(windows)]
    {
        require(manifest["ort_dll"].get("path").is_none(), "ort_dll must not supply a path")?;
        let mut binding = manifest["ort_dll"].clone();
        binding["path"] = json!("onnxruntime.dll");
        portable_artifact(bin_dir, &binding)
    }
    #[cfg(not(windows))]
    {
        Err("shared model requires an explicit ort_libraries binding for this platform".into())
    }
}
fn validate_snapshot_policy(c: &Connection, m: Mode) -> Result<()> {
    let id: String = c.query_row(
        "SELECT value FROM build_meta WHERE key='snapshot'",
        [],
        |r| r.get(0),
    )?;
    require(digest(&json!(id)), "invalid snapshot build identity")?;
    let v: String = c.query_row(
        "SELECT value FROM build_meta WHERE key='contract_version'",
        [],
        |r| r.get(0),
    )?;
    require(v == "2", "snapshot contract mismatch")?;
    if m == Mode::Full {
        let v: String = c.query_row(
            "SELECT value FROM build_meta WHERE key='index_episodes'",
            [],
            |r| r.get(0),
        )?;
        require(v == "false", "index_episodes policy must be false")?;
    }
    Ok(())
}
fn validate_mapping(c: &Connection, n: usize) -> Result<()> {
    let b: (i64, i64, i64) = c.query_row(
        "SELECT count(*),min(position),max(position) FROM chunks",
        [],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
    )?;
    require(
        b == (n as i64, 0, n as i64 - 1),
        "mapping row identity mismatch",
    )
}
pub struct SharedEncoder {
    tokenizer: Tokenizer,
    session: Session,
    model_id: String,
    contract: Value,
    model_manifest: Option<PathBuf>,
    tokenizer_sha256: Option<String>,
    last_tokens: usize,
    pub query_encodings: usize,
    pub cache_hits: usize,
    cache: embedding_cache::EmbeddingCache,
}
impl SharedEncoder {
    fn from_paths(paths: &BTreeMap<String, PathBuf>, model_id: String, contract: Value) -> Result<Self> {
        let tokenizer = Tokenizer::from_file(&paths["tokenizer"]).map_err(|e| e.to_string())?;
        let environment = ort::init_from(&paths["ort_dll"])?;
        require(runtime_version(&paths["ort_dll"])? == "1.24.1", "ORT runtime version mismatch")?;
        require(environment.with_execution_providers([ep::CPU::default().build()]).commit(),
            "ORT already initialized; explicit runtime ownership required")?;
        let session = Session::builder()?
            .with_execution_providers([ep::CPU::default().build().error_on_failure()])?
            .with_intra_threads(8)?.with_inter_threads(1)?
            .with_parallel_execution(false)?.commit_from_file(&paths["model"])?;
        require(session.inputs().len() == 2 && session.inputs()[0].name() == "input_ids"
            && session.inputs()[1].name() == "attention_mask" && session.outputs().len() == 1
            && session.outputs()[0].name() == "embeddings", "unexpected ONNX graph interface")?;
        Ok(Self { tokenizer, session, model_id, contract, model_manifest: None, tokenizer_sha256: None, last_tokens: 0, query_encodings:0, cache_hits:0, cache:embedding_cache::EmbeddingCache::new() })
    }
    pub fn open_model(model_manifest: impl AsRef<Path>, bin_dir: impl AsRef<Path>) -> Result<Self> {
        let p = model_manifest.as_ref();
        let manifest = read_package_manifest(p, "sakura-shared-model-v1")?;
        let model_id = text(&manifest, "model_id")?;
        let contract = shared_encoder_contract(model_id)?;
        require(manifest["revision"] == contract["revision"], "shared model revision mismatch")?;
        for (field, expected) in contract.as_object().unwrap() {
            require(manifest["contract"][field] == *expected, "shared encoder contract mismatch")?;
        }
        let root = p.parent().ok_or("manifest has no parent")?;
        let mut paths = BTreeMap::new();
        for name in ["model", "tokenizer"] {
            paths.insert(name.into(), portable_artifact(root, &manifest["artifacts"][name])?);
        }
        let tensors = manifest["artifacts"]["external_data"].as_array().ok_or("missing external_data")?;
        require(!tensors.is_empty(), "missing external tensors")?;
        for binding in tensors { portable_artifact(root, binding)?; }
        paths.insert("ort_dll".into(), shared_runtime_path(&manifest, bin_dir.as_ref())?);
        let mut encoder = Self::from_paths(&paths, model_id.to_owned(), contract)?;
        encoder.model_manifest = Some(std::fs::canonicalize(p)?);
        encoder.tokenizer_sha256 = Some(text(&manifest["artifacts"]["tokenizer"], "sha256")?.to_owned());
        Ok(encoder)
    }
    pub fn encode(&mut self, query: &str) -> Result<Vec<f32>> {
        validate_query(query)?;
        let input = format!("{}{}", self.contract["query_prefix"].as_str().unwrap(), query);
        self.encode_input(&input, false)
    }
    /// Text-only use of the shared model, independent of any Knowledge pack/index.
    /// Derived memory vectors use at most 512 tokens; the original text is untouched.
    pub fn encode_text(&mut self, text: &str, document: bool) -> Result<Vec<f32>> {
        require(!text.trim().is_empty() && text.chars().count() <= 8000, "text must contain 1..8000 characters")?;
        let input = if document {
            self.contract["document_template"].as_str().unwrap_or("{text}")
                .replace("{title}", self.contract["untitled_document"].as_str().unwrap_or("none"))
                .replace("{text}", text)
        } else { format!("{}{}", self.contract["query_prefix"].as_str().unwrap(), text) };
        self.encode_input(&input, true)
    }
    pub fn model_identity(&self) -> Value {
        json!({"model_id":self.model_id,"revision":self.contract["revision"],"dimension":self.contract["dimension"]})
    }
    fn encode_input(&mut self, input: &str, truncate: bool) -> Result<Vec<f32>> {
        if let Some((vector, tokens)) = self.cache.get(input) {
            require(truncate || tokens <= 512, "invalid token shape")?;
            self.last_tokens = tokens.min(512);
            self.cache_hits += 1;
            return Ok(vector);
        }
        let encoded = self.tokenizer.encode(input, true).map_err(|e| e.to_string())?;
        let full_tokens = encoded.get_ids().len();
        require(truncate || full_tokens <= 512, "invalid token shape")?;
        let ids: Vec<i64> = encoded.get_ids().iter().take(512).map(|&v| i64::from(v)).collect();
        let mask: Vec<i64> = encoded.get_attention_mask().iter().take(512).map(|&v| i64::from(v)).collect();
        require(!ids.is_empty() && ids.len() == mask.len(), "invalid token shape")?;
        let tokens = ids.len();
        self.last_tokens = tokens;
        self.query_encodings+=1;
        let output = self.session.run(ort::inputs!["input_ids"=>Tensor::from_array(([1usize,tokens],ids))?,"attention_mask"=>Tensor::from_array(([1usize,tokens],mask))?])?;
        let (shape, values) = output["embeddings"].try_extract_tensor::<f32>()?;
        let dimension = self.contract["dimension"].as_u64().unwrap() as usize;
        require(shape.as_ref() == [1_i64, dimension as i64], "unexpected embeddings shape")?;
        validate_vector(values, dimension)?;
        self.cache.insert(input, values, full_tokens);
        Ok(values.to_vec())
    }
}
pub fn open_model(model_manifest: impl AsRef<Path>, bin_dir: impl AsRef<Path>) -> Result<SharedEncoder> {
    SharedEncoder::open_model(model_manifest, bin_dir)
}
fn read_package_manifest(path: &Path, schema: &str) -> Result<Value> {
    reject_path_links(path)?;
    require(std::fs::metadata(path)?.len() <= 1_000_000, "manifest too large")?;
    let manifest: Value = serde_json::from_slice(&std::fs::read(path)?)?;
    require(manifest["schema"] == schema, "unsupported package schema")?;
    Ok(manifest)
}
fn validate_query(query: &str) -> Result<()> {
    require(!query.is_empty() && query.chars().count() <= 4096, "query must contain 1..4096 characters")
}
pub struct SemanticEngine {
    encoder: Option<Rc<RefCell<SharedEncoder>>>,
    index: Option<Index>,
    mapping: Connection,
    mapping_projected: bool,
    lexical: Connection,
    base: Connection,
    manifest: Value,
    mode: Mode,
    rows: usize,
    full_members: Vec<(i64, i64)>,
    fts_members: Vec<(i64,i64,i64)>,
    pub open_timings_ms: Value,
}
impl SemanticEngine {
    pub fn query_encodings(&self) -> usize {
        self.encoder.as_ref().map_or(0, |encoder| encoder.borrow().query_encodings)
    }
    pub fn open_source(base_db: impl AsRef<Path>, source_manifest: impl AsRef<Path>, model_manifest: impl AsRef<Path>, encoder: Rc<RefCell<SharedEncoder>>) -> Result<Self> {
        require(encoder.borrow().model_manifest.as_ref() == Some(&std::fs::canonicalize(model_manifest.as_ref())?), "shared model manifest mismatch")?;
        let p = source_manifest.as_ref();
        let source = read_package_manifest(p, "sakura-source-pack-v1")?;
        validate_source_manifest(&source)?;
        require(source["requires_model"] == encoder.borrow().model_id, "source/shared encoder mismatch")?;
        if source["requires_model"] == "embeddinggemma-2" {
            require(source["text_projection"]["tokenizer_sha256"].as_str() == encoder.borrow().tokenizer_sha256.as_deref(),
                "source/model tokenizer mismatch")?;
        }
        let root = p.parent().ok_or("manifest has no parent")?;
        let mut paths = BTreeMap::new();
        for name in ["snapshot", "mapping", "index", "lexical_membership"] {
            paths.insert(name, portable_artifact(root, &source["artifacts"][name])?);
        }
        require(std::fs::canonicalize(base_db.as_ref())? == paths["snapshot"], "snapshot path mismatch")?;
        require(paths["snapshot"].ends_with("knowledge.sqlite"), "snapshot identity mismatch")?;
        let rows = source["semantic"]["rows"].as_u64().ok_or("missing semantic rows")? as usize;
        let mut contract = portable_contract(rows)?;
        for (field, value) in encoder.borrow().contract.as_object().unwrap() {
            contract[field] = value.clone();
        }
        let dimension = contract["dimension"].as_u64().unwrap() as usize;
        contract["ann"]["expansion_search"] = json!(2048);
        contract["ann"]["chunk_depth"] = source["semantic"]["chunk_depth"].clone();
        let manifest = json!({"pack_version":"portable-cpu-i8-v1","pack_id":source["pack_id"],"snapshot":source["artifacts"]["snapshot"],"artifacts":source["artifacts"],"lexical_membership":source["lexical_membership"],"contract":contract});
        let base = readonly(&paths["snapshot"])?;
        validate_snapshot_policy(&base, Mode::Full)?;
        let actual_sources: BTreeSet<String> = base.prepare("SELECT source_id FROM sources")?.query_map([], |r| r.get(0))?.collect::<rusqlite::Result<_>>()?;
        let declared: BTreeSet<String> = source["source_ids"].as_array().ok_or("missing source_ids")?.iter().map(|s| s.as_str().map(str::to_owned).ok_or("invalid source_id")).collect::<std::result::Result<_,_>>()?;
        require(actual_sources == declared, "source_ids mismatch")?;
        let fts_members = load_prepared_members(&paths["lexical_membership"], &manifest)?;
        // Prepared membership is digest-bound to this exact snapshot; relationships
        // were checked during export. Never rebuild/scan snapshot FTS at startup.
        require(source["lexical_membership"]["rows"].as_u64()==Some(fts_members.len() as u64), "membership row count mismatch")?;
        let mut full_members: Vec<_> = fts_members.iter().map(|&(_,e,d)| (e,d)).collect();
        full_members.sort_unstable(); full_members.dedup();
        let mapping = readonly(&paths["mapping"])?;
        validate_mapping(&mapping, rows)?;
        mapping.prepare("SELECT position,original_position,chunk_id,document_id,kind,namespace,value,source_id,evidence_id FROM chunks LIMIT 0")?;
        let ip = paths["index"].to_str().ok_or("non UTF-8 index path")?;
        let metadata = Index::metadata(ip)?;
        require(metadata.dimensions == dimension as u64 && metadata.metric == MetricKind::Cos, "index metadata mismatch")?;
        let index = Index::new(&metadata.into())?;
        index.view(ip)?;
        require(index.size() == rows && index.dimensions() == dimension && index.metric_kind() == MetricKind::Cos && index.scalar_kind() == ScalarKind::I8 && index.connectivity() == 16, "index contract mismatch")?;
        configure_search_expansion(&index, &manifest["contract"])?;
        Ok(Self { encoder: Some(encoder), index: Some(index), mapping, mapping_projected: true, lexical: readonly(&paths["snapshot"] )?, base, manifest, mode: Mode::Full, rows, full_members, fts_members, open_timings_ms: json!({}) })
    }
    pub fn open(base_db: impl AsRef<Path>, manifest_path: impl AsRef<Path>) -> Result<Self> {
        let total = Instant::now();
        let p = manifest_path.as_ref();
        require(
            std::fs::metadata(p)?.len() <= 1_000_000,
            "manifest too large",
        )?;
        let manifest: Value = serde_json::from_slice(&std::fs::read(p)?)?;
        validate_manifest(&manifest)?;
        let mode = mode(&manifest)?;
        let rows = row_count(&manifest)?;
        let root = p.parent().ok_or("manifest has no parent")?;
        let (paths, bp) = if is_portable(&manifest) {
            reject_path_links(p)?;
            let paths = portable_paths(root, &manifest)?;
            reject_path_links(base_db.as_ref())?;
            let bp = paths["snapshot"].clone();
            require(std::fs::canonicalize(base_db.as_ref())? == bp, "snapshot path mismatch")?;
            require(bp.ends_with(text(&manifest["snapshot"], "identity")?), "snapshot identity mismatch")?;
            (paths, bp)
        } else if mode == Mode::Full {
            // Legacy full packs use project-relative inputs from the current
            // project root, not the machine directory embedded by the compiler.
            let repository = std::env::current_dir()?;
            controlled_path(&repository, p)?;
            let paths = full_paths(&repository, root, &manifest, None)?;
            reject_path_links(base_db.as_ref())?;
            let bp = paths["snapshot"].clone();
            require(
                std::fs::canonicalize(base_db.as_ref())? == bp,
                "snapshot path mismatch",
            )?;
            let id = Path::new(text(&manifest["snapshot"], "identity")?);
            require(
                !id.is_absolute()
                    && id
                        .components()
                        .all(|c| matches!(c, std::path::Component::Normal(_)))
                    && bp.ends_with(id),
                "snapshot identity mismatch",
            )?;
            (paths, bp)
        } else {
            let mut paths = BTreeMap::new();
            for n in [
                "model",
                "tokenizer",
                "ort_dll",
                "index",
                "mapping",
                "corpus",
            ] {
                paths.insert(n.to_owned(), artifact(root, &manifest["artifacts"][n])?);
            }
            paths.insert(
                "lexical".into(),
                artifact(root, &manifest["artifacts"]["lexical"])?,
            );
            external_paths(root, &manifest)?;
            let bp = snapshot_path(base_db.as_ref(), root, &manifest["snapshot"])?;
            (paths, bp)
        };
        let base = readonly(&bp)?;
        validate_snapshot_policy(&base, mode)?;
        // Independent readonly handles even when FULL uses the same file.
        let lexical = readonly(if mode == Mode::Full {
            &bp
        } else {
            &paths["lexical"]
        })?;
        if mode == Mode::Pilot {
            let s: String = lexical.query_row("SELECT value FROM metadata", [], |r| r.get(0))?;
            require(
                serde_json::from_str::<Value>(&s)? == manifest["lexical_metadata"],
                "lexical metadata mismatch",
            )?;
        } else {
            validate_snapshot_policy(&lexical, mode)?;
            lexical.prepare("SELECT text,document_id,entry_id FROM search_fts LIMIT 0")?;
        }
        let member_start = Instant::now();
        let fts_members = if mode == Mode::Full {
            require(is_portable(&manifest) || manifest["pack_version"] == "p4-full-prepared-lexical-v1", "FULL membership missing: run explicit prepare-lexical")?;
            load_prepared_members(&paths["lexical_membership"], &manifest)?
        } else { Vec::new() };
        let mut full_members: Vec<_> = fts_members.iter().map(|&(_,e,d)| (e,d)).collect();
        full_members.sort_unstable(); full_members.dedup();
        let membership_ms = ms(member_start);
        let mapping = readonly(&paths["mapping"])?;
        validate_mapping(&mapping, rows)?;
        let mapping_projected = mapping_projection(&mapping)?;
        let metadata_ms = ms(total);
        let start = Instant::now();
        let tokenizer = Tokenizer::from_file(&paths["tokenizer"]).map_err(|e| e.to_string())?;
        let tokenizer_ms = ms(start);
        let start = Instant::now();
        let environment = ort::init_from(&paths["ort_dll"])?;
        require(
            runtime_version(&paths["ort_dll"])? == "1.24.1",
            "ORT runtime version mismatch",
        )?;
        require(
            environment
                .with_execution_providers([ep::CPU::default().build()])
                .commit(),
            "ORT already initialized; explicit runtime ownership required",
        )?;
        let session = Session::builder()?
            .with_execution_providers([ep::CPU::default().build().error_on_failure()])?
            .with_intra_threads(8)?
            .with_inter_threads(1)?
            .with_parallel_execution(false)?
            .commit_from_file(&paths["model"])?;
        require(
            session.inputs().len() == 2
                && session.inputs()[0].name() == "input_ids"
                && session.inputs()[1].name() == "attention_mask"
                && session.outputs().len() == 1
                && session.outputs()[0].name() == "embeddings",
            "unexpected ONNX graph interface",
        )?;
        let ort_ms = ms(start);
        let start = Instant::now();
        let ip = paths["index"].to_str().ok_or("non UTF-8 index path")?;
        let metadata = Index::metadata(ip)?;
        require(
            metadata.dimensions == 1024 && metadata.metric == MetricKind::Cos,
            "index metadata mismatch",
        )?;
        let index = Index::new(&metadata.into())?;
        index.view(ip)?;
        require(
            index.size() == rows
                && index.dimensions() == 1024
                && index.metric_kind() == MetricKind::Cos
                && index.scalar_kind() == if is_portable(&manifest) { ScalarKind::I8 } else { ScalarKind::F32 }
                && index.connectivity() == 16,
            "index contract mismatch",
        )?;
        configure_search_expansion(&index, &manifest["contract"])?;
        let open_timings_ms = json!({"metadata":metadata_ms,"tokenizer":tokenizer_ms,"ort":ort_ms,"ann":ms(start),"total":ms(total),"membership_load":membership_ms,
            "fts_membership_count":fts_members.len(),
            "fts_membership_payload_bytes":fts_members.len() * 24,
            "fts_membership_allocation_bytes":fts_members.capacity() * 24,
            "membership_count":full_members.len(),
            "membership_payload_bytes":full_members.len() * std::mem::size_of::<(i64,i64)>(),
            "membership_allocation_bytes":full_members.capacity() * std::mem::size_of::<(i64,i64)>(),
            "model_sessions":1});
        Ok(Self {
            encoder: Some(Rc::new(RefCell::new(SharedEncoder { tokenizer, session, model_id: "bge-m3".into(), contract: shared_encoder_contract("bge-m3")?, model_manifest: None, tokenizer_sha256: None, last_tokens: 0, query_encodings:0, cache_hits:0, cache:embedding_cache::EmbeddingCache::new() }))),
            index: Some(index),
            mapping,
            mapping_projected,
            lexical,
            base,
            manifest,
            mode,
            rows,
            full_members,
            fts_members,
            open_timings_ms,
        })
    }
    /// Branch depths precede filters, without backfill. All ambiguous pins remain.
    pub fn retrieve(&mut self, query: &str, options: &RetrieveOptions) -> Result<Value> {
        options.validate()?;
        let start = Instant::now();
        let before = self.query_encodings();
        let vector = self.encoder.as_ref().ok_or("no shared encoder")?.borrow_mut().encode(query)?;
        let tokens = self.encoder.as_ref().ok_or("no shared encoder")?.borrow().last_tokens;
        let encoding_ms = ms(start);
        let mut result = self.retrieve_encoded(query, options, &vector)?;
        result["actual_tokens"] = json!(tokens);
        result["timings_ms"]["ort"] = json!(encoding_ms);
        result["timings_ms"]["total"] = json!(ms(start));
        result["timings_ms"]["query_encodings"] = json!(self.query_encodings() - before);
        result["timings_ms"]["embedding_cache_hit"] = json!(self.query_encodings() == before);
        result["timings_ms"]["process_embedding_cache_hits"] = json!(self.encoder.as_ref().unwrap().borrow().cache_hits);
        result["timings_ms"]["process_query_encodings"] = json!(self.query_encodings());
        require(ms(start) <= 5000.0, "query_budget_exceeded")?;
        Ok(result)
    }
    pub fn federation_contract(&self) -> Value { self.manifest["contract"].clone() }
    pub fn retrieve_branches_encoded(&mut self, query: &str, options: &RetrieveOptions, vector: &[f32]) -> Result<Value> { self.retrieve_internal(query, options, vector, true, false) }
    pub fn retrieve_encoded(&mut self, query: &str, options: &RetrieveOptions, vector: &[f32]) -> Result<Value> { self.retrieve_internal(query, options, vector, false, false) }
    pub(crate) fn retrieve_deferred_encoded(&mut self, query: &str, options: &RetrieveOptions, vector: &[f32]) -> Result<Value> {
        self.retrieve_internal(query, options, vector, false, true)
    }
    pub(crate) fn hydrate_documents(&self, response: &mut Value, pack: &str, deadline: Instant) -> Result<()> {
        hydrate_documents(&self.base, response, pack, deadline)
    }
    fn retrieve_internal(&mut self, query: &str, options: &RetrieveOptions, vector: &[f32], branches_only: bool, defer_bodies: bool) -> Result<Value> {
        let total = Instant::now();
        options.validate()?;
        if let Some(index) = &self.index { validate_vector(vector, index.dimensions())?; }
        require(
            !query.is_empty() && query.chars().count() <= 4096,
            "query must contain 1..4096 characters",
        )?;
        for c in [&self.base, &self.lexical, &self.mapping] {
            c.progress_handler(1000, Some(move || total.elapsed().as_secs_f64() > 5.0));
        }
        let start = Instant::now();
        let compiled = crate::match_query(query).map_err(|e| e.to_string())?;
        let tokens = 0usize;
        let tokenize_ms = ms(start);
        let ort_ms = 0.0;
        let start = Instant::now();
        let depth = if self.mode == Mode::Full {
            self.rows.min(self.manifest["contract"]["ann"]["chunk_depth"].as_u64().unwrap_or(512) as usize)
        } else {
            512
        };
        let matches = self.index.as_ref().map(|index| index.search(vector, depth)).transpose()?;
        let index_search_ms = ms(start);
        let mapping_start = Instant::now();
        let dense = if let Some(matches) = matches { dense_hits_for(
            &self.mapping,
            self.mapping_projected,
            &matches.keys,
            &matches.distances,
            self.rows,
            self.mode,
            branches_only,
        ).map_err(|e| format!("dense_mapping: {e}; tokenize_ms={tokenize_ms}; ort_ms={ort_ms}; total_ms={}", ms(total)))? } else { Vec::new() };
        let dense_mapping_ms = ms(mapping_start);
        let ann_ms = ms(start);
        let start = Instant::now();
        let mut lexical_stages = (0.0, 0.0);
        let mut lexical_work = (0usize,0usize,0usize);
        let (lexical, pins) = if self.mode == Mode::Pilot {
            lexical_hits(&self.lexical, query, &compiled)?
        } else {
            full_lexical_hits_ranked(&self.lexical, query, &compiled, &self.full_members, &self.fts_members, total, &mut lexical_stages, &mut lexical_work).map_err(|e|
                format!("full_lexical: {e}; tokenize_ms={tokenize_ms}; ort_ms={ort_ms}; ann_ms={ann_ms}; lexical_ms={}; total_ms={}", ms(start), ms(total)))?
        };
        let bm25_ms = ms(start);
        let start = Instant::now();
        let mut proofs = ProofContext::new(&self.base, query);
        for pin in &pins { proofs.pin(pin)?; }
        if branches_only {
            for hit in &dense { require(hit["distance"].as_f64().is_some_and(f64::is_finite), "nonfinite ANN distance")?; }
            return Ok(json!({"contract":self.manifest["contract"],"snapshot":self.manifest["snapshot"],"dense_hits":dense,"lexical_hits":lexical,"trusted_pins":pins,"candidates":[],"timings_ms":{"ann":ann_ms,"bm25":bm25_ms,"total":ms(total)}}));
        }
        let fused = fuse(&lexical, &dense, &pins)?;
        let mut candidates = Vec::new();
        let mut documents = BTreeMap::new();
        let mut sources = BTreeMap::new();
        if self.mode == Mode::Full {
            // Pins are validated above independently of ranking/candidate limits.
            // Retain their actual source closure even when candidates are truncated.
            for pin in &pins {
                add_source(&self.base, &mut sources, text(pin, "source_id")?)?;
            }
        }
        let mut evidence = BTreeMap::new();
        for proof in semantic_evidence::pin_proofs(&mut proofs, &pins, &mut sources)? {
            evidence.insert((text(&proof, "source_id")?.to_owned(), text(&proof, "evidence_id")?.to_owned(), String::new()), proof);
        }
        for candidate in fused.iter().take(100) {
            let key = EntryKey::parse(&candidate["entry"])?;
            if !options.accepts(&key) {
                continue;
            }
            require(
                self.mode != Mode::Full || key.kind != "episode",
                "FULL episode excluded",
            )?;
            let mut candidate = candidate.clone();
            let eid = proofs.entry(&key)?;
            candidate["typed_identity"] =
                json!({"namespace":key.namespace,"kind":key.kind,"entry_id":eid.to_string()});
            for p in candidate["provenance"]
                .as_array()
                .ok_or("invalid provenance")?
            {
                let hit = &p["hit"];
                let did = text(hit, "document_id")?;
                let sql = if defer_bodies {
                    "SELECT '', '',status,source_id,evidence_id FROM documents WHERE id=? AND entry_id=? AND status IN ('source_backed','generated_from_evidence')"
                } else {
                    "SELECT title,original,status,source_id,evidence_id FROM documents WHERE id=? AND entry_id=? AND status IN ('source_backed','generated_from_evidence')"
                };
                let doc=self.base.query_row(sql,params![did,eid],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?,r.get::<_,String>(4)?)))?;
                require(
                    hit["source_id"] == doc.3 && hit["evidence_id"] == doc.4,
                    "document evidence mismatch",
                )?;
                if self.mode == Mode::Full {
                    validate_full_document_cached(&self.base, did, eid, &self.full_members)?;
                }
                add_source(&self.base, &mut sources, &doc.3)?;
                evidence.insert((doc.3.clone(),doc.4.clone(),did.to_owned()),json!({"document_id":did,"entry_id":eid.to_string(),"source_id":doc.3,"evidence_id":doc.4,"status":doc.2}));
                documents.insert(did.to_owned(),json!({"document_id":did,"entry_id":eid.to_string(),"entry_key":key.json(),"title":doc.0,"original":doc.1,"status":doc.2,"source_id":doc.3,"evidence_id":doc.4}));
            }
            for pin in candidate["trusted_pins"].as_array().ok_or("invalid pins")? {
                add_source(&self.base, &mut sources, text(pin, "source_id")?)?;
            }
            candidates.push(candidate);
            if candidates.len() == options.limit {
                break;
            }
        }
        let trusted: BTreeSet<_> = pins
            .iter()
            .map(|p| EntryKey::parse(&p["entry"]))
            .collect::<Result<_>>()?;
        let mut warnings = vec![WARNING];
        if trusted.len() > 1 {
            warnings.push("multiple_trusted_identities_preserved_not_resolved");
        }
        if trusted.len() > 100 {
            warnings.push("ranking_truncated_all_trusted_pins_retained_separately");
        }
        if compiled.is_empty() {
            warnings.push("no_fts_tokens");
        }
        let citations:Vec<_>=documents.values().map(|d|json!({"document_id":d["document_id"],"source_id":d["source_id"],"evidence_id":d["evidence_id"]})).chain(evidence.values().filter(|e|e.get("document_id").is_none()).cloned()).collect();
        let mut result = json!({"contract_version":"2","response_version":"p4-semantic-evidence-v1","pack_version":self.manifest["pack_version"],"snapshot":self.manifest["snapshot"],"contract":self.manifest["contract"],"query":query,"status":"PASS","identity_status":"not_asserted","promoted_identities":[],"canonical":null,"entity_tag":null,"warnings":warnings,"trusted_pins":pins,"dense_hits":dense,"lexical_hits":lexical,"hybrid":fused.iter().take(100).collect::<Vec<_>>(),"candidates":candidates,"documents":documents.into_values().collect::<Vec<_>>(),"sources":sources.into_values().collect::<Vec<_>>(),"evidence":evidence.into_values().collect::<Vec<_>>(),"citations":citations,"actual_tokens":tokens,"filter_policy":"post_fusion_no_backfill"});
        if options.include_vector {
            result["vector"] = json!(vector);
        }
        let fusion_ms = ms(start);
        let elapsed = ms(total);
        require(elapsed <= 5000.0, "query_budget_exceeded")?;
        result["timings_ms"] = json!({"tokenize":tokenize_ms,"ort":ort_ms,"ann":ann_ms,"index_search":index_search_ms,"dense_mapping":dense_mapping_ms,"bm25":bm25_ms,"pins_sql":lexical_stages.0,"bm25_sql":lexical_stages.1,"fusion_evidence":fusion_ms,"total":elapsed});
        result["lexical_work"] = json!({"cursor_rows":lexical_work.0,"eligible_rows":lexical_work.1,"boundary_ties":lexical_work.2});
        close_public_evidence(&mut result);
        Ok(result)
    }
    pub fn materialize_candidates(&mut self, query: &str, options: &RetrieveOptions, candidates: &[Value], all_pins: &[Value], deadline: Instant) -> Result<Value> {
        require(candidates.len() <= 100, "global materialization limit")?;
        self.base.progress_handler(1000, Some(move || Instant::now() > deadline));
        let mut accepted=Vec::new(); let mut documents=BTreeMap::new();let mut sources=BTreeMap::new();let mut evidence=BTreeMap::new();
        let mut proofs = ProofContext::new(&self.base, query);
        for proof in semantic_evidence::pin_proofs(&mut proofs, all_pins, &mut sources)? {
            evidence.insert((text(&proof, "source_id")?.to_owned(), text(&proof, "evidence_id")?.to_owned(), String::new()), proof);
        }
        for candidate in candidates {
            require(Instant::now() <= deadline, "query_budget_exceeded")?;
            let key=EntryKey::parse(&candidate["entry"])?;
            if !options.accepts(&key) {continue;}
            require(key.kind != "episode", "FULL episode excluded")?;
            let eid=proofs.entry(&key)?;
            for p in candidate["provenance"].as_array().ok_or("invalid provenance")? {
                let hit=&p["hit"];
                require(EntryKey::parse(&hit["entry"])? == key, "hit typed identity mismatch")?;
                let did=text(hit,"document_id")?;
                let doc=self.base.query_row("SELECT title,original,status,source_id,evidence_id FROM documents WHERE id=? AND entry_id=? AND status IN ('source_backed','generated_from_evidence')",params![did,eid],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?,r.get::<_,String>(4)?)))?;
                require(hit["source_id"]==doc.3 && hit["evidence_id"]==doc.4,"document evidence mismatch")?;
                validate_full_document_cached(&self.base,did,eid,&self.full_members)?;
                add_source(&self.base,&mut sources,&doc.3)?;
                evidence.insert((doc.3.clone(),doc.4.clone(),did.to_owned()),json!({"document_id":did,"entry_id":eid.to_string(),"source_id":doc.3,"evidence_id":doc.4,"status":doc.2}));
                documents.insert(did.to_owned(),json!({"document_id":did,"entry_id":eid.to_string(),"entry_key":key.json(),"title":doc.0,"original":doc.1,"status":doc.2,"source_id":doc.3,"evidence_id":doc.4}));
            }
            for pin in candidate["trusted_pins"].as_array().ok_or("invalid pins")? {
                require(EntryKey::parse(&pin["entry"])? == key,"pin typed identity mismatch")?;
                proofs.pin(pin)?;add_source(&self.base,&mut sources,text(pin,"source_id")?)?;
            }
            accepted.push(candidate.clone());
        }
        let citations:Vec<_>=documents.values().map(|d|json!({"document_id":d["document_id"],"source_id":d["source_id"],"evidence_id":d["evidence_id"]})).chain(evidence.values().filter(|e|e.get("document_id").is_none()).cloned()).collect();
        // These local documents already belong to selected candidates. Candidate
        // origins are federated while local proof rows are not yet pack-qualified:
        // close only in the caller after qualification, never before that boundary.
        Ok(json!({"candidates":accepted,"trusted_pins":all_pins,"documents":documents.into_values().collect::<Vec<_>>(),"sources":sources.into_values().collect::<Vec<_>>(),"evidence":evidence.into_values().collect::<Vec<_>>(),"citations":citations}))
    }
}
fn validate_source_manifest(source: &Value) -> Result<()> {
    require(source["schema"] == "sakura-source-pack-v1", "unsupported source schema")?;
    let model_id = text(source, "requires_model")?;
    let contract = shared_encoder_contract(model_id)?;
    if model_id == "embeddinggemma-2" {
        let projection = &source["text_projection"];
        require(projection["model_revision"] == contract["revision"], "source model revision mismatch")?;
        for field in ["document_template", "untitled_document"] {
            require(projection[field] == contract[field], "source document encoding mismatch")?;
        }
        require(projection["synthetic_test_encoder"] == false, "synthetic source cannot use the production encoder")?;
        require(projection["document_text"] == "canonical_title_and_original" && projection["max_sequence_tokens"] == 512,
            "source text projection mismatch")?;
    }
    text(source, "pack_id")?;
    require(source["capabilities"].as_array().is_some_and(|v| v.iter().any(|s| s == "semantic")), "semantic capability required")?;
    let s = &source["semantic"];
    require(s["rows"].as_u64().is_some_and(|n| n > 0 && n <= i64::MAX as u64) && s["dimension"] == contract["dimension"] && s["metric"] == "cos" && s["dtype"] == "i8" && s["connectivity"] == 16 && s["expansion_add"] == 256 && s["expansion_search"] == 2048 && s["chunk_depth"].as_u64().is_some_and(|n| (512..=65536).contains(&n)), "invalid source semantic contract")?;
    require(source["artifacts"]["snapshot"]["identity"] == "knowledge.sqlite", "source snapshot identity must be knowledge.sqlite")?;
    Ok(())
}
/// FULL lexical retrieval with the same trust proofs and evidence closure, without ORT/ANN.
pub fn lexical_retrieve(db: impl AsRef<Path>, query: &str, options: &RetrieveOptions) -> Result<Value> {
    lexical_retrieve_until(db, query, options, Instant::now()+std::time::Duration::from_secs(5))
}
pub(crate) fn lexical_retrieve_until(db: impl AsRef<Path>, query: &str, options: &RetrieveOptions, deadline: Instant) -> Result<Value> {
    lexical_retrieve_projection(db.as_ref(), query, options, deadline, false)
}
pub(crate) fn lexical_retrieve_deferred(db: &Path, query: &str, options: &RetrieveOptions, deadline: Instant) -> Result<Value> {
    lexical_retrieve_projection(db, query, options, deadline, true)
}
fn lexical_retrieve_projection(db: &Path, query: &str, options: &RetrieveOptions, deadline: Instant, defer_bodies: bool) -> Result<Value> {
    options.validate()?;
    validate_query(query)?;
    let mut runtime=crate::Runtime::open(db)?;
    runtime.set_deadline(deadline);
    let response=runtime.search(query,100,options.kind.as_deref(),options.namespace.as_deref())?;
    let mut candidates=response["candidates"].as_array().cloned().unwrap_or_default();
    for candidate in &mut candidates {candidate["entry"]=candidate["entry_key"].clone();}
    let pins:Vec<_>=candidates.iter().filter(|c|c["matched_by"]=="exact"||c["matched_by"]=="alias").cloned().collect();
    let conn=readonly(db.as_ref())?;let compiled=crate::match_query(query).map_err(|e|e.to_string())?;
    conn.progress_handler(1000,Some(move || Instant::now()>deadline));
    let mut hits=Vec::new();let mut documents=Vec::new();let mut sources=BTreeMap::new();let mut evidence=Vec::new();
    if !compiled.is_empty() {
        let selected=rank_lexical_documents(&conn,&compiled,deadline)?;
        let mut stmt=conn.prepare("SELECT '', '',source_id,evidence_id,status,payload FROM documents WHERE id=? AND entry_id=?")?;
        for (score,kind,namespace,value,did,eid) in selected {
            require(Instant::now()<=deadline,"query_budget_exceeded lexical materialization")?;
            let (title,original,sid,refid,status,payload):(String,String,String,String,String,String)=stmt.query_row(params![did,eid],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?)))?;
            let payload:Value=serde_json::from_str(&payload)?;
            let key=json!({"kind":kind,"namespace":namespace,"value":value});let did=did.to_string();let eid=eid.to_string();
            let hit=json!({"entry":key,"document_id":did,"source_id":sid,"evidence_id":refid,"rank":hits.len()+1,"score":score});hits.push(hit);
            documents.push(json!({"entry_key":key,"entry_id":eid,"document_id":did,"title":title,"original":original,"source_id":sid,"evidence_id":refid,"status":status,"text_provenance":payload["text_provenance"]}));
            evidence.push(json!({"entry_id":eid,"document_id":did,"source_id":sid,"evidence_id":refid,"status":status}));add_source(&conn,&mut sources,&sid)?;
        }
    }
    candidates.truncate(options.limit);
    let retained:Vec<_>=candidates.iter().chain(pins.iter()).cloned().collect();
    let identities=semantic_evidence::identity_proofs(&conn,&retained,&mut sources)?;
    evidence.extend(identities.iter().cloned());
    let citations:Vec<_>=documents.iter().map(|d|json!({"document_id":d["document_id"],"source_id":d["source_id"],"evidence_id":d["evidence_id"]})).chain(identities).collect();
    let mut result=json!({"status":"PASS","query":query,"response_version":"sakura-lexical-evidence-v1","identity_status":"not_asserted","candidates":candidates,"trusted_pins":pins,"dense_hits":[],"lexical_hits":hits,"hybrid":[],"documents":documents,"sources":sources.into_values().collect::<Vec<_>>(),"evidence":evidence,"citations":citations,"promoted_identities":[],"canonical":null,"entity_tag":null,"timings_ms":{},"lexical_mode":"trusted_documents_and_identity"});
    close_public_evidence(&mut result);
    if !defer_bodies { hydrate_documents(&conn, &mut result, "", deadline)?; }
    Ok(result)
}
// Used only after the final candidate limit and pack-qualified evidence closure.
// Ranking/proof metadata stays at its historical depth; discarded bodies never
// cross the SQL/Rust boundary. Recheck the exact retained document binding.
pub(crate) fn hydrate_lexical_documents(db: &Path, response: &mut Value, pack: &str, deadline: Instant) -> Result<()> {
    hydrate_documents(&readonly(db)?, response, pack, deadline)
}
fn hydrate_documents(conn: &Connection, response: &mut Value, pack: &str, deadline: Instant) -> Result<()> {
    conn.progress_handler(1000, Some(move || Instant::now() > deadline));
    let mut stmt = conn.prepare_cached("SELECT title,original,status,source_id,evidence_id FROM documents WHERE id=? AND entry_id=?")?;
    for doc in response["documents"].as_array_mut().ok_or("invalid documents")? {
        let local = pack.is_empty() && doc.get("source_packs").is_none();
        if !local && !doc["source_packs"].as_array().is_some_and(|ids| ids.iter().any(|id| id == pack)) { continue; }
        require(Instant::now() <= deadline, "query_budget_exceeded document hydration")?;
        let (title, original, status, sid, eid): (String,String,String,String,String) = stmt.query_row(
            params![text(doc,"document_id")?,text(doc,"entry_id")?], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?)))?;
        require(doc["status"] == status && doc["source_id"] == sid && doc["evidence_id"] == eid,
            "document evidence mismatch during hydration")?;
        doc["title"] = json!(title); doc["original"] = json!(original);
    }
    Ok(())
}
type LexicalDocument = (f64,String,String,String,i64,i64);
// Preserve the original proof SQL's document depth, eligibility, numeric scores and
// complete boundary ties, without sorting every matched full body in SQLite TEMP.
fn rank_lexical_documents(conn:&Connection, compiled:&str, deadline:Instant) -> Result<Vec<LexicalDocument>> {
    let mut rank=conn.prepare("SELECT rowid,rank FROM search_fts WHERE search_fts MATCH ?1 AND rank MATCH 'bm25()' ORDER BY rank")?;
    let mut cursor=rank.query([compiled])?;
    let mut metadata=conn.prepare("SELECT e.kind,e.namespace,e.value,d.id,d.entry_id FROM search_fts f JOIN documents d ON d.id=f.document_id JOIN entries e ON e.id=d.entry_id WHERE f.rowid=? AND e.conflicted=0 AND d.status IN ('source_backed','generated_from_evidence') AND EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed')")?;
    let mut selected:Vec<LexicalDocument>=Vec::new();
    while let Some(row)=cursor.next()? {
        require(Instant::now()<=deadline,"query_budget_exceeded lexical rank cursor")?;
        let score:f64=row.get(1)?;require(score.is_finite(),"nonfinite lexical score")?;
        if selected.len()==100 && score>selected[99].0 {break;}
        let Some((kind,namespace,value,did,eid))=metadata.query_row([row.get::<_,i64>(0)?],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,i64>(3)?,r.get::<_,i64>(4)?))).optional()? else {continue;};
        let item=(score,kind,namespace,value,did,eid);
        let pos=selected.partition_point(|other|lexical_document_order(other,&item).is_le());
        selected.insert(pos,item);if selected.len()>100 {selected.pop();}
    }
    Ok(selected)
}
fn lexical_document_order(a:&LexicalDocument,b:&LexicalDocument)->std::cmp::Ordering {
    // SQL numeric equality treats signed zero equally; nonfinite values fail above.
    a.0.partial_cmp(&b.0).unwrap().then_with(||(&a.1,&a.2,&a.3,a.4).cmp(&(&b.1,&b.2,&b.3,b.4)))
}
pub fn lexical_only_retrieve(db: impl AsRef<Path>, query: &str, options: &RetrieveOptions) -> Result<Value> {
    lexical_retrieve(db, query, options)
}
fn configure_search_expansion(index: &usearch::Index, contract: &Value) -> Result<()> {
    let width = contract["ann"]["expansion_search"].as_u64().ok_or("positive integer ef_search required")?;
    require(width > 0 && width <= 65536, "ef_search outside supported range")?;
    index.change_expansion_search(width as usize);
    require(index.expansion_search() == width as usize, "ef_search mismatch")
}
fn trusted_entry(c: &Connection, k: &EntryKey) -> Result<i64> {
    Ok(c.query_row("SELECT id FROM entries WHERE kind=? AND namespace=? AND value=? AND conflicted=0 AND EXISTS(SELECT 1 FROM entry_evidence v JOIN sources s ON s.source_id=v.source_id WHERE v.entry_id=entries.id AND v.status='source_backed')",params![k.kind,k.namespace,k.value],|r|r.get(0))?)
}
struct ProofContext<'a> {
    conn: &'a Connection,
    query: &'a str,
    entries: BTreeMap<EntryKey, i64>,
    pins: BTreeSet<(EntryKey, String, String, String)>,
}
impl<'a> ProofContext<'a> {
    fn new(conn: &'a Connection, query: &'a str) -> Self {
        Self { conn, query, entries: BTreeMap::new(), pins: BTreeSet::new() }
    }
    fn entry(&mut self, key: &EntryKey) -> Result<i64> {
        if let Some(id) = self.entries.get(key) { return Ok(*id); }
        let id = trusted_entry(self.conn, key)?;
        self.entries.insert(key.clone(), id);
        Ok(id)
    }
    fn pin(&mut self, pin: &Value) -> Result<i64> {
        let key = EntryKey::parse(&pin["entry"])?;
        let source = text(pin, "source_id")?;
        let evidence = text(pin, "evidence_id")?;
        let matched = text(pin, "match")?;
        let identity = (key.clone(), matched.to_owned(), source.to_owned(), evidence.to_owned());
        let eid = self.entry(&key)?;
        if self.pins.contains(&identity) { return Ok(eid); }
        let ok: bool = match matched {
            "exact" => {
                require(self.query == key.value, "exact pin query mismatch")?;
                self.conn.query_row("SELECT EXISTS(SELECT 1 FROM entry_evidence v JOIN sources s ON s.source_id=v.source_id WHERE v.entry_id=? AND v.source_id=? AND v.evidence_id=? AND v.status='source_backed')",params![eid,source,evidence],|r|r.get(0))?
            },
            "alias" => self.conn.query_row("SELECT EXISTS(SELECT 1 FROM aliases a JOIN sources s ON s.source_id=a.source_id WHERE a.entry_id=? AND a.source_id=? AND a.evidence_id=? AND a.text=? AND a.status='source_backed')",params![eid,source,evidence,self.query],|r|r.get(0))?,
            _ => return Err("invalid pin match".into()),
        };
        require(ok, "untrusted pin evidence")?;
        self.pins.insert(identity);
        Ok(eid)
    }
}
fn add_source(c: &Connection, sources: &mut BTreeMap<String, Value>, s: &str) -> Result<()> {
    if !sources.contains_key(s) {
        let raw: String =
            c.query_row("SELECT metadata FROM sources WHERE source_id=?", [s], |r| {
                r.get(0)
            })?;
        sources.insert(
            s.into(),
            json!({"source_id":s,"metadata":serde_json::from_str::<Value>(&raw)?}),
        );
    }
    Ok(())
}
fn validate_vector(v: &[f32], dimension: usize) -> Result<()> {
    require(
        v.len() == dimension && v.iter().all(|n| n.is_finite()),
        "invalid embedding values",
    )?;
    let n: f64 = v.iter().map(|&x| f64::from(x).powi(2)).sum();
    require(
        (n.sqrt() - 1.0).abs() <= 1e-4,
        "embedding is not L2 normalized",
    )
}
fn field_string(v: &Value, n: &str) -> Result<String> {
    if let Some(i) = v[n].as_i64() {
        require(i >= 0, "negative mapping ID")?;
        return Ok(i.to_string());
    }
    Ok(text(v, n)?.into())
}

fn mapping_projection(c: &Connection) -> Result<bool> {
    let columns: BTreeSet<String> = c.prepare("PRAGMA table_info(chunks)")?
        .query_map([], |row| row.get(1))?.collect::<std::result::Result<_, _>>()?;
    let projected = ["chunk_id","document_id","kind","namespace","value","source_id","evidence_id"].iter().all(|name| columns.contains(*name));
    c.prepare(if projected { "SELECT chunk_id,document_id,kind,namespace,value,source_id,evidence_id FROM chunks LIMIT 0" } else { "SELECT metadata FROM chunks LIMIT 0" })?;
    Ok(projected)
}
fn mapped_text(value: &rusqlite::types::Value, name: &str) -> Result<String> {
    match value {
        rusqlite::types::Value::Text(text) if !text.trim().is_empty() => Ok(text.clone()),
        _ => Err(format!("missing/nontext {name}").into()),
    }
}
fn mapped_id(value: &rusqlite::types::Value, name: &str) -> Result<String> {
    if let rusqlite::types::Value::Integer(id) = value {
        require(*id >= 0, "negative mapping ID")?;
        Ok(id.to_string())
    } else { mapped_text(value, name) }
}
fn dense_hits_for(
    c: &Connection,
    projected: bool,
    keys: &[u64],
    distances: &[f32],
    rows: usize,
    m: Mode,
    raw_chunks: bool,
) -> Result<Vec<Value>> {
    let depth = if m == Mode::Full { rows.min(512) } else { 512 };
    require(
        keys.len() == depth && distances.len() == depth,
        "512 ANN matches required",
    )?;
    let mut seen = BTreeSet::new();
    let mut positions = BTreeSet::new();
    let mut previous = f32::NEG_INFINITY;
    let mut hits = Vec::new();
    let mut stmt = c.prepare_cached(if projected { "SELECT chunk_id,document_id,kind,namespace,value,source_id,evidence_id FROM chunks WHERE position=?" } else { "SELECT metadata FROM chunks WHERE position=?" })?;
    for (&p, &d) in keys.iter().zip(distances) {
        require(
            p < rows as u64 && positions.insert(p),
            "invalid/duplicate ANN row",
        )?;
        require(
            d.is_finite() && d >= previous,
            "nonfinite/unordered ANN distance",
        )?;
        previous = d;
        let (key, columns, legacy) = if projected {
            let columns: Vec<rusqlite::types::Value> = stmt.query_row([p], |row| {
                (0..7).map(|i| row.get(i)).collect()
            })?;
            if columns.iter().any(|v| matches!(v, rusqlite::types::Value::Blob(_)) || matches!(v, rusqlite::types::Value::Real(n) if !n.is_finite())) {
                // Preserve JSONB interpretation and JSON nonfinite-number rejection
                // without serializing ordinary typed rows.
                let raw: String = c.prepare_cached("SELECT json_object('chunk_id',chunk_id,'document_id',document_id,'entry_key',json_object('kind',kind,'namespace',namespace,'value',value),'source_id',source_id,'evidence_id',evidence_id) FROM chunks WHERE position=?")?.query_row([p], |r| r.get(0))?;
                let row: Value = serde_json::from_str(&raw)?;
                (EntryKey::parse(&row["entry_key"])? , Vec::new(), row)
            } else {
                let key = EntryKey::from_parts(mapped_text(&columns[2],"kind")?, mapped_text(&columns[3],"namespace")?, mapped_text(&columns[4],"value")?)?;
                (key, columns, Value::Null)
            }
        } else {
            let raw: String = stmt.query_row([p], |r| r.get(0))?;
            let row: Value = serde_json::from_str(&raw)?;
            (EntryKey::parse(&row["entry_key"])? , Vec::new(), row)
        };
        let k = key;
        require(
            m != Mode::Full || k.kind != "episode",
            "FULL episode excluded",
        )?;
        if raw_chunks || (seen.insert(k.clone()) && hits.len() < 100) {
            let (chunk, document, source, evidence) = if !columns.is_empty() {
                (mapped_id(&columns[0],"chunk_id")?, mapped_id(&columns[1],"document_id")?, mapped_text(&columns[5],"source_id")?, mapped_text(&columns[6],"evidence_id")?)
            } else { (field_string(&legacy,"chunk_id")?, field_string(&legacy,"document_id")?, text(&legacy,"source_id")?.to_owned(), text(&legacy,"evidence_id")?.to_owned()) };
            let mut hit=json!({"entry":k.json(),"rank":hits.len()+1,"score":1.0-f64::from(d),"document_id":document,"chunk_id":chunk,"source_id":source,"evidence_id":evidence});
            if raw_chunks { hit["distance"]=json!(d);hit["local_position"]=json!(p); }
            hits.push(hit);
        }
    }
    if m == Mode::Pilot {
        require(
            hits.len() == 100,
            "fewer than 100 unique ANN entries; no backfill",
        )?;
    }
    Ok(hits)
}
fn read_pins(stmt: &mut rusqlite::Statement<'_>, q: &str) -> Result<Vec<Value>> {
    read_pins_cached(stmt, q, None)
}
fn read_pins_cached(stmt: &mut rusqlite::Statement<'_>, q: &str, members: Option<&[(i64,i64)]>) -> Result<Vec<Value>> {
    let mut cursor = stmt.query([q])?;
    let mut pins = Vec::new();
    while let Some(r) = cursor.next()? {
        if let Some(members) = members {
            let eid: i64 = r.get(6)?;
            let pos = members.partition_point(|&(entry, _)| entry < eid);
            if members.get(pos).map(|&(entry, _)| entry) != Some(eid) { continue; }
        }
        let k = EntryKey::parse(
            &json!({"kind":r.get::<_,String>(0)?,"namespace":r.get::<_,String>(1)?,"value":r.get::<_,String>(2)?}),
        )?;
        let how: String = r.get(3)?;
        require(
            matches!(how.as_str(), "exact" | "alias"),
            "invalid pin match",
        )?;
        let p = json!({"entry":k.json(),"match":how,"source_id":r.get::<_,String>(4)?,"evidence_id":r.get::<_,String>(5)?});
        text(&p, "source_id")?;
        text(&p, "evidence_id")?;
        pins.push(p);
    }
    Ok(pins)
}
fn read_lexical(stmt: &mut rusqlite::Statement<'_>, q: &str) -> Result<Vec<Value>> {
    let mut cursor = stmt.query([q])?;
    let mut hits = Vec::new();
    while let Some(r) = cursor.next()? {
        let k = EntryKey::parse(
            &json!({"kind":r.get::<_,String>(0)?,"namespace":r.get::<_,String>(1)?,"value":r.get::<_,String>(2)?}),
        )?;
        let score: f64 = r.get(3)?;
        require(score.is_finite(), "nonfinite BM25 score")?;
        let h = json!({"entry":k.json(),"rank":hits.len()+1,"score":score,"document_id":r.get::<_,i64>(4)?.to_string(),"chunk_id":null,"source_id":r.get::<_,String>(5)?,"evidence_id":r.get::<_,String>(6)?});
        text(&h, "source_id")?;
        text(&h, "evidence_id")?;
        hits.push(h);
    }
    Ok(hits)
}
fn lexical_hits(c: &Connection, q: &str, compiled: &str) -> Result<(Vec<Value>, Vec<Value>)> {
    let mut stmt=c.prepare_cached("SELECT DISTINCT kind,namespace,value,match,source_id,evidence_id FROM pins WHERE text=? ORDER BY kind,namespace,value,match,source_id,evidence_id")?;
    let pins = read_pins(&mut stmt, q).map_err(|e| format!("pins SQL: {e}"))?;
    let hits = if compiled.is_empty() {
        Vec::new()
    } else {
        let mut stmt=c.prepare_cached("SELECT d.kind,d.namespace,d.value,bm25(search_fts) AS score,d.document_id,d.source_id,d.evidence_id FROM search_fts JOIN documents d ON d.document_id=search_fts.document_id WHERE search_fts MATCH ? ORDER BY score,d.kind,d.namespace,d.value,d.document_id LIMIT 100")?;
        read_lexical(&mut stmt, compiled).map_err(|e| format!("BM25 SQL: {e}"))?
    };
    Ok((hits, pins))
}
// Source-backed document trust; source/evidence resolution is a separate output check.
// Raw document depth is applied before entry deduplication in fuse.

fn load_prepared_members(path: &Path, manifest: &Value) -> Result<Vec<(i64,i64,i64)>> {
    require(is_portable(manifest) || manifest["artifacts"]["lexical_membership"]["path"] == "lexical-membership.sqlite", "local membership required: run explicit prepare-lexical")?;
    if !is_portable(manifest) {
        let bytes = std::fs::read(path)?;
        require(sha256(&bytes) == text(&manifest["artifacts"]["lexical_membership"],"sha256")?, "membership digest mismatch: run explicit prepare-lexical")?;
    }
    let c = readonly(path)?;
    let integrity: String = c.query_row("PRAGMA integrity_check",[],|r| r.get(0))?;
    require(integrity == "ok", "membership corrupt: run explicit prepare-lexical")?;
    let tables: Vec<String> = c.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")?.query_map([],|r| r.get(0))?.collect::<rusqlite::Result<_>>()?;
    require(tables == ["members","meta"], "membership schema mismatch: run explicit prepare-lexical")?;
    let columns: Vec<(String,String,i64,i64)> = c.prepare("PRAGMA table_info(members)")?.query_map([],|r| Ok((r.get(1)?,r.get(2)?,r.get(3)?,r.get(5)?)))?.collect::<rusqlite::Result<_>>()?;
    require(columns == [("fts_rowid".into(),"INTEGER".into(),0,1),("entry_id".into(),"INTEGER".into(),1,0),("document_id".into(),"INTEGER".into(),1,0)], "membership schema mismatch: run explicit prepare-lexical")?;
    let meta_columns: Vec<(String,String,i64,i64)> = c.prepare("PRAGMA table_info(meta)")?.query_map([],|r| Ok((r.get(1)?,r.get(2)?,r.get(3)?,r.get(5)?)))?.collect::<rusqlite::Result<_>>()?;
    require(meta_columns == [("key".into(),"TEXT".into(),0,1),("value".into(),"TEXT".into(),1,0)], "membership meta schema: run explicit prepare-lexical")?;
    let meta_count: i64 = c.query_row("SELECT count(*) FROM meta",[],|r| r.get(0))?;
    require(meta_count == if is_portable(manifest) { 5 } else { 4 }, "membership meta keys: run explicit prepare-lexical")?;
    let mut stmt = c.prepare("SELECT key,value FROM meta ORDER BY key")?;
    let meta: BTreeMap<String,String> = stmt.query_map([],|r| Ok((r.get(0)?,r.get(1)?)))?.collect::<rusqlite::Result<_>>()?;
    let declaration = &manifest["lexical_membership"];
    let rows = declaration["rows"].as_u64().ok_or("membership rows: run explicit prepare-lexical")?;
    let mut expected = BTreeMap::from([
        ("version".to_owned(),"p4-full-membership-v1".to_owned()),
        ("snapshot_sha256".to_owned(),text(&manifest["snapshot"],"sha256")?.to_owned()),
        ("snapshot_size".to_owned(),manifest["snapshot"]["size"].as_u64().ok_or("snapshot size")?.to_string()),
        ("rows".to_owned(),rows.to_string())]);
    if is_portable(manifest) {
        let identity = text(&manifest["snapshot"],"identity")?;
        require(declaration["snapshot_identity"] == identity, "membership snapshot identity mismatch")?;
        expected.insert("snapshot_identity".into(),identity.into());
    }
    require(meta == expected && declaration["version"] == "p4-full-membership-v1" &&
        declaration["snapshot_sha256"] == manifest["snapshot"]["sha256"] &&
        declaration["snapshot_size"] == manifest["snapshot"]["size"], "membership binding mismatch: run explicit prepare-lexical")?;
    let mut stmt = c.prepare("SELECT fts_rowid,entry_id,document_id FROM members ORDER BY fts_rowid")?;
    let mut cursor = stmt.query([])?;
    let mut members = Vec::new();
    while let Some(row) = cursor.next()? {
        let item: (i64,i64,i64) = (row.get(0)?,row.get(1)?,row.get(2)?);
        require(members.last().is_none_or(|&(id,_,_)| id < item.0), "membership duplicate/order: run explicit prepare-lexical")?;
        require(item.0>0 && item.1>0 && item.2>0,"membership IDs must be positive")?;
        members.push(item);
    }
    require(members.len() as u64 == rows, "membership row count mismatch: run explicit prepare-lexical")?;
    Ok(members)
}


fn validate_full_document_cached(c: &Connection, did: &str, eid: i64, members: &[(i64,i64)]) -> Result<()> {
    // Use SQLite's actual integer ID; preserve its original parameter coercion.
    let mut stmt = c.prepare_cached("SELECT d.id FROM documents d WHERE d.id=? AND d.entry_id=? AND EXISTS(SELECT 1 FROM sources s WHERE s.source_id=d.source_id) AND length(trim(d.evidence_id))>0")?;
    let mut rows = stmt.query(params![did,eid])?;
    let ok = match rows.next()? {
        Some(row) => members.binary_search(&(eid,row.get::<_,i64>(0)?)).is_ok(),
        None => false,
    };
    require(ok, "untrusted FULL document")
}

fn full_lexical_hits_ranked(c: &Connection, q: &str, compiled: &str, members: &[(i64,i64)], fts: &[(i64,i64,i64)], deadline: Instant, stages: &mut (f64,f64), work: &mut (usize,usize,usize)) -> Result<(Vec<Value>,Vec<Value>)> {
    let start = Instant::now();
    let sql = "SELECT DISTINCT e.kind AS kind,e.namespace AS namespace,e.value AS value,'exact' AS match,v.source_id AS source_id,v.evidence_id AS evidence_id,e.id AS entry_id FROM entries e JOIN entry_evidence v ON v.entry_id=e.id JOIN sources s ON s.source_id=v.source_id WHERE e.value=?1 AND v.status='source_backed' AND length(trim(v.evidence_id))>0 UNION SELECT DISTINCT e.kind,e.namespace,e.value,'alias',a.source_id,a.evidence_id,e.id FROM entries e JOIN aliases a ON a.entry_id=e.id JOIN sources s ON s.source_id=a.source_id WHERE a.text=?1 AND a.status='source_backed' AND length(trim(a.evidence_id))>0 ORDER BY kind,namespace,value,match,source_id,evidence_id";
    let mut pins_stmt = c.prepare_cached(sql)?;
    let pins = read_pins_cached(&mut pins_stmt,q,Some(members))?;
    stages.0 = ms(start);
    let start = Instant::now();
    let hits = rank_full_hits(c,compiled,fts,deadline,work).map_err(|e| format!("rank cursor: {e}; pins_ms={}; cursor_ms={}",stages.0,ms(start)))?;
    stages.1 = ms(start);
    Ok((hits,pins))
}
fn rank_full_hits(c: &Connection, compiled: &str, fts: &[(i64,i64,i64)], deadline: Instant, work: &mut (usize,usize,usize)) -> Result<Vec<Value>> {
    if compiled.is_empty() { return Ok(Vec::new()); }
    let mut stmt = c.prepare_cached("SELECT rowid,rank FROM search_fts WHERE search_fts MATCH ?1 AND rank MATCH 'bm25()' ORDER BY rank")?;
    let mut cursor = stmt.query([compiled])?;
    let mut metadata = c.prepare_cached("SELECT kind,namespace,value FROM entries WHERE id=?")?;
    let mut chosen: Vec<(f64,String,String,String,i64,i64)> = Vec::new();
    let mut read = 0usize; let mut eligible = 0usize; let mut ties = 0usize;
    while let Some(row) = cursor.next()? {
        read += 1;
        require(deadline.elapsed().as_secs_f64() <= 5.0,"query_budget_exceeded rank cursor")?;
        let id: i64 = row.get(0)?; let score: f64 = row.get(1)?;
        require(score.is_finite(),"nonfinite FTS rank")?;
        if chosen.len() == 100 && score > chosen[99].0 { break; }
        let Ok(pos) = fts.binary_search_by_key(&id, |&(r,_,_)| r) else { continue; };
        let (_,eid,did) = fts[pos]; eligible += 1;
        if chosen.len() == 100 && score == chosen[99].0 { ties += 1; }
        let (kind,namespace,value): (String,String,String) = metadata.query_row([eid],|r| Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?;
        let candidate = (score,kind,namespace,value,did,eid);
        let pos = chosen.partition_point(|other| {
            other.0.total_cmp(&candidate.0).then_with(|| (&other.1,&other.2,&other.3,other.4).cmp(&(&candidate.1,&candidate.2,&candidate.3,candidate.4))).is_le()
        });
        chosen.insert(pos,candidate);
        if chosen.len() > 100 { chosen.pop(); }
    }
    let mut result = Vec::new();
    let mut evidence = c.prepare_cached("SELECT source_id,evidence_id FROM documents WHERE id=? AND entry_id=?")?;
    for (score,kind,namespace,value,did,eid) in chosen {
        require(deadline.elapsed().as_secs_f64() <= 5.0,"query_budget_exceeded rank evidence")?;
        let (source,proof): (String,String) = evidence.query_row(params![did,eid],|r| Ok((r.get(0)?,r.get(1)?)))?;
        let entry = EntryKey::parse(&json!({"kind":kind,"namespace":namespace,"value":value}))?;
        let hit = json!({"entry":entry.json(),"rank":result.len()+1,"score":score,"chunk_id":null,"document_id":did.to_string(),"source_id":source,"evidence_id":proof});
        text(&hit,"source_id")?; text(&hit,"evidence_id")?;
        result.push(hit);
    }
    // Work counters are attached to query telemetry, never obtained with COUNT.
    *work = (read,eligible,ties);
    Ok(result)
}


#[derive(Default)]
struct Candidate {
    ranks: BTreeMap<&'static str, usize>,
    provenance: Vec<Value>,
    pins: Vec<Value>,
}
fn fuse(lexical: &[Value], dense: &[Value], pins: &[Value]) -> Result<Vec<Value>> {
    let mut candidates: BTreeMap<EntryKey, Candidate> = BTreeMap::new();
    for (backend, hits) in [("bm25", lexical), ("dense", dense)] {
        for (i, h) in hits.iter().enumerate() {
            require(
                h["rank"].as_u64() == Some((i + 1) as u64) && i < 100,
                "invalid branch rank",
            )?;
            let c = candidates.entry(EntryKey::parse(&h["entry"])?).or_default();
            c.ranks.entry(backend).or_insert(i + 1);
            c.provenance.push(json!({"backend":backend,"hit":h}));
        }
    }
    for p in pins {
        candidates
            .entry(EntryKey::parse(&p["entry"])?)
            .or_default()
            .pins
            .push(p.clone());
    }
    let mut ordered: Vec<_> = candidates
        .into_iter()
        .map(|(k, c)| {
            let s: f64 = c.ranks.values().map(|&r| 1.0 / (60.0 + r as f64)).sum();
            (k, c, s)
        })
        .collect();
    ordered.sort_by(|a, b| {
        a.1.pins
            .is_empty()
            .cmp(&b.1.pins.is_empty())
            .then_with(|| {
                if a.1.pins.is_empty() {
                    b.2.total_cmp(&a.2)
                } else {
                    std::cmp::Ordering::Equal
                }
            })
            .then_with(|| a.0.cmp(&b.0))
    });
    Ok(ordered.into_iter().enumerate().map(|(i,(k,c,s))|json!({"entry":k.json(),"hybrid_rank":i+1,"rrf_score":s,"backend_ranks":c.ranks.into_iter().collect::<Vec<_>>(),"provenance":c.provenance,"trusted_pins":c.pins,"warnings":[WARNING]})).collect())
}
