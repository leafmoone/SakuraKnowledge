# Final directed A–I closure — READY_FOR_REVIEW / WAITING_REVIEW

This is a readiness **proposal**, not approval, a main merge, or P4 authorization.
Readiness is under the user's explicit formal-only policy and authorized continuation
with the targeted S02 protection failure disclosed. The fixed-SHA reviewer must assess
that evidence limitation. All receipts are authoritative; historical FAILs stay FAIL.

## Source and immutable scope

- Reviewed STOP baseline: `1badc465c2fdeae8250bba1ef3c1c8f142c42818`.
- PERF_HARNESS_FIX_SHA: `7eb371a95b164fe436c91cc4cb8ed97da90bc06e`.
- Fresh artifact source: `e19d2278f26c12cba28eaff82a6eed2f0cda62cb`.
- Final checked code/tool/test source: `fef485c1b4a9716251ac70606a666e0ca4fbc18d`.
  Later documentation/evidence commits do not become the archive source.
- Runtime `src/` and `rust/` Git blobs remain equal to
  `9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102`; no runtime, compiler/storage,
  Python public API/CLI, query, budget, workload or frozen expected changes.
- Main/P3_BASE: `894dc6a73bfd42f18cc7648e8ab7481aae211ab1`, unchanged.
- No third FULL build, DB overlay/patch, upstream refresh, performance rerun or G42 probe.
  Original/retry1 snapshot build attempts remain total2. All source inputs read-only.

## A / H — frozen bytes and end protection

`final-A-full-hash.json` actually read the complete FULL before this round.
`final-protection-baseline.json` establishes a separately timed current safe read-only
baseline; it does not refreeze expectations or prove an earlier unsaved observation.
`final-protection.json` and command receipt actually streamed all protected bytes at end,
command exit0, 53.4391737s, no SQL/query/write probe:

| Protected artifact | Bytes | SHA256 |
|---|---:|---|
| FULL `build/p3-full-authorized-retry1/knowledge.sqlite` | 21718736896 | `61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9` |
| FULL manifest | 33308 | `373fcb69731db877929c102b75292142c0ccff1b5f6075310acc03432ddb6b8b` |
| old P2 `build/snapshot-full-20bf5b3/knowledge.sqlite` | 21516320768 | `4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073` |

Original failed-build partial DB/WAL/SHM, six private inputs, zero-byte lock and moved
cancelled-preparation files were also byte-checked unchanged. Frozen FULL55/P2151,
contract/source evidence, former receipts and artifact modules remain bound unchanged.
Full/oldP2 protection compares to original hashes, not freshly substituted hashes.

## B / C — formal-only policy, offline independent reevaluation

Warmups remain the same fixed attempts, excluded diagnostics. Formal success requires
exactly15 fixed workloads ×2 modes ×30 rounds0..29, uniquely complete: **900/900 PASS**.
Empty, missing, duplicate, wrong mode/op/case, actual timeout, partial result and wrong
whole JSON fail closed. Legitimate frozen S02/S18 `budget_limited` case classification
is not an exemption for actual partial/time-budget failures. Fixed5s internal and15s
CLI deadlines, workloads and expected bytes are unchanged.

`final-performance-recomputed-repair1.json` was computed read-only from old receipts and
raw JSON/JSONL, not by the performance executor, exit0, 1.4848171s. It verifies every
formal result against frozen independent expectations, request/response order,
complete grid, raw hashes, process exits, no timeouts, counts and nearest-rank timing
summaries. Warmups do not enter formal counts or percentiles. No cold-cache claim.

- Original receipt: `close-performance.json`, 774783bytes, SHA256
  `4d9bd35326f3e3e4eefeaf348fce17ef142b11f317171897dff2bd1ec9707936`.
- Original status **FAIL remains unchanged**. New policy formal900PASS/0FAIL.
- Fixed warmups30:29PASS,1diagnosticFAIL. G42 reused_connection round-1/index4,
  `query_budget_exceeded`, **5.0000352s**, original raw/response retained.
