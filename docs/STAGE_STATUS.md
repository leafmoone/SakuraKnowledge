# Stage Status (SakuraKnowledge)

## Current P4 — RUST_SEMANTIC_PILOT_PASS / WAITING_REVIEW

- Dependency/tokenizer120 exact PASS; Rust ORT1.24.1CPU and direct USearch load PASS.
- Fixed runtime c417655:120/120quality/resident PASS,2warmups,0retry. Dense overlap
  all1.0, benchmark-v2/regression PASS. Linear total p95 378.150915ms,max460.4315ms.
- Approved-baseline P2 151/P3 55 PASS,wrong/timeouts/retries0. Default/semantic
  matrices PASS; pytest1187PASS143SKIP61subtests. Ruff final PASS.
- Report reports/P4/RUST_SEMANTIC_PILOT_REPORT.md discloses failed wrappers,
  activation repair and percentile convention. FULL attempts0,packNOT_RUN.
  Ready for FULL BUILD GATE review only, no automatic build/main merge.
- Historical ANN/v3 records follow.

- Authorized optional telemetry repair: no psutil installed. Real backend
  preflight PASS, tests53PASS. Old FAIL/config/raw artifacts remain unchanged.
- Retry1 exit0:16 candidates,12PASS,1920formal/32warmups,zero actual failures
  or not-run. SelectedM16/Eadd256/ef128,macroRecall10/20/100 .9925/.9916667/.97725,
  minima .9/.9/.91; pure search p95 4.65615ms. Benchmark-v2/regression PASS.
- ProcessRSS NOT_AVAILABLE, index memory285778304bytes, acceleration serial.
  See reports/P4/ANN_V1_RETRY1_REPORT.md. Ready for next gate, not production.
  Rust NOT_STARTED, FULL attempts0. Stop for review; historical record follows.

- User authorizes ANN V1 from256e2f1: BGE-M3_ONNX_FP32 quality/residentCPU PASS.
  Resident120/120 operation p50 71.96055ms,p95 82.42782ms.
- Fresh diagnostic122/122 timeouts occurred at setup/provenance validation,
  before tokenizer/session/query. FAIL_SETUP_VALIDATION; product cold-start
  NOT_MEASURED, not an ONNX cold-start performance failure.
- USearch2.26.2 isolated .venv-p4-ann available; fixed4-build16-candidate FP32
  grid invoked once after contract/tool push86ddf86. Four indexes saved, but
  build bookkeeping failed: missing isolated psutil for RSS. All16 candidates
  unqualified; actual query attempts0. No retry. See reports/P4/ANN_V1_REPORT.md.
  src/rust unchanged; no embedding/export/quantization or FULL execution.
- Historical v3 preparation and review records follow.

- V3 validates the existing FP32 ONNX artifact only: no export, native reference
  regeneration, passage rebuild, gold/RRF change or model reselection.
- V3 numerical query120/passages128 (batches1/8) PASS; all120 cases have
  set overlap1.0 at10/20/100. Ordered equality119/120 at10,111/120 at100 remains
  diagnostic. Benchmark-v2 and subset metric-regression gates PASS.
- Receipt: reports/P4/onnx-quality-v3-retry1.json. Initial pre-inference
  contract-byte failure remains in onnx-quality-v3.json; CRLF storage corrected
  without changing contract semantics. Resident CPU has NOT_STARTED.
- User requests this v3 submission be fixed and pushed for review before CPU.
  CPU harness code exists but is unexecuted; ANN/Rust/FULL remain NOT_RUN.
- Historical v2 records follow; their FAIL results remain unchanged.

- External review of ffff13b: CHANGES_REQUIRED, pilot evidence VALID;
  benchmark-v1 ceiling defect confirmed. V1 FAIL/NONE receipts remain preserved.
- User authorizes model-independent capped Recall10 selection contract v2 and
  read-only recompute of frozen results. No new gold, embedding build, selection
  retrieval, or RRF retuning. Quality PASS is required before BGE-M3 CPU tests;
  V2 recompute PASS: A FAIL/B quality PASS; native CPU qualification FAIL
  at fresh P4-075 timeout after120 reused successes and74 fresh successes.
- Separately authorized new query reference PASS (not historical evidence).
  Single FP32 ONNX export PASS, numerical query/passage agreement PASS;
  predeclared top100 ordered identity agreement FAIL at P4-002. No retuning,
  re-export, or final model selection. ONNX performance/ANN/Rust/FULL NOT_RUN.
  See reports/P4/V2_STOP_REPORT.md for explicit NOT_READY gate evidence.
