# Tool integration interface repair

Implementation starts from the actual `dev` / `origin/dev` base
`62886224b3dd0743ac0269cc28fc9bbbe399b20b`. This is an interface acceptance round,
not a source refresh, retrieval-quality retuning, or live Tool/Pi integration.
The first ordinary implementation submission is
`4a19414aa45537533072d1a42be29bb537cb8948`. Its independent decision is
**CHANGES_REQUIRED**, solely for the request deadline missing parsing/serialization/
blocked output; Top-K/CLI had no additional blocking finding. Its original evidence
and failed commands remain below and in `tool-integration-receipt.json`.
The ordinary append deadline repair uses its own receipt; independent review binds
the actual pushed SHA, not a guessed self-referential SHA.

## Fatal-diagnostic lifetime repair (latest append candidate)

Fixed `d356945dc4c267b016d72fba583b90788bfeec69` received
**CHANGES_REQUIRED** for one remaining P1: after the request controller dropped,
CLI outer `eprintln!` or Rust's default `Result`-returning pilot could print to a
full stderr without a deadline. Its successful-path evidence below remains valid
for that fixed SHA; it is not retroactively called approved.

The narrow follow-up keeps cold startup/open-error diagnostics separate. Once in
runtime, fatal errors terminate only the current process with exit1 without an
unguarded secondary diagnostic or stdio/destructor cleanup. The pilot uses an
explicit `ExitCode` entry point. Deadline expiry remains124; guarded sender
profiling that blocks on stderr remains covered by the watchdog. Read-only
assets cannot have a runtime write transaction interrupted by this exit.

New create-only candidate4:
`build/tool-integration-v1/SakuraKnowledge-core-win-x64-candidate4/`;
19 files, **83,521,781 bytes**; manifest SHA256
`c606f1d6a9701dceac47ae9ff51376edcc83f4016e00ffc68f518d70ac16b361`.
Earlier candidates and the old Core remain unchanged. New actual native tests
query the OS pipe capacity, prefill stderr before triggering fatal errors and do
not consume it until child exit. Cases include invalid UTF-8 stdin I/O, fixture DB
corruption, single-query fast engine failure and broken stdout; these are fixture
transport/lifecycle tests, not source/model qualification. Rust115 +release/helper
build **exit0**; native interface/deadline/helper/budget **74 passed,25.51s,exit0**.
A separate raw capture confirms the actual filled capacity is4096 bytes in each
scenario, with stderr containing only that parent filler after child termination:

| Native full-stderr scenario | Exit | Observed seconds | Delivery interpretation |
|---|---:|---:|---|
| Resident invalid UTF-8 stdin | 1 | .00343 | Only opened event; no business response |
| Resident fixture DB corruption | 124 | 5.01436 | Full runtime_error frame precedes blocked profiling; not completed delivery |
| Single fast engine query failure | 1 | .03779 | No stdout response; no unguarded secondary diagnostic |
| Single broken stdout | 124 | 5.04049 | No readable business response; no claimed FAIL delivery |

Raw files and summary: `fatal-stderr-candidate4-receipt/`. Capture attempts1/2 failed
before native execution due to helper import/base-directory prerequisites; their
stderr/exit1 records remain, not counted as runtime PASS.

Candidate4 real TopK10 passes with scope failures0, DB pack-qualified proof checks
PASS and every ordered typed key/rank field unchanged from the frozen baseline.
Internal lexical/ANN depths, RRF and ranking were not changed. One key need not
have just one document: Moegirl top1 legitimately retains9 same-key source-backed
documents. All-installed top1 retains1 document and7,821 JSONL bytes (921.43ms);
this is output closure, not a universal latency improvement claim.

