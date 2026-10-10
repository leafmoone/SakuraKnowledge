use super::{add_source, text, ProofContext, EntryKey, Result};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

type TypedKey = (String, String, String);
fn key(record: &Value) -> Option<TypedKey> {
    let entry = record.get("entry").or_else(|| record.get("entry_key")).unwrap_or(record);
    Some((entry["kind"].as_str()?.into(), entry["namespace"].as_str()?.into(), entry["value"].as_str()?.into()))
}
fn origins(record: &Value) -> Vec<String> {
    match record.get("source_packs").or_else(|| record.get("source_pack")) {
        Some(Value::Array(values)) => values.iter().filter_map(Value::as_str).map(str::to_owned).collect(),
        Some(Value::String(value)) => vec![value.clone()],
        _ => vec![String::new()], // Single-snapshot responses have no pack qualifier.
    }
}
const NESTED_PROOFS: &[&str] = &["citations", "identity_evidence", "aliases", "descriptions", "matched_documents", "source_fields_evidence", "trusted_pins"];

/// Qualify only public proofs; raw ANN/lexical IDs and ranking tie keys stay local.
pub(crate) fn qualify_public_record(record: &Value, pack: &str) -> Value {
    let mut record = record.clone();
    if !record.is_object() { return record; }
    record["source_packs"] = json!([pack]);
    for field in NESTED_PROOFS {
        if let Some(rows) = record[*field].as_array_mut() {
            for row in rows { *row = qualify_public_record(row, pack); }
        }
    }
    record
}

/// Publish every independently validated pin, even when its key is outside TopK.
pub(super) fn pin_proofs(context: &mut ProofContext<'_>, pins: &[Value], sources: &mut BTreeMap<String, Value>) -> Result<Vec<Value>> {
    let mut proofs = Vec::new();
    for pin in pins {
        let eid = context.pin(pin)?;
        let entry = EntryKey::parse(&pin["entry"])?;
        add_source(context.conn, sources, text(pin, "source_id")?)?;
        let proof = json!({"entry_key":entry.json(),"entry_id":eid.to_string(),"source_id":pin["source_id"],"evidence_id":pin["evidence_id"],"status":"source_backed"});
        if !proofs.contains(&proof) { proofs.push(proof); }
    }
    Ok(proofs)
}

fn collect_nested<'a>(record: &'a Value, proofs: &mut Vec<&'a Value>) {
    proofs.push(record);
    for field in NESTED_PROOFS {
        for row in record[*field].as_array().into_iter().flatten() { collect_nested(row, proofs); }
    }
}

/// Structured candidates can carry several identity/alias proofs from several
/// sources. Check each against its typed entry, never promote generated text.
pub(super) fn identity_proofs(conn: &Connection, records: &[Value], sources: &mut BTreeMap<String, Value>) -> Result<Vec<Value>> {
    let mut proofs = Vec::new();
    let mut checked = BTreeSet::new();
    let mut context = ProofContext::new(conn, "");
    let mut supported = conn.prepare_cached("SELECT EXISTS(SELECT 1 FROM entry_evidence WHERE entry_id=?1 AND source_id=?2 AND evidence_id=?3 AND status='source_backed' UNION ALL SELECT 1 FROM aliases WHERE entry_id=?1 AND source_id=?2 AND evidence_id=?3 AND status='source_backed')")?;
    for record in records {
        let entry = EntryKey::parse(record.get("entry").or_else(|| record.get("entry_key")).unwrap_or(record))?;
        let eid = context.entry(&entry)?;
        let mut nested = Vec::new();
        collect_nested(record, &mut nested);
        for proof in nested {
            if proof.get("document_id").is_some_and(|v| !v.is_null()) || proof.get("status").is_some_and(|v| v != "source_backed") { continue; }
            let (Some(sid), Some(refid)) = (proof["source_id"].as_str(), proof["evidence_id"].as_str()) else { continue; };
            if !checked.insert((eid, sid.to_owned(), refid.to_owned())) { continue; }
            if !supported.query_row(params![eid, sid, refid], |r| r.get::<_, bool>(0))? { continue; }
            add_source(conn, sources, sid)?;
            let mut row = json!({"entry_key":entry.json(),"entry_id":eid.to_string(),"source_id":sid,"evidence_id":refid,"status":"source_backed"});
            // Keep source proof payload/locators, but do not duplicate entire candidate bodies.
            for field in ["type", "locator", "payload", "text"] {
                if let Some(value) = proof.get(field) { row[field] = value.clone(); }
            }
            proofs.push(row);
        }
    }
    Ok(proofs)
}

/// Close only the public evidence projection, after the caller's final candidate
/// limit. Allowed origins are selected typed keys plus every independent pin.
pub(crate) fn close_public_evidence(response: &mut Value) {
    let mut allowed = BTreeSet::new();
    for field in ["candidates", "trusted_pins"] {
        for record in response[field].as_array().into_iter().flatten() {
            if let Some(key) = key(record) {
                for pack in origins(record) { allowed.insert((pack, key.clone())); }
            }
        }
    }
    let mut documents = BTreeMap::new();
    if let Some(rows) = response["documents"].as_array_mut() {
        rows.retain(|row| {
            let (Some(key), Some(did), Some(sid), Some(eid)) = (key(row), row["document_id"].as_str(), row["source_id"].as_str(), row["evidence_id"].as_str()) else { return false; };
            let mut keep = false;
            for pack in origins(row) {
                if allowed.contains(&(pack.clone(), key.clone())) {
                    let locator = (pack, did.to_owned());
                    if !documents.contains_key(&locator) {
                        documents.insert(locator, (sid.to_owned(), eid.to_owned()));
                        keep = true;
                    }
                }
            }
            keep
        });
    }
    let mut used_sources = BTreeSet::new();
    for field in ["evidence", "citations"] {
        if let Some(rows) = response[field].as_array_mut() {
            let mut seen = BTreeSet::new();
            rows.retain(|row| {
                let (Some(sid), Some(eid)) = (row["source_id"].as_str(), row["evidence_id"].as_str()) else { return false; };
                let mut keep = false;
                for pack in origins(row) {
                    let supported = match row.get("document_id").filter(|v| !v.is_null()) {
                        Some(did) => did.as_str().is_some_and(|did| documents.get(&(pack.clone(), did.to_owned())).is_some_and(|binding| binding == &(sid.to_owned(), eid.to_owned()))),
                        None => key(row).is_some_and(|key| allowed.contains(&(pack.clone(), key))) && row["status"] == "source_backed",
                    };
                    if supported && seen.insert((pack.clone(), row.to_string())) {
                        used_sources.insert((pack, sid.to_owned()));
                        keep = true;
                    }
                }
                keep
            });
        }
    }
    if let Some(rows) = response["sources"].as_array_mut() {
        let mut seen = BTreeSet::new();
        rows.retain(|row| row["source_id"].as_str().is_some_and(|sid| origins(row).into_iter().any(|pack| used_sources.contains(&(pack.clone(), sid.to_owned())) && seen.insert((pack, sid.to_owned())))));
    }
}
