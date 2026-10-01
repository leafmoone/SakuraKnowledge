//! Local-only semantic pilot. Activation verifies full artifact hashes; open only
//! checks manifest contracts, sizes and identities. Activated packs must be immutable.
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

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct EntryKey {
    pub kind: String,
    pub namespace: String,
    pub value: String,
}
impl EntryKey {
    fn parse(v: &Value) -> Result<Self> {
        let key = Self {
            kind: text(v, "kind")?.into(),
            namespace: text(v, "namespace")?.into(),
            value: text(v, "value")?.into(),
        };
        require(
            matches!(
                key.kind.as_str(),
                "subject" | "character" | "person" | "episode" | "page" | "tag"
            ),
            "invalid EntryKey kind",
        )?;
        require(
            key.namespace.chars().count() <= 1024 && key.value.chars().count() <= 1024,
            "invalid EntryKey length",
        )?;
        Ok(key)
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
        if let Some(kind) = &self.kind {
            EntryKey::parse(&json!({"kind":kind,"namespace":"x","value":"x"}))?;
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
    json!({"lexical_mode":"pilot_sidecar","revision":"5617a9f61b028005a4858fdac845db406aefb181",
        "dimension":1024,"pooling":"cls","normalize":true,"query_prefix":"","dtype":"float32",
        "output":"embeddings","provider":"CPUExecutionProvider","ort_version":"1.24.1",
        "intra_threads":8,"inter_threads":1,"sequential":true,
        "ann":{"rows":52664,"metric":"cos","dtype":"f32","connectivity":16,"expansion_add":256,"expansion_search":128,"chunk_depth":512,"entry_depth":100},
        "bm25_document_depth":100,"rrf_k":60,"ties":"kind,namespace,value","pins":"trusted_exact_alias"})
}
fn require(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}
fn text<'a>(v: &'a Value, field: &str) -> Result<&'a str> {
    v[field]
        .as_str()
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| format!("missing/nontext {field}").into())
}
fn digest(v: &Value) -> bool {
    v.as_str().is_some_and(|s| {
        s.len() == 64
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}
fn ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
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
    let path = root.join(text(v, "path")?);
    let meta = std::fs::metadata(&path)?;
    require(
        meta.is_file() && Some(meta.len()) == v["size"].as_u64(),
        "artifact file size mismatch",
    )?;
    Ok(std::fs::canonicalize(path)?)
}
fn lexical_config() -> Value {
    json!({"version":"p4-pilot-lexical-v1",
        "fts_schema":"CREATE VIRTUAL TABLE search_fts USING fts5(text, document_id UNINDEXED, entry_id UNINDEXED)",
        "tokenizer":"FTS5 default unicode61 remove_diacritics=1",
        "text":"search_text((title + SPACE + original)[:100000])",
        "query":"model.match_query: NFKC/casefold, CJK bigrams, quoted OR",
        "document_depth":100,"depth_before_entry_dedup":true,
        "ties":"score ASC, kind ASC, namespace ASC, value ASC, document_id ASC",
        "pins":"verbatim value or source_backed alias; trusted nonconflicted pilot entries only; typed-key order",
        "pin_depth":"all pins retained separately; final ranking capped at 100",
        "identity_assertions":"none; ambiguity is never collapsed"})
}
fn validate_manifest(v: &Value) -> Result<()> {
    require(
        v["schema"] == "p4-rust-semantic-pack-v1",
        "unsupported pack schema",
    )?;
    text(v, "pack_version")?;
    text(&v["snapshot"], "identity")?;
    validate_binding(&v["snapshot"])?;
    require(
        v["contract"] == fixed_contract(),
        "semantic contract mismatch",
    )?;
    for name in [
        "model",
        "tokenizer",
        "ort_dll",
        "index",
        "mapping",
        "corpus",
        "lexical",
    ] {
        validate_binding(&v["artifacts"][name])?;
    }
    let external = v["artifacts"]["external_data"]
        .as_array()
        .ok_or("external_data must be an array")?;
    require(!external.is_empty(), "missing external tensors")?;
    let mut names = BTreeSet::new();
    for tensor in external {
        validate_binding(tensor)?;
        require(
            names.insert(text(tensor, "path")?),
            "duplicate external tensor",
        )?;
    }
    require(
        v["artifacts"]["ort_dll"]["sha256"] == DLL_SHA
            && v["artifacts"]["ort_dll"]["size"] == 15355936_u64,
        "unpinned ORT DLL",
    )?;
    require(
        v["artifacts"]["lexical"]["sha256"] == LEX_SHA,
        "unpinned lexical sidecar",
    )?;
    let lex = &v["lexical_metadata"];
    require(
        lex["version"] == "p4-pilot-lexical-v1"
            && lex["document_count"] == 50000
            && lex["snapshot"]["sha256"] == v["snapshot"]["sha256"]
            && lex["snapshot"]["size"] == v["snapshot"]["size"]
            && lex["corpus"]["sha256"] == v["artifacts"]["corpus"]["sha256"]
            && lex["corpus"]["size"] == v["artifacts"]["corpus"]["size"],
        "lexical manifest binding mismatch",
    )?;
    let expected = lexical_config();
    for (name, value) in expected.as_object().unwrap() {
        require(
            lex["config"][name] == *value,
            "lexical configuration mismatch",
        )?;
    }
    require(
        digest(&lex["config"]["model_sha256"])
            && digest(&lex["config_sha256"])
            && digest(&lex["binding_sha256"]),
        "invalid lexical configuration binding",
    )?;
    require(
        lex["config"]["unicode_version"] == "16.0.0",
        "lexical Unicode version mismatch",
    )?;
    text(&lex["config"], "sqlite_version")?;
    Ok(())
}
fn external_paths(root: &Path, manifest: &Value) -> Result<()> {
    let mut paths = BTreeSet::new();
    for tensor in manifest["artifacts"]["external_data"]
        .as_array()
        .ok_or("external_data must be an array")?
    {
        require(
            paths.insert(artifact(root, tensor)?),
            "duplicate external tensor path",
        )?;
    }
    require(!paths.is_empty(), "missing external tensors")
}
fn snapshot_path(base: &Path, root: &Path, snapshot: &Value) -> Result<PathBuf> {
    let bound = artifact(root, snapshot)?;
    require(
        std::fs::canonicalize(base)? == bound,
        "snapshot path mismatch",
    )?;
    // Driver identity is repository-relative filename, NOT build_meta.snapshot
    // (the latter is the source manifest hash).
    let identity = Path::new(text(snapshot, "identity")?);
    require(
        !identity.is_absolute()
            && identity
                .components()
                .all(|c| matches!(c, std::path::Component::Normal(_)))
            && bound.ends_with(identity),
        "snapshot identity mismatch",
    )?;
    Ok(bound)
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
        let module = GetModuleHandleW(name.as_ptr());
        require(!module.is_null(), "explicit ORT DLL not loaded")?;
        let symbol = GetProcAddress(module, c"OrtGetApiBase".as_ptr().cast());
        require(!symbol.is_null(), "missing OrtGetApiBase")?;
        let get: unsafe extern "system" fn() -> *const ort::sys::OrtApiBase =
            std::mem::transmute(symbol);
        let base = get().as_ref().ok_or("null OrtApiBase")?;
        let version = (base.GetVersionString)();
        require(!version.is_null(), "null runtime version")?;
        Ok(CStr::from_ptr(version).to_str()?.into())
    }
}
#[cfg(not(windows))]
fn runtime_version(_: &Path) -> Result<String> {
    Err("pinned Windows DLL required".into())
}

