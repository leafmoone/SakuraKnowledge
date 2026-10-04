//! Resident semantic JSONL driver; no retries or index writes.
#[cfg(feature = "semantic")]
fn parse_request(request: &serde_json::Value) -> sakura_knowledge_runtime::semantic::Result<(&str, &str, sakura_knowledge_runtime::semantic::RetrieveOptions)> {
    use sakura_knowledge_runtime::semantic::RetrieveOptions;
    let query = request["query"].as_str().ok_or("query must be text")?;
    let case_id = request["case_id"].as_str().filter(|s| !s.is_empty()).ok_or("case_id must be nonempty text")?;
    let mut options = RetrieveOptions::default();
    if let Some(limit) = request.get("limit") {
        options.limit = usize::try_from(limit.as_u64().ok_or("limit must be integer")?)?;
    }
    for (field, target) in [("kind", &mut options.kind), ("namespace", &mut options.namespace)] {
        if let Some(value) = request.get(field).filter(|v| !v.is_null()) {
            *target = Some(value.as_str().ok_or("filter must be text")?.into());
        }
    }
    if let Some(value) = request.get("include_vector") {
        options.include_vector = value.as_bool().ok_or("include_vector must be boolean")?;
    }
    Ok((query, case_id, options))
}

#[cfg(feature = "semantic")]
fn main() -> sakura_knowledge_runtime::semantic::Result<()> {
    use sakura_knowledge_runtime::semantic::SemanticEngine;
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
        let (query, case_id, options) = parse_request(&request)?;
        let started = std::time::Instant::now();
        match engine.retrieve(query,&options) {
            Ok(mut result) => { result["case_id"] = json!(case_id); send_response(&mut output,&result,case_id,started.elapsed().as_secs_f64()*1000.0)?; }
            Err(error) => { send_response(&mut output,&json!({"case_id":case_id,"status":"FAIL","error":error.to_string(),"retries":0}),case_id,started.elapsed().as_secs_f64()*1000.0)?; return Err(error); }
        }
    }
    Ok(())
}
#[cfg(all(test, feature = "semantic"))]
mod tests {
    use super::parse_request;
    use serde_json::{json, Value};
    fn request() -> Value { json!({"query":"q","case_id":"id"}) }
    #[test]
    fn case_id_requires_nonempty_text_without_trimming() {
        for valid in ["id", " ", " id "] {
            let mut r=request();r["case_id"]=json!(valid);
            assert_eq!(parse_request(&r).unwrap().1,valid);
        }
        let mut r=request();r.as_object_mut().unwrap().remove("case_id");
        assert!(parse_request(&r).is_err());
        for invalid in [json!(""), Value::Null, json!(1),json!(true),json!([]),json!({})] {
            r["case_id"]=invalid;assert!(parse_request(&r).is_err());
        }
    }
    #[test]
    fn filters_are_optional_null_or_verbatim_text_never_silently_ignored() {
        for field in ["kind","namespace"] {
            let mut r=request();
            assert!(parse_request(&r).is_ok());
            r[field]=Value::Null;
            let options=parse_request(&r).unwrap().2;
            assert!(options.kind.is_none() && options.namespace.is_none());
            for valid in ["character","", " ", " spaced "] {
                r[field]=json!(valid);let options=parse_request(&r).unwrap().2;
                assert_eq!(if field=="kind" {options.kind} else {options.namespace},Some(valid.into()));
            }
            for invalid in [json!(1),json!(false),json!([]),json!({})] {
                r[field]=invalid;
                assert!(parse_request(&r).unwrap_err().to_string().contains("filter must be text"));
            }
        }
    }
    #[test]
    fn limit_uses_checked_conversion_and_preserves_engine_range_ownership() {
        assert_eq!(parse_request(&request()).unwrap().2.limit,sakura_knowledge_runtime::semantic::RetrieveOptions::default().limit);
        for value in [0,1,100,u64::MAX] {
            let mut r=request();r["limit"]=json!(value);
            match usize::try_from(value) {
                Ok(expected)=>assert_eq!(parse_request(&r).unwrap().2.limit,expected),
                Err(_)=>assert!(parse_request(&r).is_err()),
            }
        }
        for invalid in [Value::Null,json!(-1),json!(1.5),json!(true),json!("1"),json!([]),json!({})] {
            let mut r=request();r["limit"]=invalid;assert!(parse_request(&r).is_err());
        }
    }
}

#[cfg(not(feature = "semantic"))]
fn main() { eprintln!("semantic_pilot requires --features semantic"); std::process::exit(2); }