Real modular resident:18 responses, opened1/session1, q1/q2/q3 PASS/FAIL/PASS,
encodings1/0/1, EOF0. Candidate4 monolithic first process instead exited124 with
zero complete business responses; without a stage profile its slow phase is
unknown. A separate explicit same-input manual process accepted16 responses,
opened1/session1, q1/q2/q3 PASS/FAIL/PASS, encodings1/0/1, EOF0. Its three valid
queries took646.55/2907.67/4680.73ms: near-five-second headroom is a real limitation.
No internal automatic retry, reload, budget relaxation or first-FAIL reclassification.
The final changed-code normal complete Python run is **1426 passed,19 skipped,
55 passing subtests,127.68s,exit0**, with empty stderr. All19 skips are unavailable
Windows symlink/privilege fixtures, not converted to PASS. Candidate4 and its
separate test-only text_probe prerequisite clone are byte-bound to the runtime
under test. The d356945 matrix below remains bound to its own earlier code.
[Final fatal-lifetime append receipt](tool-integration-fatal-receipt.json) records
commands/exits/JUnit/code/Core/checks/real native/capture and retained failures.
The ordinary appended implementation SHA still requires fixed-SHA independent
review before approved baseline status.

## Absolute deadline repair (prior append submission, candidate3)

`request_deadline.rs` adds one absolute monotonic deadline and one reusable
process-local watchdog. Resident timing begins after a complete line has been
read and before JSON parsing. JSON validation, retrieval, serialization, write,
flush and profiling use that deadline; cold opening and input-line waiting are
excluded. Both semantic single-query entry modes use the same checked sender and
watchdog, debiting argument-validation time but not cold opening.

The watchdog never writes stdout/stderr or emits a competing failure frame.
Unsafe timeout or blocked output hard-terminates only the current native process
with exit124; no cleanup or asset write is performed. Recoverable errors retain
one complete FAIL and continuation if it can be completed before the deadline.
Unknown/late engine results remain fatal; generic host APIs cannot interrupt an
arbitrary blocking host writer without the native watchdog. Successful flush and
absolute-time checks precede generation disarm; old generations cannot cancel or
expire later requests. A frame read before an uncompleted flush/session fatal is
not proof of completed delivery. Desktop scheduling is not hard real time.

Final-version Rust relevant tests: **114 library +1 CLI =115 PASS, exit0**;
release +test-helper build: **exit0**. Final native deadline/interface/helper/budget
fixtures: **70 passed, 14.59s, exit0**. This includes actual non-drained stdout pipes
for resident and modular single retrieval, alongside fast-drained PASS/FAIL/PASS.
Separately retained native blocked-pipe receipts observe resident exit124 at
**5.008s** after the completed request and single CLI exit124 at **5.385s** including
cold fixture opening. Neither emitted a complete business frame or a claimed
failure; stderr was empty. Raw receipts: `blocked-resident-candidate3/` and
`blocked-single-candidate3/`. Sender unit tests separately cover late engine PASS,
serialization deadline chunks, slow partial writes and slow flush, not just a
sleeping engine. Precise case-ID escape sizing replaces the initial conservative
control-character estimate; nine character families test exact wire thresholds.

New create-only candidate:
`build/tool-integration-v1/SakuraKnowledge-core-win-x64-candidate3/`;
19 files, **83,527,978 bytes**; manifest SHA256
`793d89035e11cb4b01d9c3f178b64baaed29a48f86f03d874a3a1ddbcf8f4e52`.
Candidate2 and old Core are unchanged. A separate test-only binary copy is verified
byte-for-byte against candidate3 and contains `examples/text_probe.exe` before the
final normal-environment Python matrix. No helper is inserted into the Core.
Final candidate3 real Top-K: all ten fixed cases **PASS**, scope failures0 and
all candidate ranking fields unchanged. Final candidate3 measurements:

