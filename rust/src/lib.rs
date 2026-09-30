//! Read-only Rust runtime for SakuraKnowledge snapshots.
//!
//! Faithful port of the Python reference contract (api.py / model.py):
//! identity trust is `source_backed` only; text trust additionally allows
//! `generated_from_evidence`. No models, no services, no writes.

use rusqlite::{params, Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::{Duration, Instant};
mod resolver;
mod response;
pub use resolver::TagOptions;
mod search;
mod unicode16;

pub const CONTRACT_VERSION: &str = "2";
const ID_STATUSES: &str = "'source_backed'";
const TEXT_STATUSES: &str = "'generated_from_evidence','source_backed'";
const MAX_QUERY_CHARS: usize = 4096;
const MAX_QUERY_TOKENS: usize = 256;
const MAX_WORD: usize = 256;
const BUDGET_SECS: u64 = 5;
type EntryRow = (i64, String, String, String, Option<String>);

#[derive(Debug)]
pub enum Error {
    Sql(rusqlite::Error),
    Budget,
    Invalid(String),
}

impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        if let rusqlite::Error::SqliteFailure(f, _) = &e {
            if f.code == rusqlite::ErrorCode::OperationInterrupted {
                return Error::Budget;
            }
        }
        Error::Sql(e)
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Sql(e) => write!(f, "sqlite: {e}"),
            Error::Budget => write!(f, "query_budget_exceeded"),
            Error::Invalid(m) => write!(f, "{m}"),
        }
    }
}

pub type Result<T> = std::result::Result<T, Error>;

// ---------------------------------------------------------------- tokenizer

fn is_cjk_kana(c: char) -> bool {
    matches!(c, '\u{3040}'..='\u{30ff}' | '\u{3400}'..='\u{9fff}')
}

fn is_ws(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}

/// Same lexing as the Python reference: NFKC + casefold; CJK/kana runs become
/// overlapping bigrams, other word runs stay whole (max 256 chars).
fn lex(text: &str) -> Vec<String> {
    let lower: Vec<char> = unicode16::normalize_fold(text).chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < lower.len() {
        if is_cjk_kana(lower[i]) {
            let start = i;
            while i < lower.len() && is_cjk_kana(lower[i]) {
                i += 1;
            }
            let word: Vec<char> = lower[start..i].to_vec();
            for j in 0..word.len().saturating_sub(1) {
                out.push([word[j], word[j + 1]].iter().collect());
            }
        } else if unicode16::is_alnum(lower[i]) {
            let start = i;
            while i < lower.len() && unicode16::is_alnum(lower[i]) {
                i += 1;
            }
            let word: String = lower[start..i].iter().collect();
            if word.chars().count() <= MAX_WORD {
                out.push(word);
            }
        } else {
            i += 1;
        }
    }
    out
}

pub fn tokens(text: &str) -> Result<Vec<String>> {
    if text.chars().count() > MAX_QUERY_CHARS {
        return Err(Error::Invalid("query exceeds 4096 characters".into()));
    }
    let mut result = Vec::new();
    for token in lex(text) {
        if result.len() == MAX_QUERY_TOKENS {
            return Err(Error::Invalid("query exceeds 256 tokens".into()));
        }
        result.push(token);
    }
    Ok(result)
}

pub fn match_query(text: &str) -> Result<String> {
    let mut seen = std::collections::HashSet::new();
    let quoted: Vec<String> = tokens(text)?
        .into_iter()
        .filter(|t| seen.insert(t.clone()))
        .map(|t| format!("\"{}\"", t.replace('"', "\"\"")))
        .collect();
    Ok(quoted.join(" OR "))
}

// ------------------------------------------------------------------ runtime

#[derive(Debug)]
pub struct Runtime {
    conn: Connection,
    snapshot: String,
    operation_depth: usize,
    deadline: Instant,
    pub last_search_profile: Value,
}

fn base(query: &Value, snapshot: &str, status: &str) -> Value {
    json!({
        "contract_version": CONTRACT_VERSION,
        "response_version": response::VERSION,
        "snapshot": snapshot,
        "query": query,
        "status": status,
        "entry_key": Value::Null,
        "tag_key": Value::Null,
        "canonical": Value::Null,
        "candidates": Vec::<Value>::new(),
        "descriptions": Vec::<Value>::new(),
        "relations": Vec::<Value>::new(),
        "citations": Vec::<Value>::new(),
        "warnings": Vec::<Value>::new()
    })
}

fn key_of(kind: &str, namespace: &str, value: &str) -> Value {
    json!({"kind": kind, "namespace": namespace, "value": value})
}

/// Mirror of the Python `EntryKey` validation (model.py).
fn validate_key(kind: &str, namespace: &str, value: &str) -> Result<()> {
    if !matches!(
        kind,
        "subject" | "character" | "person" | "episode" | "page" | "tag"
    ) || namespace.is_empty()
    {
        return Err(Error::Invalid("invalid EntryKey".into()));
    }
    if value.is_empty() || namespace.chars().count() > 1024 || value.chars().count() > 1024 {
        return Err(Error::Invalid("invalid EntryKey length".into()));
    }
    Ok(())
}

