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
const MAX_RESPONSE_BYTES: usize = 524288;

#[cfg(feature = "semantic")]
#[derive(Default)]
struct BoundedJson {
    bytes: Vec<u8>,
    total: usize,
}
#[cfg(feature = "semantic")]
impl std::io::Write for BoundedJson {
    fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
        self.total = self.total.checked_add(data.len()).ok_or(std::io::ErrorKind::InvalidData)?;
        let room = (MAX_RESPONSE_BYTES - 1).saturating_sub(self.bytes.len());
        self.bytes.extend_from_slice(&data[..room.min(data.len())]);
        Ok(data.len())
    }
    fn flush(&mut self) -> std::io::Result<()> { Ok(()) }
}
#[cfg(feature = "semantic")]
fn send_response(output: &mut impl std::io::Write, value: &serde_json::Value, case_id: &str, retrieval_ms: f64) -> semantic::Result<()> {
    use std::time::Instant;
    let start = Instant::now();
    let mut buffer = BoundedJson::default();
    if let Err(error) = serde_json::to_writer(&mut buffer,value) {
        eprintln!("{}",serde_json::json!({"case_id":case_id,"phase":"serialization","error":error.to_string(),"serialize_ms":start.elapsed().as_secs_f64()*1000.0}));
        return Err(error.into());
    }
    let total_bytes = buffer.total + 1; // UTF-8 serialized bytes plus JSONL newline.
    let serialize_ms = start.elapsed().as_secs_f64()*1000.0;
    let oversized = total_bytes > MAX_RESPONSE_BYTES;
    if oversized {
        buffer.bytes = serde_json::to_vec(&serde_json::json!({"case_id":case_id,"status":"FAIL","error":"response_too_large","retries":0,"response_bytes":total_bytes,"limit_bytes":MAX_RESPONSE_BYTES}))?;
        if buffer.bytes.len()+1 > MAX_RESPONSE_BYTES { return Err("failure envelope too large".into()); }
    }
    buffer.bytes.push(b'\n');
    let start = Instant::now();
    if let Err(error) = output.write_all(&buffer.bytes).and_then(|_|output.flush()) {
        eprintln!("{}",serde_json::json!({"case_id":case_id,"phase":"transmission","error":error.to_string(),"transmit_ms":start.elapsed().as_secs_f64()*1000.0}));
        return Err(error.into());
    }
    let transmit_ms = start.elapsed().as_secs_f64()*1000.0;
    eprintln!("{}",serde_json::json!({"case_id":case_id,"retrieval_ms":retrieval_ms,"serialize_ms":serialize_ms,"transmit_ms":transmit_ms,"response_bytes":total_bytes,"sent_bytes":buffer.bytes.len(),"response_too_large":oversized}));
    Ok(())
}

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
        let started = std::time::Instant::now();
        match engine.retrieve(query, &options) {
            Ok(mut result) => {
                result["case_id"] = json!(case_id);
                send_response(&mut output,&result,case_id,started.elapsed().as_secs_f64()*1000.0)?;
            }
            Err(error) => {
                send_response(&mut output,&json!({"case_id":case_id,"status":"FAIL","error":error.to_string(),"retries":0}),case_id,started.elapsed().as_secs_f64()*1000.0)?;
                return Err(error);
            }
        }
    }
    Ok(())
}

#[cfg(all(test, feature = "semantic"))]
mod tests {
    use super::*;
    #[test]
    fn utf8_newline_boundary_and_oversize_are_complete_envelopes() {
        let mut output=Vec::new();
        let mut value=serde_json::json!({"case_id":"tiny","status":"PASS","text":""});
        let overhead=serde_json::to_vec(&value).unwrap().len()+1;
        value["text"]=serde_json::json!("x".repeat(MAX_RESPONSE_BYTES-overhead));
        send_response(&mut output,&value,"tiny",1.0).unwrap();
        assert_eq!(output.len(),MAX_RESPONSE_BYTES);
        assert_eq!(output.last(),Some(&b'\n'));
        output.clear();value["text"]=serde_json::json!("日".repeat(MAX_RESPONSE_BYTES));
        let total=serde_json::to_vec(&value).unwrap().len()+1;
        send_response(&mut output,&value,"tiny",1.0).unwrap();
        let failed:serde_json::Value=serde_json::from_slice(&output).unwrap();
        assert_eq!(failed["error"],"response_too_large");
        assert_eq!(failed["response_bytes"],total);
        assert!(output.len()<MAX_RESPONSE_BYTES);
    }
}

#[cfg(not(feature = "semantic"))]
fn main() {
    eprintln!("semantic_pilot requires --features semantic");
    std::process::exit(2);
}
