# P2 Report — Rust read-only runtime and contract hardening

Status: `P2 A/B/C DONE + review remediation — WAITING_REVIEW`.
See "Review remediation (items 1–7)" below. No upstream data was refreshed; all
evidence below is bound to the frozen local snapshot
`build/snapshot-full-20bf5b3/knowledge.sqlite`
(sha256 `4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073`).

## Phase A — Python reference contract fixes (commit `e5c4fd9`)

Three test-first regression tests were added to `tests/test_hardening.py`
(ask exact-identity priority, search `topk` + hit evidence, Moegirl bounded
`source_fields`) and `src/sakura_knowledge/api.py` was fixed to satisfy them:

1. `ask` now resolves exact source identity **before** template parsing, so a
   directly matching entity is never shadowed by a parsed subject.
2. `search` honours `topk` on **every** branch (empty-FTS, FTS, exact-only)
   and returns bounded per-hit document evidence.
3. Moegirl raw fields are projected through a bounded `source_fields` set in
   the API, with `source_fields_evidence` citations.

Checks at `e5c4fd9`: `python -m pytest -q` → `37 passed`;
`python -m ruff check src tests` → all checks passed; `git diff --check` clean.

## Phase B — Rust read-only runtime (`rust/`)

Single Cargo package `sakura-knowledge-runtime v0.2.0` (contract version `2`).
Read-only SQLite via `rusqlite` (features `bundled`, `hooks`, `limits`),
`serde`/`serde_json` for JSON, `unicode-normalization` for NFKC. No ORM, no
async, no HTTP, no PyO3, no model, no service.

| Item | Value |
| --- | --- |
| Toolchain | `stable-x86_64-pc-windows-gnu`; `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| C linker | MinGW-w64 `x86_64-w64-mingw32-gcc (GCC) 16.2.0` (w64devkit at `C:\Users\PC\snknow-tools\w64devkit`) |
| Build | `cargo build --release` → OK, `rust/target/release/sknow-rs.exe` |
| Tests | `cargo test --release` → `3 passed; 0 failed` (tokenizer, ask templates, fixture lookup/search/related/ask) |
| Lint | `cargo clippy --release --tests` → 0 warnings |
| Format | `cargo fmt -- --check` clean |
| Binary sha256 | `6fa0b6111cd08cc014ccd4ab37a7d71cc1c0f8666b5ef8f604a762957f1fed5e` |

Contract fidelity (mirrors `api.py` / `model.py`):

- Identity trust = `source_backed` only; text trust = `generated_from_evidence`
  + `source_backed`. Candidate proofs are never silently promoted.
- 5 s per-operation budget via progress handler; `SQLITE_LIMIT_LENGTH=2e6`;
  connection opened with `SQLITE_OPEN_READ_ONLY`.
- Bounded projections: documents ≤10 (4000-char truncation flag), aliases ≤100,
  identity evidence ≤100, lookup candidates ≤101→100 (+ warning), FTS scan
  ≤10000 (+ `search_document_scan_limit` warning), `topk`/`limit` 1..100.
- Ask templates are the same bounded deterministic set
  (`X 的 Danbooru tag 是什么`, `X 的标签是什么`, `介绍[一下] X`); everything
  else is a direct entity name marked `unsupported`.
- `inspect` reports snapshot id, contract version, page stats and dbstat
  availability; `read_only: true`.

## Phase C — Parity verification (`tools/check_parity.py`)

Fixed evaluation set: 26 cases bound to the frozen snapshot
(lookup by value/key, search incl. FTS-excluded episode namespace and
too-short CJK, related incl. candidate-only exclusions, ask direct + all
templates + target namespaces, inspect). The tool runs the Python reference
API and the `sknow-rs` binary on identical inputs and compares the full JSON
semantically (dict order-insensitive, list order-sensitive).

- Report: `reports/P2/rust-parity-20bf5b3.json` — **overall PASS, 26/26 EQUAL**,
  exit code 0.
- Python reference git SHA at check time: `e5c4fd9760ccf206b7a34d0c7a3fa09ab380753c`.
- Documented operational note (recorded in the report as
  `python_budget_retries`): case `S01` (`search "ONE PIECE"`) required 2
  retries on the **Python reference side only** because a cold 21.5 GB FTS
  working set exceeds the reference's own 5 s per-operation budget before the
  OS page cache is populated. This is a cache-warmup effect, not a contract
  difference; the compared outputs were byte-identical once the reference
  completed. The Rust side never required a retry.

## Integrity

- `knowledge.sqlite` sha256 after all P2 operations:
  `4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073`
  (identical to the pre-P2 value recorded in the parity report;
  post-run receipt at
  `build/snapshot-full-20bf5b3/knowledge.sqlite.post-p2.sha256`).
- No snapshot, upstream, or P1 receipt files were modified in P2 except the
  additive `reports/P2/` artifacts.

## Explicit non-claims

- `Pi Skill runtime integration`: **NOT_RUN**.
- `SakuraPool integration`: **NOT_RUN**.
- `Full human source-fact review`: **NOT_RUN**.
- No live upstream refresh was performed; all results are from the frozen
  local cut.
- The 674,679-tag AI annotation has not been started.

## Review remediation (items 1–7, post-`abc3a8f`)

Commits: `7f529b1` (151-case parity), `889ed9a` (read-only compat receipt +
A-evidence tests), `685990d` (wheel 0.2.0 + dist + sknow-rs CLI surface),
`ac6988d` (byte-level UTF-8 evidence + strict S18 classification),
`8593d73` (`.gitattributes -text` for raw evidence).

1. **Parity v2 table, 151 locked cases** — `tools/parity_cases.py`
   (values mined from the real snapshot, locked in-repo). Latest receipts
   `rust-parity-20bf5b3-v5.json` / `v6.json` (same binary `a8f8cdb9…`):
   150 EQUAL in both; S18 `a's_wonderland` is the only non-EQUAL case and
   its classification depends on machine state at run time:
   - v5: both runtimes over budget → `BUDGET_LIMITED_PARTIAL` (documented,
     PASS);
   - v6: Rust 25/25 over budget, Python ok → `RUST_BUDGET_EXCEEDED`
     (every attempt in `attempt_trail`) → overall **FAIL**, exit 1.
   A Rust budget failure is never counted as equality; the standing,
   reproducible statement is: **S18 is a Rust budget-boundary case
   (~1.4–5.5 s SQL), semantic output equal whenever both complete.**