| Packs / K | Before → final documents | Before → final JSONL bytes | Before → final query ms |
|---|---:|---:|---:|
| tag-wiki / 1 | 100 →1 | 279,908 →51,764 | 189.649 →217.382 |
| tag-wiki / 5 | 100 →5 | 296,458 →88,967 | 57.714 →79.098 |
| Moegirl / 1 | 100 →9 | 339,035 →174,655 | 205.726 →293.042 |
| Moegirl / 5 | 100 →9 | 386,333 →237,149 | 62.845 →116.155 |
| Danbooru / 1 | 100 →1 | 180,513 →83,589 | 250.900 →229.149 |
| Danbooru / 5 | 100 →5 | 189,859 →99,792 | 246.663 →212.222 |
| Danbooru + Bangumi / 1 | 1 →1 | 7,044 →7,714 | 459.948 →363.222 |
| Danbooru + Bangumi / 5 | 5 →5 | 25,105 →27,954 | 359.699 →351.841 |
| all four / 1 | 201 →1 | 486,681 →7,822 | 768.958 →853.234 |
| all four / 5 | 205 →5 | 504,764 →28,080 | 750.800 →761.931 |

Byte totals include timing fields, so tiny differences from candidate2 are expected.
No uniform latency improvement is claimed. Moegirl's9 independently retained
pins/documents are intentional, not permission to return the original Top100 pool.

Modular real resident:18 responses, opened/session1, valid encodings1/1/1 and
process totals1/2/3, EOFexit0.
Its first monolithic validation instead terminated with **exit124**, opened1 and
zero complete business responses; raw stderr was empty. The exact inner engine
phase cannot be inferred without a delivered profile. This attempt remains FAIL,
not a delivered FAIL envelope or successful sequence. A separately invoked manual
acceptance is retained under its own path; no automatic retry or budget relaxation
is introduced. Its separately invoked monolithic attempt2 **PASS**:16 responses,
opened/session1, q1 PASS/q2 invalid_limit FAIL/q3 PASS, per-query encoder deltas1/0/1,
Unicode tail PASS with process encoder total3, EOFexit0. Engine query times are
532.996, 2629.747 and4312.339ms; final transmission remains within the absolute
budget. Modular successful query times are917.064, 479.626 and503.522ms. The append
receipt records both paths and the initial failed monolithic process. The final
Python matrix for this changed deadline version is **1422 passed, 19 skipped,
55 subtests passed, 102.73s, exit0**. The helper prerequisites were present before
execution; all19 skips are Windows symlink-privilege fixtures, not converted PASS.
Final raw command/JUnit/code/Core/model-sequence bindings are in
[the append receipt](tool-integration-deadline-receipt.json). Earlier failed commands
below remain historical FAIL. Ruff over `src tests tools` and `git diff --check`
return0. The new ordinary pushed SHA still requires fixed-SHA independent review
before this can be marked an approved Tool integration baseline.

## Changes and boundaries

- `semantic.rs`, `semantic_evidence.rs`, `modular.rs`, `semantic_federation.rs`:
  close public documents/source/evidence/citations after final candidate selection.
  Retain all independent trusted-pin identity/alias proofs and source-qualified
  multiple documents. Numeric document IDs are not deduplicated across packs.
  Internal bounded lexical/ANN hits and RRF/fusion ordering are unchanged.
- `modular_cli.rs`, `main.rs`, `modular.rs`: parse and reject unsupported/missing/
  inapplicable options before discovery; support incoming/outgoing existing Runtime
  methods and both resolve-tag namespace aliases. Repeated/comma source selection
  remains supported; empty members and conflicting aliases are errors.
- `resident.rs`, `semantic_pilot.rs`, `semantic_jsonl.rs`: both entry modes use one
  typed request validator and one loop. Only explicit `RequestError` permits
  continuation. Unsafe internal errors, unproven-safe timeouts, and I/O failures
  terminate. Valid case IDs are verbatim; unreliable IDs are null. Overlong IDs
  are explicitly invalid protocol input so a complete failure envelope fits.
- `README.md`, `runtime-contract.md`, and Skill describe 2MiB UTF-8 **including
  newline**, five-second query budget, evidence scope and resident lifecycle.

