//! Read-only Rust runtime for SakuraKnowledge snapshots.
//!
//! Faithful port of the Python reference contract (api.py / model.py):
//! identity trust is `source_backed` only; text trust additionally allows
//! `generated_from_evidence`. No models, no services, no writes.

use rusqlite::{params, Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;
use std::time::{Duration, Instant};
use unicode_normalization::UnicodeNormalization;

pub const CONTRACT_VERSION: &str = "2";
const ID_STATUSES: &str = "'source_backed'";
const TEXT_STATUSES: &str = "'generated_from_evidence','source_backed'";
const MAX_QUERY_CHARS: usize = 4096;
const MAX_QUERY_TOKENS: usize = 256;
const MAX_WORD: usize = 256;
const BUDGET_SECS: u64 = 5;
type EntryRow = (i64, String, String, String, Option<String>);
type FtsRow = (
    i64,
    String,
    String,
    String,
    f64,
    String,
    String,
    bool,
    String,
    String,
);

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
    matches!(c, ' ' | '\t' | '\n' | '\r')
}

/// Same lexing as the Python reference: NFKC + casefold; CJK/kana runs become
/// overlapping bigrams, other word runs stay whole (max 256 chars).
fn lex(text: &str) -> Vec<String> {
    let normalized = text.nfkc().to_string();
    let lower: Vec<char> = normalized.to_lowercase().chars().collect();
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
        } else if lower[i].is_alphanumeric() {
            let start = i;
            while i < lower.len() && (lower[i].is_alphanumeric() || is_cjk_kana(lower[i])) {
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
}

fn base(query: &Value, snapshot: &str, status: &str) -> Value {
    json!({
        "contract_version": CONTRACT_VERSION,
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
        Ok(Runtime { conn, snapshot })
    }

    fn install_budget(conn: &Connection) {
        let deadline = Duration::from_secs(BUDGET_SECS);
        let start = Instant::now();
        conn.progress_handler(1000, Some(move || start.elapsed() > deadline));
    }

    pub fn snapshot(&self) -> &str {
        &self.snapshot
    }

    pub fn runtime_info() -> Value {
        json!({"contract_version": CONTRACT_VERSION,
               "runtime": "rust",
               "sqlite_version": "bundled (libsqlite3-sys)"})
    }

    pub fn inspect(&mut self) -> Result<Value> {
        Self::install_budget(&self.conn);
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
        let dbstat: Option<i64> = self
            .conn
            .query_row("SELECT count(*) FROM dbstat", [], |r| r.get(0))
            .ok();
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
            "dbstat_status": if dbstat.is_some() { "available" } else { "unavailable" },
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
        let (identities, payloads) = self.fetch_evidence(id)?;
        let mut fields = serde_json::Map::new();
        for payload in &payloads {
            let parsed: Value = serde_json::from_str(payload).unwrap_or(Value::Null);
            let raw = parsed.get("raw").unwrap_or(&parsed);
            if let Some(obj) = raw.as_object() {
                for name in [
                    "raw_attributes",
                    "raw_subject_categories",
                    "raw_cv_names",
                    "raw_gender",
                ] {
                    if let Some(v) = obj.get(name) {
                        fields.insert(name.to_string(), v.clone());
                    }
                }
            }
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
            "source_fields": Value::Object(fields),
            "source_fields_evidence": citations,
            "matched_by": if use_alias_proofs { "alias" } else { "exact" },
            "source_id": first.as_ref().and_then(|f| f.get("source_id").cloned()).unwrap_or(Value::Null),
            "evidence_id": first.as_ref().and_then(|f| f.get("evidence_id").cloned()).unwrap_or(Value::Null),
            "citations": citations
        }))
    }

    fn fetch_docs(&mut self, id: i64) -> Result<Vec<Value>> {
        let sql = format!(
            "SELECT title,substr(original,1,4000),length(original)>4000,
                     json_extract(payload,'$.search_text_truncated'),source_id,evidence_id,status
             FROM documents WHERE entry_id=? AND status IN ({TEXT_STATUSES})
             ORDER BY id LIMIT 10"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt.query_map([id], |r| {
            Ok(json!({
                "title": r.get::<_, String>(0)?,
                "original": r.get::<_, String>(1)?,
                "response_truncated": r.get::<_, bool>(2)?,
                "search_text_truncated": r.get::<_, Option<bool>>(3)?,
                "source_id": r.get::<_, String>(4)?,
                "evidence_id": r.get::<_, String>(5)?,
                "status": r.get::<_, String>(6)?
            }))
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
             ORDER BY source_id,evidence_id LIMIT 100"
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
                            "status": status, "type": typ, "locator": loc,
                            "payload": payload}));
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

    pub fn lookup(
        &mut self,
        query: &str,
        kind: Option<&str>,
        namespace: Option<&str>,
    ) -> Result<Value> {
        Self::install_budget(&self.conn);
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
        Ok(result)
    }

    pub fn lookup_key(&mut self, kind: &str, namespace: &str, value: &str) -> Result<Value> {
        Self::install_budget(&self.conn);
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
        Ok(result)
    }

    pub fn search(
        &mut self,
        query: &str,
        topk: u32,
        kind: Option<&str>,
        namespace: Option<&str>,
    ) -> Result<Value> {
        if !(1..=100).contains(&topk) {
            return Err(Error::Invalid("topk must be 1..100".into()));
        }
        let mut exact = self.lookup(query, kind, namespace)?;
        let compiled = match_query(query)?;
        if compiled.is_empty() {
            let cands = exact["candidates"].as_array().cloned().unwrap_or_default();
            exact["candidates"] = json!(cands.into_iter().take(topk as usize).collect::<Vec<_>>());
            if exact["status"] == json!("not_found") {
                exact["warnings"]
                    .as_array_mut()
                    .unwrap()
                    .push(json!("too_short"));
            }
            return Ok(exact);
        }
        let sql = format!(
            "SELECT e.id,e.kind,e.namespace,e.value,
                    bm25(search_fts),
                    d.title,substr(d.original,1,4000),length(d.original)>4000,
                    d.source_id,d.evidence_id
             FROM search_fts JOIN documents d ON d.id=search_fts.document_id
             JOIN entries e ON e.id=search_fts.entry_id
             WHERE search_fts MATCH ?1
             AND e.conflicted=0 AND d.status IN ({TEXT_STATUSES})
             AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id
                    AND v.status IN ({ID_STATUSES}))
             AND (?2 IS NULL OR e.kind=?2) AND (?3 IS NULL OR e.namespace=?3)
             ORDER BY bm25(search_fts),e.kind,e.namespace,e.value,search_fts.rowid
             LIMIT 10001"
        );
        let raw: Vec<FtsRow> = {
            let mut stmt = self.conn.prepare(&sql)?;
            let rows = stmt.query_map(params![compiled, kind, namespace], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, f64>(4)?,
                    r.get::<_, String>(5)?,
                    r.get::<_, String>(6)?,
                    r.get::<_, bool>(7)?,
                    r.get::<_, String>(8)?,
                    r.get::<_, String>(9)?,
                ))
            })?;
            let mut v = Vec::new();
            for row in rows {
                v.push(row?);
            }
            v
        };
        let mut rows = raw.into_iter();
        let mut candidates = exact["candidates"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .take(topk as usize)
            .collect::<Vec<_>>();
        let mut seen: std::collections::HashSet<(String, String, String)> = candidates
            .iter()
            .map(|c| {
                (
                    c["entry_key"]["kind"].as_str().unwrap().to_string(),
                    c["entry_key"]["namespace"].as_str().unwrap().to_string(),
                    c["entry_key"]["value"].as_str().unwrap().to_string(),
                )
            })
            .collect();
        let mut scanned = 0u32;
        loop {
            if candidates.len() >= topk as usize {
                break;
            }
            let Some((id, k, ns, v, score, title, original, truncated, sid, eid)) = rows.next()
            else {
                break;
            };
            scanned += 1;
            if scanned > 10000 {
                break;
            }
            let ident = (k.clone(), ns.clone(), v.clone());
            if seen.contains(&ident) {
                continue;
            }
            let Some(mut candidate) = self.candidate_for(id, &k, &ns, &v, None, None)? else {
                continue;
            };
            candidate["matched_by"] = json!("fts");
            candidate["score"] = json!(score);
            candidate["matched_documents"] = json!([{
                "title": title, "original": original,
                "response_truncated": truncated,
                "source_id": sid, "evidence_id": eid
            }]);
            candidate["source_id"] = json!(sid);
            candidate["evidence_id"] = json!(eid);
            seen.insert(ident);
            candidates.push(candidate);
        }
        exact["candidates"] = json!(candidates);
        if exact["status"] == json!("not_found") && !candidates.is_empty() {
            exact["status"] = json!("found");
        }
        if scanned > 10000
            && exact["candidates"]
                .as_array()
                .map(|a| a.len() < topk as usize)
                .unwrap_or(false)
        {
            exact["warnings"]
                .as_array_mut()
                .unwrap()
                .push(json!("search_document_scan_limit"));
        }
        Ok(exact)
    }

    pub fn related(
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
        let mut result = self.lookup_key(kind, namespace, value)?;
        if result["status"] != json!("found") {
            return Ok(result);
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
        Ok(result)
    }

    // ---------------------------------------------------------------- ask

    fn ask_resolved(
        &mut self,
        query: &str,
        kind: Option<&str>,
        namespace: Option<&str>,
        target: Option<&str>,
    ) -> Result<Value> {
        let mut result = self.lookup(query, kind, namespace)?;
        result["input_query"] = json!(query);
        result["parsed_subject"] = Value::Null;
        result["target_namespace"] = target.map(|t| json!(t)).unwrap_or(Value::Null);
        result["mapping_status"] = json!("unknown");
        if result["status"] == json!("not_found") {
            result["status"] = json!("unknown");
            result["answer"] = json!("No reliable exact source entity match.");
            return Ok(result);
        }
        if result["status"] == json!("ambiguous") {
            result["status"] = json!("entity_ambiguous");
            result["mapping_status"] = json!("entity_ambiguous");
            result["answer"] = json!("Multiple source entity matches; specify a source key.");
            return Ok(result);
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
            return Ok(result);
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
        Ok(result)
    }

    pub fn ask(
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
        Self::install_budget(&self.conn);
        let direct = self.lookup(query, kind, namespace)?;
        if direct["status"] == json!("found") {
            let mut result = self.ask_resolved(query, kind, namespace, target)?;
            result["input_query"] = json!(query);
            result["parsed_subject"] = Value::Null;
            result["query_template"] = json!("unsupported");
            return Ok(result);
        }
        let parsed = parse_ask_template(query);
        let (subject, mode) = match parsed {
            Some(p) => p,
            None => {
                let mut result = self.ask_resolved(query, kind, namespace, target)?;
                result["query_template"] = json!("unsupported");
                if result["status"] == json!("unknown") {
                    result["warnings"]
                        .as_array_mut()
                        .unwrap()
                        .push(json!("unsupported_query_template"));
                }
                return Ok(result);
            }
        };
        match mode.as_str() {
            "introduce" => {
                if target.is_some() {
                    return Err(Error::Invalid(
                        "introduce template cannot combine with target_tag_namespace".into(),
                    ));
                }
                let mut result = self.ask_resolved(&subject, kind, namespace, None)?;
                result["input_query"] = json!(query);
                result["parsed_subject"] = json!(subject);
                result["query_template"] = json!("introduce");
                if result["status"] == json!("found") {
                    let key = &result["entry_key"];
                    result["answer"] = json!(format!(
                        "Source entity {}/{}; see descriptions and citations for source-backed text.",
                        key["namespace"], key["value"]
                    ));
                }
                Ok(result)
            }
            "danbooru.tag" => {
                if matches!(target, Some(t) if t != "danbooru.tag") {
                    return Err(Error::Invalid(
                        "template implies target danbooru.tag; explicit target_tag_namespace conflicts"
                            .into(),
                    ));
                }
                let mut result =
                    self.ask_resolved(&subject, kind, namespace, Some("danbooru.tag"))?;
                result["input_query"] = json!(query);
                result["parsed_subject"] = json!(subject);
                result["query_template"] = json!("danbooru_tag");
                Ok(result)
            }
            _ => {
                let mut result = self.ask_resolved(&subject, kind, namespace, target)?;
                result["input_query"] = json!(query);
                result["parsed_subject"] = json!(subject);
                result["query_template"] = json!("tag");
                Ok(result)
            }
        }
    }
}

// ------------------------------------------------------------- ask template

/// Bounded deterministic templates, mirroring the Python reference regexes.
/// Python `.+?` requires at least one character; `\s*` in the templates means
/// zero or more ASCII whitespace characters. Returns the verbatim subject and
/// mode (`danbooru.tag`, `tag`, `introduce`); anything else returns None.
pub fn parse_ask_template(query: &str) -> Option<(String, String)> {
    if query.is_empty() || query.chars().count() > MAX_QUERY_CHARS {
        return None;
    }
    let chars: Vec<char> = query.chars().collect();
    let lower: Vec<char> = chars
        .iter()
        .map(|c| c.to_lowercase().collect::<String>().chars().next().unwrap())
        .collect();

    // First "的" splits the subject (Python `^(.+?)的` is non-greedy).
    if let Some(pos) = lower.iter().position(|&c| c == '的') {
        let mut i = pos + 1;
        while i < lower.len() && is_ws(lower[i]) {
            i += 1;
        }
        let rest: String = lower[i..].iter().collect();
        let mode = if rest == "danbooru tag 是什么" || rest == "danbooru  tag 是什么" {
            Some("danbooru.tag")
        } else if rest == "标签是什么" {
            Some("tag")
        } else {
            None
        };
        if let Some(mode) = mode {
            let mut end = pos;
            while end > 0 && is_ws(chars[end - 1]) {
                end -= 1;
            }
            if end > 0 {
                let subject: String = chars[..end].iter().collect();
                return Some((subject, mode.to_string()));
            }
        }
    }

    // "介绍 X" / "介绍一下 X"
    for prefix in ["介绍一下", "介绍"] {
        let pc: Vec<char> = prefix.chars().collect();
        if lower.len() >= pc.len() && lower[..pc.len()] == pc {
            let mut i = pc.len();
            while i < lower.len() && is_ws(lower[i]) {
                i += 1;
            }
            let mut end = lower.len();
            while end > i
                && (is_ws(lower[end - 1]) || matches!(lower[end - 1], '？' | '?' | '。' | '.'))
            {
                end -= 1;
            }
            if end > i {
                let subject: String = lower[i..end].iter().collect();
                return Some((subject, "introduce".to_string()));
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
    fn fixture_lookup_search_related_ask() {
        let dir = std::env::temp_dir().join("sknow-rs-test");
        std::fs::create_dir_all(&dir).unwrap();
        let db_path = dir.join("fixture.sqlite");
        build_fixture(&db_path);
        let mut rt = Runtime::open(&db_path).unwrap();

        let v = rt.lookup("hero", None, None).unwrap();
        assert_eq!(v["status"], "found");
        assert_eq!(v["entry_key"]["value"], "hero");
        assert_eq!(v["source_fields"]["raw_attributes"][0], "hair");
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

        let v = rt.ask("hero", None, None, None).unwrap();
        assert_eq!(v["query_template"], "unsupported");
        assert_eq!(v["input_query"], "hero");
    }
}
