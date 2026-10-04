//! sknow-rs CLI: read-only query surface over a published snapshot.

use sakura_knowledge_runtime::{Error, Runtime, TagOptions};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::{Duration, Instant};

struct Opt {
    kind: Option<String>,
    namespace: Option<String>,
    relation: Option<String>,
    limit: u32,
    limit_given: bool,
    topk: u32,
    key: bool,
    target: Option<String>,
    category: Option<i64>,
    direction: String,
}

const USAGE: &str = "usage: sknow-rs lookup DB QUERY [--kind K --namespace N] [--key]
       sknow-rs search DB QUERY [--limit N | --topk N] [--kind K --namespace N]
       sknow-rs related DB VALUE --kind K --namespace N [--relation R --limit N --direction out|in]
       sknow-rs related DB KIND NAMESPACE VALUE [--relation R --kind DSTKIND --limit N]
       sknow-rs ask DB QUERY [--kind K --namespace N --target-tag-namespace T]
       sknow-rs resolve-tag DB QUERY [--target-namespace T --category N --kind K --namespace N --key --limit N]
       sknow-rs retrieve BASE_DB PACK_MANIFEST QUERY [--limit N --kind K --namespace N]
         Requires build --features semantic; example: retrieve knowledge.sqlite manifest.json \"blue hair\"
       sknow-rs inspect DB
       sknow-rs runtime
       sknow-rs -h | --help";

/// Usage errors follow the same contract as the Python CLI:
/// {"error": "UsageError", "message": "..."} on stderr, empty stdout, exit 2.
fn usage_error(message: &str) -> ExitCode {
    eprintln!(
        "{}",
        serde_json::json!({"error": "UsageError", "message": format!("sknow-rs: {message}")})
    );
    ExitCode::from(2)
}