No source pack, mother DB, original mapping, ANN, BGE-M3, RRF constant, gold,
identity trust rule, or Moegirl/tag-wiki provenance is rebuilt/modified. Structured
business algorithms remain unchanged; only argument routing uses existing
`related_in` / `related`. Therefore the historical151 business and full120 quality
matrices were not rerun. Ten fixed real queries retain candidate keys/ranks/scores;
this is not a new claim that the existing quality gate has passed.

## First-submission real Top-K before/after (candidate2)

Same queries and frozen four-pack installation; Top1 and Top5 for each combination.
Every returned document is checked against its owning read-only DB for typed key,
source/evidence ID, status, exact body, and (Moegirl/tag-wiki) exact text provenance.
Selected keys/pins retain public proof; dependencies retain their sources. All ten
candidate ordering/ranking-field comparisons and final proof checks **PASS**.

| Selected packs / K | Documents before → after | UTF-8 JSONL bytes before → after | Query ms before → after |
|---|---:|---:|---:|
| tag-wiki / 1 | 100 → 1 | 279,908 → 51,763 | 189.649 → 72.839 |
| tag-wiki / 5 | 100 → 5 | 296,458 → 88,957 | 57.714 → 62.187 |
| Moegirl / 1 | 100 → 9 | 339,035 → 174,655 | 205.726 → 190.402 |
| Moegirl / 5 | 100 → 9 | 386,333 → 237,148 | 62.845 → 74.087 |
| Danbooru / 1 | 100 → 1 | 180,513 → 83,600 | 250.900 → 198.169 |
| Danbooru / 5 | 100 → 5 | 189,859 → 99,816 | 246.663 → 200.597 |
| Danbooru + Bangumi / 1 | 1 → 1 | 7,044 → 7,705 | 459.948 → 348.735 |
| Danbooru + Bangumi / 5 | 5 → 5 | 25,105 → 27,963 | 359.699 → 344.322 |
| all four / 1 | 201 → 1 | 486,681 → 7,811 | 768.958 → 884.238 |
| all four / 5 | 205 → 5 | 504,764 → 28,060 | 750.800 → 791.344 |

Moegirl retains nine independent alias/exact pins: nine documents are allowed even
with K=1. Existing closed multi-semantic responses grow slightly because citations
now include explicit pack origins, not because ranking depth or identities change.
These one-shot timings are observations, not a benchmark/speedup guarantee; cold
model/process opening is separately recorded. Small fixtures cover colliding
numeric IDs in distinct packs, shared typed keys, and multiple documents per key.

Receipts: `build/tool-integration-v1/topk-before-v1/summary.json` and
`topk-after-candidate2/summary.json`; raw stdout/stderr retained for every case.

## First-submission real resident acceptance (candidate2)

Real native binary plus existing BGE-M3 and indexes, one process per sequence:

| Mode | Read requests | opened / model sessions | q1 / q2 / q3 | Encoder totals | EOF exit |
|---|---:|---:|---|---|---:|
| `--config` four packs | 18 | 1 / 1 | PASS / invalid_limit FAIL / PASS | 1 / 1 / 2 | 0 |
| monolithic existing mother/full manifest | 16 | 1 / 1 | PASS / invalid_limit FAIL / PASS | 1 / 1 / 2 | 0 |

Valid request encodings are each1; invalid limit and other input failures add zero.
The final Unicode query with whitespace/Unicode case ID is PASS with encoder total3.
Malformed JSON returns `invalid_json`, `case_id:null`, `retries:0`, then continues;
missing/non-string IDs, invalid query/filter/source, zero/out-of-range limit and
unknown options also continue. No reopened event/session, duplicate response,
engine retry, or ANN reload occurs within these accepted sequences.

Successful query times: modular 910.961, 461.583, 458.781ms; monolithic 460.570,
2829.472, 4614.496ms. All are below5000ms; serialization/transmission is recorded
separately and the serialized response never exceeds2,097,152 bytes including LF.