- Historical continuation record follows; its STOP remains valid for v1.

- P1/P2/P3: **CLOSED_AND_MERGED**, per explicit user authorization.
- P4 base: `269e34eeeac920c29f2d684cfe37c93a95c73057`. Initial fetch verified
  origin/main, origin/dev and local dev at this exact SHA with a clean worktree;
  development switched to dev. Main requires external fixed-SHA approval.
- P4 scope: independent hybrid retrieval / RAG evidence sidecar; no generative LLM,
  no production Python API changes, no P3 snapshot mutation or rebuild.
- Freeze source-anchored retrieval gold and deterministic 50k-document pilot before
  embedding benchmarks. Compare pinned official multilingual-e5-small and bge-m3;
  production Rust semantic implementation is gated on meaningful pilot improvement.
- Explicit CPU/GPU device selection; CPU remains the required baseline. Configurable
  model identity/contracts, not hard-coded runtime model names. Downloaded models
  live in project `model/` and remain local-only, as do vectors and ONNX artifacts.
- External review of `e9ffff87acceb9fa16798a0db76597b605997282` requires changes;
  preparation code blocker NONE. User revoked mandatory four-source dense coverage.
  New authorized text strata: Bangumi subject690068/character221960/person102338
  and Danbooru wiki281272, total1,295,638. Moegirl/local-tag dense coverage remains
  zero and explicitly disclosed, not a v1 blocker; their structured access remains.
  Historical `trusted-corpus-coverage-audit.json`, `STOP_REPORT.md`, `DELIVERY.json`
  are preserved unchanged as authentic failures under the old contract.
- Original FULL55 oracle recovery remains0/55. New approved P3 behavior baseline
  **P4_APPROVED_P3_BEHAVIOR_BASELINE_V1 PASS**: P2 151/151, P3 55/55
  (39 resolved/16 nonresolved), wrong_resolved0/timeouts0/retries0. Captured before
  production edits; `reports/P4/continuation-approved-baseline.json` binds evidence.
- New trusted-text audit **PASS**: exact1295638, all four strata exact,
  index_episodes=false, matching FTS text, snapshot/sidecars unchanged. See
  `reports/P4/continuation-trusted-text-audit-command.json`. Old FAIL remains old FAIL.
- Unknown-provenance uv.lock moved with byte/hash verification to authorized
  `../SakuraKnowledge-p4-local-preserve-e9ffff/uv.lock`; external manifest saved.
  Do not access unrelated P3 preservation. Continuation results are pending.
- Retrieval gold is 120-case **FROZEN_PRE_EMBEDDING**, source-anchor validation PASS
  in `reports/P4/continuation-gold-validation.json`; queries/targets unchanged.
  SHA256 `ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba`.
  Deterministic50000-document pilot export PASS (fixed stratum quotas,50 mandatory
  anchor documents); each model-specific projection contains52664 chunks,0 empty.
  Same-pilot BM25 prepare and120-case query commands exit0; no quality claim yet.
- Model A first CUDA/float32/batch8 embedding attempt exited1 before first forward:
  strict raw/HF token-ID mismatch. Failure and partial index are retained.
  Tokenizer-only diagnosis identifies Transformers5.12.1 backend reconstruction
  dropping trailing-space ID6; serialization-preserving loader fix applied with
  strict backend/ID checks. Full tokenizer-only parity PASS for both models:
  52664 chunks +120 queries each; max passage tokens A388/B386; frozen inputs
  verified before/after. A corrected build and B first build exit0; separate
  index hash/shape/normalization checks exit0 (52664x384 /52664x1024).
  Both120-case exact queries PASS. Original A failure retained.
  Five-route quality evaluation exit0: STOP/NONE. Both hybrids fail frozen
  semantic Recall10 +.10 gain (BM25 .975, hybrid1.0, actual gain .025).
  A also fails crosslingual gains/nonregression. No thresholds or gold changed.
  CPU qualification, ANN, production runtime NOT_RUN after quality STOP.
  See reports/P4/CONTINUATION_STOP_REPORT.md; review preparation in progress.
- FULL semantic build attempts: **0**; FULL semantic pack: **NOT_RUN**. At most one
  attempt after all pilot, Rust, regression, disk, fixed-SHA and snapshot gates pass.
- P3 external local-only preservation is out of scope: do not read, move, delete or
  commit it. Historical reports below are retained, not rewritten as new passes.
- No SakuraPool modifications or SakuraTool integration authorized for P4.

## Historical final A-I closure — subsequently APPROVED and merged