impl Runtime {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        conn.set_limit(rusqlite::limits::Limit::SQLITE_LIMIT_LENGTH, 2_000_000);
        Self::install_budget(&conn);
        let snapshot = conn
            .query_row(
                "SELECT value FROM build_meta WHERE key='snapshot'",
                [],
                |r| r.get::<_, String>(0),
            )
            .map_err(|_| Error::Invalid("not a SakuraKnowledge snapshot".into()))?;
        for key in ["contract_version", "search_text_version"] {
            let version: Option<String> = conn
                .query_row("SELECT value FROM build_meta WHERE key=?", [key], |r| {
                    r.get(0)
                })
                .ok();
            if version.as_deref() != Some("2") {
                return Err(Error::Invalid(format!(
                    "unsupported {key}: {}",
                    version.as_deref().unwrap_or("None")
                )));
            }
        }
        for (table, names) in [
            ("entries", "id kind namespace value locator conflicted"),
            (
                "entry_evidence",
                "id entry_id source_id evidence_id status type locator payload",
            ),
            ("aliases", "id entry_id text source_id evidence_id status"),
            (
                "documents",
                "id entry_id title original status source_id evidence_id payload",
            ),
            (
                "links",
                "id src dst relation method verification_status source_id evidence_id payload",
            ),
            ("search_fts", "text document_id entry_id"),
        ] {
            let mut stmt = conn.prepare(&format!("PRAGMA table_info({table})"))?;
            let cols = stmt
                .query_map([], |r| r.get::<_, String>(1))?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            let mut missing: Vec<_> = names
                .split_whitespace()
                .filter(|name| !cols.iter().any(|c| c == name))
                .collect();
            missing.sort();
            if !missing.is_empty() {
                return Err(Error::Invalid(format!(
                    "invalid snapshot schema: {table} missing {}",
                    missing.join(",")
                )));
            }
        }
        let definition: String = conn.query_row(
            "SELECT sql FROM sqlite_master WHERE name='search_fts'",
            [],
            |r| r.get(0),
        )?;
        let definition = definition.to_lowercase();
        if !definition.starts_with("create virtual table") || !definition.contains("using fts5") {
            return Err(Error::Invalid(
                "invalid snapshot schema: search_fts is not FTS5".into(),
            ));
        }
        let hidden: Vec<(String, i64)> = conn
            .prepare("PRAGMA table_xinfo(search_fts)")?
            .query_map([], |r| Ok((r.get(1)?, r.get(6)?)))?
            .collect::<std::result::Result<_, _>>()?;
        if !hidden.contains(&("rank".into(), 1)) || !hidden.contains(&("search_fts".into(), 1)) {
            return Err(Error::Invalid("invalid FTS5 hidden columns".into()));
        }
        conn.prepare(
            "SELECT rank,bm25(search_fts) FROM search_fts WHERE search_fts MATCH ? LIMIT 0",
        )?
        .query(["runtime_capability_probe"])?
        .next()?;
        let json_probe: i64 =
            conn.query_row("SELECT json_extract('{\"probe\":1}', '$.probe')", [], |r| {
                r.get(0)
            })?;
        if json_probe != 1 || snapshot.is_empty() {
            return Err(Error::Invalid(
                "invalid snapshot capability or identity".into(),
            ));
        }
        Ok(Runtime {
            conn,
            snapshot,
            operation_depth: 0,
            deadline: Instant::now() + Duration::from_secs(5),
            last_search_profile: json!({}),
        })
    }

    fn install_budget(conn: &Connection) {
        let deadline = Duration::from_secs(BUDGET_SECS);
        let start = Instant::now();
        conn.progress_handler(1000, Some(move || start.elapsed() > deadline));
    }

    fn check_deadline(&self) -> Result<()> {
        if Instant::now() > self.deadline {
            Err(Error::Budget)
        } else {
            Ok(())
        }
    }

    fn operation(&mut self, call: impl FnOnce(&mut Self) -> Result<Value>) -> Result<Value> {
        if self.operation_depth == 0 {
            self.deadline = Instant::now() + Duration::from_secs(5);
            let deadline = self.deadline;
            self.conn
                .progress_handler(1000, Some(move || Instant::now() > deadline));
        }
        self.operation_depth += 1;
        let result = call(self);
        self.operation_depth -= 1;
        self.check_deadline()?;
        if self.operation_depth == 0 {
            result.and_then(|value| response::bound_response(value, self.deadline))
        } else {
            result
        }
    }

    pub fn inspect(&mut self) -> Result<Value> {
        self.operation(|s| s.inspect_inner())
    }
    pub fn lookup(&mut self, q: &str, k: Option<&str>, ns: Option<&str>) -> Result<Value> {
        self.operation(|s| s.lookup_inner(q, k, ns))
    }
    pub fn lookup_key(&mut self, k: &str, ns: &str, v: &str) -> Result<Value> {
        self.operation(|s| s.lookup_key_inner(k, ns, v))
    }
    pub fn search(
        &mut self,
        q: &str,
        topk: u32,
        k: Option<&str>,
        ns: Option<&str>,
    ) -> Result<Value> {
        self.operation(|s| s.search_inner(q, topk, k, ns))
    }
    pub fn related(
        &mut self,
        k: &str,
        ns: &str,
        v: &str,
        rel: Option<&str>,
        filter: Option<&str>,
        limit: u32,
    ) -> Result<Value> {
        self.operation(|s| s.related_inner(k, ns, v, rel, filter, limit))
    }
    pub fn ask(
        &mut self,
        q: &str,
        k: Option<&str>,
        ns: Option<&str>,
        target: Option<&str>,
    ) -> Result<Value> {
        self.operation(|s| s.ask_inner(q, k, ns, target))
    }

    pub fn snapshot(&self) -> &str {
        &self.snapshot
    }

    pub fn runtime_info() -> Value {
        json!({"contract_version": CONTRACT_VERSION,
               "runtime": "rust",
               "sqlite_version": rusqlite::version(),
               "unicode_version": unicode16::VERSION,
               "normalization_library_unicode": format!("{:?}", unicode_normalization::UNICODE_VERSION)})
    }

    fn inspect_inner(&mut self) -> Result<Value> {
        self.check_deadline()?;
        let page_size: i64 = self
            .conn
            .query_row("PRAGMA page_size", [], |r| r.get(0))
            .unwrap_or(0);
        let page_count: i64 = self
            .conn
            .query_row("PRAGMA page_count", [], |r| r.get(0))
            .unwrap_or(0);
        let freelist_count: i64 = self
            .conn
            .query_row("PRAGMA freelist_count", [], |r| r.get(0))
            .unwrap_or(0);
        // Optional whole-file dbstat walk is deliberately outside lightweight inspect.
        let dbstat: Option<i64> = None;
        let contract: Option<String> = self
            .conn
            .query_row(
                "SELECT value FROM build_meta WHERE key='contract_version'",
                [],
                |r| r.get(0),
            )
            .ok();
        Ok(json!({
            "snapshot": self.snapshot,
            "contract_version": contract,
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "dbstat_pages": dbstat,
            "dbstat_status": "not_run",
            "read_only": true
        }))
    }

    // ------------------------------------------------------------ helpers

    /// Bounded projection of one trusted entry (Python `describe`).
    fn describe(
        &mut self,
        id: i64,
        kind: &str,
        namespace: &str,
        value: &str,
        locator: Option<&str>,
        alias_text: Option<&str>,
    ) -> Result<Value> {
        let docs = self.fetch_docs(id)?;
        let aliases = if let Some(text) = alias_text {
            self.fetch_aliases(id, text)?
        } else {
            Vec::new()
        };
        let (mut identities, mut payloads) = self.fetch_evidence(id)?;
        let identities_truncated = identities.len() > 100;
        identities.truncate(100);
        payloads.truncate(100);
        let (fields, field_evidence, mut field_truncated) =
            response::observations(&identities, &payloads, self.deadline)?;
        if identities_truncated {
            let mut names = response::FIELDS.to_vec();
            names.sort();
            field_truncated = json!(names);
        }
        let use_alias_proofs = matches!(alias_text, Some(t) if t != value);
        let proofs: Vec<Value> = if use_alias_proofs {
            aliases.clone()
        } else {
            identities.clone()
        };
        let citations: Vec<Value> = proofs
            .iter()
            .map(|p| {
                json!({"source_id": p.get("source_id").cloned().unwrap_or(Value::Null),
                       "evidence_id": p.get("evidence_id").cloned().unwrap_or(Value::Null)})
            })
            .collect();
        let first = citations.first().cloned();
        Ok(json!({
            "entry_key": key_of(kind, namespace, value),
            "locator": locator,
            "descriptions": docs,
            "matched_documents": docs,
            "aliases": aliases,
            "identity_evidence": identities,
            "source_fields": fields,
            "source_fields_evidence": field_evidence,
            "source_fields_truncated": field_truncated,
            "identity_evidence_truncated": identities_truncated,
            "matched_by": if use_alias_proofs { "alias" } else { "exact" },
            "source_id": first.as_ref().and_then(|f| f.get("source_id").cloned()).unwrap_or(Value::Null),
            "evidence_id": first.as_ref().and_then(|f| f.get("evidence_id").cloned()).unwrap_or(Value::Null),
            "citations": citations
        }))
    }

    fn fetch_docs(&self, id: i64) -> Result<Vec<Value>> {
        let sql = format!(
            "SELECT substr(title,1,256),substr(original,1,4000),length(original)>4000,
                     json_extract(payload,'$.search_text_truncated'),source_id,evidence_id,status,length(title)>256
             FROM documents WHERE entry_id=? AND status IN ({TEXT_STATUSES})
             ORDER BY id LIMIT 10"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map([id], |r| {
            let mut doc = json!({
                "title": r.get::<_, String>(0)?,
                "original": r.get::<_, String>(1)?,
                "response_truncated": r.get::<_, bool>(2)?,
                "search_text_truncated": r.get::<_, Option<bool>>(3)?,
                "source_id": r.get::<_, String>(4)?,
                "evidence_id": r.get::<_, String>(5)?,
                "status": r.get::<_, String>(6)?
            });
            if r.get::<_, bool>(7)? {
                doc["title_truncated"] = json!(true);
            }
            Ok(doc)
        })?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r?);
        }
        Ok(out)
    }

    fn fetch_aliases(&mut self, id: i64, text: &str) -> Result<Vec<Value>> {
        let sql = format!(
            "SELECT text,source_id,evidence_id,status FROM aliases
             WHERE entry_id=? AND text=? AND status IN ({ID_STATUSES})
             ORDER BY source_id,evidence_id LIMIT 100"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map(params![id, text], |r| {
            Ok(json!({"text": r.get::<_, String>(0)?,
                      "source_id": r.get::<_, String>(1)?,
                      "evidence_id": r.get::<_, String>(2)?,
                      "status": r.get::<_, String>(3)?}))
        })?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r?);
        }
        Ok(out)
    }

    fn fetch_evidence(&mut self, id: i64) -> Result<(Vec<Value>, Vec<String>)> {
        let sql = format!(
            "SELECT source_id,evidence_id,status,type,locator,payload FROM entry_evidence
             WHERE entry_id=? AND status IN ({ID_STATUSES})
             ORDER BY source_id,evidence_id LIMIT 101"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map([id], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, Option<String>>(3)?,
                r.get::<_, Option<String>>(4)?,
                r.get::<_, String>(5)?,
            ))
        })?;
        let mut ids = Vec::new();
        let mut payloads = Vec::new();
        for row in rows {
            let (sid, eid, status, typ, loc, payload) = row?;
            ids.push(json!({"source_id": sid, "evidence_id": eid,
                            "status": status, "type": typ, "locator": loc}));
            payloads.push(payload);
        }
        Ok((ids, payloads))
    }

    /// Resolve an entry row to a candidate, keeping only candidates that have
    /// at least one trusted proof (Python pairing semantics).
    fn candidate_for(
        &mut self,
        id: i64,
        kind: &str,
        namespace: &str,
        value: &str,
        locator: Option<&str>,
        alias_text: Option<&str>,
    ) -> Result<Option<Value>> {
        let v = self.describe(id, kind, namespace, value, locator, alias_text)?;
        if v["citations"]
            .as_array()
            .map(|a| a.is_empty())
            .unwrap_or(true)
        {
            Ok(None)
        } else {
            Ok(Some(v))
        }
    }

    fn apply_found(result: &mut Value, c: &Value, kind: &str) {
        result["entry_key"] = c["entry_key"].clone();
        result["canonical"] = c.clone();
        result["descriptions"] = c["descriptions"].clone();
        result["matched_documents"] = c["matched_documents"].clone();
        result["source_fields"] = c["source_fields"].clone();
        result["source_fields_evidence"] = c["source_fields_evidence"].clone();
        result["source_fields_truncated"] = c["source_fields_truncated"].clone();
        result["matched_by"] = c["matched_by"].clone();
        result["source_id"] = c["source_id"].clone();
        result["evidence_id"] = c["evidence_id"].clone();
        result["citations"] = c["citations"].clone();
        if kind == "tag" {
            let key = &c["entry_key"];
            result["tag_key"] = json!({"namespace": key["namespace"].clone(),
                                       "value": key["value"].clone()});
        }
    }

    // ------------------------------------------------------------- queries

    fn lookup_inner(
        &mut self,
        query: &str,
        kind: Option<&str>,
        namespace: Option<&str>,
    ) -> Result<Value> {
        self.check_deadline()?;
        if query.is_empty() || query.chars().count() > MAX_QUERY_CHARS {
            return Err(Error::Invalid(
                "query must contain 1..4096 characters".into(),
            ));
        }
        let sql = format!(
            "SELECT DISTINCT e.id,e.kind,e.namespace,e.value,e.locator FROM entries e
             WHERE (e.value=?1 OR e.id IN (SELECT entry_id FROM aliases
                    WHERE text=?1 AND status IN ({ID_STATUSES})))
             AND (?2 IS NULL OR e.kind=?2) AND (?3 IS NULL OR e.namespace=?3)
             AND e.conflicted=0 AND EXISTS (SELECT 1 FROM entry_evidence v
                    WHERE v.entry_id=e.id AND v.status IN ({ID_STATUSES}))
             ORDER BY e.kind,e.namespace,e.value LIMIT 101"
        );
        let raw: Vec<EntryRow> = {
            let mut stmt = self.conn.prepare(&sql)?;
            let rows = stmt.query_map(params![query, kind, namespace], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, Option<String>>(4)?,
                ))
            })?;
            let mut v = Vec::new();
            for row in rows {
                v.push(row?);
            }
            v
        };
        let mut paired: Vec<(String, Value)> = Vec::new();
        for (id, k, ns, v, loc) in raw {
            let alias_text = if query != v { Some(query) } else { None };
            if let Some(c) = self.candidate_for(id, &k, &ns, &v, loc.as_deref(), alias_text)? {
                paired.push((k, c));
            }
        }
        let status = if paired.is_empty() {
            "not_found"
        } else if paired.len() == 1 {
            "found"
        } else {
            "ambiguous"
        };
        let mut result = base(&json!(query), &self.snapshot, status);
        result["candidates"] = json!(paired
            .iter()
            .map(|(_, c)| c.clone())
            .take(100)
            .collect::<Vec<_>>());
        if let Some((kind, c)) = paired.first() {
            if paired.len() == 1 {
                Self::apply_found(&mut result, c, kind);
            }
        }
        if paired.len() > 100 {
            result["warnings"]
                .as_array_mut()
                .unwrap()
                .push(json!("candidate_limit_reached"));
        }
        response::bound_response(result, self.deadline)
    }

    fn lookup_key_inner(&mut self, kind: &str, namespace: &str, value: &str) -> Result<Value> {
        self.check_deadline()?;
        validate_key(kind, namespace, value)?;
        let sql = format!(
            "SELECT e.id,e.kind,e.namespace,e.value,e.locator FROM entries e
             WHERE e.kind=?1 AND e.namespace=?2 AND e.value=?3
             AND e.conflicted=0 AND EXISTS (SELECT 1 FROM entry_evidence v
                    WHERE v.entry_id=e.id AND v.status IN ({ID_STATUSES}))"
        );
        let raw: Vec<EntryRow> = {
            let mut stmt = self.conn.prepare(&sql)?;
            let rows = stmt.query_map(params![kind, namespace, value], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, Option<String>>(4)?,
                ))
            })?;
            let mut v = Vec::new();
            for row in rows {
                v.push(row?);
            }
            v
        };
        let mut paired: Vec<(String, Value)> = Vec::new();
        for (id, k, ns, v, loc) in raw {
            if let Some(c) = self.candidate_for(id, &k, &ns, &v, loc.as_deref(), None)? {
                paired.push((k, c));
            }
        }
        let query = key_of(kind, namespace, value);
        let status = if paired.is_empty() {
            "not_found"
        } else if paired.len() == 1 {
            "found"
        } else {
            "ambiguous"
        };
        let mut result = base(&query, &self.snapshot, status);
        result["candidates"] = json!(paired.iter().map(|(_, c)| c.clone()).collect::<Vec<_>>());
        if let Some((kind, c)) = paired.first() {
            if paired.len() == 1 {
                Self::apply_found(&mut result, c, kind);
            }
        }
        response::bound_response(result, self.deadline)
    }

    fn search_inner(
        &mut self,
        query: &str,
        topk: u32,
        kind: Option<&str>,
        namespace: Option<&str>,
    ) -> Result<Value> {
        if !(1..=100).contains(&topk) {
            return Err(Error::Invalid("topk must be 1..100".into()));
        }
        let started = Instant::now();
        self.last_search_profile = json!({"scanned_rows":0,"materialized_matched_documents":0,
                                         "returned_matched_body_utf8_bytes":0});
        let mut exact = self.lookup(query, kind, namespace)?;
        self.last_search_profile["exact_identity_assembly_s"] =
            json!(started.elapsed().as_secs_f64());
        let compiled = match_query(query)?;
        if exact["candidates"].as_array().unwrap().len() >= topk as usize {
            exact["candidates"]
                .as_array_mut()
                .unwrap()
                .truncate(topk as usize);
            self.last_search_profile["fts_skipped_exact_sufficient"] = json!(true);
            return response::bound_response(exact, self.deadline);
        }
        if compiled.is_empty() {
            let cands = exact["candidates"].as_array().cloned().unwrap_or_default();
            exact["candidates"] = json!(cands.into_iter().take(topk as usize).collect::<Vec<_>>());
            if exact["status"] == json!("not_found") {
                exact["warnings"]
                    .as_array_mut()
                    .unwrap()
                    .push(json!("too_short"));
            }
            return response::bound_response(exact, self.deadline);
        }

        let mut candidates = exact["candidates"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .take(topk as usize)
            .collect::<Vec<_>>();
        let seen: std::collections::HashSet<(String, String, String)> = candidates
            .iter()
            .map(|c| {
                (
                    c["entry_key"]["kind"].as_str().unwrap().to_string(),
                    c["entry_key"]["namespace"].as_str().unwrap().to_string(),
                    c["entry_key"]["value"].as_str().unwrap().to_string(),
                )
            })
            .collect();
        let start = Instant::now();
        let selected = search::select(
            &self.conn,
            &compiled,
            kind,
            namespace,
            seen,
            topk as usize - candidates.len(),
            self.deadline,
        )?;
        self.last_search_profile["fts_execute_select_s"] = json!(start.elapsed().as_secs_f64());
        self.last_search_profile["scanned_rows"] = json!(selected.scanned);
        self.last_search_profile["selected_identities"] = json!(selected.hits.len());
        let mut assembly_s = 0.0;
        let mut body_s = 0.0;
        let mut body_bytes = 0;
        let mut documents = 0;
        for hit in selected.hits {
            self.check_deadline()?;
            let start = Instant::now();
            let Some(mut candidate) = self.candidate_for(
                hit.id,
                &hit.key.0,
                &hit.key.1,
                &hit.key.2,
                hit.locator.as_deref(),
                None,
            )?
            else {
                continue;
            };
            assembly_s += start.elapsed().as_secs_f64();
            let start = Instant::now();
            let (title, original, truncated, sid, eid, title_truncated): (String, String, bool, String, String, bool) = self.conn.query_row(
                "SELECT substr(title,1,256),substr(original,1,4000),length(original)>4000,source_id,evidence_id,length(title)>256 FROM documents WHERE id=?",
                [hit.document_id], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?)))?;
            body_s += start.elapsed().as_secs_f64();
            body_bytes += original.len();
            documents += 1;
            candidate["matched_by"] = json!("fts");
            candidate["score"] = json!(hit.score);
            candidate["matched_documents"] = json!([{
                "title": title, "original": original, "response_truncated": truncated,
                "source_id": sid, "evidence_id": eid
            }]);
            if title_truncated {
                candidate["matched_documents"][0]["title_truncated"] = json!(true);
            }
            candidate["source_id"] = json!(sid);
            candidate["evidence_id"] = json!(eid);
            candidates.push(candidate);
        }
        self.last_search_profile["identity_field_assembly_s"] = json!(assembly_s);
        self.last_search_profile["matched_document_read_s"] = json!(body_s);
        self.last_search_profile["returned_matched_body_utf8_bytes"] = json!(body_bytes);
        self.last_search_profile["materialized_matched_documents"] = json!(documents);
        exact["candidates"] = json!(candidates);
        if exact["status"] == json!("not_found") && !candidates.is_empty() {
            exact["status"] = json!("found");
        }
        if selected.truncated {
            exact["warnings"]
                .as_array_mut()
                .unwrap()
                .push(json!("search_document_scan_limit"));
        }
        response::bound_response(exact, self.deadline)
    }

    fn related_inner(
        &mut self,
        kind: &str,
        namespace: &str,
        value: &str,
        relation: Option<&str>,
        kind_filter: Option<&str>,
        limit: u32,
    ) -> Result<Value> {
        if !(1..=100).contains(&limit) {
            return Err(Error::Invalid("limit must be 1..100".into()));
        }
        validate_key(kind, namespace, value)?;
        let mut result = self.lookup_key(kind, namespace, value)?;
        if result["status"] != json!("found") {
            return response::bound_response(result, self.deadline);
        }
        let sql = format!(
            "SELECT d.kind,d.namespace,d.value,l.relation,l.method,
                    l.verification_status,l.source_id,l.evidence_id,l.payload
             FROM links l JOIN entries s ON s.id=l.src JOIN entries d ON d.id=l.dst
             WHERE s.kind=?1 AND s.namespace=?2 AND s.value=?3
             AND l.verification_status IN ('native','redirect','verified')
             AND d.conflicted=0 AND EXISTS (SELECT 1 FROM entry_evidence v
                    WHERE v.entry_id=d.id AND v.status IN ({ID_STATUSES}))
             AND (?4 IS NULL OR l.relation=?4) AND (?5 IS NULL OR d.kind=?5)
             ORDER BY l.relation,d.kind,d.namespace,d.value,l.id LIMIT ?6"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map(
            params![kind, namespace, value, relation, kind_filter, limit],
            |r| {
                Ok(json!({"dst": key_of(r.get::<_, String>(0)?.as_str(),
                                   r.get::<_, String>(1)?.as_str(),
                                   r.get::<_, String>(2)?.as_str()),
                          "relation": r.get::<_, String>(3)?,
                          "method": r.get::<_, String>(4)?,
                          "verification_status": r.get::<_, String>(5)?,
                          "source_id": r.get::<_, String>(6)?,
                          "evidence_id": r.get::<_, String>(7)?,
                          "payload": r.get::<_, String>(8)?}))
            },
        )?;
        let mut relations = Vec::new();
        for r in rows {
            relations.push(r?);
        }
        result["relations"] = json!(relations);
        response::bound_response(result, self.deadline)
    }

    // ---------------------------------------------------------------- ask

    fn ask_resolved(
        &mut self,
        query: &str,
        kind: Option<&str>,
        namespace: Option<&str>,
        target: Option<&str>,
        resolved: Option<Value>,
    ) -> Result<Value> {
        let mut result = match resolved {
            Some(value) => value,
            None => self.lookup(query, kind, namespace)?,
        };
        result["input_query"] = json!(query);
        result["parsed_subject"] = Value::Null;
        result["target_namespace"] = target.map(|t| json!(t)).unwrap_or(Value::Null);
        result["mapping_status"] = json!("unknown");
        if result["status"] == json!("not_found") {
            result["status"] = json!("unknown");
            result["answer"] = json!("No reliable exact source entity match.");
            return response::bound_response(result, self.deadline);
        }
        if result["status"] == json!("ambiguous") {
            result["status"] = json!("entity_ambiguous");
            result["mapping_status"] = json!("entity_ambiguous");
            result["answer"] = json!("Multiple source entity matches; specify a source key.");
            return response::bound_response(result, self.deadline);
        }

        let source_tag = result.get("tag_key").cloned().unwrap_or(Value::Null);
        let tag_is_target = if source_tag.is_object() {
            match target {
                Some(tn) => source_tag.get("namespace").and_then(|n| n.as_str()) == Some(tn),
                None => true,
            }
        } else {
            false
        };
        if tag_is_target {
            let ns = source_tag["namespace"].clone();
            result["mapping_status"] = json!(if target.is_some() {
                "target_identity"
            } else if ns.as_str() == Some("local.tag_aggregate") {
                "local_identity_only"
            } else {
                "source_identity_only"
            });
            result["answer"] = json!(format!(
                "Exact tag identity in {}; no cross-namespace mapping inferred.",
                ns.as_str().unwrap_or("?")
            ));
            return response::bound_response(result, self.deadline);
        }

        result["tag_key"] = Value::Null;
        let key = &result["entry_key"];
        let src_id: i64 = self.conn.query_row(
            "SELECT id FROM entries WHERE kind=? AND namespace=? AND value=?",
            params![
                key["kind"].as_str().unwrap(),
                key["namespace"].as_str().unwrap(),
                key["value"].as_str().unwrap()
            ],
            |r| r.get(0),
        )?;
        let sql = format!(
            "SELECT d.namespace,d.value,MIN(l.id) AS proof_id FROM links l
             JOIN entries d ON d.id=l.dst
             WHERE l.src=?1 AND l.relation='entity_tag'
             AND l.verification_status='verified' AND d.kind='tag' AND d.conflicted=0
             AND (?2 IS NULL OR d.namespace=?2)
             AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=d.id
                    AND v.status IN ({ID_STATUSES}))
             GROUP BY d.namespace,d.value ORDER BY d.namespace,d.value LIMIT 2"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map(params![src_id, target], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
            ))
        })?;
        let mut identities = Vec::new();
        for r in rows {
            identities.push(r?);
        }
        for (ns, value, proof_id) in &identities {
            let proof_sql = "SELECT relation,method,verification_status,source_id,evidence_id,payload FROM links WHERE id=?";
            let mut stmt = self.conn.prepare(proof_sql)?;
            let proof = stmt.query_row([proof_id], |r| {
                Ok(json!({"relation": r.get::<_, String>(0)?,
                          "method": r.get::<_, String>(1)?,
                          "verification_status": r.get::<_, String>(2)?,
                          "source_id": r.get::<_, String>(3)?,
                          "evidence_id": r.get::<_, String>(4)?,
                          "payload": r.get::<_, String>(5)?}))
            })?;
            let mut relation = proof.clone();
            relation["dst"] = key_of("tag", ns, value);
            result["relations"].as_array_mut().unwrap().push(relation);
            result["citations"].as_array_mut().unwrap().push(json!({
                "source_id": proof["source_id"].clone(),
                "evidence_id": proof["evidence_id"].clone()
            }));
        }
        if identities.len() == 1 {
            let (ns, value, _) = &identities[0];
            result["tag_key"] = json!({"namespace": ns, "value": value});
            result["mapping_status"] = json!(if target.is_some() {
                "target_verified"
            } else {
                "verified"
            });
            result["answer"] = json!(format!(
                "Verified entity_tag mapping to {ns}; source entity retained."
            ));
        } else if identities.len() > 1 {
            result["status"] = json!("tag_ambiguous");
            result["mapping_status"] = json!(if target.is_some() {
                "target_ambiguous"
            } else {
                "ambiguous"
            });
            result["answer"] = json!("Multiple verified tag mappings; no tag selected.");
        } else {
            result["status"] = json!("entity_found_tag_unmapped");
            result["mapping_status"] = json!(if target.is_some() {
                "target_unmapped"
            } else {
                "unmapped"
            });
            result["answer"] = json!(if let Some(t) = target {
                format!("Source entity found; no verified tag mapping to {t}.")
            } else {
                "Source entity found; no verified tag mapping in any namespace.".to_string()
            });
        }
        response::bound_response(result, self.deadline)
    }

    fn ask_inner(
        &mut self,
        query: &str,
        kind: Option<&str>,
        namespace: Option<&str>,
        target: Option<&str>,
    ) -> Result<Value> {
        if let Some(t) = target {
            if t.is_empty() || t.chars().count() > 256 {
                return Err(Error::Invalid(
                    "target_tag_namespace must contain 1..256 characters".into(),
                ));
            }
        }
        self.check_deadline()?;
        let direct = self.lookup(query, kind, namespace)?;
        if direct["status"] == json!("found") || direct["status"] == json!("ambiguous") {
            let mut result = self.ask_resolved(query, kind, namespace, target, Some(direct))?;
            result["input_query"] = json!(query);
            result["parsed_subject"] = Value::Null;
            result["query_template"] = json!("unsupported");
            return response::bound_response(result, self.deadline);
        }
        let parsed = parse_ask_template(query);
        let (subject, mode) = match parsed {
            Some(p) => p,
            None => {
                let mut result = self.ask_resolved(query, kind, namespace, target, Some(direct))?;
                result["query_template"] = json!("unsupported");
                if result["status"] == json!("unknown") {
                    result["warnings"]
                        .as_array_mut()
                        .unwrap()
                        .push(json!("unsupported_query_template"));
                }
                return response::bound_response(result, self.deadline);
            }
        };
        match mode.as_str() {
            "introduce" => {
                if target.is_some() {
                    return Err(Error::Invalid(
                        "introduce template cannot combine with target_tag_namespace".into(),
                    ));
                }
                let mut result = self.lookup(&subject, kind, namespace)?;
                result["mapping_status"] = json!("not_requested");
                result["target_namespace"] = Value::Null;
                if result["status"] == json!("not_found") {
                    result["status"] = json!("unknown");
                    result["answer"] = json!("No reliable exact source entity match.");
                } else if result["status"] == json!("ambiguous") {
                    result["status"] = json!("entity_ambiguous");
                    result["answer"] =
                        json!("Multiple source entity matches; specify a source key.");
                }
                result["input_query"] = json!(query);
                result["parsed_subject"] = json!(subject);
                result["query_template"] = json!("introduce");
                if result["status"] == json!("found") {
                    let key = &result["entry_key"];
                    result["answer"] = json!(format!(
                        "Source entity {}/{}; see descriptions and citations for source-backed text.",
                        key["namespace"].as_str().unwrap_or(""), key["value"].as_str().unwrap_or("")
                    ));
                }
                response::bound_response(result, self.deadline)
            }
            "danbooru.tag" => {
                if matches!(target, Some(t) if t != "danbooru.tag") {
                    return Err(Error::Invalid(
                        "template implies target danbooru.tag; explicit target_tag_namespace conflicts"
                            .into(),
                    ));
                }
                let mut result =
                    self.ask_resolved(&subject, kind, namespace, Some("danbooru.tag"), None)?;
                result["input_query"] = json!(query);
                result["parsed_subject"] = json!(subject);
                result["query_template"] = json!("danbooru_tag");
                response::bound_response(result, self.deadline)
            }
            _ => {
                let mut result = self.ask_resolved(&subject, kind, namespace, target, None)?;
                result["input_query"] = json!(query);
                result["parsed_subject"] = json!(subject);
                result["query_template"] = json!("tag");
                response::bound_response(result, self.deadline)
            }
        }
    }
}

