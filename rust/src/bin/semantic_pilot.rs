//! Resident JSONL diagnostic driver. No retries, embedding export or index writes.
//! Usage: semantic_pilot BASE_DB PACK_MANIFEST
//! stdin: {"case_id":"...","query":"...","limit":100,"kind":null,
//!         "namespace":null,"include_vector":true}
//! One flushed JSON response per request. The acceptance runner owns the frozen
//! SHA gate, 2 warmups and 120 formal requests; this driver never launches them.
//! Until the parent exports semantic from lib.rs, compile the identical module here.
#[cfg(feature = "semantic")]
pub use sakura_knowledge_runtime::match_query;
#[cfg(feature = "semantic")]
use sakura_knowledge_runtime::semantic;

#[cfg(feature = "semantic")]
fn main() -> semantic::Result<()> {
    use serde_json::{json, Value};
    use std::io::{BufRead, Write};
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 {
        return Err("Usage: semantic_pilot BASE_DB PACK_MANIFEST (resident JSONL stdin)".into());
    }
    let mut engine = semantic::SemanticEngine::open(&args[0], &args[1])?;
    let mut output = std::io::stdout().lock();
    writeln!(
        output,
        "{}",
        json!({"event":"opened","open_timings_ms":engine.open_timings_ms,"retries":0})
    )?;
    output.flush()?;
    for line in std::io::stdin().lock().lines() {
        let request: Value = serde_json::from_str(&line?)?;
        let query = request["query"].as_str().ok_or("query must be text")?;
        let case_id = request["case_id"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or("case_id must be nonempty text")?;
        let mut options = semantic::RetrieveOptions::default();
        if let Some(limit) = request.get("limit") {
            options.limit = usize::try_from(limit.as_u64().ok_or("limit must be integer")?)?;
        }
        for (field, target) in [
            ("kind", &mut options.kind),
            ("namespace", &mut options.namespace),
        ] {
            if let Some(value) = request.get(field).filter(|v| !v.is_null()) {
                *target = Some(value.as_str().ok_or("filter must be text")?.into());
            }
        }
        if let Some(value) = request.get("include_vector") {
            options.include_vector = value.as_bool().ok_or("include_vector must be boolean")?;
        }
        match engine.retrieve(query, &options) {
            Ok(mut result) => {
                result["case_id"] = json!(case_id);
                writeln!(output, "{result}")?;
                output.flush()?;
            }
            Err(error) => {
                writeln!(
                    output,
                    "{}",
                    json!({"case_id":case_id,"status":"FAIL","error":error.to_string(),"retries":0})
                )?;
                output.flush()?;
                return Err(error);
            }
        }
    }
    Ok(())
}

#[cfg(not(feature = "semantic"))]
fn main() {
    eprintln!("semantic_pilot requires --features semantic");
    std::process::exit(2);
}
