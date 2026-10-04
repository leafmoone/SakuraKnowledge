//! Resident semantic JSONL driver; no retries or index writes.
#[cfg(feature = "semantic")]
fn main() -> sakura_knowledge_runtime::semantic::Result<()> {
    use sakura_knowledge_runtime::semantic::{RetrieveOptions, SemanticEngine};
    use sakura_knowledge_runtime::semantic_jsonl::send_response;
    use serde_json::{json, Value};
    use std::io::{BufRead, Write};
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 { return Err("Usage: semantic_pilot BASE_DB PACK_MANIFEST (resident JSONL stdin)".into()); }
    let mut engine = SemanticEngine::open(&args[0], &args[1])?;
    let mut output = std::io::stdout().lock();
    writeln!(output,"{}",json!({"event":"opened","open_timings_ms":engine.open_timings_ms,"retries":0}))?;
    output.flush()?;
    for line in std::io::stdin().lock().lines() {
        let request: Value = serde_json::from_str(&line?)?;
        let query = request["query"].as_str().ok_or("query required")?;
        let case_id = request["case_id"].as_str().ok_or("case_id required")?;
        let mut options = RetrieveOptions::default();
        if let Some(value) = request.get("limit") { options.limit = value.as_u64().ok_or("limit must be integer")? as usize; }
        if let Some(value) = request.get("kind").and_then(Value::as_str) { options.kind = Some(value.into()); }
        if let Some(value) = request.get("namespace").and_then(Value::as_str) { options.namespace = Some(value.into()); }
        if let Some(value) = request.get("include_vector") { options.include_vector = value.as_bool().ok_or("include_vector must be boolean")?; }
        let started = std::time::Instant::now();
        match engine.retrieve(query,&options) {
            Ok(mut result) => { result["case_id"] = json!(case_id); send_response(&mut output,&result,case_id,started.elapsed().as_secs_f64()*1000.0)?; }
            Err(error) => { send_response(&mut output,&json!({"case_id":case_id,"status":"FAIL","error":error.to_string(),"retries":0}),case_id,started.elapsed().as_secs_f64()*1000.0)?; return Err(error); }
        }
    }
    Ok(())
}
#[cfg(not(feature = "semantic"))]
fn main() { eprintln!("semantic_pilot requires --features semantic"); std::process::exit(2); }
