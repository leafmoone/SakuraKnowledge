//! Bounded legacy SQL reproduction for diagnosis, not formal acceptance.
use rusqlite::{params, Connection, OpenFlags};
use sakura_knowledge_runtime::{match_query, Runtime};
use serde_json::json;
use std::time::{Duration, Instant};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let db = std::env::args().nth(1).expect("DB path");
    let sql = include_str!("../../tools/s18_legacy.sql");
    let query = "a's_wonderland";
    let compiled = match_query(query).unwrap();
    let conn = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let mut report = json!({"purpose":"legacy SQL diagnostic, not acceptance", "attempts":1,
        "query":query,"topk":10,"match":compiled,"sql":sql,"sqlite":rusqlite::version()});
    let mut rt = Runtime::open(&db).unwrap();
    let start = Instant::now();
    let exact = rt.lookup(query, None, None).unwrap();
    report["exact_identity_assembly_s"] = json!(start.elapsed().as_secs_f64());
    report["exact_candidates"] = json!(exact["candidates"].as_array().unwrap().len());
    let mut explain = conn.prepare(&format!("EXPLAIN QUERY PLAN {sql}"))?;
    let plan = explain
        .query_map(
            params![compiled, Option::<String>::None, Option::<String>::None],
            |r| {
                Ok(json!([
                    r.get::<_, i64>(0)?,
                    r.get::<_, i64>(1)?,
                    r.get::<_, i64>(2)?,
                    r.get::<_, String>(3)?
                ]))
            },
        )?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    report["explain"] = json!(plan);
    for name in ["page_size", "cache_size", "mmap_size", "temp_store"] {
        let n: i64 = conn.query_row(&format!("PRAGMA {name}"), [], |r| r.get(0))?;
        report["configuration"][name] = json!(n);
    }
    let start = Instant::now();
    conn.progress_handler(1000, Some(move || start.elapsed() > Duration::from_secs(5)));
    let mut scanned = 0;
    let mut body_bytes = 0;
    let mut first = None;
    let mut full_rows = Vec::new();
    let result = (|| -> rusqlite::Result<()> {
        let mut stmt = conn.prepare(sql)?;
        let mut rows = stmt.query(params![
            compiled,
            Option::<String>::None,
            Option::<String>::None
        ])?;
        while let Some(row) = rows.next()? {
            if first.is_none() {
                first = Some(start.elapsed().as_secs_f64());
            }
            let body: String = row.get(6)?;
            body_bytes += body.len();
            full_rows.push((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, f64>(4)?,
                row.get::<_, String>(5)?,
                body,
                row.get::<_, bool>(7)?,
                row.get::<_, String>(8)?,
                row.get::<_, String>(9)?,
            ));
            scanned += 1;
        }
        Ok(())
    })();
    report["fts_execute_sort_first_row_s"] = json!(first);
    report["fts_collect_total_s"] = json!(start.elapsed().as_secs_f64());
    report["rows_materialized"] = json!(scanned);
    report["body_utf8_bytes"] = json!(body_bytes);
    report["fts_status"] = json!(if result.is_ok() { "success" } else { "failure" });
    report["error"] = json!(result.err().map(|e| e.to_string()));
    report["post_fts_assembly"] = json!("NOT_RUN (SQL diagnostic only)");
    println!("{report}");
    Ok(())
}
