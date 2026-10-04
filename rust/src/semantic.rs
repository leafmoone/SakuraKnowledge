//! Local-only semantic retrieval. Activation verifies current product bindings.
use ort::{ep, session::Session, value::Tensor};
use rusqlite::{params, Connection, OpenFlags};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    time::Instant,
};
use tokenizers::Tokenizer;
use usearch::{Index, MetricKind, ScalarKind};
pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const ROWS: usize = 52664;
const WARNING: &str =
    "Retrieval relevance is not verified identity or permission to promote identity.";
const DLL_SHA: &str = "4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847";
const LEX_SHA: &str = "c664b3c81181942d202321fe81448d2cfc4e00ab658b864732e758ce7a1829b3";
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
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Mode {
    Pilot,
    Full,
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
    if !resolved.starts_with(std::fs::canonicalize(repository)?) {
        let approved = proof.ok_or("external FULL artifact requires approved receipt")?;
        require(
            kind == "ort_dll"
                && resolved == approved.0
                && binding["size"].as_u64() == Some(approved.1)
                && binding["sha256"].as_str() == Some(approved.2.as_str()),
            "unapproved external FULL artifact",
        )?;
    }
    Ok(resolved)
}
// Current asset specification is shared with Python activation, not pilot receipts.
fn approved_full_dll(_repository: &Path) -> Result<(PathBuf, u64, String)> {
    let assets: Value = serde_json::from_str(CURRENT_ASSETS)?;
    require(
        assets["schema"] == "product_asset_spec_v1",
        "invalid current assets",
    )?;
    let binding = &assets["ort_dll"];
    validate_binding(binding)?;
    let path = PathBuf::from(text(binding, "path")?);
    require(path.is_absolute(), "external DLL must be absolute")?;
    reject_path_links(&path)?;
    Ok((
        artifact(Path::new(""), binding)?,
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
    let expected: BTreeSet<_> = [
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
    if manifest["pack_version"] == "p4-full-existing-assets-v1" {
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
        let path = full_artifact(repository, root, kind, binding, proof)?;
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
// Resolve only the compiled repository location, never the caller working directory.
fn canonical_bytes() -> Result<Vec<u8>> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("missing canonical repository root")?;
    let directory = root.join("configs");
    let path = root.join(CANONICAL_PATH);
    for p in [&directory, &path] {
        require(
            !std::fs::symlink_metadata(p)?.file_type().is_symlink(),
            "canonical symlink forbidden",
        )?;
    }
    let controlled = std::fs::canonicalize(root)?.join(CANONICAL_PATH);
    require(
        std::fs::canonicalize(&path)? == controlled,
        "canonical path escape",
    )?;
    let metadata = std::fs::metadata(&path)?;
    require(
        metadata.is_file() && metadata.len() <= 1_000_000,
        "canonical file size mismatch",
    )?;
    Ok(std::fs::read(path)?)
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
    let mut padded = bytes.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&((bytes.len() as u64) * 8).to_be_bytes());
    for block in padded.as_chunks::<64>().0 {
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
    h.iter().map(|word| format!("{word:08x}")).collect()
}
fn validate_manifest(v: &Value) -> Result<()> {
    let m = mode(v)?;
    let schema = match m {
        Mode::Pilot => "p4-rust-semantic-pack-v1",
        Mode::Full => "p4-rust-semantic-full-pack-v1",
    };
    require(v["schema"] == schema, "unsupported pack schema")?;
    text(v, "pack_version")?;
    text(&v["snapshot"], "identity")?;
    validate_binding(&v["snapshot"])?;
    let expected = if m == Mode::Pilot {
        fixed_contract()
    } else {
        full_contract(row_count(v)?)?
    };
    require(v["contract"] == expected, "semantic contract mismatch")?;
    require(
        v.get("full_declaration").is_none(),
        "private FULL declaration wrapper is forbidden",
    )?;
    if m == Mode::Full {
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
    } else {
        for n in [
            "canonical_contract",
            "declarative_contract",
            "full_chunk_count",
        ] {
            require(v.get(n).is_none(), "pilot must not carry FULL fields")?;
        }
    }
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
    let external = v["artifacts"]["external_data"]
        .as_array()
        .ok_or("external_data must be an array")?;
    require(!external.is_empty(), "missing external tensors")?;
    let mut names = BTreeSet::new();
    for t in external {
        validate_binding(t)?;
        require(names.insert(text(t, "path")?), "duplicate external tensor")?;
    }
    require(
        v["artifacts"]["ort_dll"]["sha256"] == DLL_SHA
            && v["artifacts"]["ort_dll"]["size"] == 15355936_u64,
        "unpinned ORT DLL",
    )?;
    if m == Mode::Full {
        let artifacts = v["artifacts"].as_object().ok_or("invalid artifacts")?;
        let expected: BTreeSet<_> = [
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
#[cfg(not(windows))]
fn runtime_version(_: &Path) -> Result<String> {
    Err("pinned Windows DLL required".into())
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
pub struct SemanticEngine {
    tokenizer: Tokenizer,
    session: Session,
    index: Index,
    mapping: Connection,
    lexical: Connection,
    base: Connection,
    manifest: Value,
    mode: Mode,
    rows: usize,
    pub open_timings_ms: Value,
}
impl SemanticEngine {
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
        let (paths, bp) = if mode == Mode::Full {
            let repository = Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .ok_or("missing controlled repository root")?;
            controlled_path(repository, p)?;
            let paths = full_paths(repository, root, &manifest, None)?;
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
        let mapping = readonly(&paths["mapping"])?;
        validate_mapping(&mapping, rows)?;
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
                && index.scalar_kind() == ScalarKind::F32
                && index.connectivity() == 16,
            "index contract mismatch",
        )?;
        index.change_expansion_search(128);
        require(index.expansion_search() == 128, "ef_search mismatch")?;
        let open_timings_ms = json!({"metadata":metadata_ms,"tokenizer":tokenizer_ms,"ort":ort_ms,"ann":ms(start),"total":ms(total)});
        Ok(Self {
            tokenizer,
            session,
            index,
            mapping,
            lexical,
            base,
            manifest,
            mode,
            rows,
            open_timings_ms,
        })
    }
    /// Branch depths precede filters, without backfill. All ambiguous pins remain.
    pub fn retrieve(&mut self, query: &str, options: &RetrieveOptions) -> Result<Value> {
        let total = Instant::now();
        options.validate()?;
        require(
            !query.is_empty() && query.chars().count() <= 4096,
            "query must contain 1..4096 characters",
        )?;
        for c in [&self.base, &self.lexical, &self.mapping] {
            c.progress_handler(1000, Some(move || total.elapsed().as_secs_f64() > 5.0));
        }
        let start = Instant::now();
        let compiled = crate::match_query(query).map_err(|e| e.to_string())?;
        let encoded = self
            .tokenizer
            .encode(query, true)
            .map_err(|e| e.to_string())?;
        let ids: Vec<i64> = encoded.get_ids().iter().map(|&v| i64::from(v)).collect();
        let mask: Vec<i64> = encoded
            .get_attention_mask()
            .iter()
            .map(|&v| i64::from(v))
            .collect();
        require(
            !ids.is_empty() && ids.len() == mask.len() && ids.len() <= 512,
            "invalid token shape",
        )?;
        let tokens = ids.len();
        let tokenize_ms = ms(start);
        let start = Instant::now();
        let output=self.session.run(ort::inputs!["input_ids"=>Tensor::from_array(([1usize,tokens],ids))?,"attention_mask"=>Tensor::from_array(([1usize,tokens],mask))?])?;
        let (shape, values) = output["embeddings"].try_extract_tensor::<f32>()?;
        require(
            shape.as_ref() == [1_i64, 1024],
            "unexpected embeddings shape",
        )?;
        validate_vector(values)?;
        // Exported graph performs CLS/L2; do not renormalize its f32 output.
        let vector = values.to_vec();
        drop(output);
        let ort_ms = ms(start);
        let start = Instant::now();
        let depth = if self.mode == Mode::Full {
            self.rows.min(512)
        } else {
            512
        };
        let matches = self.index.search(&vector, depth)?;
        let dense = dense_hits_for(
            &self.mapping,
            &matches.keys,
            &matches.distances,
            self.rows,
            self.mode,
        ).map_err(|e| format!("dense_mapping: {e}; tokenize_ms={tokenize_ms}; ort_ms={ort_ms}; total_ms={}", ms(total)))?;
        let ann_ms = ms(start);
        let start = Instant::now();
        let (lexical, pins) = if self.mode == Mode::Pilot {
            lexical_hits(&self.lexical, query, &compiled)?
        } else {
            full_lexical_hits(&self.lexical, query, &compiled).map_err(|e|
                format!("full_lexical: {e}; tokenize_ms={tokenize_ms}; ort_ms={ort_ms}; ann_ms={ann_ms}; lexical_ms={}; total_ms={}", ms(start), ms(total)))?
        };
        let bm25_ms = ms(start);
        let start = Instant::now();
        for pin in &pins {
            validate_pin(&self.base, query, pin)?;
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
            let eid = trusted_entry(&self.base, &key)?;
            candidate["typed_identity"] =
                json!({"namespace":key.namespace,"kind":key.kind,"entry_id":eid.to_string()});
            for p in candidate["provenance"]
                .as_array()
                .ok_or("invalid provenance")?
            {
                let hit = &p["hit"];
                let did = text(hit, "document_id")?;
                let doc=self.base.query_row("SELECT title,original,status,source_id,evidence_id FROM documents WHERE id=? AND entry_id=? AND status IN ('source_backed','generated_from_evidence')",params![did,eid],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?,r.get::<_,String>(4)?)))?;
                require(
                    hit["source_id"] == doc.3 && hit["evidence_id"] == doc.4,
                    "document evidence mismatch",
                )?;
                if self.mode == Mode::Full {
                    validate_full_document(&self.base, did, eid)?;
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
        let citations:Vec<_>=documents.values().map(|d|json!({"document_id":d["document_id"],"source_id":d["source_id"],"evidence_id":d["evidence_id"]})).collect();
        let mut result = json!({"contract_version":"2","response_version":"p4-semantic-evidence-v1","pack_version":self.manifest["pack_version"],"snapshot":self.manifest["snapshot"],"contract":self.manifest["contract"],"query":query,"status":"PASS","identity_status":"not_asserted","promoted_identities":[],"canonical":null,"entity_tag":null,"warnings":warnings,"trusted_pins":pins,"dense_hits":dense,"lexical_hits":lexical,"hybrid":fused.iter().take(100).collect::<Vec<_>>(),"candidates":candidates,"documents":documents.into_values().collect::<Vec<_>>(),"sources":sources.into_values().collect::<Vec<_>>(),"evidence":evidence.into_values().collect::<Vec<_>>(),"citations":citations,"actual_tokens":tokens,"filter_policy":"post_fusion_no_backfill"});
        if options.include_vector {
            result["vector"] = json!(vector);
        }
        let fusion_ms = ms(start);
        let elapsed = ms(total);
        require(elapsed <= 5000.0, "query_budget_exceeded")?;
        result["timings_ms"] = json!({"tokenize":tokenize_ms,"ort":ort_ms,"ann":ann_ms,"bm25":bm25_ms,"fusion_evidence":fusion_ms,"total":elapsed});
        Ok(result)
    }
}
fn trusted_entry(c: &Connection, k: &EntryKey) -> Result<i64> {
    Ok(c.query_row("SELECT id FROM entries WHERE kind=? AND namespace=? AND value=? AND conflicted=0 AND EXISTS(SELECT 1 FROM entry_evidence v JOIN sources s ON s.source_id=v.source_id WHERE v.entry_id=entries.id AND v.status='source_backed')",params![k.kind,k.namespace,k.value],|r|r.get(0))?)
}
fn validate_pin(c: &Connection, query: &str, p: &Value) -> Result<()> {
    let k = EntryKey::parse(&p["entry"])?;
    let eid = trusted_entry(c, &k)?;
    let s = text(p, "source_id")?;
    let e = text(p, "evidence_id")?;
    let ok:bool=match text(p,"match")? {
        "exact"=>{ require(query==k.value,"exact pin query mismatch")?; c.query_row("SELECT EXISTS(SELECT 1 FROM entry_evidence v JOIN sources s ON s.source_id=v.source_id WHERE v.entry_id=? AND v.source_id=? AND v.evidence_id=? AND v.status='source_backed')",params![eid,s,e],|r|r.get(0))? },
        "alias"=>c.query_row("SELECT EXISTS(SELECT 1 FROM aliases a JOIN sources s ON s.source_id=a.source_id WHERE a.entry_id=? AND a.source_id=? AND a.evidence_id=? AND a.text=? AND a.status='source_backed')",params![eid,s,e,query],|r|r.get(0))?,_=>return Err("invalid pin match".into()) };
    require(ok, "untrusted pin evidence")
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
fn validate_vector(v: &[f32]) -> Result<()> {
    require(
        v.len() == 1024 && v.iter().all(|n| n.is_finite()),
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
#[cfg(test)]
fn dense_hits(c: &Connection, k: &[u64], d: &[f32]) -> Result<Vec<Value>> {
    dense_hits_for(c, k, d, ROWS, Mode::Pilot)
}
fn dense_hits_for(
    c: &Connection,
    keys: &[u64],
    distances: &[f32],
    rows: usize,
    m: Mode,
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
    let mut stmt = c.prepare_cached("SELECT metadata FROM chunks WHERE position=?")?;
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
        let raw: String = stmt.query_row([p], |r| r.get(0))?;
        let row: Value = serde_json::from_str(&raw)?;
        let k = EntryKey::parse(&row["entry_key"])?;
        require(
            m != Mode::Full || k.kind != "episode",
            "FULL episode excluded",
        )?;
        if seen.insert(k.clone()) && hits.len() < 100 {
            hits.push(json!({"entry":k.json(),"rank":hits.len()+1,"score":1.0-f64::from(d),"document_id":field_string(&row,"document_id")?,"chunk_id":field_string(&row,"chunk_id")?,"source_id":text(&row,"source_id")?,"evidence_id":text(&row,"evidence_id")?}));
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
    let mut cursor = stmt.query([q])?;
    let mut pins = Vec::new();
    while let Some(r) = cursor.next()? {
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
// Exact p4_corpus.TRUST; source/evidence resolution is a separate output check.
// Raw document depth is applied before entry deduplication in fuse.
const FULL_DOCUMENT_TRUST: &str = "e.conflicted=0
 AND d.status IN ('source_backed','generated_from_evidence')
 AND e.kind!='episode'
 AND EXISTS (SELECT 1 FROM entry_evidence v
             WHERE v.entry_id=e.id AND v.status='source_backed')";
fn validate_full_document(c: &Connection, did: &str, eid: i64) -> Result<()> {
    let sql=format!("SELECT EXISTS(SELECT 1 FROM documents d JOIN entries e ON e.id=d.entry_id WHERE d.id=? AND e.id=? AND {FULL_DOCUMENT_TRUST} AND EXISTS(SELECT 1 FROM sources s WHERE s.source_id=d.source_id) AND length(trim(d.evidence_id))>0 AND EXISTS(SELECT 1 FROM search_fts f WHERE f.document_id=d.id AND f.entry_id=e.id AND f.text=d.search_text))");
    let ok: bool = c.query_row(&sql, params![did, eid], |r| r.get(0))?;
    require(ok, "untrusted FULL document")
}
fn full_lexical_hits(c: &Connection, q: &str, compiled: &str) -> Result<(Vec<Value>, Vec<Value>)> {
    let eligible=format!("e.conflicted=0 AND e.kind!='episode' AND EXISTS(SELECT 1 FROM documents d WHERE d.entry_id=e.id AND {FULL_DOCUMENT_TRUST} AND EXISTS(SELECT 1 FROM search_fts f WHERE f.document_id=d.id AND f.entry_id=e.id AND f.text=d.search_text))");
    let sql=format!("SELECT DISTINCT e.kind AS kind,e.namespace AS namespace,e.value AS value,'exact' AS match,v.source_id AS source_id,v.evidence_id AS evidence_id FROM entries e JOIN entry_evidence v ON v.entry_id=e.id JOIN sources s ON s.source_id=v.source_id WHERE e.value=?1 AND v.status='source_backed' AND length(trim(v.evidence_id))>0 AND {eligible} UNION SELECT DISTINCT e.kind,e.namespace,e.value,'alias',a.source_id,a.evidence_id FROM entries e JOIN aliases a ON a.entry_id=e.id JOIN sources s ON s.source_id=a.source_id WHERE a.text=?1 AND a.status='source_backed' AND length(trim(a.evidence_id))>0 AND {eligible} ORDER BY kind,namespace,value,match,source_id,evidence_id");
    let mut stmt = c.prepare_cached(&sql)?;
    let pins = read_pins(&mut stmt, q).map_err(|e| format!("pins SQL: {e}"))?;
    let hits = if compiled.is_empty() {
        Vec::new()
    } else {
        let sql=format!("SELECT e.kind,e.namespace,e.value,bm25(search_fts) AS score,d.id,d.source_id,d.evidence_id FROM search_fts JOIN documents d ON d.id=search_fts.document_id JOIN entries e ON e.id=d.entry_id WHERE search_fts MATCH ? AND search_fts.entry_id=e.id AND search_fts.text=d.search_text AND {FULL_DOCUMENT_TRUST} ORDER BY score,e.kind,e.namespace,e.value,d.id LIMIT 100");
        let mut stmt = c.prepare_cached(&sql)?;
        read_lexical(&mut stmt, compiled).map_err(|e| format!("BM25 SQL: {e}"))?
    };
    Ok((hits, pins))
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
#[cfg(test)]
mod tests {
    use super::*;
    fn key(v: &str) -> Value {
        json!({"kind":"subject","namespace":"test","value":v})
    }
    fn hit(v: &str, r: usize) -> Value {
        json!({"entry":key(v),"rank":r,"score":0.5,"document_id":r.to_string(),"chunk_id":null,"source_id":"s","evidence_id":"e"})
    }
    fn manifest() -> Value {
        let b = json!({"path":"artifact","size":1,"sha256":"a".repeat(64)});
        let mut a = json!({});
        for n in [
            "model",
            "tokenizer",
            "ort_dll",
            "index",
            "mapping",
            "corpus",
            "lexical",
        ] {
            a[n] = b.clone();
        }
        a["ort_dll"]["sha256"] = json!(DLL_SHA);
        a["ort_dll"]["size"] = json!(15355936);
        a["lexical"]["sha256"] = json!(LEX_SHA);
        a["external_data"] = json!([b]);
        let mut c = lexical_config();
        c["unicode_version"] = json!("16.0.0");
        c["sqlite_version"] = json!("3.51.2");
        c["model_sha256"] = json!("a".repeat(64));
        let mut s = b.clone();
        s["identity"] = json!("artifact");
        json!({"schema":"p4-rust-semantic-pack-v1","pack_version":"test","snapshot":s,"contract":fixed_contract(),"artifacts":a,"lexical_metadata":{"version":"p4-pilot-lexical-v1","document_count":50000,"snapshot":b,"corpus":b,"config":c,"config_sha256":"a".repeat(64),"binding_sha256":"b".repeat(64)}})
    }
    fn full_manifest() -> Value {
        let mut v = manifest();
        let d = full_declaration();
        v["schema"] = json!("p4-rust-semantic-full-pack-v1");
        v["object_type"] = json!("runtime_pack");
        let bytes = canonical_bytes().unwrap();
        v["canonical_contract"] = json!({"schema":"p4-full-semantic-contract-v1","path":CANONICAL_PATH,"size":bytes.len(),"sha256":sha256(&bytes)});
        v["contract"] = full_contract(7).unwrap();
        v["declarative_contract"] = d["declarative_contract"].clone();
        v["full_chunk_count"] = json!(7);
        v.as_object_mut().unwrap().remove("lexical_metadata");
        v["artifacts"].as_object_mut().unwrap().remove("lexical");
        v["snapshot"] = d["snapshot"].clone();
        v["snapshot"]["identity"] = v["snapshot"]["path"].clone();
        for name in [
            "model",
            "tokenizer",
            "ort_dll",
            "index",
            "mapping",
            "corpus",
        ] {
            v["artifacts"][name]["path"] = json!(name);
        }
        v["artifacts"]["external_data"][0]["path"] = json!("tensor");
        v
    }
    #[test]
    fn builder_synthetic_reader_interop() {
        // Env input is private to tests; production authority stays immutable.
        let Some(root) = std::env::var_os("SKNOW_P4_BUILD_INTEROP_DIR") else {
            // Normal matrix exercises shared manifest validation independently.
            validate_manifest(&full_manifest()).unwrap();
            return;
        };
        let root = PathBuf::from(root);
        let builder: Value = serde_json::from_slice(
            &std::fs::read(root.join("builder-runtime-manifest.json")).unwrap(),
        )
        .unwrap();
        let expected: Value =
            serde_json::from_slice(&std::fs::read(root.join("interop-expected.json")).unwrap())
                .unwrap();
        let mut v = builder.clone();
        let frozen = full_manifest();
        for name in ["canonical_contract", "declarative_contract"] {
            v[name] = frozen[name].clone();
        }
        v["contract"] = full_contract(row_count(&builder).unwrap()).unwrap();
        for name in ["identity", "size", "sha256"] {
            v["snapshot"][name] = frozen["snapshot"][name].clone();
        }
        for name in ["size", "sha256"] {
            v["artifacts"]["ort_dll"][name] = frozen["artifacts"]["ort_dll"][name].clone();
        }
        validate_manifest(&v).unwrap();
        let mut missing = v.clone();
        missing.as_object_mut().unwrap().remove("pack_version");
        assert!(validate_manifest(&missing).is_err());
        for field in ["schema", "lexical_metadata", "lexical"] {
            let mut mixed = v.clone();
            match field {
                "schema" => mixed["schema"] = json!("p4-rust-semantic-pack-v1"),
                "lexical_metadata" => mixed[field] = json!({}),
                _ => mixed["artifacts"][field] = v["artifacts"]["corpus"].clone(),
            }
            assert!(validate_manifest(&mixed).is_err());
        }
        let pack = root.join("synthetic");
        let mapping = full_artifact(
            &root,
            &pack,
            "mapping",
            &builder["artifacts"]["mapping"],
            None,
        )
        .unwrap();
        let before = std::fs::read(&mapping).unwrap();
        let c = readonly(&mapping).unwrap();
        assert!(c.execute("DELETE FROM chunks", []).is_err());
        let n = row_count(&v).unwrap();
        validate_mapping(&c, n).unwrap();
        let rows = expected["metadata"].as_array().unwrap();
        assert_eq!(rows.len(), n);
        let keys: Vec<u64> = (0..n as u64).collect();
        let distances = vec![0.0; n];
        for (position, row) in rows.iter().enumerate() {
            let raw: String = c
                .query_row(
                    "SELECT metadata FROM chunks WHERE position=?",
                    [position as u64],
                    |r| r.get(0),
                )
                .unwrap();
            assert_eq!(serde_json::from_str::<Value>(&raw).unwrap(), *row);
            let mut selected = keys.clone();
            selected.rotate_left(position);
            let hits = dense_hits_for(&c, &selected, &distances, n, Mode::Full).unwrap();
            let first = &hits[0];
            assert_eq!(
                EntryKey::parse(&first["entry"]).unwrap(),
                EntryKey::parse(&row["entry_key"]).unwrap()
            );
            for name in ["document_id", "chunk_id"] {
                assert_eq!(text(first, name).unwrap(), field_string(row, name).unwrap());
            }
            for name in ["source_id", "evidence_id"] {
                assert_eq!(first[name], row[name]);
            }
        }
        let corpus_path = full_artifact(
            &root,
            &pack,
            "corpus",
            &builder["artifacts"]["corpus"],
            None,
        )
        .unwrap();
        let bytes = std::fs::read(corpus_path).unwrap();
        assert_eq!(builder["artifacts"]["corpus"]["sha256"], sha256(&bytes));
        // Fixture-only JSONL join: production binds corpus, has no corpus parser.
        let docs: Vec<Value> = std::str::from_utf8(&bytes)
            .unwrap()
            .lines()
            .map(|s| serde_json::from_str(s).unwrap())
            .collect();
        assert_eq!(json!(docs), expected["documents"]);
        for row in rows {
            let doc = docs
                .iter()
                .find(|d| d["document_id"] == row["document_id"])
                .unwrap();
            for name in ["entry_key", "entry_id", "source_id", "evidence_id"] {
                assert_eq!(row[name], doc[name]);
            }
        }
        for sql in [
            "UPDATE chunks SET metadata='{}' WHERE position=0",
            "DELETE FROM chunks WHERE position=0",
        ] {
            let corrupt = root.join("rust-corrupt-mapping.sqlite");
            std::fs::copy(&mapping, &corrupt).unwrap();
            {
                let writable = Connection::open(&corrupt).unwrap();
                writable.execute(sql, []).unwrap();
            }
            {
                let bad = readonly(&corrupt).unwrap();
                assert!(
                    validate_mapping(&bad, n).is_err()
                        || dense_hits_for(&bad, &keys, &distances, n, Mode::Full).is_err()
                );
            }
            std::fs::remove_file(corrupt).unwrap();
        }
        for field in ["source_id", "document_id"] {
            let corrupt = root.join("rust-corrupt-mapping.sqlite");
            std::fs::copy(&mapping, &corrupt).unwrap();
            let mut invalid = rows[0].clone();
            invalid[field] = json!("wrong-fixture-provenance");
            {
                let writable = Connection::open(&corrupt).unwrap();
                writable
                    .execute(
                        "UPDATE chunks SET metadata=? WHERE position=0",
                        [invalid.to_string()],
                    )
                    .unwrap();
            }
            {
                let bad = readonly(&corrupt).unwrap();
                // Nonempty wrong provenance is readable, but fixture corpus closure
                // MUST fail: the runtime reader does not authenticate these joins.
                let hits = dense_hits_for(&bad, &keys, &distances, n, Mode::Full).unwrap();
                assert_ne!(hits[0][field], rows[0][field]);
                assert!(!docs
                    .iter()
                    .any(|doc| doc["document_id"] == invalid["document_id"]
                        && doc["source_id"] == invalid["source_id"]));
            }
            std::fs::remove_file(corrupt).unwrap();
        }
        drop(c);
        assert_eq!(std::fs::read(mapping).unwrap(), before);
    }
    #[test]
    fn full_paths_controlled_assets_receipt_exception_and_aliases() {
        let temp = std::env::temp_dir().join(format!("sknow-full-path-{}", std::process::id()));
        let repo = temp.join("ROOT");
        let pack = repo.join("build/packfolder");
        let assets = repo.join("assets");
        std::fs::create_dir_all(&pack).unwrap();
        std::fs::create_dir_all(&assets).unwrap();
        let result = (|| -> Result<()> {
            let mut v = json!({"snapshot":{"path":"../../assets/snapshot","size":1,"sha256":"a".repeat(64)},"artifacts":{}});
            for name in [
                "snapshot",
                "model",
                "tokenizer",
                "ort_dll",
                "index",
                "mapping",
                "corpus",
                "tensor",
            ] {
                std::fs::write(assets.join(name), b"x")?;
                if name != "snapshot" && name != "tensor" {
                    v["artifacts"][name] = json!({"path":format!("../../assets/{name}"),"size":1,"sha256":"a".repeat(64)});
                }
            }
            v["artifacts"]["external_data"] =
                json!([{"path":"../../assets/tensor","size":1,"sha256":"a".repeat(64)}]);
            full_paths(&repo, &pack, &v, None).unwrap();
            for name in ["model", "tokenizer", "index", "mapping", "corpus"] {
                let mut bad = v.clone();
                bad["artifacts"][name]["path"] = json!("../../assets/../assets/tensor");
                assert!(full_paths(&repo, &pack, &bad, None).is_err());
            }
            let mut bad = v.clone();
            bad["artifacts"]["model"]["path"] = v["snapshot"]["path"].clone();
            assert!(full_paths(&repo, &pack, &bad, None).is_err());
            for name in [
                "model",
                "tokenizer",
                "ort_dll",
                "index",
                "mapping",
                "corpus",
                "external_data",
            ] {
                let mut bad = v.clone();
                bad["artifacts"].as_object_mut().unwrap().remove(name);
                assert!(full_paths(&repo, &pack, &bad, None).is_err());
            }
            let mut bad = v.clone();
            bad["artifacts"]["extra"] = v["artifacts"]["model"].clone();
            assert!(full_paths(&repo, &pack, &bad, None).is_err());
            let outside = temp.join("outside.dll");
            std::fs::write(&outside, b"x")?;
            let binding = json!({"path":outside,"size":1,"sha256":"a".repeat(64)});
            let proof = (std::fs::canonicalize(&outside)?, 1, "a".repeat(64));
            assert!(full_artifact(&repo, &pack, "ort_dll", &binding, None).is_err());
            assert!(full_artifact(&repo, &pack, "ort_dll", &binding, Some(&proof)).is_ok());
            for kind in ["model", "snapshot", "external_data"] {
                assert!(full_artifact(&repo, &pack, kind, &binding, Some(&proof)).is_err());
            }
            for wrong in [
                (assets.join("ort_dll"), 1, proof.2.clone()),
                (proof.0.clone(), 2, proof.2.clone()),
                (proof.0.clone(), 1, "b".repeat(64)),
            ] {
                assert!(full_artifact(&repo, &pack, "ort_dll", &binding, Some(&wrong)).is_err());
            }
            let mut external = v.clone();
            external["artifacts"]["ort_dll"] = binding;
            assert!(full_paths(&repo, &pack, &external, Some(&proof)).is_ok());
            assert!(full_paths(&repo, &pack, &external, None).is_err());
            #[cfg(windows)]
            {
                let link = repo.join("junction");
                let status = std::process::Command::new("cmd")
                    .args(["/C", "mklink", "/J"])
                    .arg(&link)
                    .arg(&assets)
                    .output()?;
                require(status.status.success(), "test junction creation failed")?;
                assert!(full_artifact(
                    &repo,
                    &pack,
                    "model",
                    &json!({"path":link.join("model"),"size":1,"sha256":"a".repeat(64)}),
                    None
                )
                .is_err());
                std::fs::remove_dir(&link)?;
            }
            #[cfg(unix)]
            {
                let link = repo.join("symlink");
                std::os::unix::fs::symlink(&assets, &link)?;
                assert!(controlled_path(&repo, &link.join("model")).is_err());
            }
            Ok(())
        })();
        std::fs::remove_dir_all(temp).unwrap();
        result.unwrap();
    }
    #[test]
    fn malformed_contracts_fail_before_assets() {
        assert!(validate_manifest(&json!({})).is_err());
        assert!(EntryKey::parse(&json!({"kind":"unknown","namespace":"n","value":"v"})).is_err());
        assert!(EntryKey::parse(&key(" ")).is_err());
        for limit in [0, 101] {
            assert!(RetrieveOptions {
                limit,
                ..Default::default()
            }
            .validate()
            .is_err());
        }
        assert!(RetrieveOptions {
            namespace: Some(" ".into()),
            ..Default::default()
        }
        .validate()
        .is_err());
        let v = manifest();
        assert!(validate_manifest(&v).is_ok());
        for x in [
            Value::Null,
            json!([]),
            json!({"path":"x"}),
            json!([
                v["artifacts"]["external_data"][0],
                v["artifacts"]["external_data"][0]
            ]),
        ] {
            let mut b = v.clone();
            b["artifacts"]["external_data"] = x;
            assert!(validate_manifest(&b).is_err());
        }
        let mut b = v.clone();
        b["contract"]["intra_threads"] = json!(1);
        assert!(validate_manifest(&b).is_err());
        let mut b = v.clone();
        b["lexical_metadata"]["snapshot"]["sha256"] = json!("b".repeat(64));
        assert!(validate_manifest(&b).is_err());
        for n in lexical_config().as_object().unwrap().keys() {
            let mut b = v.clone();
            b["lexical_metadata"]["config"][n] = Value::Null;
            assert!(validate_manifest(&b).is_err(), "{n}");
        }
    }
    #[test]
    fn canonical_sha256_known_vectors() {
        assert_eq!(
            sha256(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
    #[test]
    fn full_canonical_binding_is_required_and_exact() {
        let v = full_manifest();
        let bytes = canonical_bytes().unwrap();
        assert!(verify_canonical_bytes(&v, &bytes).is_ok());
        for (field, value) in [
            ("schema", json!("p4-rust-semantic-full-pack-v1")),
            ("path", json!("../configs/p4-full-semantic-v1.json")),
            ("path", json!("configs/other.json")),
            ("path", json!("D:/configs/p4-full-semantic-v1.json")),
            ("size", json!(bytes.len() + 1)),
            ("size", json!(true)),
            ("sha256", json!("a".repeat(64))),
            ("sha256", json!("invalid")),
        ] {
            let mut b = v.clone();
            b["canonical_contract"][field] = value;
            assert!(validate_manifest(&b).is_err(), "{field}");
        }
        for field in ["canonical_contract", "object_type"] {
            let mut b = v.clone();
            b.as_object_mut().unwrap().remove(field);
            assert!(validate_manifest(&b).is_err());
        }
        for value in [Value::Null, json!({}), full_declaration()] {
            let mut b = v.clone();
            b["canonical_contract"] = value;
            assert!(validate_manifest(&b).is_err());
        }
        for value in [Value::Null, json!("canonical_contract"), json!(true)] {
            let mut b = v.clone();
            b["object_type"] = value;
            assert!(validate_manifest(&b).is_err());
        }
        let mut b = v.clone();
        b["schema"] = json!("p4-full-semantic-contract-v1");
        assert!(validate_manifest(&b).is_err());
    }
    #[test]
    fn canonical_format_is_not_history_but_contract_and_content_binding_are_checked() {
        let v = full_manifest();
        let bytes = canonical_bytes().unwrap();
        let mut changed = bytes.clone();
        changed.push(b' ');
        let mut equivalent = v.clone();
        equivalent["canonical_contract"]["size"] = json!(changed.len());
        equivalent["canonical_contract"]["sha256"] = json!(sha256(&changed));
        assert!(verify_canonical_bytes(&equivalent, &changed).is_ok());
        assert!(verify_canonical_bytes(&v, &changed).is_err());
        let mut declaration = full_declaration();
        declaration["declarative_contract"]["encoder"]["dimension"] = json!(4);
        let semantic_change = serde_json::to_vec(&declaration).unwrap();
        let mut mutated = bytes.clone();
        mutated[0] ^= 1;
        for actual in [semantic_change, mutated, Vec::new()] {
            let mut b = v.clone();
            b["canonical_contract"]["size"] = json!(actual.len());
            b["canonical_contract"]["sha256"] = json!(sha256(&actual));
            assert!(verify_canonical_bytes(&b, &actual).is_err());
        }
    }
    #[test]
    fn full_contract_is_shared_dynamic_and_not_mixed() {
        let v = full_manifest();
        assert!(validate_manifest(&v).is_ok());
        assert_eq!(row_count(&v).unwrap(), 7);
        assert_eq!(
            v["declarative_contract"],
            full_declaration()["declarative_contract"]
        );
        assert_eq!(v["declarative_contract"]["corpus"]["documents"], 1295638);
        assert!(v.get("full_declaration").is_none());
        assert!(full_contract(0).is_err());
        for n in ["schema", "dimension", "bm25_document_depth"] {
            let mut b = v.clone();
            b["contract"][n] = Value::Null;
            assert!(validate_manifest(&b).is_err());
        }
        let mut b = v.clone();
        b["artifacts"]["lexical"] = Value::Null;
        assert!(validate_manifest(&b).is_err());
        let mut b = v.clone();
        b["lexical_metadata"] = Value::Null;
        assert!(validate_manifest(&b).is_err());
    }
    #[test]
    fn full_artifact_closed_set_and_global_paths() {
        let v = full_manifest();
        let mut extra = v.clone();
        extra["artifacts"]["unexpected"] = extra["artifacts"]["model"].clone();
        assert!(validate_manifest(&extra).is_err());
        for name in [
            "model",
            "tokenizer",
            "ort_dll",
            "index",
            "mapping",
            "corpus",
            "external_data",
        ] {
            let mut missing = v.clone();
            missing["artifacts"].as_object_mut().unwrap().remove(name);
            assert!(validate_manifest(&missing).is_err());
        }
        for name in ["tokenizer", "index", "mapping", "corpus"] {
            let mut duplicate = v.clone();
            duplicate["artifacts"][name]["path"] = duplicate["artifacts"]["model"]["path"].clone();
            assert!(validate_manifest(&duplicate).is_err());
        }
        let mut duplicate = v.clone();
        duplicate["artifacts"]["model"]["path"] =
            duplicate["artifacts"]["external_data"][0]["path"].clone();
        assert!(validate_manifest(&duplicate).is_err());
    }
    #[test]
    fn full_requires_actual_top_level_declarative_contract() {
        let v = full_manifest();
        for x in [Value::Null, json!({}), full_declaration(), fixed_contract()] {
            let mut b = v.clone();
            b["declarative_contract"] = x;
            assert!(validate_manifest(&b).is_err());
        }
        let mut b = v.clone();
        b.as_object_mut().unwrap().remove("declarative_contract");
        assert!(validate_manifest(&b).is_err());
        b["full_declaration"] = full_declaration();
        assert!(validate_manifest(&b).is_err());
        let mut b = v.clone();
        b["full_declaration"] = full_declaration();
        assert!(validate_manifest(&b).is_err());
        for section in [
            "corpus", "encoder", "chunk", "ann", "hybrid", "runtime", "build",
        ] {
            let mut b = v.clone();
            b["declarative_contract"][section] = Value::Null;
            assert!(validate_manifest(&b).is_err(), "{section}");
        }
        let mut b = v.clone();
        b["declarative_contract"]["runtime"]["lexical_mode"] = json!("pilot_sidecar");
        assert!(validate_manifest(&b).is_err());
    }
    #[test]
    fn full_count_is_top_level_positive_integer_and_matches_projection() {
        let v = full_manifest();
        for x in [
            json!(0),
            json!(-1),
            json!(true),
            json!(7.0),
            json!("7"),
            json!(u64::MAX),
            Value::Null,
        ] {
            let mut b = v.clone();
            b["full_chunk_count"] = x;
            assert!(row_count(&b).is_err());
            assert!(validate_manifest(&b).is_err());
        }
        let mut b = v.clone();
        b.as_object_mut().unwrap().remove("full_chunk_count");
        assert!(validate_manifest(&b).is_err());
        for n in [1, 8, ROWS] {
            let mut b = v.clone();
            b["full_chunk_count"] = json!(n);
            assert_eq!(row_count(&b).unwrap(), n);
            assert!(validate_manifest(&b).is_err());
            b["contract"] = full_contract(n).unwrap();
            assert!(validate_manifest(&b).is_ok());
        }
        for x in [json!(0), json!(true), json!(ROWS), Value::Null] {
            for field in ["full_chunk_count", "rows"] {
                let mut b = v.clone();
                if field == "rows" {
                    b["contract"]["ann"][field] = x.clone();
                } else {
                    b["contract"][field] = x.clone();
                }
                assert!(validate_manifest(&b).is_err());
            }
        }
    }
    #[test]
    fn pilot_and_full_schema_and_fields_cannot_be_confused() {
        let full = full_manifest();
        let pilot = manifest();
        assert!(validate_manifest(&pilot).is_ok());
        assert_eq!(row_count(&pilot).unwrap(), ROWS);
        for (v, schema) in [
            (&full, "p4-rust-semantic-pack-v1"),
            (&pilot, "p4-full-semantic-contract-v1"),
        ] {
            let mut b = v.clone();
            b["schema"] = json!(schema);
            assert!(validate_manifest(&b).is_err());
        }
        for (v, lexical_mode) in [(&full, "pilot_sidecar"), (&pilot, "full_snapshot_fts")] {
            let mut b = v.clone();
            b["contract"]["lexical_mode"] = json!(lexical_mode);
            assert!(validate_manifest(&b).is_err());
        }
        for n in [
            "canonical_contract",
            "declarative_contract",
            "full_chunk_count",
        ] {
            let mut b = pilot.clone();
            b[n] = full[n].clone();
            assert!(validate_manifest(&b).is_err(), "{n}");
        }
        let mut b = pilot.clone();
        b["full_declaration"] = full_declaration();
        assert!(validate_manifest(&b).is_err());
        let mut b = pilot.clone();
        b["contract"]["ann"]["rows"] = json!(7);
        assert!(validate_manifest(&b).is_err());
    }
    #[test]
    fn full_snapshot_remains_bound_to_fixed_reference() {
        let v = full_manifest();
        for (field, x) in [
            ("identity", json!("wrong")),
            ("size", json!(1)),
            ("sha256", json!("a".repeat(64))),
        ] {
            let mut b = v.clone();
            b["snapshot"][field] = x;
            assert!(validate_manifest(&b).is_err(), "{field}");
        }
        let mut b = v.clone();
        b["snapshot"]["path"] = json!("relative-pack-snapshot.sqlite");
        assert!(validate_manifest(&b).is_ok());
    }
    #[test]
    fn all_tensor_sizes_and_snapshot_identity_are_checked() {
        let root = std::env::temp_dir().join(format!("sknow-semantic-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let result = (|| -> Result<()> {
            std::fs::write(root.join("artifact"), b"a")?;
            std::fs::write(root.join("second"), b"bb")?;
            let mut v = manifest();
            assert!(external_paths(&root, &v).is_ok());
            let mut second = v["artifacts"]["external_data"][0].clone();
            second["path"] = json!("second");
            v["artifacts"]["external_data"]
                .as_array_mut()
                .unwrap()
                .push(second);
            assert!(external_paths(&root, &v).is_err());
            v["artifacts"]["external_data"][1]["size"] = json!(2);
            assert!(external_paths(&root, &v).is_ok());
            assert!(snapshot_path(&root.join("artifact"), &root, &v["snapshot"]).is_ok());
            v["snapshot"]["identity"] = json!("wrong");
            assert!(snapshot_path(&root.join("artifact"), &root, &v["snapshot"]).is_err());
            v["snapshot"]["identity"] = json!("artifact");
            assert!(snapshot_path(&root.join("second"), &root, &v["snapshot"]).is_err());
            Ok(())
        })();
        std::fs::remove_dir_all(root).unwrap();
        result.unwrap();
    }
    #[test]
    fn embeddings_fail_closed_without_renormalizing() {
        assert!(validate_vector(&vec![0.0; 1024]).is_err());
        assert!(validate_vector(&vec![f32::NAN; 1024]).is_err());
        assert!(validate_vector(&vec![1.0; 1023]).is_err());
        assert!(validate_vector(&vec![1.0 / 32.0; 1024]).is_ok());
    }
    #[test]
    fn invalid_ann_never_backfills() {
        let c = Connection::open_in_memory().unwrap();
        assert!(dense_hits(&c, &[], &[]).is_err());
        c.execute_batch("CREATE TABLE chunks(position INTEGER PRIMARY KEY,metadata TEXT NOT NULL)")
            .unwrap();
        assert!(dense_hits(&c, &vec![ROWS as u64; 512], &vec![0.0; 512]).is_err());
        for p in 0..7 {
            let v = json!({"entry_key":key("a"),"document_id":1,"chunk_id":p,"source_id":"s","evidence_id":"e"});
            c.execute("INSERT INTO chunks VALUES(?,?)", params![p, v.to_string()])
                .unwrap();
        }
        validate_mapping(&c, 7).unwrap();
        assert!(validate_mapping(&c, ROWS).is_err());
        assert_eq!(
            dense_hits_for(&c, &[0, 1, 2, 3, 4, 5, 6], &[0.0; 7], 7, Mode::Full)
                .unwrap()
                .len(),
            1
        );
        assert!(dense_hits_for(&c, &[0, 1, 2, 3, 4, 5, 7], &[0.0; 7], 7, Mode::Full).is_err());
    }
    #[test]
    fn rrf_uses_first_raw_document_rank_and_source_key_ties() {
        let f = fuse(
            &[hit("z", 1), hit("z", 2), hit("a", 3)],
            &[hit("a", 1), hit("z", 2)],
            &[],
        )
        .unwrap();
        assert_eq!(f[0]["entry"], key("z"));
        assert_eq!(f[0]["provenance"].as_array().unwrap().len(), 3);
        assert_eq!(f[0]["rrf_score"], json!(1.0 / 61.0 + 1.0 / 62.0));
        assert_eq!(
            fuse(&[hit("z", 1)], &[hit("a", 1)], &[]).unwrap()[0]["entry"],
            key("a")
        );
        assert!(fuse(&[hit("a", 2)], &[], &[]).is_err());
    }
    #[test]
    fn trusted_pins_precede_scores_preserving_ambiguity() {
        let p = vec![
            json!({"entry":key("z"),"match":"exact","source_id":"s","evidence_id":"e"}),
            json!({"entry":key("a"),"match":"alias","source_id":"s","evidence_id":"e"}),
        ];
        let f = fuse(&[hit("z", 1)], &[], &p).unwrap();
        assert_eq!(f[0]["entry"], key("a"));
        assert_eq!(f[1]["entry"], key("z"));
        assert_eq!(f[0]["rrf_score"], 0.0);
    }
    #[test]
    fn lexical_raw_depth_and_verbatim_pins() {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE VIRTUAL TABLE search_fts USING fts5(text,document_id UNINDEXED,entry_id UNINDEXED); CREATE TABLE documents(document_id INTEGER,entry_id INTEGER,kind TEXT,namespace TEXT,value TEXT,source_id TEXT,evidence_id TEXT); CREATE TABLE pins(text TEXT,entry_id INTEGER,kind TEXT,namespace TEXT,value TEXT,match TEXT,source_id TEXT,evidence_id TEXT); INSERT INTO pins VALUES('Alpha',1,'subject','test','a','exact','s','e'); INSERT INTO documents VALUES(1,1,'subject','test','a','s','e'),(2,1,'subject','test','a','s','e'); INSERT INTO search_fts VALUES('alpha',1,1),('alpha',2,1);").unwrap();
        let (h, p) = lexical_hits(&c, "Alpha", "\"alpha\"").unwrap();
        assert_eq!(h.len(), 2);
        assert_eq!(p.len(), 1);
        assert_eq!(h[0]["document_id"], "1");
        assert!(lexical_hits(&c, "alpha", "").unwrap().1.is_empty());
    }
    #[test]
    fn pins_require_matching_trusted_evidence_not_only_entry_identity() {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE TABLE entries(id INTEGER,kind TEXT,namespace TEXT,value TEXT,conflicted INTEGER); CREATE TABLE sources(source_id TEXT,metadata TEXT); CREATE TABLE entry_evidence(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT); CREATE TABLE aliases(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT,text TEXT); INSERT INTO entries VALUES(1,'subject','test','a',0); INSERT INTO sources VALUES('s','{}'); INSERT INTO entry_evidence VALUES(1,'s','e','source_backed'); INSERT INTO aliases VALUES(1,'s','alias-e','source_backed','Alpha');").unwrap();
        let mut p =
            json!({"entry":key("a"),"match":"exact","source_id":"s","evidence_id":"forged"});
        assert!(validate_pin(&c, "a", &p).is_err());
        p["evidence_id"] = json!("e");
        assert!(validate_pin(&c, "a", &p).is_ok());
        assert!(validate_pin(&c, "Alpha", &p).is_err());
        p["match"] = json!("alias");
        assert!(validate_pin(&c, "Alpha", &p).is_err());
        p["evidence_id"] = json!("alias-e");
        assert!(validate_pin(&c, "Alpha", &p).is_ok());
        c.execute("UPDATE entries SET conflicted=1", []).unwrap();
        assert!(validate_pin(&c, "Alpha", &p).is_err());
    }
    fn native_fixture(c: &Connection) -> Result<()> {
        c.execute_batch("CREATE TABLE sources(source_id TEXT PRIMARY KEY,metadata TEXT); CREATE TABLE entries(id INTEGER PRIMARY KEY,kind TEXT,namespace TEXT,value TEXT,conflicted INTEGER); CREATE TABLE entry_evidence(id INTEGER PRIMARY KEY,entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT); CREATE TABLE aliases(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT,text TEXT); CREATE TABLE documents(id INTEGER PRIMARY KEY,entry_id INTEGER,title TEXT,original TEXT,search_text TEXT,status TEXT,source_id TEXT,evidence_id TEXT); CREATE VIRTUAL TABLE search_fts USING fts5(text,document_id UNINDEXED,entry_id UNINDEXED); CREATE TABLE build_meta(key TEXT,value TEXT); INSERT INTO sources VALUES('s','{\"provider\":\"bangumi\"}'); INSERT INTO build_meta VALUES('contract_version','2'),('index_episodes','false'); INSERT INTO entries VALUES(1,'subject','test','Alpha',0),(2,'character','other','Beta',0),(3,'episode','test','Episode',0),(4,'subject','test','Conflict',1),(5,'subject','test','Untrusted',0); INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status) VALUES(1,'s','e1','source_backed'),(2,'s','e2','source_backed'),(3,'s','e3','source_backed'),(4,'s','e4','source_backed'),(5,'s','e5','unverified'); INSERT INTO aliases VALUES(1,'s','a1','source_backed','Shared'),(2,'s','a2','source_backed','Shared'),(3,'s','a3','source_backed','Shared'),(4,'s','a4','source_backed','Shared'),(5,'s','a5','source_backed','Shared'),(1,'missing','forged','source_backed','Shared'),(1,'s','unverified','unverified','Shared');")?;
        c.execute(
            "INSERT INTO build_meta VALUES('snapshot',?)",
            ["a".repeat(64)],
        )?;
        for id in 1..=105 {
            c.execute("INSERT INTO documents VALUES(?,1,'Alpha','alpha','alpha','source_backed','s','d1')",[id])?;
            c.execute("INSERT INTO search_fts VALUES('alpha',?,1)", [id])?;
        }
        for (id, eid) in [(106, 2), (107, 3), (108, 4), (109, 5)] {
            c.execute("INSERT INTO documents VALUES(?,?,'Other','alpha','alpha','generated_from_evidence','s','d2')",params![id,eid])?;
            c.execute(
                "INSERT INTO search_fts VALUES('alpha',?,?)",
                params![id, eid],
            )?;
        }
        Ok(())
    }
    #[test]
    fn full_sql_trust_matches_approved_corpus_predicate() {
        let source = include_str!("../../tools/p4_corpus.py");
        let trust = source
            .split("TRUST = \"\"\"")
            .nth(1)
            .unwrap()
            .split("\"\"\"")
            .next()
            .unwrap();
        assert_eq!(
            FULL_DOCUMENT_TRUST.split_whitespace().collect::<Vec<_>>(),
            trust.split_whitespace().collect::<Vec<_>>()
        );
        let c = Connection::open_in_memory().unwrap();
        native_fixture(&c).unwrap();
        c.execute(
            "UPDATE entry_evidence SET source_id='missing' WHERE entry_id=2",
            [],
        )
        .unwrap();
        let (h, _) = full_lexical_hits(&c, "", "\"alpha\"").unwrap();
        assert!(h.iter().any(|v| v["entry"]["value"] == "Beta"));
        assert!(trusted_entry(
            &c,
            &EntryKey::parse(&json!({"kind":"character","namespace":"other","value":"Beta"}))
                .unwrap()
        )
        .is_err());
    }
    #[test]
    fn native_full_fts_trust_pins_depth_filters_and_provenance() {
        let c = Connection::open_in_memory().unwrap();
        native_fixture(&c).unwrap();
        validate_snapshot_policy(&c, Mode::Full).unwrap();
        let (h, p) = full_lexical_hits(&c, "Shared", "\"alpha\"").unwrap();
        assert_eq!(h.len(), 100);
        assert_eq!(p.len(), 2);
        for pin in &p {
            validate_pin(&c, "Shared", pin).unwrap();
        }
        assert_eq!(p[0]["entry"]["kind"], "character");
        assert_eq!(p[1]["entry"], key("Alpha"));
        assert!(full_lexical_hits(&c, "shared", "").unwrap().1.is_empty());
        let (_, exact) = full_lexical_hits(&c, "Alpha", "").unwrap();
        assert_eq!(exact.len(), 1);
        assert_eq!(exact[0]["match"], "exact");
        let f = fuse(&h, &[], &p).unwrap();
        assert_eq!(f.len(), 2);
        assert_eq!(f[0]["entry"]["kind"], "character");
        let alpha = f.iter().find(|v| v["entry"] == key("Alpha")).unwrap();
        assert_eq!(alpha["provenance"].as_array().unwrap().len(), 99);
        let o = RetrieveOptions {
            kind: Some("subject".into()),
            namespace: Some("test".into()),
            ..Default::default()
        };
        assert_eq!(
            f.iter()
                .filter(|v| o.accepts(&EntryKey::parse(&v["entry"]).unwrap()))
                .count(),
            1
        );
        assert_eq!(p.len(), 2);
        validate_full_document(&c, "1", 1).unwrap();
        assert!(validate_full_document(&c, "107", 3).is_err());
        c.execute("UPDATE documents SET evidence_id='' WHERE id=1", [])
            .unwrap();
        assert!(validate_full_document(&c, "1", 1).is_err());
        c.execute(
            "UPDATE build_meta SET value='true' WHERE key='index_episodes'",
            [],
        )
        .unwrap();
        assert!(validate_snapshot_policy(&c, Mode::Full).is_err());
    }
    #[test]
    fn native_full_readonly_independent_handles_close_on_success_and_error() {
        let root = std::env::temp_dir().join(format!("sknow-full-native-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("snapshot.sqlite");
        let result = (|| -> Result<()> {
            {
                let c = Connection::open(&path)?;
                native_fixture(&c)?;
            }
            let before = std::fs::read(&path)?;
            {
                let base = readonly(&path)?;
                let lexical = readonly(&path)?;
                let mapping = readonly(&path)?;
                for c in [&base, &lexical, &mapping] {
                    assert_eq!(
                        c.query_row("PRAGMA query_only", [], |r| r.get::<_, i64>(0))?,
                        1
                    );
                    assert!(c.execute("DELETE FROM entries", []).is_err());
                }
                base.execute_batch("PRAGMA query_only=OFF")?;
                assert!(base.execute("DELETE FROM entries", []).is_err());
                assert_eq!(
                    lexical.query_row("PRAGMA query_only", [], |r| r.get::<_, i64>(0))?,
                    1
                );
                assert_eq!(
                    full_lexical_hits(&lexical, "Shared", "\"alpha\"")?.0.len(),
                    100
                );
                assert!(full_lexical_hits(&lexical, "Shared", "\"").is_err());
            }
            assert_eq!(std::fs::read(&path)?, before);
            // On Windows this succeeds only after handles and cached statements close.
            std::fs::remove_file(&path)?;
            Ok(())
        })();
        std::fs::remove_dir_all(&root).unwrap();
        result.unwrap();
    }
}
