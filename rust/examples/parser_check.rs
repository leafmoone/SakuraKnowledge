//! Dev tool: print parse_ask_template output per stdin line (JSON).
use sakura_knowledge_runtime::parse_ask_template;
use std::io::{BufRead, BufReader};

fn main() {
    let stdin = BufReader::new(std::io::stdin());
    for line in stdin.lines() {
        let q = line.unwrap();
        let out = parse_ask_template(&q);
        let j = match out {
            Some((s, m)) => format!(
                "{{\"subject\":{},\"mode\":{}}}",
                serde_json::to_string(&s).unwrap(),
                serde_json::to_string(&m).unwrap()
            ),
            None => "null".to_string(),
        };
        println!("{j}");
    }
}
