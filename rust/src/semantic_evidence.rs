use super::{add_source, text, trusted_entry, validate_pin, EntryKey, Result};
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
pub(super) fn pin_proofs(conn: &Connection, query: &str, pins: &[Value], sources: &mut BTreeMap<String, Value>) -> Result<Vec<Value>> {
    let mut proofs = Vec::new();
    for pin in pins {
        validate_pin(conn, query, pin)?;
        let entry = EntryKey::parse(&pin["entry"])?;
        let eid = trusted_entry(conn, &entry)?;
        add_source(conn, sources, text(pin, "source_id")?)?;
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
    let mut supported = conn.prepare_cached("SELECT EXISTS(SELECT 1 FROM entry_evidence WHERE entry_id=?1 AND source_id=?2 AND evidence_id=?3 AND status='source_backed' UNION ALL SELECT 1 FROM aliases WHERE entry_id=?1 AND source_id=?2 AND evidence_id=?3 AND status='source_backed')")?;
    for record in records {
        let entry = EntryKey::parse(record.get("entry").or_else(|| record.get("entry_key")).unwrap_or(record))?;
        let eid = trusted_entry(conn, &entry)?;
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

#[cfg(test)]
mod tests {
    use super::*;
    fn entry(value: &str) -> Value { json!({"kind":"subject","namespace":"test","value":value}) }
    fn fixture() -> Value {
        let mut value = json!({"candidates":[],"trusted_pins":[],"documents":[],"citations":[],"evidence":[],"sources":[],"identity_status":"not_asserted","promoted_identities":[]});
        for pack in ["a", "b"] {
            value["sources"].as_array_mut().unwrap().push(json!({"source_id":"s","source_packs":[pack]}));
            for index in 0..6 {
                for suffix in 0..2 {
                    let did = format!("{}", index * 2 + suffix);
                    value["documents"].as_array_mut().unwrap().push(json!({"entry_key":entry(&index.to_string()),"document_id":did,"source_id":"s","evidence_id":did,"original":"uncut body","status":"generated_from_evidence","source_packs":[pack]}));
                    let proof = json!({"document_id":did,"source_id":"s","evidence_id":did,"source_packs":[pack]});
                    value["citations"].as_array_mut().unwrap().push(proof.clone());
                    value["evidence"].as_array_mut().unwrap().push(proof);
                }
            }
        }
        value
    }
    #[test]
    fn topk_one_and_five_keep_all_selected_documents_and_both_origins() {
        for limit in [1, 5] {
            let mut value = fixture();
            value["candidates"] = json!((0..limit).map(|i| json!({"entry":entry(&i.to_string()),"source_packs":["a","b"],"hybrid_rank":i+1,"rrf_score":1.0/(61.0+i as f64)})).collect::<Vec<_>>());
            let ranked = value["candidates"].clone();
            close_public_evidence(&mut value);
            assert_eq!(value["candidates"], ranked);
            for field in ["documents", "citations", "evidence"] { assert_eq!(value[field].as_array().unwrap().len(), limit * 4); }
            assert_eq!(value["sources"].as_array().unwrap().len(), 2);
            assert!(value["documents"].as_array().unwrap().iter().all(|d| d["original"] == "uncut body"));
            assert_eq!(value["identity_status"], "not_asserted");
            assert_eq!(value["promoted_identities"], json!([]));
        }
    }
    #[test]
    fn federated_local_materialization_qualifies_before_final_closure() {
        let mut value = json!({"candidates":[{"entry":entry("0"),"source_packs":["a"]}],
            "trusted_pins":[],"documents":[{"entry_key":entry("0"),"document_id":"1",
                "source_id":"s","evidence_id":"e","original":"selected body"}],
            "evidence":[{"document_id":"1","source_id":"s","evidence_id":"e"}],
            "citations":[{"document_id":"1","source_id":"s","evidence_id":"e"}],
            "sources":[{"source_id":"s"}]});
        for field in ["documents","sources","evidence","citations"] {
            for row in value[field].as_array_mut().unwrap() { *row=qualify_public_record(row,"a"); }
        }
        close_public_evidence(&mut value);
        for field in ["documents","sources","evidence","citations"] {
            assert_eq!(value[field].as_array().unwrap().len(),1);
            assert_eq!(value[field][0]["source_packs"],json!(["a"]));
        }
    }
    #[test]
    fn independent_pin_keeps_multiple_identity_sources_but_not_unselected_evidence() {
        let mut value = fixture();
        value["candidates"] = json!([{"entry":entry("0"),"source_packs":["a"]}]);
        value["trusted_pins"] = json!([{"entry":entry("5"),"source_packs":["b"]}]);
        for sid in ["one", "two"] {
            value["sources"].as_array_mut().unwrap().push(json!({"source_id":sid,"source_packs":["b"]}));
            let proof = json!({"entry_key":entry("5"),"source_id":sid,"evidence_id":sid,"status":"source_backed","source_packs":["b"]});
            value["evidence"].as_array_mut().unwrap().push(proof.clone());
            value["citations"].as_array_mut().unwrap().push(proof);
        }
        value["sources"].as_array_mut().unwrap().push(json!({"source_id":"orphan","source_packs":["b"]}));
        close_public_evidence(&mut value);
        assert_eq!(value["documents"].as_array().unwrap().len(), 4);
        for field in ["citations", "evidence"] { assert_eq!(value[field].as_array().unwrap().len(), 6); }
        assert_eq!(value["sources"].as_array().unwrap().len(), 4);
    }
    #[test]
    fn qualification_preserves_raw_ranking_ids_and_nested_origins() {
        let raw = json!({"entry":entry("0"),"provenance":[{"hit":{"document_id":"7"}}],"citations":[{"document_id":"7","source_id":"s","evidence_id":"e"}],"matched_documents":[{"document_id":"7"}]});
        let qualified = qualify_public_record(&raw, "pack");
        assert_eq!(qualified["provenance"], raw["provenance"]);
        assert_eq!(qualified["citations"][0]["document_id"], "7");
        assert_eq!(qualified["citations"][0]["source_packs"], json!(["pack"]));
        assert_eq!(qualified["matched_documents"][0]["source_packs"], json!(["pack"]));
    }
    #[test]
    fn nested_pin_proofs_are_source_backed_not_generated_identity() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch("CREATE TABLE entries(id INTEGER,kind TEXT,namespace TEXT,value TEXT,conflicted INTEGER); CREATE TABLE entry_evidence(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT); CREATE TABLE aliases(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT,text TEXT); CREATE TABLE sources(source_id TEXT,metadata TEXT); INSERT INTO entries VALUES(1,'subject','test','0',0); INSERT INTO sources VALUES('one','{}'),('two','{}'),('generated','{}'); INSERT INTO entry_evidence VALUES(1,'one','identity','source_backed'),(1,'generated','g','generated_from_evidence'); INSERT INTO aliases VALUES(1,'two','alias','source_backed','q');").unwrap();
        let records = vec![json!({"entry":entry("0"),"source_id":"one","evidence_id":"identity","citations":[{"source_id":"two","evidence_id":"alias"}],"identity_evidence":[{"source_id":"one","evidence_id":"identity","status":"source_backed"}],"descriptions":[{"source_id":"generated","evidence_id":"g","status":"generated_from_evidence"}]})];
        let mut sources = BTreeMap::new();
        let proofs = identity_proofs(&conn, &records, &mut sources).unwrap();
        assert_eq!(proofs.len(), 2);
        assert_eq!(sources.len(), 2);
        assert!(proofs.iter().all(|p| p["status"] == "source_backed"));
        conn.execute("UPDATE entry_evidence SET status='generated_from_evidence'", []).unwrap();
        assert!(identity_proofs(&conn, &records, &mut sources).is_err());
    }
}
