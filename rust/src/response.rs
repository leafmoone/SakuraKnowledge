//! Response v3: bounded source observations, no implicit fact winner.
use crate::{Error, Result};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

pub const VERSION: &str = "3";
const FIELDS: [&str; 4] = [
    "raw_attributes",
    "raw_subject_categories",
    "raw_cv_names",
    "raw_gender",
];
const RESPONSE_BYTES: usize = 524288;

fn size(value: &Value) -> usize {
    serde_json::to_vec(value)
        .expect("JSON Value is serializable")
        .len()
}

fn bounded(value: &Value, depth: usize) -> (Value, bool) {
    match value {
        Value::String(s) => (
            json!(s.chars().take(256).collect::<String>()),
            s.chars().count() > 256,
        ),
        Value::Array(items) => {
            if depth >= 4 {
                return (Value::Null, true);
            }
            let mut changed = items.len() > 16;
            let out: Vec<Value> = items
                .iter()
                .take(16)
                .map(|v| {
                    let (b, c) = bounded(v, depth + 1);
                    changed |= c;
                    b
                })
                .collect();
            let out = Value::Array(out);
            if size(&out) > 2048 {
                (Value::Null, true)
            } else {
                (out, changed)
            }
        }
        Value::Object(items) => {
            if depth >= 4 {
                return (Value::Null, true);
            }
            let mut changed = items.len() > 16;
            let out: Map<String, Value> = items
                .iter()
                .take(16)
                .map(|(k, v)| {
                    let (b, c) = bounded(v, depth + 1);
                    changed |= c || k.chars().count() > 256;
                    (k.chars().take(256).collect(), b)
                })
                .collect();
            let out = Value::Object(out);
            if size(&out) > 2048 {
                (Value::Null, true)
            } else {
                (out, changed)
            }
        }
        _ => (value.clone(), false),
    }
}

pub fn observations(proofs: &[Value], payloads: &[String]) -> Result<(Value, Value, Value)> {
    let mut fields: Map<String, Value> = Map::new();
    let mut evidence = Vec::new();
    let mut truncated_fields = BTreeSet::new();
    for (proof, payload) in proofs.iter().zip(payloads) {
        let parsed: Value = serde_json::from_str(payload)
            .map_err(|e| Error::Invalid(format!("invalid evidence JSON: {e}")))?;
        let raw = parsed.get("raw").unwrap_or(&parsed);
        for name in FIELDS {
            if let Some(value) = raw.get(name) {
                let list = fields
                    .entry(name)
                    .or_insert_with(|| json!([]))
                    .as_array_mut()
                    .unwrap();
                if list.len() >= 4 {
                    truncated_fields.insert(name);
                    continue;
                }
                let (bounded, truncated) = bounded(value, 0);
                let state = if value.is_null() {
                    "null"
                } else if value == &json!([]) || value == &json!({}) || value == &json!("") {
                    "empty"
                } else {
                    "present"
                };
                list.push(
                    json!({"source_id": proof["source_id"], "evidence_id": proof["evidence_id"],
                    "status": proof["status"], "value": bounded, "value_state": state,
                    "truncated": truncated}),
                );
                evidence.push(json!({"field": name, "source_id": proof["source_id"],
                    "evidence_id": proof["evidence_id"], "status": proof["status"]}));
            }
        }
    }
    Ok((
        Value::Object(fields),
        json!(evidence),
        json!(truncated_fields),
    ))
}

pub fn bound_response(mut value: Value) -> Result<Value> {
    while size(&value) > RESPONSE_BYTES {
        let warnings = value["warnings"].as_array_mut().unwrap();
        if !warnings.contains(&json!("response_budget_truncated")) {
            warnings.push(json!("response_budget_truncated"));
        }
        if value["candidates"].as_array().unwrap().len() > 1 {
            value["candidates"].as_array_mut().unwrap().pop();
        } else if !value["relations"].as_array().unwrap().is_empty() {
            value["relations"].as_array_mut().unwrap().pop();
        } else {
            return Err(Error::Invalid("response_budget_exceeded".into()));
        }
    }
    Ok(value)
}