- Final readiness proposal under the explicitly authorized formal-only performance
  policy; **not self-approval**. See `reports/P3/FINAL_DIRECTED_REPORT.md` and adjacent
  `final-*.json` receipts for actual commands, source/artifact bindings and failures.
- Harness fix `7eb371a95b164fe436c91cc4cb8ed97da90bc06e`; fresh artifact source
  `e19d2278f26c12cba28eaff82a6eed2f0cda62cb`; final checked tool/test source
  `fef485c1b4a9716251ac70606a666e0ca4fbc18d`. Runtime src/rust remains byte-equivalent
  in Git to `9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102`. No new snapshot build.
- Independent read-only old performance recomputation: 900/900 complete formal
  samples PASS; 30 fixed warmups, 29 PASS/1 diagnostic G42 budget failure retained.
  Original overall FAIL/raw/SHA unchanged; no performance rerun or extra G42 probe.
- Fresh source-external FULL151/151 PASS (135 full values/16 exact error contracts),
  installed Python151/151; single new FULL55/55 PASS, wrong resolved0/timeouts0,
  G42 gold invocation1. External module/API/help/error/UTF-8 checks PASS.
- Targeted S02 queried exactly once: exit0/full JSON PASS/profilequery1/0.176008s.
  **Original phase remains protection FAIL**; original after metadata NOT_SAVED.
  Independent review is QUERY_PASS_PROTECTION_FAIL, never retroactive protection PASS.
  Authorized current byte baseline and subsequent whole-file/known-safe sidecar gates
  PASS; only unchanged-content SHM mtime is diagnostic. Later S02 in151 is its normal
  case, not a targeted retry. Reviewer must assess this disclosed evidence limitation.
- Final seven checks at fixed fef485c all exit0: pytest697 PASS/0SKIP, Rust7+1,
  Ruff/diff/fmt/clippy/release. Initial pytest632PASS/4FAIL missing text_probe is
  preserved; authorized fixture-only compile left CLI/wheel/source bytes unchanged.
- GCC16.1 (MSYS2) is a **new toolchain validation**, not historical GCC16.2 equivalence.
  Original gcc-not-found artifact FAIL and all preparation/preflight failures preserved.
  Every compilation and pytest child uses explicit contained Cargo target and local
  PATH/CC/CXX; no global configuration, installation or external target writes.
- End FULL/oldP2/manifest/original partial+WAL+SHM/private inputs/lock whole hashes PASS.
  Frozen expected/source facts and prior reports unchanged. Verified entity_tag0 remains
  OPTIONAL_COVERAGE; no candidate promotion or inferred mappings.
- **F=WAIVED_BY_USER / NOT_COMPLETED**: no further Pool audit. Historical build-artifact
  writes YES; Pool tracked-source status/historical attribution UNVERIFIED. No claim of
  verified Pool cleanliness or responsibility for observed dirty report.
- Final ordinary dev push/remote equality/cleanliness and fixed-SHA review are required
  by the committed binding; main remains894. Linux/Pi/Pool integration/live refresh/full
  human fact review remain NOT_RUN. No main merge/P4 or success approval is claimed.

## Historical A-L directed closure — NOT_READY / STOP (G42 performance warmup budget failure)

- Fixed runtime/artifact source `9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102`.
  Only explicit index_episodes=false plus kind=episode skips FTS after exact/alias
  and too-short handling; same5s budget/Python public API unchanged. Opt-in create-new
  profile records one invocation, never overwrites files or queries twice.
- New source-external release/wheel/installed12modules built once from clean commit.
  S02 actual exit0/0.1970192s, profile4.3481ms/skiptrue/scanned0; new FULL P2151/151
  PASS (135fullvalues+16errorcontracts), installed Python151/151, no timeouts/retries.
- FULL two-mode fixed15cases30samples:900/900 measured PASS;29/30warmupsPASS.
  **Overall FAIL**: reused_connection G42 warmup -1 internal budget exceeded at
  5.0000352s. No sample dropped/retried or budget raised. Rootcause remains unknown.
- New code FULL55/J external environment/help validation **NOT_RUN after I FAIL**.
  Old9dfa55/55 is historical only, not substituted as new-code success.
- K seven actual commands at fixed code all exit0:pytest324PASS/Rust7+1PASS/
  Ruff/fmt/diff/clippy/release. Receipts preserve exactflags/env and earlier FAIL.
- Snapshot not rebuilt or patched. Original/retrybuild attempts remain total2.
  Verified entity_tag0 remains OPTIONAL_COVERAGE; candidate100/human0 unchanged.