**Retained failure:** the first monolithic validation process exceeded the query
budget while cold ANN pages were read (`ann≈4863.892ms`, lexical interrupt around
5000.679ms, total request≈5075.962ms). It emitted a fatal `runtime_error` and exited1,
without executing later requests. This is not marked PASS or made recoverable.
The subsequent explicitly invoked validation process used the same fixed inputs
and succeeded; it is a separate acceptance attempt, not automatic process retry.

Receipts: `resident-modular-candidate2/summary.json`,
`resident-monolithic-candidate2-attempt2/summary.json`; initial FAIL retained in
`resident-monolithic-candidate2/`. Each retains full input/stdout/stderr/exit.

## Small native/loop fixtures

`tests/test_tool_runtime_integration.py` executes native processes over synthetic
new fixture packs (not real-source qualification). It covers recoverable chains,
oversized response → next PASS, null IDs, invalid sources, strict CLI usage errors,
both related forms/directions versus the existing direct Rust CLI, resolve aliases,
no candidate mapping promotion, pack-qualified Top1/5 proof checks, fatal fixture
DB corruption, bad initialization and actual broken stdout pipe.
`resident.rs` loop tests additionally inject stdin/write/flush/internal errors and
verify fatal-default classification, no second response after a partial write, and
no encodings for invalid input. Shared sender tests include the exact2MiB boundary.
Helper fixtures are explicitly separate from these engine/native checks.

A separately retained actual native lexical-fixture process produced a
**2,235,154-byte** would-be response, sent one complete **238-byte**
`response_too_large` FAIL with the original Unicode ID, then returned `tiny-next`
PASS (**12,460 bytes**) and exited0. It emitted `opened` once; this lexical fixture
requires no model. Receipt: `oversize-resident-candidate2/summary.json` with raw
input/stdout/stderr. This demonstrates recovery, not response truncation or a
claim of real-source oversize/model qualification.

The scoped native/helper/legacy-budget run: **66 passed, 4.28s, exit0** on candidate1.
The only whole-Python run uses candidate2: **1415 passed, 4 failed, 19 skipped,
55 subtests passed, 99.24s, exit1**. All four failures are missing test-only
`bin/examples/text_probe.exe`, which is not part of the Core distribution. The
failed command remains FAIL. The helper is subsequently built against the same
crate, and only these four tests are rerun using the byte-identical release CLI:
**4 passed, 1.17s, exit0**. The targeted result is separately recorded, not
relabeled as a full-suite PASS.
See the [machine-readable receipt](tool-integration-receipt.json) for the exact
failed-case/delta-case binding. No success claim replaces a failed/missing run.

## First-submission candidate2 and ongoing limitations

Historical create-only candidate:
`build/tool-integration-v1/SakuraKnowledge-core-win-x64-candidate2/`.
19 files, **83,481,693 bytes**; component manifest SHA256:
`5aeb64b49f601cc7a5746a9f6a253fab6664a76a9dcd9a46b29b566c84497bba`.
Original Core remains untouched; selected complete pack directories and the
matching independent model component are still required. Candidate1 and its
failed comparison are retained, not overwritten or promoted.

- Unsafe/unproven engine timeouts remain fatal. The observed cold monolithic
  timeout means uninterrupted operation under every cold/load condition is not
  promised; five-second budget was not relaxed.
- Source rights remain `NOT_CLEARED`; original `QUALITY_FAIL` remains. Upload or
  interface tests do not clear either, nor establish new verified identities.
- New-machine acceptance, live upstream refresh, full human source-fact review,
  Pi Skill runtime integration and SakuraTool/Pool integration are **NOT_RUN**.
- No wheel or replacement source/model/ANN pack is produced by this round.
- Normal push, live dev SHA equality, unchanged main and independent review are
  required for closure. The final review is external to the self-contained commit.
- After this round stops, no automatic Knowledge restructuring or Tool development
  is started.
