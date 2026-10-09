//! Resident semantic JSONL driver; both entry modes share lifecycle/error semantics.
#[cfg(feature = "semantic")]
fn main() -> std::process::ExitCode {
    use sakura_knowledge_runtime::resident::{run_native_resident, ResidentEngine};
    use sakura_knowledge_runtime::semantic::Result;
    use std::process::ExitCode;
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 {
        eprintln!("Usage: semantic_pilot BASE_DB PACK_MANIFEST | --config CONFIG (resident JSONL stdin)");
        return ExitCode::from(2);
    }
    let engine: Result<Box<dyn ResidentEngine>> = if args[0] == "--config" {
        sakura_knowledge_runtime::modular::ModularSemantic::open(
            std::path::Path::new(&args[1]), &[],
        ).map(|engine| Box::new(engine) as Box<dyn ResidentEngine>)
    } else {
        sakura_knowledge_runtime::semantic::SemanticEngine::open(&args[0], &args[1])
            .map(|engine| Box::new(engine) as Box<dyn ResidentEngine>)
    };
    let mut engine = match engine {
        Ok(engine) => engine,
        Err(error) => {
            // Cold initialization is separate from a completed request deadline.
            eprintln!("{}", serde_json::json!({"error":"InitializationError","message":error.to_string()}));
            return ExitCode::from(1);
        }
    };
    let input = std::io::stdin();
    let output = std::io::stdout();
    match run_native_resident(engine.as_mut(), input.lock(), &mut output.lock()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(_) => {
            // Result-returning main would print again after the watchdog was
            // dropped. Do not touch either pipe or cleanup on runtime fatal exit.
            sakura_knowledge_runtime::request_deadline::terminate_current_process_with_code(1)
        }
    }
}
#[cfg(not(feature = "semantic"))]
fn main() { eprintln!("semantic_pilot requires --features semantic"); std::process::exit(2); }
