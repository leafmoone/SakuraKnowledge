//! One actual runtime search with measured phases and complete JSON output.
use sakura_knowledge_runtime::Runtime;
use serde_json::json;
use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let start = Instant::now();
    let mut rt = Runtime::open(&args[1]).unwrap();
    let open_s = start.elapsed().as_secs_f64();
    let start = Instant::now();
    let result = rt.search("a's_wonderland", 10, None, None);
    let search_s = start.elapsed().as_secs_f64();
    match result {
        Ok(value) => {
            let start = Instant::now();
            let bytes = serde_json::to_vec(&value).unwrap();
            let serialization_s = start.elapsed().as_secs_f64();
            println!(
                "{}",
                json!({"query":"a's_wonderland","topk":10,"open_s":open_s,
                "search_s":search_s,"serialization_s":serialization_s,"response_bytes":bytes.len(),
                "profile":rt.last_search_profile,"value":value,"runtime":Runtime::runtime_info()})
            );
        }
        Err(e) => {
            eprintln!("{}", json!({"error":e.to_string(),"search_s":search_s}));
            std::process::exit(2);
        }
    }
}
