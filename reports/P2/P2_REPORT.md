# P2 Report — Rust read-only runtime and contract hardening

## Current b7547a A-C repair: READY_FOR_REVIEW / WAITING_REVIEW

New delivery: [`review-b754-delivery.json`](review-b754-delivery.json).
Per-finding implementation/test IDs/receipts: [`review-b754-findings.md`](review-b754-findings.md).
Prior b7547a review was CHANGES_REQUIRED for A-C; no aggregate PASS substitutes
for the new independent scalar/inspect cases. External approval remains NOT_RUN.

Reference/implementation/clean artifact source `42fa24810040349d05c0f8f0e10f9c7b3363e0b7`;
evidence commit `74ebf585101150f5a714319d6a2082bf99665de4`. Final binding hashes24
exact committed Git blobs, separately recording checkout bytes. Source runtime
is unchanged after clean builds; artifacts are new local-only files.

- A: local bounded parse_int never converts more than20characters; no global digits
  guard changes.5001digit± projected/ignored fixtures preserve raw and identity.
- B: finite float projected values, not raw lexeme lengths, receive byte budgets;
  overflow null/truncated/present, invalid JSON constants rejected. Raw unchanged.
- C: every outer successful Rust public response, including inspect, passes total
  cap; oversized snapshot identity fails explicitly without truncation or panic.
- Correct baseline13FAIL/4PASS; after17PASS. First fixture run is retained FAIL but
  explicitly invalid defect evidence because writer checkpoint was missing.
- Final pytest167/Rust5; all seven check exits0. Formal151=135fullvalue+16error,
  no retries/timeouts,604 raw streams verified.10 A-C source-external artifact pairs
  plus8 frozen-source CLI pairs pass; collector command exits0 with explicit UTF-8.
- Performance960/960 measured+32fixed excluded warmups;496 JSON pairs/996rawhashes.
  S18 p50/p95 seconds: reused Python0.3141/0.3933, Rust0.2405/0.2851;
  independent CLI Python0.3451/0.3646, Rust0.2187/0.2317, each30/30 successful.
  Inner5s, CLI outer15s, reused whole-batch600s unchanged. No retries; failures
  would remain in attempted counts. RSS sampled, no disk-cold/universal-speedup claim.
- Final snapshot21516320768bytes SHA256
  `4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073` unchanged.

No old receipt/raw/P1/main edits, no R4 reopening, no Pool/P3/live refresh. Existing
Linux/Pi/full human facts/dbstat/Pool/live NOT_RUN unchanged. Final submission SHA
is supplied after normal push/independent ls-remote verification, not self-embedded.

## Historical f99a115 nine-finding repair — b7547a review required A-C follow-up

Delivery: [`review-f99-delivery.json`](review-f99-delivery.json).
Independent per-finding test IDs and implementation: [`review-f99-nine-findings.md`](review-f99-nine-findings.md).
The prior f99a115 review was CHANGES_REQUIRED/NOT_READY. This is a new fixed-source
repair submission, not an assertion that external review is now approved.

Implementation/reference/artifact source: `5305e48bcc0f7d794bc21155cb834033256911d4`.
Evidence commit: `1d5954fb233a63ef01f39ab0cd16def1f45399ce`.
`review-f99-final-binding.json` hashes25 exact Git blobs at that commit and separately
records checkout bytes. `review-f99-historical-binding.json` corrects the old index's
24/26 committed-byte mismatch without changing historical receipts or artifacts.

| Gate | New evidence |
|---|---|
| Failure-first |24 failed/5 passed on original runtime; each of findings1–8 has concrete regression; finding9 has byte-index counterexample |
| Final checks |150 pytest with Rust enabled,5 Rust tests; seven commands exit0 |
| Formal parity |151 PASS=135 full-value pairs+16error contracts; zero retries/timeouts;604 raw streams verified |
| Dual-mode performance |960/960 measured success,32fixed excluded warmups;496 JSON pairs/996raw streams verified |
| Artifacts |Clean source builds; fresh offline wheel install;8 external-source paired CLI plus real a・b and control-whitespace queries pass |
| Snapshot |21,516,320,768bytes; SHA2564c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073 unchanged |

S18 p50/p95 seconds (30/30 successful attempts per runtime/mode):

| Mode | Python | Rust |
|---|---|---|
| Reused object/connection |0.3036 / 0.3388 |0.2427 / 0.2780 |
| Independent CLI |0.3572 / 0.4696 |0.2217 / 0.2400 |