- Performance REUSED=YES, RERUN=NO, retries0. Root cause of historical G42 warm failure
  remains unknown; no probe/retry/runtime fix, no budget increase or dropped sample.
- Original new-verifier schema failure (`mode=value` assumption), missing local full
  stream/elapsed limitation and subsequent preparation failures stay separately recorded.

## D / E — clean fresh artifacts and source-external FULL acceptance

`final-artifacts.json` preserves the first FAIL (Cargo101, gcc.exe not found).
User then explicitly authorized one compiler-bound independent retry. Fresh clean
`e19…` archive, Rust CLI, wheel and installed venv succeeded in
`final-artifacts-retry1.json`, separate start marker/directory, no overwrite.
GCC16.1.0 Rev5 MSYS2/current Rust1.98.1 Windows-GNU is **new toolchain validation**, not
historical GCC16.2 equality. Exact compiler-version/target output retained. Command-local
PATH prefix/CC/CXX/target-specific CC/CXX and resolved Knowledge-contained Cargo targets
are explicit, including pytest children; no global environment change/install/download.

| Fresh artifact | Bytes | SHA256 |
|---|---:|---|
| Rust `sknow-rs.exe` | 5149588 | `b07620893fbea7523c10d0184f24f7db3ef4d3b3bff7922bb5e1d135bb0d1274` |
| `sakura_knowledge-0.2.0-py3-none-any.whl` | 33641 | `401219bcb02bffbdbd3bb7f78a286e304ff634f659f0549a42f1d0b8bd4bc169` |

Root: `dist/p3-final-e19d2278f26c12cba28eaff82a6eed2f0cda62cb-retry1`.
12 module files are byte-equal across git archive/wheel/installed package. Runtime source
inventory, archive, binaries, wheel and installed files are verified before every phase.

- `final-P2.json`: **151/151 PASS**,135 whole-value comparisons +16 exact error contracts;
  installed Python151/151 PASS, timeout0/retry0. Source-external temporary cwd,
  isolated installed interpreter, strict UTF-8 and complete values/evidence.
  Wrapper exit0/82.7662764s. S02 inside this fixed151 is its normal case, not target retry.
- `final-gold.json`: **55/55 PASS**, wrong_resolved0,timeout0,retry0; full source/evidence
  comparisons. Wrapper exit0/55.4387092s. Exactly one55 invocation serves both D and E.
  G42 appears exactly once in that declared gold, not a performance retry/probe.
- `final-external-repair1.json`: PASS, wrapper exit0/44.3031181s. Four non-query checks:
  installed module/API provenance, Rust help, Python help, Python resolve-tag refusal.
  Python has no public resolve_tag addition. Strict UTF-8 non-ASCII/query/error coverage,
  source-backed descriptions and non-resolved empty descriptions are linked to already
  executed fixed151/55 records, not extra probes.
  Original external preflight FAIL from non-UTF8 PowerShell process enumeration remains
  in `final-external.json`; no runtime child ran before that gate failed. New local
  process observer explicitly requests UTF-8, retains raw and conservatively blocks
  related processes. Frozen historical helper not rewritten.

### Targeted S02: query PASS, original phase protection FAIL — not erased

`final-S02.json` remains **FAIL**. Exactly one targeted CLI search succeeded with exit0,
0.176008s, full frozen expected JSON, stderr0, no timeout; same invocation profile says
query_invocations1,query_succeededtrue,fts_skipped_kind_not_indexedtrue,scanned0.
The phase then failed because its old sidecar comparison included SHM mtime.

`final-S02-independent-review.json` is **QUERY_PASS_PROTECTION_FAIL**, never a historical
protection PASS. It binds original raw/profile/runplan/frozen expected and exact historical
922 validator Git blob. That code's FULL after-hash `check_binding` returned before the
metadata-comparison exception. **Original exact after metadata/hash receipt NOT_SAVED**;
this is a control-flow proof, not a fabricated measured after receipt. Later observation
shows unchanged SHM content SHA/size/known zero-frame headers with changed mtime, but
historical cause is **NOT_PROVEN**; later values cannot become the missing earlier values.