- Exception: initial preparatory cargo inherited external target and wrote Pool build
  artifacts. **SAKURAPOOL_MODIFIED=YES_BUILD_ARTIFACTS_ONLY**, no Pool source edit
  performed; no global config change or cleanup. All later cargo targets confined.
- Three cancelled preparation files safely moved/hash-verified to ignored
  `build/p3-retry1-cancelled-prep/`; original content/names preserved, not product.
- See `reports/P3/CLOSE_DIRECTED_STOP_REPORT.md`, `close-*.json` and newly committed
  `close-raw/`. New STOP fixed-SHA review is requested only after normal dev push.

## Historical retry1 STOP — NOT_READY (P2 S02 budget failure, approved STOP evidence only)

- Retry1 build code: `9dfa610640eca1e32b6da89f78f3d4aff6062adf`.
  The independently authorized retry1 completed once, wrapper exit0 in
  13984.489062299952 seconds, no deadline, no automatic retry. Original attempt1
  host-timeout evidence/partial/lock remain unchanged; total formal attempts2.
- Published `build/p3-full-authorized-retry1/knowledge.sqlite`: 21718736896 bytes,
  SHA256 `61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.
  Manifest SHA256 `373fcb69731db877929c102b75292142c0ccff1b5f6075310acc03432ddb6b8b`.
  Builder integrity/FK/FTS/accounting checks passed; projection352/nativeWiki28/
  verified entity_tag0/capability1. WAL checkpoint [0,0,0]; old bytes protected.
- FULL gold frozen before Rust and actual55/55 PASS, wrong resolved0, timeouts0,
  39positive/16nonresolved. Original path-spelling gate FAIL retained separately.
- FULL P2: **151 attempted / 150 passed**, 134 complete-value comparisons and16
  error contracts verified. S02 `search "ONE PIECE" --topk20 --kind episode`
  exceeded unchanged5s Rust budget: exit2, `query_budget_exceeded`, elapsed
  5.172278400044888 seconds. No timeout retry, changed expected or increased budget.
  Original empty-sidecar gate FAIL retained; explicitly authorized gate-only
  continuation rejected nonempty WAL/journal/hash changes and did not delete sidecars.
- FULL dual-mode performance/source-external runtime: **NOT_RUN after actual P2 FAIL**.
  Fresh9dfa wheel/binary/venv, prior synthetic ABC and owner/quarantine fixture
  receipts do not substitute for missing FULL performance/external validation.
- User chose A for WAL repair: isolated synthetic experiment only under
  `build/p3-wal-batch-repair-A/`; 11+55 tests passed, never applied to dev/runtime
  or this build. No new formal build, main merge, GET, P4, Pool or SakuraTool changes.
- See `reports/P3/FULL_RETRY1_STOP_REPORT.md` and `full-retry1-*` for exact raw
  commands, original failures and limitations. Completion is not claimed.

## Historical original authorized P3 — NOT_READY (formal attempt failed; STOP)

- P1/P2: **CLOSED_AND_MERGED**. P2 fixed review `894dc6a73bfd42f18cc7648e8ab7481aae211ab1`
  APPROVE / NO_BLOCKING_FINDINGS within authorized Windows targeted/artifact scope.
- P3_BASE and immutable main: `894dc6a73bfd42f18cc7648e8ab7481aae211ab1`.
  Actual fetch and independent ls-remote verified initial main/dev equality, clean
  single worktree; ordinary switch to dev. Reviewed scoped resolver implementation approved;
  fullsnapshot readiness failed at the newly authorized sole formal build timeout;
  scoped resolver approval remains closed and is not fullsnapshot approval.
- P3 resolver/necessary new runtime capability: **Rust only**. Existing Python
  P2 public API/CLI frozen; Python additions restricted to ETL/audit/independent oracle.
- Scope: frozen native tags/active aliases/Wiki evidence and trusted entity names,
  typed identity, independent fixtures then real pilot including conflicts; a full
  candidate build is permitted only once after every documented gate is satisfied.
- Reviewed partial delivery `cf807c1a5179ce4b451b9a85870b6684d2dccaf3` received
  **CHANGES_REQUIRED** for endpoint substitution/proof gaps/gold coverage/redirects.
  Authorized four-item repair source/artifact SHA:
  `7393d601a6d95432f41da243395ed5d3e0a2fda1`. Fixed delivery `9d5f26d...`
  reviewed: endpoint/category, realgold and redirect **closed**. One MEDIUM residual:
  actual terminal Wiki quarantine omitted on canonical aliases. Authorized 15-line
  compiler-only repair source/artifact `229c2ddcc43c0d3919d44a4ea823f6a999a48a57`;
  independent rawcompiler+normalbuilder eight completeJSON paths before5FAIL/3PASS,
  after8PASS, fullpytest242; fixed delivery `d01b23c...` then found owner/target
  conflation when nativeC itself aliases to A. Same authorized residual only:
  source/artifact `8a5b3d23695a43970d1902d6d6dea7c9e7dd1882` aggregates quarantine
  refs by their own typed tag_key, not containing projection.target/last-writer.
  New dualnative/doublecut fixture18completeJSON paths in both raworders before18FAIL,
  after18+prior8=26PASS; fullpytest260. Fixed `28cf51bda963ded8bed2def289fd316a4db6bfd0`
  reviewer APPROVE / NO_BLOCKING_FINDINGS solely for this residual and authorized
  scoped evidence. Historical P3 receipts remain unchanged; `review-d01-*` and
  `REVIEW_D01_OWNER_REPORT.md` describe the then-REQUIRED coverage policy.
- Real pilot:30 native tags,28 compatible same-source Wiki links,352 assessments;
  451entries/222FTS,874input records all accounted. 100candidate decisions,0verified
  cross-source entity_tag/0human_verified. Two changed Wiki versions quarantined.
- Historical50 queries/failed49 acceptance preserved. New55 raw/input expected
  gold froze before repaired runtime acceptance: includes actual BGMsubject265
  candidate-only, four-Moegirl-character ambiguity, two missing native terminals,
  explicit empty descriptions for both changed Wiki versions and proof assertions.
  This is scoped pilot coverage, not verified cross-source positives/full-source recall.
- New explicit root/user closure authorization at baseline28cf: real verified
  entity_tag positive is **OPTIONAL_COVERAGE**, verified0 legal, not a fullbuild gate.
  Candidate100/human0 unchanged; no guessing names, promoting candidates, fabricated
  positives or changes to resolver/tag_decisions safety. Historical REQUIRED gate
  failures remain factual under their former policy, not relabeled PASS.
- Formal fullsnapshot gate actually READY (all recorded mandatory noncoverage gates
  true): originalfive+scopedSHA/old21.5GB/pilot/gold55/old151/cleanSHA/disk/newoutput,
  fixed `0aa46a57b1dcb4ac9a04a3c3ba49b97234ea616d`. Exactly **ATTEMPTS1 / MAX1**.
  Normalbuilder interrupted by our omitted `record_check.py` timeoutoverride:
  default300s hostdeadline, outerexit124/childexitnull, **FAIL_HOST_TIMEOUT**.
  Output not published; .sknow-z7dkmnsi SQLite/WAL/SHM/.inputs and outputlock preserved.
  Exact processaudit no residualbuilder; old21.5GB rehash unchanged. No retry/resume/
  alternatepath/attemptreset/overlay/postpatch/VACUUM/newGET/human. Root confirmedSTOP.
- FULLsnapshot integrity/projections/runtime/gold/old151compatibility/performance
  **BLOCKED / NOT_RUN** (no published validated candidate); PILOT evidence cannot
  substitute. Fresh0aaartifacts/checkreceipts and stoppedpartial/failure/bytebinding
  collected only. Currentruff cleanupPASS distinct from originalPERF402FAIL receipt;
  both auditfailure and original300s timeout remain unchanged. See
  `reports/P3/FULL_AUTHORIZED_STOP_REPORT.md` and `full-authorized-*`.
  Overall NOT_READY / WAITING_REVIEW; optionalverified0 legal, failedbuild is blocker.
  Only new explicit user authorization could permit further formalexecution.
- Old151 and seven Windows checks are recorded in `reports/P3/`; independent
  new artifacts and pilot-only dual-mode performance are not full-build acceptance.
- Existing P1/P2 reports/receipts and published 21.5GB snapshot remain immutable.
- No main merge/P4/Pool/SakuraTool integration. Existing Linux/Pi/full human facts/
  dbstat/Pool/live refresh NOT_RUN remain limitations, not new blockers.

## Historical b7547a A-C delivery — subsequently APPROVED and merged

New submission evidence: `reports/P2/review-b754-delivery.json`, with per-finding
mapping `review-b754-findings.md`. This proposes review, not external approval.
Prior b7547a review was CHANGES_REQUIRED for A-C; earlier nine fixes remain closed.

- Reference/implementation/clean artifact source: `42fa24810040349d05c0f8f0e10f9c7b3363e0b7`.
- A-C independent17 tests pass; corrected baseline13FAIL/4PASS retained. Initial
  stale-fixture FAIL is explicitly invalid reproduction evidence, not hidden.
- Final pytest167/Rust5; seven checks exit0; formal151=135fullvalue+16error, no retries.
- New960/960 measured performance successes plus32fixedwarmups;496pairs/996hashes verified.
- New source-external8 real-query pairs and10 A-C fixture pairs pass on installed wheel/binary.
- New24-receipt exact Gitblob binding at `74ebf585101150f5a714319d6a2082bf99665de4`.
- Snapshot/main/P1/old receipts unchanged; no R4 reopening or P3. Artifacts local-only.
- Linux/Pi/full human facts/dbstat/Pool/live refresh NOT_RUN. Final dev SHA independently verified after push.

## Historical f99a115 nine-finding repair — b7547a review required A-C follow-up

Submission evidence: `reports/P2/review-f99-delivery.json` and
`reports/P2/review-f99-nine-findings.md`. This proposes readiness, not external approval.
The f99a115 review was **CHANGES_REQUIRED / NOT_READY**; its passing aggregate tests
were insufficient and remain historical. Its checkout-byte receipt index is superseded
by `review-f99-historical-binding.json`, not silently treated as a committed-byte index.

- Implementation/reference/clean artifact source: `5305e48bcc0f7d794bc21155cb834033256911d4`.
- Failure-first regression:24 FAIL/5 PASS before; final pytest150/Rust5, seven checks exit0.
- New formal151 PASS=135 full-value+16error contracts; zero retries/timeouts,604 raw hashes verified.
- New performance960/960 measured+32fixed warmups;496 pairs/996 stream hashes verified.
- New wheel/binary source-external8 pairs plus2 reviewer real-query counterexamples pass.
- New25-receipt binding hashes exact committed bytes at `1d5954fb233a63ef01f39ab0cd16def1f45399ce`.
- Snapshot unchanged; P1/main/old receipts untouched, R4 not reopened, P3 not started.
- Local-only artifacts; Linux/Pi/full human review/dbstat/Pool/live refresh NOT_RUN.
- Final push SHA is verified independently and reported with submission, without a self-referential file hash.

## Historical bd99b7a repair — superseded by f99a115 CHANGES_REQUIRED review

Current evidence: `reports/P2/repair-bd99b7a-delivery.json` (R1–R6 and all gates).
This is implementation/validation readiness, **not external review approval**.
Final submission/origin SHA is verified after the normal dev push; main is not merged.

- Final Python/Rust implementation: `199af7595fa60a5af9d8e5daa9fc80be1e382d5d`.
- Clean artifact source: `eac2c9685e81ab33c0ff1390dfc29ae179456611`.
- Formal parity v3: 151/151 accepted, **135 actual full JSON comparisons + 16
  expected-error contracts**, no retries/timeouts. Repaired v1/v2 failures retained.
- Independent and integration pytest: 108 passed; Rust: 4 passed; full seven-command
  check matrix exit 0. Synthetic expected behavior is separate from real-source facts.
- Performance v2: 960 measured successes + 32 excluded fixed warmups; 8 workloads,
  2 runtimes, reused-connection API and independent CLI, 30 measured per group.
  Perf v1 remains FAIL because its Python search CLI used invalid `--topk`; v2 fixes
  the measurement to `--limit`, without changing runtime or artifact bytes.
- New wheel/standalone Rust: source-external validation 8 paired full JSON cases,
  help/errors and verified UTF-8 pass. New artifacts are **local-only**, not Git downloads.
- Frozen snapshot SHA remains `4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073`.
- P1 CLOSED_AND_MERGED; no snapshot rebuild, main changes, Pool or P3 work.
- Linux, Pi runtime, full human fact review, dbstat scan and upstream refresh NOT_RUN.

## Historical submission below — not the current conclusion

The following records the earlier submission (`reports/P2/p2-delivery.json`).
Its claims and failed receipts are retained as historical context, not current acceptance.

## Stage matrix

| Stage | Scope | Status | Evidence |
|---|---|---|---|
| P1 build | Full 4-source snapshot (bangumi archive, moegirl, mapping, danbooru + tag_wiki) | DONE | `reports/P1/full-reconciliation-20bf5b3.json`, snapshot sha256 `4c5ebae1…`, verify EXIT 0 |
| P1 quality | Query performance, reconciliation, trust split | DONE | `reports/P1/` receipts |
| P2 A | Reference fixes (trust split, ask templates, identity boundary) | DONE | commit `e5c4fd9` |
| P2 B/C | Rust runtime + CLI + 26-case parity | DONE (replaced by v2/v4/v6 151-case parity) | commits `abc3a8f`, `7f529b1` |
| P2 review remediation | Parity 151, compat receipt, wheel/dist, perf, docs | IN PROGRESS — this document set | `reports/P2/` receipts below |

## P2 review remediation — item status

1. **151-case parity** — `reports/P2/rust-parity-20bf5b3-v6.json`: 150 EQUAL + S18
   `RUST_BUDGET_EXCEEDED` (Rust 25/25 attempts > 5 s budget; every attempt
   recorded in `attempt_trail`). Honest result: overall **FAIL**, exit 1.
   The Rust reference is budget-boundary on `a's_wonderland` — not a
   semantic mismatch, but not PASS either.