// ------------------------------------------------------------- ask template

// ------------------------------------------------------------- ask template

/// Bounded deterministic templates — a faithful port of the Python
/// reference regexes (api.py):
///   danbooru: ^(?P<x>.+?)\s*的\s*danbooru\s*tag\s*是什么\s*[？?。.\s]*$   (IGNORECASE)
///   tag:      ^(?P<x>.+?)\s*的\s*标签\s*是什么\s*[？?。.\s]*$
///   introduce:^介绍(?:一下)?\s*(?P<x>.+?)\s*[？?。.\s]*$
/// Try order: danbooru, tag, introduce. `.+?` is lazy: the subject is the
/// shortest prefix whose remainder matches; the returned subject is
/// whitespace-stripped and must be non-empty.
fn is_trail(c: char) -> bool {
    matches!(c, '？' | '?' | '。' | '.') || is_ws(c)
}

fn template_subject(query: &[char], mid: &[&str]) -> Option<String> {
    // mid: ordered literal words between the subject and the fixed tail,
    // each preceded by ws*; the fixed tail is "是什么" + [？?。.\s]*.
    let tail: Vec<char> = "是什么".chars().collect();
    let n = query.len();
    // Try subject end positions from the left (lazy .+? => shortest subject).
    for end in 1..n {
        let rest = &query[end..];
        // rest must match: ws* <mid words with ws* between> 是什么 [？?。.\s]*
        let mut i = 0;
        while i < rest.len() && is_ws(rest[i]) {
            i += 1;
        }
        let mut ok = true;
        for &word in mid {
            let wc: Vec<char> = word.chars().collect();
            if rest.len().saturating_sub(i) < wc.len() {
                ok = false;
                break;
            }
            for (a, b) in rest[i..i + wc.len()].iter().zip(wc.iter()) {
                let la: String = a.to_lowercase().collect();
                let lb: String = b.to_lowercase().collect();
                if la != lb {
                    ok = false;
                    break;
                }
            }
            if !ok {
                break;
            }
            i += wc.len();
            while i < rest.len() && is_ws(rest[i]) {
                i += 1;
            }
        }
        if !ok || rest.len().saturating_sub(i) < tail.len() {
            continue;
        }
        for (a, b) in rest[i..i + tail.len()].iter().zip(tail.iter()) {
            if a != b {
                ok = false;
                break;
            }
        }
        if !ok {
            continue;
        }
        let mut j = i + tail.len();
        while j < rest.len() && is_trail(rest[j]) {
            j += 1;
        }
        if j != rest.len() {
            continue;
        }
        let subject: String = query[..end].iter().collect();
        let stripped = subject.trim_matches(is_ws);
        if !stripped.is_empty() {
            return Some(stripped.to_string());
        }
    }
    None
}

