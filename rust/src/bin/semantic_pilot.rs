//! Resident semantic JSONL driver; both entry modes share lifecycle/error semantics.
#[cfg(feature = "semantic")]
fn main() -> sakura_knowledge_runtime::semantic::Result<()> {
    use sakura_knowledge_runtime::resident::run_resident;
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 {
        return Err("Usage: semantic_pilot BASE_DB PACK_MANIFEST | --config CONFIG (resident JSONL stdin)".into());
    }
    let input = std::io::stdin();
    let output = std::io::stdout();
    if args[0] == "--config" {
        let mut engine = sakura_knowledge_runtime::modular::ModularSemantic::open(
            std::path::Path::new(&args[1]), &[],
        )?;
        run_resident(&mut engine, input.lock(), &mut output.lock())
    } else {
        let mut engine = sakura_knowledge_runtime::semantic::SemanticEngine::open(&args[0], &args[1])?;
        run_resident(&mut engine, input.lock(), &mut output.lock())
    }
}
#[cfg(not(feature = "semantic"))]
fn main() { eprintln!("semantic_pilot requires --features semantic"); std::process::exit(2); }