2. **Docs + delivery JSON** — this file, `runtime-contract.md`,
   `rust-migration.md`, `reports/P2/p2-delivery.json`.
3. **Wheel 0.2.0 in isolated venv** — `reports/P2/p2-wheel-cli-20bf5b3.json`:
   fresh `--without-pip` venv, `pip --no-index` install, 11-command matrix
   incl. a GBK-console sample (code-page independence), all strict UTF-8
   (0 U+FFFD), success stdout parses as full JSON, error stderr is JSON
   (`UsageError` contract on both runtimes), in-process Unicode cross-check
   8/8. overall PASS.
4. **sknow-rs outside source tree** — binary copied to
   `dist/p2/sknow-rs-0.2.0-win64/`, same matrix, hash manifest
   `reports/P2/p2-artifact-manifest.json`, binary sha256 `a8f8cdb9…`.
5. **Read-only snapshot compatibility** —
   `reports/P2/snapshot-compatibility-20bf5b3.json`: sha256 identical
   before/after, python write attempt blocked, Rust `SQLITE_OPEN_READ_ONLY`
   inspect ok, required columns verified, inspect error path both runtimes.
   **dbstat: NOT AVAILABLE** in this system's SQLite build (recorded, not
   faked).
6. **Performance** — `reports/P2/p2-perf-20bf5b3.json` + raw JSONL
   `reports/P2/raw/perf/p2-perf-samples.jsonl` (1,596 end-to-end CLI
   samples, no retries, 120 s hard bound). Rust p50 ≈ 40–45 ms vs Python
   ≈ 190–240 ms (interpreter start dominates). Budget failures are failure
   samples: S18 rust 6/6 rounds, python 4/6; S17 once each on round 0;
   S01 python once on round 0.