pub fn parse_ask_template(query: &str) -> Option<(String, String)> {
    if query.is_empty() || query.chars().count() > MAX_QUERY_CHARS {
        return None;
    }
    let chars: Vec<char> = query.chars().collect();
    // danbooru: <x> \s* 的 \s* danbooru \s* tag \s* 是什么 [tail]
    if let Some(subject) = template_subject(&chars, &["的", "danbooru", "tag"]) {
        return Some((subject, "danbooru.tag".to_string()));
    }
    // tag: <x> \s* 的 \s* 标签 \s* 是什么 [tail]
    if let Some(subject) = template_subject(&chars, &["的", "标签"]) {
        return Some((subject, "tag".to_string()));
    }
    // introduce: 介绍 (一下)? \s* <x> [tail]
    // The optional 一下 group is greedy with backtracking: try with it
    // first, then without it (mirrors Python re semantics).
    let intro: Vec<char> = "介绍".chars().collect();
    let youxia: Vec<char> = "一下".chars().collect();
    if chars.len() >= intro.len() && chars[..intro.len()] == intro {
        let starts: [usize; 2] = [
            if chars.len() >= intro.len() + youxia.len()
                && chars[intro.len()..intro.len() + youxia.len()] == youxia
            {
                intro.len() + youxia.len()
            } else {
                usize::MAX
            },
            intro.len(),
        ];
        for start in starts {
            if start == usize::MAX {
                continue;
            }
            let mut i = start;
            while i < chars.len() && is_ws(chars[i]) {
                i += 1;
            }
            if i >= chars.len() {
                continue;
            }
            let subject: String = chars[i..].iter().collect();
            let stripped = subject.trim_matches(is_ws);
            if !stripped.is_empty() && !stripped.contains('\n') {
                return Some((stripped.to_string(), "introduce".to_string()));
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokenizer_matches_reference() {
        assert_eq!(
            tokens("hello 世界 hello").unwrap(),
            vec!["hello", "世界", "hello"]
        );
        assert_eq!(match_query("世界世界").unwrap(), "\"世界\" OR \"界世\"");
        assert!(tokens(&"a".repeat(5000)).is_err());
    }

    #[test]
    fn unicode16_complete_examples() {
        for (input, expected) in [
            (
                "Straße STRASSE ẞ SS",
                vec!["strasse", "strasse", "ss", "ss"],
            ),
            ("Σ σ ς", vec!["σ", "σ", "σ"]),
            ("İ i\u{307}", vec!["i", "i"]),
            ("ＡＢＣ ｶﾀｶﾅ", vec!["abc", "カタ", "タカ", "カナ"]),
            ("中文日本", vec!["中文", "文日", "日本"]),
            ("a\u{a0}b\u{2003}c", vec!["a", "b", "c"]),
            ("a中文 中文a", vec!["a中文", "中文", "a"]),
            ("e\u{301} 𐐀", vec!["é", "𐐨"]),
        ] {
            assert_eq!(tokens(input).unwrap(), expected);
        }
        assert!(tokens(&"a".repeat(257)).unwrap().is_empty());
        assert!(tokens(&" ".repeat(4097)).is_err());
        assert!(tokens(&"a ".repeat(257)).is_err());
        assert_eq!(
            match_query("Straße STRASSE ς").unwrap(),
            "\"strasse\" OR \"σ\""
        );
    }

    #[test]
    fn templates_parse() {
        assert_eq!(
            parse_ask_template("solo 的 Danbooru tag 是什么"),
            Some(("solo".to_string(), "danbooru.tag".to_string()))
        );
        assert_eq!(
            parse_ask_template("hero 的标签是什么"),
            Some(("hero".to_string(), "tag".to_string()))
        );
        assert_eq!(
            parse_ask_template("介绍一下 975"),
            Some(("975".to_string(), "introduce".to_string()))
        );
        assert_eq!(parse_ask_template(" 的标签是什么"), None);
        assert_eq!(parse_ask_template("hero"), None);
        assert_eq!(
            parse_ask_template("介绍一下 name."),
            Some(("name.".into(), "introduce".into()))
        );
        assert_eq!(
            parse_ask_template("介绍一下 name_(x)"),
            Some(("name_(x)".into(), "introduce".into()))
        );
    }

    fn build_fixture(path: &Path) {
        let _ = std::fs::remove_file(path);
        let conn = Connection::open(path).unwrap();
        conn.execute_batch(
            "CREATE TABLE entries(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, namespace TEXT NOT NULL,
              value TEXT NOT NULL, type TEXT, locator TEXT, conflicted INTEGER NOT NULL DEFAULT 0,
              UNIQUE(kind,namespace,value));
             CREATE TABLE aliases(id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries,
              text TEXT NOT NULL, source_id TEXT NOT NULL, evidence_id TEXT NOT NULL, status TEXT NOT NULL);
             CREATE TABLE documents(id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries,
              title TEXT, original TEXT, search_text TEXT, language TEXT, status TEXT,
              source_id TEXT, evidence_id TEXT, payload TEXT);
             CREATE TABLE entry_evidence(id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries,
              source_id TEXT NOT NULL, evidence_id TEXT NOT NULL, status TEXT NOT NULL,
              type TEXT, locator TEXT, payload TEXT);
             CREATE TABLE links(id INTEGER PRIMARY KEY, src INTEGER NOT NULL, dst INTEGER NOT NULL,
              relation TEXT NOT NULL, method TEXT NOT NULL, verification_status TEXT NOT NULL,
              source_id TEXT NOT NULL, evidence_id TEXT NOT NULL, payload TEXT);
             CREATE TABLE build_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
             CREATE VIRTUAL TABLE search_fts USING fts5(text, document_id UNINDEXED, entry_id UNINDEXED);
             INSERT INTO build_meta VALUES('snapshot','fixture-test');
             INSERT INTO build_meta VALUES('contract_version','2');
             INSERT INTO build_meta VALUES('search_text_version','2');
             INSERT INTO entries(id,kind,namespace,value,locator) VALUES
               (1,'character','fixture','hero','line:1'),
               (2,'character','fixture','hero2','line:2'),
               (3,'tag','fixture','hero-tag','line:3');
             INSERT INTO aliases VALUES (1,1,'the hero','s','e-alias-1','source_backed');
             INSERT INTO documents(id,entry_id,title,original,search_text,language,status,source_id,evidence_id,payload) VALUES
               (1,1,'Hero','Hero desc','hero desc','en','source_backed','s','e-doc-1','{}'),
               (2,2,'Hero Two','Second hero desc','second hero desc','en','source_backed','s','e-doc-2','{}');
             INSERT INTO entry_evidence VALUES
               (1,1,'s','e-ev-1','source_backed','entity','line:1','{\"raw\":{\"raw_attributes\":[\"hair\"]}}'),
               (2,2,'s','e-ev-2','source_backed','entity','line:2','{}'),
               (3,3,'s','e-ev-3','source_backed','entity','line:3','{}');
             INSERT INTO links VALUES (1,1,3,'entity_tag','mapping','verified','s','e-link-1','{}');
             INSERT INTO search_fts(text,document_id,entry_id) VALUES
               ('Hero desc',1,1),('Second hero desc',2,2);",
        )
        .unwrap();
        conn.close().unwrap();
    }

    #[test]
    fn review_f99_forced_deadline_covers_errors_inspect_and_projection() {
        let dir = std::env::temp_dir().join("sknow-rs-review-f99-deadline");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("fixture.sqlite");
        build_fixture(&path);
        let mut rt = Runtime::open(&path).unwrap();
        let fail = rt.operation(|s| {
            s.deadline = Instant::now() - Duration::from_secs(1);
            Err(Error::Invalid("response_budget_exceeded".into()))
        });
        assert!(matches!(fail, Err(Error::Budget)));
        let fail = rt.operation(|s| {
            let result = s.inspect_inner()?;
            s.deadline = Instant::now() - Duration::from_secs(1);
            Ok(result)
        });
        assert!(matches!(fail, Err(Error::Budget)));
        let expired = Instant::now() - Duration::from_secs(1);
        assert!(matches!(
            response::bound_response(json!({}), expired),
            Err(Error::Budget)
        ));
        assert!(matches!(
            response::observations(&[json!({})], &["{}".into()], expired),
            Err(Error::Budget)
        ));
        drop(rt);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn p3_shared_deadline_nested_resolver_and_reset() {
        let dir = std::env::temp_dir().join("sknow-rs-p3-budget");
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("fixture.sqlite");
        build_fixture(&path);
        let conn = Connection::open(&path).unwrap();
        conn.execute_batch("CREATE TABLE sources(source_id TEXT PRIMARY KEY,metadata TEXT); INSERT INTO sources VALUES('s','{}');").unwrap();
        drop(conn);
        let mut rt = Runtime::open(&path).unwrap();
        let fail = rt.operation(|s| {
            s.deadline = Instant::now() - Duration::from_secs(1);
            s.resolve_tag("hero", TagOptions::default())
        });
        assert!(matches!(fail, Err(Error::Budget)));
        assert_eq!(
            rt.resolve_tag("hero", TagOptions::default()).unwrap()["status"],
            json!("unsupported")
        );
        assert_eq!(rt.operation_depth, 0);
        drop(rt);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn fixture_lookup_search_related_ask() {
        let dir = std::env::temp_dir().join("sknow-rs-test");
        std::fs::create_dir_all(&dir).unwrap();
        let db_path = dir.join("fixture.sqlite");
        build_fixture(&db_path);
        let mut rt = Runtime::open(&db_path).unwrap();

        let v = rt.lookup("hero", None, None).unwrap();
        assert_eq!(v["status"], "found");
        assert_eq!(v["entry_key"]["value"], "hero");
        assert_eq!(
            v["source_fields"]["raw_attributes"][0]["value"],
            json!(["hair"])
        );
        assert_eq!(v["source_fields_evidence"][0]["evidence_id"], "e-ev-1");

        let v = rt.lookup("the hero", None, None).unwrap();
        assert_eq!(v["matched_by"], "alias");
        assert_eq!(v["citations"][0]["evidence_id"], "e-alias-1");

        let v = rt.search("second", 10, None, None).unwrap();
        assert_eq!(v["status"], "found");
        let c0 = &v["candidates"][0];
        assert_eq!(c0["matched_by"], "fts");
        assert_eq!(c0["entry_key"]["value"], "hero2");
        assert!(c0["matched_documents"][0]["response_truncated"].is_boolean());

        let v = rt
            .related("character", "fixture", "hero", None, None, 20)
            .unwrap();
        assert_eq!(v["relations"].as_array().unwrap().len(), 1);
        assert_eq!(v["relations"][0]["dst"]["value"], "hero-tag");

        let v = rt.ask("hero 的标签是什么", None, None, None).unwrap();
        assert_eq!(v["mapping_status"], "verified");
        assert_eq!(v["query_template"], "tag");
        assert_eq!(v["parsed_subject"], "hero");

        let intro = rt.ask("介绍一下 hero2", None, None, None).unwrap();
        assert_eq!(intro["status"], "found");
        assert_eq!(intro["mapping_status"], "not_requested");
        assert_eq!(intro["relations"], json!([]));
        assert_eq!(
            intro["answer"],
            "Source entity fixture/hero2; see descriptions and citations for source-backed text."
        );
        assert!(rt
            .ask("介绍一下 hero2", None, None, Some("danbooru.tag"))
            .is_err());
        let v = rt.ask("hero", None, None, None).unwrap();
        assert_eq!(v["query_template"], "unsupported");
        assert_eq!(v["input_query"], "hero");
    }
}