User explicitly authorized a current read-only safe baseline and subsequent continuation
without targeted S02 rerun. New protection keeps FULL size/wholeSHA and expected/artifact
hashes strict, refuses nonempty WAL/journal/unknown SHM/missing hash/content change, and
records only unchanged-content SHM mtime as diagnostic. FULL151/gold/external gates passed
with actual whole-file hashes. TOCTOU and incomplete process-handle enumeration remain.
Final reviewer must judge this disclosed original failure/evidence gap; no success overwrite.

## F — explicit user waiver, not a clean Pool audit

`final-F-user-waiver.json`: **WAIVED_BY_USER / NOT_COMPLETED**. User stopped further audit
and removed F as a gate. Original invalid-directory audit and user-specified repository
observation remain separate. Historical BUILD_ARTIFACTS_WRITTEN=YES. Pool tracked-source
status and historical attribution **UNVERIFIED**; no verified-clean claim or attribution
of the observed dirty tracked report. No subsequent Pool access, cleanup or modification.

## G — seven exact final checks, one complete corrected series

Final code SHA `fef485c1b4a9716251ac70606a666e0ca4fbc18d`; all exit0, bound to unchanged
e19 delivery artifacts and isolated compiler/child-target environment.
Receipts: `final-check-<name>-fixtureprep1.json` plus immutable start/command/raw receipts.

| Check | Exact actual argv | Result |
|---|---|---|
| pytest | `python -m pytest -q` | 697 PASS,0SKIP; exit0 |
| Ruff | `python -m ruff check src tests tools` | exit0 |
| diff | `git diff --check` | exit0 |
| format | `cargo fmt --manifest-path rust/Cargo.toml --all -- --check` | exit0 |
| Rust test | `cargo test --manifest-path rust/Cargo.toml --locked` | 7library+1binary PASS; exit0 |
| Clippy | `cargo clippy --manifest-path rust/Cargo.toml --all-targets --locked -- -D warnings` | exit0 |
| release | `cargo build --manifest-path rust/Cargo.toml --release --locked` | exit0 |

Original full pytest632PASS/4FAIL (missing required text_probe example) remains FAIL in
`final-check-pytest.json`. Explicitly authorized fixture-only compilation from the fixed
e19 archive (`cargo build --manifest-path <archive>/rust/Cargo.toml --locked --release
--example text_probe`) exit0/2.4816612s; source/example/probe hashes and CLI/wheel before/after
unchanged are independently bound in `final-text-probe-prerequisite.json`. No test SKIP,
new runtime source or FULL query. A no-test-start fixture-schema preflight rejection is
also retained; actual complete corrected seven-check sequence ran only once.

## H / I — ordinary dev delivery and fixed-SHA review

Only named intended Knowledge files are staged and ordinary dev commits used. No amend,
reset,rebase,force,main changes. Binding tool preserves earlier and post-baseline histories,
verifies committed raw bytes/embedded streams and artifact-source/validation-source distinction.
The final child commit adds only `final-committed-binding.json` to its clean evidence parent.
Before review a normal dev push and `git ls-remote origin refs/heads/dev` equality to local
HEAD, main equality and empty porcelain must be verified. Exact delivery SHA/parent/binding
and remote verification are recorded by that receipt and final read-only verification.

**WAITING_REVIEW / no reviewer approval claimed.** Mandatory executed runtime/formal policy
checks and end byte protections PASS under latest explicit instructions, with targeted S02
original protection FAIL disclosed above. If final binding/push fails, this proposal is
BLOCKED rather than a completed delivery. Existing STOP-only approval does not approve
this final readiness proposal.

## Remaining limitations (not silently completed)

Verified entity_tag0 remains OPTIONAL_COVERAGE, candidate100/human0 unchanged; no native
identity from local aggregates, candidate promotion, name-based joins or generated trust.
No live upstream refresh (frozen local cut only), full human source-fact review, Linux/Pi
Skill execution, SakuraPool integration, services/models/GPU or dbstat proof. These remain
NOT_RUN/knowledge gaps. Historical artifact writes, warmup failure, target protection FAIL,
compiler/preflight/preparation errors and original build failures remain explicit.