pub struct SemanticEngine {
    tokenizer: Tokenizer,
    session: Session,
    index: Index,
    mapping: Connection,
    lexical: Connection,
    base: Connection,
    manifest: Value,
    pub open_timings_ms: Value,
}
impl SemanticEngine {
    pub fn open(base_db: impl AsRef<Path>, manifest_path: impl AsRef<Path>) -> Result<Self> {
        let total = Instant::now();
        let path = manifest_path.as_ref();
        require(
            std::fs::metadata(path)?.len() <= 1_000_000,
            "manifest too large",
        )?;
        let manifest: Value = serde_json::from_slice(&std::fs::read(path)?)?;
        validate_manifest(&manifest)?;
        let root = path.parent().ok_or("manifest has no parent")?;
        let mut paths = BTreeMap::new();
        for name in [
            "model",
            "tokenizer",
            "ort_dll",
            "index",
            "mapping",
            "corpus",
            "lexical",
        ] {
            paths.insert(name, artifact(root, &manifest["artifacts"][name])?);
        }
        external_paths(root, &manifest)?;
        let base = readonly(&snapshot_path(
            base_db.as_ref(),
            root,
            &manifest["snapshot"],
        )?)?;
        let identity: String = base.query_row(
            "SELECT value FROM build_meta WHERE key='snapshot'",
            [],
            |r| r.get(0),
        )?;
        require(digest(&json!(identity)), "invalid snapshot build identity")?;
        let contract: String = base.query_row(
            "SELECT value FROM build_meta WHERE key='contract_version'",
            [],
            |r| r.get(0),
        )?;
        require(contract == "2", "snapshot contract mismatch")?;
        let lexical = readonly(&paths["lexical"])?;
        let metadata: String = lexical.query_row("SELECT value FROM metadata", [], |r| r.get(0))?;
        require(
            serde_json::from_str::<Value>(&metadata)? == manifest["lexical_metadata"],
            "lexical metadata mismatch",
        )?;
        let mapping = readonly(&paths["mapping"])?;
        let bounds: (i64, i64, i64) = mapping.query_row(
            "SELECT count(*),min(position),max(position) FROM chunks",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        require(
            bounds == (ROWS as i64, 0, ROWS as i64 - 1),
            "mapping row identity mismatch",
        )?;
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
        let index_path = paths["index"].to_str().ok_or("non UTF-8 index path")?;
        let metadata = Index::metadata(index_path)?;
        require(
            metadata.dimensions == 1024 && metadata.metric == MetricKind::Cos,
            "index metadata mismatch",
        )?;
        let index = Index::new(&metadata.into())?;
        index.view(index_path)?;
        require(
            index.size() == ROWS
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
            open_timings_ms,
        })
    }
    /// Fixed branch depths precede optional filtering, without backfill. Raw
    /// branches remain unfiltered to permit offline verification.
    pub fn retrieve(&mut self, query: &str, options: &RetrieveOptions) -> Result<Value> {
        let total = Instant::now();
        options.validate()?;
        require(
            !query.is_empty() && query.chars().count() <= 4096,
            "query must contain 1..4096 characters",
        )?;
        for conn in [&self.base, &self.lexical, &self.mapping] {
            conn.progress_handler(1000, Some(move || total.elapsed().as_secs_f64() > 5.0));
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
        let output = self.session.run(ort::inputs!["input_ids" => Tensor::from_array(([1usize,tokens],ids))?, "attention_mask" => Tensor::from_array(([1usize,tokens],mask))?])?;
        let (shape, values) = output["embeddings"].try_extract_tensor::<f32>()?;
        require(
            shape.as_ref() == [1_i64, 1024],
            "unexpected embeddings shape",
        )?;
        validate_vector(values)?;
        // The exported graph already performs CLS/L2. Preserve exact f32 output.
        let vector = values.to_vec();
        drop(output);
        let ort_ms = ms(start);
        let start = Instant::now();
        let matches = self.index.search(&vector, 512)?;
        let dense = dense_hits(&self.mapping, &matches.keys, &matches.distances)?;
        let ann_ms = ms(start);
        let start = Instant::now();
        let (lexical, pins) = lexical_hits(&self.lexical, query, &compiled)?;
        let bm25_ms = ms(start);
        let start = Instant::now();
        // Validate every pin, including pins outside the output cap.
        for pin in &pins {
            validate_pin(&self.base, query, pin)?;
        }
        let fused = fuse(&lexical, &dense, &pins)?;
        let mut candidates = Vec::new();
        let mut documents = BTreeMap::new();
        let mut sources = BTreeMap::new();
        let mut evidence = BTreeMap::new();
        for candidate in fused.iter().take(100) {
            let key = EntryKey::parse(&candidate["entry"])?;
            if !options.accepts(&key) {
                continue;
            }
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
                let doc = self.base.query_row("SELECT title,original,status,source_id,evidence_id FROM documents WHERE id=? AND entry_id=? AND status IN ('source_backed','generated_from_evidence')",params![did,eid],|r| Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?,r.get::<_,String>(4)?)))?;
                require(
                    hit["source_id"] == doc.3 && hit["evidence_id"] == doc.4,
                    "document evidence mismatch",
                )?;
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
        let citations: Vec<_> = documents.values().map(|d| json!({"document_id":d["document_id"],"source_id":d["source_id"],"evidence_id":d["evidence_id"]})).collect();
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
fn trusted_entry(base: &Connection, key: &EntryKey) -> Result<i64> {
    Ok(base.query_row("SELECT id FROM entries WHERE kind=? AND namespace=? AND value=? AND conflicted=0 AND EXISTS(SELECT 1 FROM entry_evidence v JOIN sources s ON s.source_id=v.source_id WHERE v.entry_id=entries.id AND v.status='source_backed')",params![key.kind,key.namespace,key.value],|r| r.get(0))?)
}
fn validate_pin(base: &Connection, query: &str, pin: &Value) -> Result<()> {
    let key = EntryKey::parse(&pin["entry"])?;
    let eid = trusted_entry(base, &key)?;
    let source = text(pin, "source_id")?;
    let evidence = text(pin, "evidence_id")?;
    let exists: bool = match text(pin,"match")? {
        "exact" => {
            require(query==key.value,"exact pin query mismatch")?;
            base.query_row("SELECT EXISTS(SELECT 1 FROM entry_evidence v JOIN sources s ON s.source_id=v.source_id WHERE v.entry_id=? AND v.source_id=? AND v.evidence_id=? AND v.status='source_backed')",params![eid,source,evidence],|r| r.get(0))?
        }
        "alias" => base.query_row("SELECT EXISTS(SELECT 1 FROM aliases a JOIN sources s ON s.source_id=a.source_id WHERE a.entry_id=? AND a.source_id=? AND a.evidence_id=? AND a.text=? AND a.status='source_backed')",params![eid,source,evidence,query],|r| r.get(0))?,
        _ => return Err("invalid pin match".into()),
    };
    require(exists, "untrusted pin evidence")
}
fn add_source(
    base: &Connection,
    sources: &mut BTreeMap<String, Value>,
    source: &str,
) -> Result<()> {
    if !sources.contains_key(source) {
        let raw: String = base.query_row(
            "SELECT metadata FROM sources WHERE source_id=?",
            [source],
            |r| r.get(0),
        )?;
        sources.insert(
            source.into(),
            json!({"source_id":source,"metadata":serde_json::from_str::<Value>(&raw)?}),
        );
    }
    Ok(())
}
fn validate_vector(v: &[f32]) -> Result<()> {
    require(
        v.len() == 1024 && v.iter().all(|n| n.is_finite()),
        "invalid embedding values",
    )?;
    let norm: f64 = v.iter().map(|&x| f64::from(x).powi(2)).sum();
    require(
        (norm.sqrt() - 1.0).abs() <= 1e-4,
        "embedding is not L2 normalized",
    )
}
fn field_string(v: &Value, name: &str) -> Result<String> {
    if let Some(n) = v[name].as_i64() {
        require(n >= 0, "negative mapping ID")?;
        return Ok(n.to_string());
    }
    Ok(text(v, name)?.into())
}
fn dense_hits(mapping: &Connection, keys: &[u64], distances: &[f32]) -> Result<Vec<Value>> {
    require(
        keys.len() == 512 && distances.len() == 512,
        "512 ANN matches required",
    )?;
    let mut seen = BTreeSet::new();
    let mut rows = BTreeSet::new();
    let mut previous = f32::NEG_INFINITY;
    let mut hits = Vec::new();
    let mut statement = mapping.prepare_cached("SELECT metadata FROM chunks WHERE position=?")?;
    for (&position, &distance) in keys.iter().zip(distances) {
        require(
            position < ROWS as u64 && rows.insert(position),
            "invalid/duplicate ANN row",
        )?;
        require(
            distance.is_finite() && distance >= previous,
            "nonfinite/unordered ANN distance",
        )?;
        previous = distance;
        let raw: String = statement.query_row([position], |r| r.get(0))?;
        let row: Value = serde_json::from_str(&raw)?;
        let key = EntryKey::parse(&row["entry_key"])?;
        if seen.insert(key.clone()) && hits.len() < 100 {
            hits.push(json!({"entry":key.json(),"rank":hits.len()+1,"score":1.0-f64::from(distance),"document_id":field_string(&row,"document_id")?,"chunk_id":field_string(&row,"chunk_id")?,"source_id":text(&row,"source_id")?,"evidence_id":text(&row,"evidence_id")?}));
        }
    }
    require(
        hits.len() == 100,
        "fewer than 100 unique ANN entries; no backfill",
    )?;
    Ok(hits)
}
fn lexical_hits(
    conn: &Connection,
    query: &str,
    compiled: &str,
) -> Result<(Vec<Value>, Vec<Value>)> {
    let mut statement = conn.prepare_cached("SELECT DISTINCT kind,namespace,value,match,source_id,evidence_id FROM pins WHERE text=? ORDER BY kind,namespace,value,match,source_id,evidence_id")?;
    let mut cursor = statement.query([query])?;
    let mut pins = Vec::new();
    while let Some(r) = cursor.next()? {
        let key = EntryKey::parse(
            &json!({"kind":r.get::<_,String>(0)?,"namespace":r.get::<_,String>(1)?,"value":r.get::<_,String>(2)?}),
        )?;
        let how: String = r.get(3)?;
        require(
            matches!(how.as_str(), "exact" | "alias"),
            "invalid pin match",
        )?;
        let pin = json!({"entry":key.json(),"match":how,"source_id":r.get::<_,String>(4)?,"evidence_id":r.get::<_,String>(5)?});
        text(&pin, "source_id")?;
        text(&pin, "evidence_id")?;
        pins.push(pin);
    }
    let mut hits = Vec::new();
    if !compiled.is_empty() {
        let mut statement = conn.prepare_cached("SELECT d.kind,d.namespace,d.value,bm25(search_fts) AS score,d.document_id,d.source_id,d.evidence_id FROM search_fts JOIN documents d ON d.document_id=search_fts.document_id WHERE search_fts MATCH ? ORDER BY score,d.kind,d.namespace,d.value,d.document_id LIMIT 100")?;
        let mut cursor = statement.query([compiled])?;
        while let Some(r) = cursor.next()? {
            let key = EntryKey::parse(
                &json!({"kind":r.get::<_,String>(0)?,"namespace":r.get::<_,String>(1)?,"value":r.get::<_,String>(2)?}),
            )?;
            let score: f64 = r.get(3)?;
            require(score.is_finite(), "nonfinite BM25 score")?;
            let hit = json!({"entry":key.json(),"rank":hits.len()+1,"score":score,"document_id":r.get::<_,i64>(4)?.to_string(),"chunk_id":null,"source_id":r.get::<_,String>(5)?,"evidence_id":r.get::<_,String>(6)?});
            text(&hit, "source_id")?;
            text(&hit, "evidence_id")?;
            hits.push(hit);
        }
    }
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
        for (i, hit) in hits.iter().enumerate() {
            require(
                hit["rank"].as_u64() == Some((i + 1) as u64) && i < 100,
                "invalid branch rank",
            )?;
            let c = candidates
                .entry(EntryKey::parse(&hit["entry"])?)
                .or_default();
            c.ranks.entry(backend).or_insert(i + 1);
            c.provenance.push(json!({"backend":backend,"hit":hit}));
        }
    }
    for pin in pins {
        candidates
            .entry(EntryKey::parse(&pin["entry"])?)
            .or_default()
            .pins
            .push(pin.clone());
    }
    let mut ordered: Vec<_> = candidates
        .into_iter()
        .map(|(key, c)| {
            let score: f64 = c.ranks.values().map(|&r| 1.0 / (60.0 + r as f64)).sum();
            (key, c, score)
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
    Ok(ordered.into_iter().enumerate().map(|(i,(key,c,score))| json!({"entry":key.json(),"hybrid_rank":i+1,"rrf_score":score,"backend_ranks":c.ranks.into_iter().collect::<Vec<_>>(),"provenance":c.provenance,"trusted_pins":c.pins,"warnings":[WARNING]})).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn key(value: &str) -> Value {
        json!({"kind":"subject","namespace":"test","value":value})
    }
    fn hit(value: &str, rank: usize) -> Value {
        json!({"entry":key(value),"rank":rank,"score":0.5,"document_id":rank.to_string(),"chunk_id":null,"source_id":"s","evidence_id":"e"})
    }
    fn manifest() -> Value {
        let binding = json!({"path":"artifact","size":1,"sha256":"a".repeat(64)});
        let mut artifacts = json!({});
        for name in [
            "model",
            "tokenizer",
            "ort_dll",
            "index",
            "mapping",
            "corpus",
            "lexical",
        ] {
            artifacts[name] = binding.clone();
        }
        artifacts["ort_dll"]["sha256"] = json!(DLL_SHA);
        artifacts["ort_dll"]["size"] = json!(15355936);
        artifacts["lexical"]["sha256"] = json!(LEX_SHA);
        artifacts["external_data"] = json!([binding]);
        let mut config = lexical_config();
        config["unicode_version"] = json!("16.0.0");
        config["sqlite_version"] = json!("3.51.2");
        config["model_sha256"] = json!("a".repeat(64));
        let mut snapshot = binding.clone();
        snapshot["identity"] = json!("artifact");
        json!({"schema":"p4-rust-semantic-pack-v1","pack_version":"test","snapshot":snapshot,"contract":fixed_contract(),"artifacts":artifacts,"lexical_metadata":{"version":"p4-pilot-lexical-v1","document_count":50000,"snapshot":binding,"corpus":binding,"config":config,"config_sha256":"a".repeat(64),"binding_sha256":"b".repeat(64)}})
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
        let valid = manifest();
        assert!(validate_manifest(&valid).is_ok());
        for invalid in [
            Value::Null,
            json!([]),
            json!({"path":"x"}),
            json!([
                valid["artifacts"]["external_data"][0],
                valid["artifacts"]["external_data"][0]
            ]),
        ] {
            let mut bad = valid.clone();
            bad["artifacts"]["external_data"] = invalid;
            assert!(validate_manifest(&bad).is_err());
        }
        let mut bad = valid.clone();
        bad["contract"]["intra_threads"] = json!(1);
        assert!(validate_manifest(&bad).is_err());
        let mut bad = valid.clone();
        bad["lexical_metadata"]["snapshot"]["sha256"] = json!("b".repeat(64));
        assert!(validate_manifest(&bad).is_err());
        for field in lexical_config().as_object().unwrap().keys() {
            let mut bad = valid.clone();
            bad["lexical_metadata"]["config"][field] = Value::Null;
            assert!(validate_manifest(&bad).is_err(), "{field}");
        }
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
        c.execute_batch(
            "CREATE TABLE chunks(position INTEGER PRIMARY KEY, metadata TEXT NOT NULL)",
        )
        .unwrap();
        assert!(dense_hits(&c, &vec![ROWS as u64; 512], &vec![0.0; 512]).is_err());
    }
    #[test]
    fn rrf_uses_first_raw_document_rank_and_source_key_ties() {
        let lexical = vec![hit("z", 1), hit("z", 2), hit("a", 3)];
        let dense = vec![hit("a", 1), hit("z", 2)];
        let fused = fuse(&lexical, &dense, &[]).unwrap();
        assert_eq!(fused[0]["entry"], key("z"));
        assert_eq!(fused[0]["provenance"].as_array().unwrap().len(), 3);
        assert_eq!(fused[0]["rrf_score"], json!(1.0 / 61.0 + 1.0 / 62.0));
        assert_eq!(
            fuse(&[hit("z", 1)], &[hit("a", 1)], &[]).unwrap()[0]["entry"],
            key("a")
        );
        assert!(fuse(&[hit("a", 2)], &[], &[]).is_err());
    }
    #[test]
    fn trusted_pins_precede_scores_preserving_ambiguity() {
        let pins = vec![
            json!({"entry":key("z"),"match":"exact","source_id":"s","evidence_id":"e"}),
            json!({"entry":key("a"),"match":"alias","source_id":"s","evidence_id":"e"}),
        ];
        let fused = fuse(&[hit("z", 1)], &[], &pins).unwrap();
        assert_eq!(fused[0]["entry"], key("a"));
        assert_eq!(fused[1]["entry"], key("z"));
        assert_eq!(fused[0]["rrf_score"], 0.0);
    }
    #[test]
    fn lexical_raw_depth_and_verbatim_pins() {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE VIRTUAL TABLE search_fts USING fts5(text,document_id UNINDEXED,entry_id UNINDEXED); CREATE TABLE documents(document_id INTEGER,entry_id INTEGER,kind TEXT,namespace TEXT,value TEXT,source_id TEXT,evidence_id TEXT); CREATE TABLE pins(text TEXT,entry_id INTEGER,kind TEXT,namespace TEXT,value TEXT,match TEXT,source_id TEXT,evidence_id TEXT); INSERT INTO pins VALUES('Alpha',1,'subject','test','a','exact','s','e'); INSERT INTO documents VALUES(1,1,'subject','test','a','s','e'),(2,1,'subject','test','a','s','e'); INSERT INTO search_fts VALUES('alpha',1,1),('alpha',2,1);").unwrap();
        let (hits, pins) = lexical_hits(&c, "Alpha", "\"alpha\"").unwrap();
        assert_eq!(hits.len(), 2);
        assert_eq!(pins.len(), 1);
        assert_eq!(hits[0]["document_id"], "1");
        assert!(lexical_hits(&c, "alpha", "").unwrap().1.is_empty());
    }
    #[test]
    fn pins_require_matching_trusted_evidence_not_only_entry_identity() {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE TABLE entries(id INTEGER,kind TEXT,namespace TEXT,value TEXT,conflicted INTEGER); CREATE TABLE sources(source_id TEXT,metadata TEXT); CREATE TABLE entry_evidence(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT); CREATE TABLE aliases(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT,text TEXT); INSERT INTO entries VALUES(1,'subject','test','a',0); INSERT INTO sources VALUES('s','{}'); INSERT INTO entry_evidence VALUES(1,'s','e','source_backed'); INSERT INTO aliases VALUES(1,'s','alias-e','source_backed','Alpha');").unwrap();
        let mut pin =
            json!({"entry":key("a"),"match":"exact","source_id":"s","evidence_id":"forged"});
        assert!(validate_pin(&c, "a", &pin).is_err());
        pin["evidence_id"] = json!("e");
        assert!(validate_pin(&c, "a", &pin).is_ok());
        assert!(validate_pin(&c, "Alpha", &pin).is_err());
        pin["match"] = json!("alias");
        assert!(validate_pin(&c, "Alpha", &pin).is_err());
        pin["evidence_id"] = json!("alias-e");
        assert!(validate_pin(&c, "Alpha", &pin).is_ok());
        c.execute("UPDATE entries SET conflicted=1", []).unwrap();
        assert!(validate_pin(&c, "Alpha", &pin).is_err());
    }
}
