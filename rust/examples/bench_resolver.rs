//! Acceptance-only reused-connection runner, not a production service.
use sakura_knowledge_runtime::{Runtime, TagOptions};
use serde_json::{json, Value};
use std::io::{self, BufRead};
use std::time::Instant;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let db = std::env::args().nth(1).ok_or("database required")?;
    let mut runtime = Runtime::open(db).map_err(|e| e.to_string())?;
    for line in io::stdin().lock().lines() {
        let case: Value = serde_json::from_str(&line?)?;
        let query = case["query"].as_str().ok_or("query required")?;
        let started = Instant::now();
        let result = runtime.resolve_tag(
            query,
            TagOptions {
                target_namespace: Some("danbooru.tag"),
                category: case["category"].as_i64(),
                kind: case["kind"].as_str(),
                namespace: case["namespace"].as_str(),
                key: case["exact"].as_bool().unwrap_or(false),
                limit: case["limit"].as_u64().unwrap_or(20) as u32,
            },
        );
        let seconds = started.elapsed().as_secs_f64();
        let out = match result {
            Ok(value) => json!({"case_id":case["id"],"elapsed_s":seconds,"value":value}),
            Err(error) => {
                json!({"case_id":case["id"],"elapsed_s":seconds,"error":error.to_string()})
            }
        };
        println!("{out}");
    }
    Ok(())
}