7. **A-evidence** — `tests/test_evidence.py` (occurrence dataset partition,
   nullable `sample_count`, invalid frequency rejected-not-published,
   `source_fields` bounded projection, read-only write blocking); CLI
   UTF-8 reconfiguration fix in `sakura_knowledge.cli.main` (GBK console
   no longer raises `UnicodeEncodeError`).

## NOT_RUN (explicit)

- Rust gold eval (ask-template quality on held-out human-expected set) —
  not run; templates verified by parity only.
- Pi Skill runtime integration — not run.
- Full human source-fact review — not run.
- SakuraPool integration — not run.
- Live upstream refresh — not run; everything above is on the frozen
  snapshot `20bf5b3`.

## Environment of record

- Windows, gnu toolchain rustc/cargo 1.98.1, GCC 16.2.0 (w64devkit).
- Python 3.14.5, SQLite 3.50.4 (FTS5 yes; **dbstat no**).
- Machine: see `reports/P2/p2-perf-20bf5b3.json` `host`.

## FULL executor implementation revision — WAITING_REVIEW

- Prior narrative above is restored verbatim from HEAD; this executor section is
  appended only. Implementation permission is not execution authorization.
- Scope: tools/p4_full_build.py, tests/test_p4_full_build.py and executor docs.
  No helper/config/Rust/public API changes, installation, formal run or commit.
  FULL attempts remain 0; actual pack and native GPU/USearch remain NOT_RUN.
