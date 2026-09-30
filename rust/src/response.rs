//! Response v3: bounded source observations, no implicit fact winner.
use crate::{Error, Result};
use serde_json::value::RawValue;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::time::Instant;

pub const VERSION: &str = "3";
pub const FIELDS: [&str; 4] = [
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

fn check(deadline: Instant) -> Result<()> {
    if Instant::now() > deadline {
        Err(Error::Budget)
    } else {
        Ok(())
    }
}

// RawValue skips unprojected JSON iteratively, without building a recursive Value.
// Only the four displayed fields recurse, and then at most four levels.
fn projected(raw: &str, depth: usize, deadline: Instant) -> Result<(Value, bool)> {
    check(deadline)?;
    let raw = raw.trim();
    if raw.starts_with('[') || raw.starts_with('{') {
        if depth >= 4 {
            return Ok((Value::Null, true));
        }
        let mut changed = false;
        let out = if raw.starts_with('[') {
            let items: Vec<Box<RawValue>> = serde_json::from_str(raw).map_err(json_error)?;
            changed |= items.len() > 16;
            let mut out = Vec::new();
            for item in items.iter().take(16) {
                let (v, c) = projected(item.get(), depth + 1, deadline)?;
                out.push(v);
                changed |= c;
            }
            Value::Array(out)
        } else {
            let items: BTreeMap<String, Box<RawValue>> =
                serde_json::from_str(raw).map_err(json_error)?;
            changed |= items.len() > 16;
            let mut out = Map::new();
            for (k, item) in items.iter().take(16) {
                let (v, c) = projected(item.get(), depth + 1, deadline)?;
                changed |= c || k.chars().count() > 256;
                out.insert(k.chars().take(256).collect(), v);
            }
            Value::Object(out)
        };
        check(deadline)?;
        return Ok(if size(&out) > 2048 {
            (Value::Null, true)
        } else {
            (out, changed)
        });
    }
    if raw.starts_with('-') || raw.starts_with(|c: char| c.is_ascii_digit()) {
        // RawValue has already validated JSON syntax. Source spelling is not
        // the projected-value budget: long finite decimals/exponents normalize.
        if raw.contains(['.', 'e', 'E']) {
            let number = raw
                .parse::<f64>()
                .map_err(|_| Error::Invalid("invalid evidence JSON number".into()))?;
            check(deadline)?;
            return Ok(if number.is_finite() {
                (json!(number), false)
            } else {
                (Value::Null, true)
            });
        }
        if raw.parse::<i64>().is_err() && raw.parse::<u64>().is_err() {
            return Ok((Value::Null, true));
        }
    }
    let value: Value = serde_json::from_str(raw).map_err(json_error)?;
    check(deadline)?;
    Ok(bounded(&value, depth))
}

fn json_error(e: serde_json::Error) -> Error {
    Error::Invalid(format!("invalid evidence JSON: {e}"))
}

pub fn observations(
    proofs: &[Value],
    payloads: &[String],
    deadline: Instant,
) -> Result<(Value, Value, Value)> {
    let mut fields: Map<String, Value> = Map::new();
    let mut evidence = Vec::new();
    let mut truncated_fields = BTreeSet::new();
    for (proof, payload) in proofs.iter().zip(payloads) {
        check(deadline)?;
        let parsed: BTreeMap<String, Box<RawValue>> =
            serde_json::from_str(payload).map_err(json_error)?;
        let nested;
        let raw = if let Some(value) = parsed.get("raw") {
            if !value.get().trim_start().starts_with('{') {
                continue;
            }
            nested = serde_json::from_str::<BTreeMap<String, Box<RawValue>>>(value.get())
                .map_err(json_error)?;
            &nested
        } else {
            &parsed
        };
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
                let (bounded, truncated) = projected(value.get(), 0, deadline)?;
                let state = if value.get().trim() == "null" {
                    "null"
                } else if !truncated
                    && (bounded == json!([]) || bounded == json!({}) || bounded == json!(""))
                {
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

fn checked_size(value: &Value, deadline: Instant) -> Result<usize> {
    struct Counter {
        bytes: usize,
        deadline: Instant,
    }
    impl std::io::Write for Counter {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            if Instant::now() > self.deadline {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    "query_budget_exceeded",
                ));
            }
            self.bytes += bytes.len();
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    check(deadline)?;
    let mut counter = Counter { bytes: 0, deadline };
    let result = serde_json::to_writer(&mut counter, value);
    check(deadline)?;
    result.map_err(json_error)?;
    Ok(counter.bytes)
}

pub fn bound_response(mut value: Value, deadline: Instant) -> Result<Value> {
    let mut total = checked_size(&value, deadline)?;
    while total > RESPONSE_BYTES {
        check(deadline)?;
        // Inspect has no candidate/warning arrays. Its identity is irreducible.
        let can_drop = value
            .get("candidates")
            .and_then(Value::as_array)
            .is_some_and(|v| v.len() > 1)
            || value
                .get("relations")
                .and_then(Value::as_array)
                .is_some_and(|v| !v.is_empty());
        if !can_drop {
            return Err(Error::Invalid("response_budget_exceeded".into()));
        }
        if value.get("warnings").is_none() {
            value["warnings"] = json!([]);
            total = checked_size(&value, deadline)?;
        }
        let warnings = value["warnings"].as_array_mut().unwrap();
        if !warnings.contains(&json!("response_budget_truncated")) {
            total += size(&json!("response_budget_truncated")) + usize::from(!warnings.is_empty());
            warnings.push(json!("response_budget_truncated"));
        }
        if value
            .get("candidates")
            .and_then(Value::as_array)
            .is_some_and(|v| v.len() > 1)
        {
            let removed = value["candidates"].as_array_mut().unwrap().pop().unwrap();
            total -= checked_size(&removed, deadline)? + 1;
        } else if value
            .get("relations")
            .and_then(Value::as_array)
            .is_some_and(|v| !v.is_empty())
        {
            let items = value["relations"].as_array_mut().unwrap();
            let removed = items.pop().unwrap();
            total -= checked_size(&removed, deadline)? + usize::from(!items.is_empty());
        } else {
            return Err(Error::Invalid("response_budget_exceeded".into()));
        }
    }
    check(deadline)?;
    Ok(value)
}