Fixed warmups, no retries, all attempted failures counted (none in this new run).
Inner5s remains unchanged; outerCLI15s and reused entire batch600s are distinct.
Exact argv/raw/RSS/timing are in review-f99-perf-v1.json; RSS is sampled, no disk-cold
or universal-speedup claim. Historical failed performance rounds remain unchanged.

The optional real-query counterexample collector wrote complete exit0 UTF-8 child
receipts, then its final console print failed in the orchestration interpreter's
GBK encoding. That print failure is retained as a limitation in delivery; a separate
read-back verified all raw hashes and both full JSON pairs. It was not a CLI failure
and was not relabeled as a successful collector command.

R4 not reopened. No snapshot/index rebuild, P1 changes, main merge, Pool/P3 or live
refresh. New artifacts remain local-only. Linux/Pi/full human facts/dbstat/Pool/live
refresh NOT_RUN. Final submission SHA is reported after independent normal-push
verification; no self-referential SHA is embedded here.

## Historical bd99b7a directed repair — superseded by CHANGES_REQUIRED review

Authoritative new delivery: [`repair-bd99b7a-delivery.json`](repair-bd99b7a-delivery.json).
External acceptance remains NOT_RUN; do not merge main or start P3.

Final Python/Rust implementation `199af7595fa60a5af9d8e5daa9fc80be1e382d5d`;
clean build source `eac2c9685e81ab33c0ff1390dfc29ae179456611`.
Submission/origin SHA is independently verified after push, not embedded
self-referentially into this report. New artifact paths and hashes are in
`repair-bd99b7a-artifact-manifest.json`; binaries remain local-only.

| Gate | Actual evidence/result |
|---|---|
| Harness | Independent status, no retries, timeout/partial cannot PASS; 17 tests |
| R1 | Lightweight rank/ID selection, selected text only, exact skip, unified deadline; EXPLAIN and before/after receipts |
| R2 | Complete generated Unicode16 casefold; direct tokens/MATCH + nonempty FTS fixture |
| R3 | Introduction does not query tags; original ambiguity first; literal punctuation |
| R4 | Actual adapter separates source coverage, dataset membership and partition; sample_count null; frozen bounded audit + build fixture |
| R5 | Per-source field observations cite actual evidence; null/empty/missing and conflicts retained; explicit bounds |
| R6 | Actual versions/schema/FTS/JSON gates; fail closes; no implicit snapshot writes |
| Full parity | v3 **151/151: 135 value comparisons + 16 expected-error contracts**, zero retries/timeouts |
| Checks | pytest **108**, Rust **4**, ruff/diff/fmt/clippy/release all exit0 |
| Performance | v2 **960/960 measured successes**, 32 excluded warmups; 496 paired full JSON outputs; all 996 raw stream hashes verified |
| Artifact CLI | Fresh offline wheel installation; source-external 8 paired full JSON responses + help/validation errors; measured UTF-8 |
| Snapshot | Post-validation SHA unchanged, 21,516,320,768 bytes |

S18 measured p50/p95 (seconds), 30 attempts per cell, all successful:

| Mode | Python | Rust |
|---|---|---|
| Reused object/connection API | 0.3281 / 0.3937 | 0.2581 / 0.2860 |
| Independent CLI | 0.3650 / 0.4022 | 0.2274 / 0.2628 |

No claim of a universal speedup: some tiny reused-connection operations are slower
in Rust. Independent process runs are not disk-cold. RSS is a sampled observed
maximum, not a precise allocation measurement.

**Failures retained:** repaired formal v1 148/151 and v2 150/151 FAIL; v3 follows
actual query-plan/CLI/inspect fixes. Perf v1 FAIL is preserved: the measurement
script used Rust's `--topk` for Python, whose CLI uses `--limit`. Perf v2 is a new
complete fixed-script run, not filtered retries. Older P2 v1–v6/raw also unchanged.

**Boundaries:** fixture success is not human source-fact verification. Common-tag
membership behavior is synthetic because the audited frozen common table is empty.
Legacy snapshot frequency is not relabeled as sample_count. No full snapshot
rebuild, index change, upstream refresh, P1 modification, main merge or Pool/P3 work.
Linux runtime, Pi integration, full human review, dbstat scan and Pool integration
remain NOT_RUN. Unicode acceptance is tested on CPython3.14/UCD16, not all Python versions.

## Historical submission below — superseded, retained for traceability

Historical status: `P2 A/B/C DONE + review remediation — WAITING_REVIEW`.
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