- Mapping uses source_id/evidence_id/text_sha256 and document_id/typedkey indexes.
  Bounded whole saved-matrix finite/norm scan and independent pinned CPU FP32
  LocalEncoder sample parity precede deferred ANN initialization. Actual reference
  identity is receipted; it is not labeled an ONNX reference.
- Activation guards exit before reservation; work/finalization guard exits precede
  manifest publication and terminal receipt. Activation errors attach attempt0 FAIL
  reports. No late outer guard can publish a false completion.
- Distinct sorted runtime_required inventory includes snapshot and canonical bytes;
  FULL_SEMANTIC_PACK_SHA256 aliases the canonical inventory digest. Receipt self
  bytes are excluded explicitly; top-level receipt binding and tempstate are recorded.
- ANN build seconds and byte/SHA binding are recorded. Optional memory/acceleration
  telemetry and supported reset/close cleanup are best effort, never blockers.
- Synthetic CLI invokes the actual FULL validator with explicit fixture authorities.
  Targeted pytest43PASS, owned RuffPASS; earlier regression41PASS/2FAIL was a fixture
  mismatch retained as historical evidence, not relabeled PASS.

### Final executor matrix / submission pending

- Latest reported executor tests: 78 passed. Final controller matrix: 12 commands,
  all exit0; full pytest1639 passed,21 skipped,67 subtests passed. Earlier counts
  above remain historical. No tests were rerun for this docs-only correction.
