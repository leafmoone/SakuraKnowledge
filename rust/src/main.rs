//! sknow-rs CLI: read-only query surface over a published snapshot.

use sakura_knowledge_runtime::{Error, Runtime};
use std::path::PathBuf;
use std::process::ExitCode;

struct Opt {
    kind: Option<String>,
    namespace: Option<String>,
    relation: Option<String>,
    limit: u32,
    topk: u32,
    key: bool,
    target: Option<String>,
}

fn usage() -> ExitCode {
    eprintln!("usage: sknow-rs lookup DB QUERY [--kind K --namespace N] [--key]");
    eprintln!("       sknow-rs search DB QUERY [--topk N --kind K --namespace N]");
    eprintln!("       sknow-rs related DB KIND NAMESPACE VALUE [--relation R --kind K --limit N]");
    eprintln!("       sknow-rs ask DB QUERY [--kind K --namespace N --target-tag-namespace T]");
    eprintln!("       sknow-rs inspect DB");
    eprintln!("       sknow-rs runtime");
    ExitCode::from(2)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        return usage();
    }
    let cmd = args[0].clone();
    let rest: Vec<String> = args[1..].to_vec();
    let mut opt = Opt {
        kind: None,
        namespace: None,
        relation: None,
        limit: 20,
        topk: 20,
        key: false,
        target: None,
    };
    let mut pos: Vec<String> = Vec::new();
    let mut i = 0usize;
    while i < rest.len() {
        let a = rest[i].clone();
        match a.as_str() {
            "--kind" => match rest.get(i + 1) {
                Some(v) => {
                    opt.kind = Some(v.clone());
                    i += 1;
                }
                None => return usage(),
            },
            "--namespace" => match rest.get(i + 1) {
                Some(v) => {
                    opt.namespace = Some(v.clone());
                    i += 1;
                }
                None => return usage(),
            },
            "--relation" => match rest.get(i + 1) {
                Some(v) => {
                    opt.relation = Some(v.clone());
                    i += 1;
                }
                None => return usage(),
            },
            "--limit" => match rest.get(i + 1).and_then(|v| v.parse().ok()) {
                Some(v) => {
                    opt.limit = v;
                    i += 1;
                }
                None => return usage(),
            },
            "--topk" => match rest.get(i + 1).and_then(|v| v.parse().ok()) {
                Some(v) => {
                    opt.topk = v;
                    i += 1;
                }
                None => return usage(),
            },
            "--key" => opt.key = true,
            "--target-tag-namespace" => match rest.get(i + 1) {
                Some(v) => {
                    opt.target = Some(v.clone());
                    i += 1;
                }
                None => return usage(),
            },
            _ if a.starts_with("--") => return usage(),
            _ => pos.push(a),
        }
        i += 1;
    }

    let result: Result<serde_json::Value, Error> = (|| match cmd.as_str() {
        "lookup" => {
            let (db, query) = two_pos(&pos)?;
            let mut rt = Runtime::open(db)?;
            if opt.key {
                match (opt.kind.clone(), opt.namespace.clone()) {
                    (Some(k), Some(n)) => Ok(rt.lookup_key(&k, &n, query)?),
                    _ => Err(Error::Invalid(
                        "exact key requires --kind and --namespace".into(),
                    )),
                }
            } else {
                Ok(rt.lookup(query, opt.kind.as_deref(), opt.namespace.as_deref())?)
            }
        }
        "search" => {
            let (db, query) = two_pos(&pos)?;
            let mut rt = Runtime::open(db)?;
            Ok(rt.search(
                query,
                opt.topk,
                opt.kind.as_deref(),
                opt.namespace.as_deref(),
            )?)
        }
        "related" => {
            if pos.len() < 4 {
                return Err(Error::Invalid(
                    "related requires KIND NAMESPACE VALUE".into(),
                ));
            }
            let mut rt = Runtime::open(pos[0].clone())?;
            Ok(rt.related(
                &pos[1],
                &pos[2],
                &pos[3],
                opt.relation.as_deref(),
                opt.kind.as_deref(),
                opt.limit,
            )?)
        }
        "ask" => {
            let (db, query) = two_pos(&pos)?;
            let mut rt = Runtime::open(db)?;
            Ok(rt.ask(
                query,
                opt.kind.as_deref(),
                opt.namespace.as_deref(),
                opt.target.as_deref(),
            )?)
        }
        "inspect" => {
            if pos.is_empty() {
                return Err(Error::Invalid("database required".into()));
            }
            let mut rt = Runtime::open(pos[0].clone())?;
            Ok(rt.inspect()?)
        }
        "runtime" => Ok(Runtime::runtime_info()),
        _ => Err(Error::Invalid("unknown command".into())),
    })();

    match result {
        Ok(v) => {
            println!("{}", serde_json::to_string(&v).unwrap());
            ExitCode::SUCCESS
        }
        Err(e) => {
            // Mirror the Python CLI contract: {"error": "<ExceptionType>",
            // "message": "..."} on stderr, exit code 2.
            let (typ, message) = match &e {
                Error::Invalid(m) => ("ValueError", m.clone()),
                Error::Budget => ("ValueError", "query_budget_exceeded".to_string()),
                Error::Sql(rusqlite::Error::SqliteFailure(_, Some(m))) => {
                    ("OperationalError", m.clone())
                }
                Error::Sql(other) => ("OperationalError", format!("SQLite error: {other}")),
            };
            eprintln!("{}", serde_json::json!({"error": typ, "message": message}));
            ExitCode::from(2)
        }
    }
}

fn two_pos(pos: &[String]) -> Result<(&String, &str), Error> {
    match (pos.first(), pos.get(1)) {
        (Some(d), Some(q)) => Ok((d, q.as_str())),
        _ => Err(Error::Invalid("database and query are required".into())),
    }
}

#[allow(dead_code)]
fn _unused_path() -> PathBuf {
    PathBuf::new()
}
