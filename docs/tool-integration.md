# Tool integration interface repair

Implementation starts from the actual `dev` / `origin/dev` base
`62886224b3dd0743ac0269cc28fc9bbbe399b20b`. This is an interface acceptance round,
not a source refresh, retrieval-quality retuning, or live Tool/Pi integration.
The final ordinary implementation commit is the commit containing this receipt;
independent review binds the actual pushed SHA, not a guessed self-referential SHA.

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

## Real Top-K before/after

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

## Real resident acceptance

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

## Candidate and limitations

New candidate only:
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