- Cargo/pytest targets remain repository-contained and process-local isolated;
  skipped cases remain NOT_RUN, not native GPU/USearch qualification.
- Authorization has exactly12 keys, including preflight_producer_sha (ccc80fd),
  preflight_evidence_sha (51346b2), and reviewed_source_bindings for count/disk/smoke.
  Historical reviewed provenance is separate from independently fixed executor SHA.
- Terminal snapshot CHANGED/HASH_FAILED or receipt persistence failure is FAIL;
  initial error type/message and failed phase remain preserved.
- docs/p4-full-semantic-v1.md retains all139 original baseline lines with an appended
  executor section. Prior no-builder wording is a historical preflight-stage boundary
  superseded for code implementation only; FULL remains unauthorized.
- Fixed-source submission/review remains pending. FULL attempts0,actual pack NOT_RUN;

### Final-review corrections — final6 pending, history retained

- Old matrix3 is supplanted after reviewer runtime `pack_version`, durable receipt
  fsync/publication and cancellation bugs. Historical results are not relabeled.
  Running matrix5 was invalidated by source changes; final6 is pending, not PASS.
  Reported base91 plus six additions is **91 + 6 = 97 expected**, not actual final97.
- Generated packs carry `pack_version=p4-full-semantic-v1`. Receipt staging fsync
  precedes exclusive hard-link publication with no overwrite. Directory durability
  is explicitly **NOT_GUARANTEED**. Every `BaseException`, including `GeneratorExit`
  and custom subclasses, preserves original reraising and finally accounting;
  secondary errors remain in the error registry with best-effort stderr accounting.
- Root approved fifth file `rust/src/semantic.rs` for `cfg(test)` only. Actual Python
  synthetic mapping/corpus products are exported to shared Rust `validate_mapping`,
  `dense_hits_for`, `full_artifact` and `validate_manifest`. Manifest coverage uses a
  TEST-authority derivative, not production FULL authority; JSONL joins are
  fixture-only, not a production corpus parser. Three actual direct-binary consumer
  version checks pass expected gates: generated version reaches subsequent FULL
  artifact-size rejection; missing/empty reject `missing/nontext pack_version`.
- Exact authorization fields: `schema`, `operation`, `fixed_code_sha`,
  `preflight_producer_sha`, `preflight_evidence_sha`, `reviewed_source_bindings`,
  `output`, `max_attempts`, `count_review`, `disk_review`, `smoke_review`,
  `executor_bindings`. Executor bindings retain four original owned files:
  `tools/p4_full_build.py`, `tests/test_p4_full_build.py`, `docs/p4-full-semantic-v1.md`,
  `docs/STAGE_STATUS.md`. Existing authenticated Rust inventory/source guards cover
  Rust test source, not a fifth executor key; fixed-source review must cover it.
- Native ORT/GPU and 21,718,736,896-byte FULL snapshot/pack opening **NOT_RUN**;
  FULL attempts **0**, actual pack **NOT_RUN**. Docs-only append; final6/review pending.

### Authorization closure correction (finalmatrix7 pending)

Earlier four-key executor binding claims are superseded: exactly five owned paths
include `rust/src/semantic.rs` alongside executor/tests/two docs. Each binds reviewed
raw SHA256 and fixed-HEAD Git bytes. Historical producer/evidence/receipt identities
are not migrated. Only the pinned appended `cfg(test)` reader-interop block may differ
from producer Rust; stripping that exact block restores all producer bytes.
Block SHA256: `8a5306d202fe4a7ee87a14d5cf05407a7b28ed18951ecf5a55c18566af876a78`.
Actual isolated temporary-Git tests cover valid closure and four rejection cases.
Finalmatrix6 is superseded by this correction; finalmatrix7 and review are pending.
No real-repository commit or formal count/disk/GPU/FULL execution; attempts0.