#[cfg(feature = "semantic")]
fn semantic_retrieve(args: &[String]) -> ExitCode {
    use sakura_knowledge_runtime::semantic::{RetrieveOptions, SemanticEngine};
    if args.len() < 3 {
        return usage_error("retrieve requires BASE_DB PACK QUERY");
    }
    let mut options = RetrieveOptions::default();
    let mut i = 3;
    while i < args.len() {
        if i + 1 >= args.len() {
            return usage_error("missing retrieve option value");
        }
        match args[i].as_str() {
            "--limit" => match args[i + 1].parse::<usize>() {
                Ok(n) => options.limit = n,
                Err(_) => return usage_error("invalid retrieve limit"),
            },
            "--kind" => options.kind = Some(args[i + 1].clone()),
            "--namespace" => options.namespace = Some(args[i + 1].clone()),
            _ => return usage_error("unknown retrieve option"),
        }
        i += 2;
    }
    let started = Instant::now();
    let result = SemanticEngine::open(&args[0], &args[1])
        .and_then(|mut engine| engine.retrieve(&args[2], &options));
    match result {
        Ok(value) => {
            match sakura_knowledge_runtime::semantic_jsonl::send_response(&mut std::io::stdout().lock(),&value,"single",started.elapsed().as_secs_f64()*1000.0) {
                Ok(false) => ExitCode::SUCCESS,
                Ok(true) => ExitCode::from(1),
                Err(error) => { eprintln!("{}",serde_json::json!({"error":"SemanticError","message":error.to_string()})); ExitCode::from(1) }
            }
        }
        Err(error) => {
            eprintln!(
                "{}",
                serde_json::json!({"error":"SemanticError","message":error.to_string()})
            );
            ExitCode::from(1)
        }
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        return usage_error("the following arguments are required: command");
    }
    if matches!(args[0].as_str(), "-h" | "--help") {
        println!("{USAGE}");
        return ExitCode::SUCCESS;
    }
    #[cfg(feature = "semantic")]
    if args[0] == "retrieve" {
        return semantic_retrieve(&args[1..]);
    }
    let cmd = args[0].clone();
    let rest: Vec<String> = args[1..].to_vec();
    let mut opt = Opt {
        kind: None,
        namespace: None,
        relation: None,
        limit: 20,
        limit_given: false,
        topk: 20,
        key: false,
        target: None,
        category: None,
        direction: "out".into(),
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
                None => return usage_error(&format!("argument {a}: expected a value")),
            },
            "--namespace" => match rest.get(i + 1) {
                Some(v) => {
                    opt.namespace = Some(v.clone());
                    i += 1;
                }
                None => return usage_error(&format!("argument {a}: expected a value")),
            },
            "--relation" => match rest.get(i + 1) {
                Some(v) => {
                    opt.relation = Some(v.clone());
                    i += 1;
                }
                None => return usage_error(&format!("argument {a}: expected a value")),
            },
            "--limit" => match rest.get(i + 1).and_then(|v| v.parse().ok()) {
                Some(v) => {
                    opt.limit = v;
                    opt.limit_given = true;
                    i += 1;
                }
                None => return usage_error(&format!("argument {a}: expected a value")),
            },
            "--topk" => match rest.get(i + 1).and_then(|v| v.parse().ok()) {
                Some(v) => {
                    opt.topk = v;
                    i += 1;
                }
                None => return usage_error(&format!("argument {a}: expected a value")),
            },
            "--key" => opt.key = true,
            "--direction" if cmd == "related" => match rest.get(i + 1) {
                Some(v) if v == "in" || v == "out" => {
                    opt.direction = v.clone();
                    i += 1;
                }
                _ => return usage_error("direction must be in or out"),
            },
            "--category" if cmd == "resolve-tag" => {
                match rest.get(i + 1).and_then(|v| v.parse().ok()) {
                    Some(v) => {
                        opt.category = Some(v);
                        i += 1;
                    }
                    None => return usage_error(&format!("argument {a}: expected a value")),
                }
            }
            "--target-namespace" if cmd != "resolve-tag" => {
                return usage_error(&format!("unrecognized arguments: {a}"))
            }
            "--target-tag-namespace" | "--target-namespace" => match rest.get(i + 1) {
                Some(v) => {
                    opt.target = Some(v.clone());
                    i += 1;
                }
                None => return usage_error(&format!("argument {a}: expected a value")),
            },
            _ if a.starts_with("--") => {
                return usage_error(&format!("unrecognized arguments: {a}"))
            }
            _ => pos.push(a),
        }
        i += 1;
    }

    const COMMANDS: [&str; 7] = [
        "lookup",
        "search",
        "related",
        "ask",
        "inspect",
        "runtime",
        "resolve-tag",
    ];
    if !COMMANDS.contains(&cmd.as_str()) {
        return usage_error(&format!(
            "argument command: invalid choice: '{cmd}' (choose from {})",
            COMMANDS.map(|c| format!("'{c}'")).join(", ")
        ));
    }
    if matches!(cmd.as_str(), "lookup" | "search" | "ask") && pos.len() < 2 {
        return usage_error("database and query are required");
    }
    let mut profile_error: Option<String> = None;
    let result: Result<serde_json::Value, Error> = (|| match cmd.as_str() {
        "resolve-tag" => {
            let (db, query) = two_pos(&pos)?;
            Runtime::open(db)?.resolve_tag(
                query,
                TagOptions {
                    target_namespace: opt.target.as_deref(),
                    category: opt.category,
                    kind: opt.kind.as_deref(),
                    namespace: opt.namespace.as_deref(),
                    key: opt.key,
                    limit: opt.limit,
                },
            )
        }
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
            // Optional audit sink is reserved before the single query, never overwritten.
            // No directories are created and default CLI stdout/errors remain unchanged.
            let mut sink = match std::env::var_os("SKNOW_SEARCH_PROFILE_OUT") {
                Some(path) => Some(
                    OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(path)
                        .map_err(|e| {
                            Error::Invalid(format!("search profile sink reservation failed: {e}"))
                        })?,
                ),
                None => None,
            };
            let mut rt = Runtime::open(db)?;
            // Python CLI surface: `search --limit N` is the result cap.
            let topk = if opt.limit_given { opt.limit } else { opt.topk };
            let started = Instant::now();
            let result = rt.search(query, topk, opt.kind.as_deref(), opt.namespace.as_deref());
            if let Some(file) = sink.as_mut() {
                let profile = serde_json::json!({
                    "profile": rt.last_search_profile,
                    "query_invocations": 1,
                    "query_elapsed_s": started.elapsed().as_secs_f64(),
                    "query_succeeded": result.is_ok(),
                    "query_error": result.as_ref().err().map(ToString::to_string),
                });
                let written = write_profile(file, &profile);
                if let Err(error) = written {
                    profile_error = Some(format!("search profile write failed: {error}"));
                } else if started.elapsed() > Duration::from_secs(5) {
                    profile_error = Some("search profile exceeded query budget".into());
                }
            }
            result
        }
        "related" => {
            if pos.len() == 2 {
                // Python CLI surface: source key given by --kind/--namespace,
                // VALUE positional; there is no destination-kind filter.
                let (kind, namespace) = match (opt.kind.clone(), opt.namespace.clone()) {
                    (Some(k), Some(n)) => (k, n),
                    _ => {
                        return Err(Error::Invalid(
                            "exact key requires --kind and --namespace".into(),
                        ))
                    }
                };
                let mut rt = Runtime::open(pos[0].clone())?;
                let call = if opt.direction == "in" {
                    Runtime::related_in
                } else {
                    Runtime::related
                };
                return call(
                    &mut rt,
                    &kind,
                    &namespace,
                    &pos[1],
                    opt.relation.as_deref(),
                    None,
                    opt.limit,
                );
            }
            if pos.len() < 4 {
                return Err(Error::Invalid(
                    "related requires KIND NAMESPACE VALUE".into(),
                ));
            }
            let mut rt = Runtime::open(pos[0].clone())?;
            let call = if opt.direction == "in" {
                Runtime::related_in
            } else {
                Runtime::related
            };
            Ok(call(
                &mut rt,
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

    if let Some(message) = &profile_error {
        eprintln!(
            "{}",
            serde_json::json!({"error":"ProfileError", "message":message})
        );
    }
    match result {
        Ok(v) => {
            println!("{}", serde_json::to_string(&v).unwrap());
            if profile_error.is_some() {
                ExitCode::from(2)
            } else {
                ExitCode::SUCCESS
            }
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

fn write_profile(sink: &mut impl Write, profile: &serde_json::Value) -> std::io::Result<()> {
    let bytes = serde_json::to_vec(profile).map_err(std::io::Error::other)?;
    sink.write_all(&bytes)?;
    sink.flush()
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

#[cfg(test)]
mod profile_tests {
    use super::*;

    #[test]
    fn profile_write_failure_is_reported_not_hidden() {
        struct Fail;
        impl Write for Fail {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("injected sink failure"))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        assert!(write_profile(&mut Fail, &serde_json::json!({"query_invocations":1})).is_err());
        let mut bytes = Vec::new();
        write_profile(&mut bytes, &serde_json::json!({"query_invocations":1})).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&bytes).unwrap()["query_invocations"],
            1
        );
    }
}
