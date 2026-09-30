//! Sequential requests, one Runtime/connection. One JSON request per line.
//! Each result includes actual API and serialization time; not CLI startup.
use sakura_knowledge_runtime::Runtime;
use serde_json::{json, Value};
use std::io::{self, BufRead};
use std::time::Instant;

fn main() {
    let db = std::env::args().nth(1).expect("DB");
    let started = Instant::now();
    let mut rt = Runtime::open(db).unwrap();
    let open_s = started.elapsed().as_secs_f64();
    for line in io::stdin().lock().lines() {
        let request: Value = serde_json::from_str(&line.unwrap()).unwrap();
        let q = request["query"].as_str().unwrap();
        let start = Instant::now();
        let result = match request["op"].as_str().unwrap() {
            "lookup" => rt.lookup(q, None, None),
            "search" => rt.search(q, 10, None, None),
            "ask" => rt.ask(q, None, None, None),
            _ => panic!("invalid workload"),
        };
        let api_s = start.elapsed().as_secs_f64();
        let start = Instant::now();
        match result {
            Ok(v) => {
                let output = serde_json::to_string(&v).unwrap();
                let serialization_s = start.elapsed().as_secs_f64();
                println!(
                    "{}",
                    json!({"api_s":api_s,"serialization_s":serialization_s,
                    "open_s":open_s,"output":output,"exit":0})
                );
            }
            Err(e) => println!(
                "{}",
                json!({"api_s":api_s,"open_s":open_s,"error":e.to_string(),"exit":2})
            ),
        }
    }
}