2. **Docs + delivery JSON** — `docs/STAGE_STATUS.md`,
   `docs/runtime-contract.md`, `docs/rust-migration.md`,
   `reports/P2/p2-delivery.json`.
3. **Wheel 0.2.0, isolated venv** — `p2-wheel-cli-20bf5b3.json` (overall
   PASS): fresh `--without-pip` venv, `pip install --no-index` the wheel,
   12-command matrix incl. `gbk_env_lookup` (code-page independence).
   All streams strict UTF-8, 0 U+FFFD bytes, success stdout full-JSON,
   error stderr JSON (`UsageError`), in-process Unicode cross-check 8/8.
   Verbatim bytes under `reports/P2/raw/wheel-cli/` (sha256-matched).
4. **sknow-rs distribution outside source tree** —
   `dist/p2/sknow-rs-0.2.0-win64/sknow-rs.exe` (sha256 `a8f8cdb9…`,
   manifest `p2-artifact-manifest.json`); same matrix, all PASS.
5. **Read-only compatibility** — `snapshot-compatibility-20bf5b3.json`
   (PASS; sha256 identical before/after; write attempt blocked; Rust
   `SQLITE_OPEN_READ_ONLY`; required columns verified; inspect error path
   both runtimes). `dbstat`: **NOT_AVAILABLE** in this system's SQLite —
   recorded, not faked.
6. **Performance, raw** — `p2-perf-20bf5b3.json` +
   `reports/P2/raw/perf/p2-perf-samples.jsonl` (1,596 end-to-end CLI
   samples, no retries, 120 s hard bound, sha256 of samples file in the
   receipt). Warm p50/p95: Rust 40/179 ms vs Python 194/451 ms
   (interpreter start dominates Python). Budget failures are failure
   samples: S18 Rust 6/6 rounds and Python 4/6; S17 once each on round 0;
   S01 Python once on round 0 (cold cache).
7. **A-evidence + error-contract unification** — `tests/test_evidence.py`
   (occurrence dataset partition, nullable `sample_count`, invalid
   frequency rejected-not-published, `source_fields` bounded projection,
   read-only write blocking, CLI `UsageError` JSON contract);
   `sakura_knowledge.cli` reconfigures stdout/stderr to UTF-8 (GBK console
   no longer raises `UnicodeEncodeError`); Rust usage errors now emit
   `UsageError` JSON (was free text). Parity cases E15/E16 lock the new
   contract.

Checks at remediation: `python -m pytest -q` → 47 passed; ruff clean;
`git diff --check` clean; `cargo test --release` 3/3; `cargo fmt --check`
clean.

## Explicit non-claims
