# Rust Migration (sknow-rs)

Status: **runtime + CLI port is functional and parity-checked; not
declared complete** — see `STAGE_STATUS.md` for the stage matrix.

## What exists

- `rust/` — `sakura-knowledge-runtime v0.2.0` (lib) + `sknow-rs` (bin).
  Dependencies: rusqlite (bundled SQLite), serde/serde_json. No models,
  no services, no writes.
- Toolchain of record: rustc/cargo 1.98.1 stable-x86_64-pc-windows-gnu,
  GCC 16.2.0 (w64devkit) as linker.
- Release binary for the current dev HEAD: sha256 `a8f8cdb9f83e43ca…`
  (`reports/P2/p2-artifact-manifest.json`).

## Port fidelity

- `Runtime::open` uses `OpenFlags::SQLITE_OPEN_READ_ONLY`; non-snapshot
  files raise `not a SakuraKnowledge snapshot` (both runtimes tested:
  `reports/P2/snapshot-compatibility-20bf5b3.json` `inspect_error_path`).
- Ask-template parser is a byte-level port of the Python regexes
  (`_ASK_DANBOORU`, `_ASK_TAG`, `_ASK_INTRODUCE`), including greedy
  backtracking order; cross-checked on 50 mined inputs at A-phase, and
  re-covered by the 42 ask cases in the 151-case table.
- `EntryKey` validation mirrors `model.py` for `lookup --key` and
  `related`.
- Error text and exit codes mirror the Python CLI (see
  `runtime-contract.md`), including `UsageError` JSON for malformed
  commands (fixed in this remediation: before, Rust printed free-text
  usage and Python printed argparse text).

## Parity status (honest)

- 151 locked cases: 150 EQUAL; **S18 `a's_wonderland` is a standing Rust
  budget failure** (SQL ~1.4–5.5 s; hits the 5 s CLI budget on loaded
  machines). Latest receipt `rust-parity-20bf5b3-v6.json` reports it as
  `RUST_BUDGET_EXCEEDED`, overall FAIL. This is a performance defect of
  the Rust search path on that token, **not** a semantic mismatch, and it
  is not waved through.
- Candidate fix (not yet done): the Rust search rescans candidate rows
  without the Python planner's early-termination hints for CJK bigram
  queries; profile before optimizing.

## Known differences (accepted, documented)

- `related` legacy 4-positional form exists only in sknow-rs; the Python
  form (`DB VALUE --kind K --namespace N`) works in both.
- Rust `inspect` output field order may differ; value equality is what
  parity compares.
- Windows process start: Rust ~40 ms, Python ~190 ms (interpreter start),
  see `reports/P2/p2-perf-20bf5b3.json`.

## NOT ported (by design, not forgotten)

- `build` / `verify` / `sources check` (Python-only in baseline; the
  snapshot is a frozen input to the Rust runtime).
- `check-latest` network refresh (explicit opt-in, out of the offline
  core).
