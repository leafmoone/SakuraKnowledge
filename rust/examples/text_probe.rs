//! Build-time validation helper; runtime normalization has no Python dependency.
use sakura_knowledge_runtime::{match_query, tokens, Runtime};
use serde_json::json;
use std::io::{self, BufRead};

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.expect("UTF-8 input");
        let text: String = serde_json::from_str(&line).expect("JSON string");
        let result = match (tokens(&text), match_query(&text)) {
            (Ok(tokens), Ok(compiled)) => json!({"tokens": tokens, "match": compiled}),
            (Err(e), _) | (_, Err(e)) => json!({"error": e.to_string()}),
        };
        println!(
            "{}",
            json!({"result": result, "runtime": Runtime::runtime_info()})
        );
    }
}
