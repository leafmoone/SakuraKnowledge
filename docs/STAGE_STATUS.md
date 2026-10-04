# Current stage status

## Outcome: PARTIAL / BLOCKED_FULL_FTS_PIN_MEMBERSHIP

Baseline: `a19f919af505b076d1129583b100abe7d6d13384`, branch `dev`.
This round fixed current configuration, lifecycle and reusable acceptance and
executed the authorized existing-assets route. **The FULL end-to-end route did
not pass.** Asset assembly and Rust startup passed; the frozen first warmup
exceeded the unchanged five-second query deadline in FULL pin membership SQL.
All 120 formal FULL cases and FULL quality remain **NOT_RUN**, not zero scores.
Python-native rebuild remains **NOT_RUN / toolchain-blocked**. No embeddings,
ANN products, gold, thresholds or source snapshots were changed.

## Fixes and boundaries

- Distinct `FULL_CONTRACT` and `CURRENT_ASSETS` constants: the actual FULL
  contract is no longer mistakenly read from the current asset inventory.
- `execute()` retains the independently verified snapshot baseline for terminal
  comparison. Terminal failures retain the original work error, record secondary
  errors and release only the lock owned by this invocation (token plus file
  identity). Replacement locks are not deleted; receipt failure cannot skip
  owned-lock cleanup.
- `AcceptanceSession` verifies actual immutable size/SHA bytes once per unique
  resolved asset in that session, rejects conflicting bindings and detects
  state/path changes. A new session hashes again. Every response independently
  checks typed identities, documents, evidence and sources; no provenance cache
  or semantic identity promotion was introduced.
- `--existing-assets` is separate from `--execute`: small staged candidate,
  atomic create-new publication and role-bound controlled relative references
  to existing assets. No `execute`, `build_stream`, encoder or Python-native
  USearch add/save/view is used. Unknown/swapped roles and unsafe paths reject;
  general containment policy was not relaxed. Necessary FULL product pins moved
  into current assets, not historical authorization receipts. Legacy metadata
  extras are projected out of live size/SHA bindings, not trusted as authority.
- Existing-binary legacy evaluation separates create-new results from the Cargo
  cache. It preserves frozen baseline comparisons and never compiles/reloads a
  Python index. Rust changes add role checks and error-stage timing only; native
  index interpretation and product bytes are unchanged. Consequently the prior
  1,366,520-key / 1,200-sample reader conclusion was reused, not re-probed.

## Actual candidate and commands

Candidate: `build/p4-existing-assets-a19f919-v1/manifest.json`, **27,727 bytes**,
SHA256 `f7738e6c565c698a5952ee704f00f5216347b7153a8c43d1791378ae45b506ed`.
It references the retained `build/p4-full-semantic-v1-retry1` corpus, mapping,
1,366,520-row ANN and vectors, the fixed P3 snapshot, and current model,
tokenizer, ONNX external tensors and ORT DLL. Actual content validation succeeded;
that is not a claim that the earlier builder completed or FULL acceptance passed.
The actual creation runner calls `existing_assets(output=..., session=...)` internally
and keeps that same session for manifest/response validation. Standalone available
CLI example (not separately executed this round):
`python -m tools.p4_full_build --existing-assets --output build/NEW-unused-candidate`.
Use a new absent output; do not rerun creation over the existing candidate.

All Python execution used explicit `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`.
Cargo used existing `C:/msys64/ucrt64/bin` on process-local PATH and
`CARGO_TARGET_DIR=D:/SakuraTool/SakuraKnowledge/build/p4-usearch-native-fix/rust-target`.
No external Pool cache, main branch or global toolchain configuration was changed.

```text
cargo test --manifest-path rust/Cargo.toml
cargo test --manifest-path rust/Cargo.toml --features semantic
cargo build --manifest-path rust/Cargo.toml --features semantic --bins
python -m pytest -q
python -m ruff check src tests tools
git diff --check
cargo build --release --manifest-path rust/Cargo.toml --features semantic --bins
# Actual v2 creation + evaluation command (before the output existed):
python -m tools.p4_existing_assets_evaluate --binary build/p4-usearch-native-fix/rust-target/debug/semantic_pilot.exe --output build/p4-existing-assets-a19f919-v1 --results build/p4-existing-assets-a19f919-evaluation-v2
# Actual v5 revalidation of the already-published immutable candidate:
python -m tools.p4_existing_assets_evaluate --binary build/p4-usearch-native-fix/rust-target/release/semantic_pilot.exe --output build/p4-existing-assets-a19f919-v1 --existing-pack --results build/p4-existing-assets-a19f919-evaluation-v5
python -m tools.p4_rust_legacy_regression --binary build/p4-usearch-native-fix/rust-target/release/sknow-rs.exe --results-dir build/p4-existing-assets-a19f919-legacy-v2 --knowledge build/p3-full-authorized-retry1/knowledge.sqlite
```

Regression: **1161 passed, 18 skipped, 55 subtests passed in 57.74s**, exit 0,
with actual `SKNOW_RS_TEST_BIN=D:/SakuraTool/SakuraKnowledge/build/p4-usearch-native-fix/rust-target/debug/sknow-rs.exe`. All 18 skips are Windows
symlink privilege limitations, not safety-test PASS. Rust default 7+1 and
semantic 29+2+1 passed, exit 0; semantic rerun after diagnostic changes also
passed (29 library tests, 0.40s). Ruff and diff-check passed. Later wrapper and
projection changes received focused regression, not another whole-suite run:
`python -m pytest -q tests/test_p4_build_entry.py tests/test_p4_existing_assets_evaluate.py tests/test_p4_full_acceptance.py`
reported **115 passed, 4 symlink skips in 7.89s**, exit 0; the subsequent warmup
failure guard received runner-only **12 passed in 0.08s**. Final wrapper-focused
checks: **20 tiny-fixture adapter tests passed**; final combined focused run
**135 passed, 4 symlink skips, 4 subtests passed in 9.12s**, exit 0, followed by
Ruff and diff-check PASS. The hardened adapter was not rerun on the large
snapshot: the prior actual 206-case evidence remains authoritative, while its
new timeout/finalization/binary guards are covered by small actual-hashing tests.

## Real runtime, quality and performance

The resident `semantic_pilot` driver calls formal `SemanticEngine::open/retrieve`.
Debug run v2 and optimized release runs v3–v5 opened the actual candidate.
Latest v5 startup wall: **2466.151 ms**; internal startup total **2085.7931 ms**
(ORT **1398.7916**, tokenizer **414.9204**, ANN **116.6372**, metadata **155.4431**).
Startup is separate from query timing and excludes Python asset hashing.

The unchanged frozen first case `P4-001` failed. Latest stderr:
`full_lexical: pins SQL: interrupted; tokenize_ms=6.3005; ort_ms=62.079;
ann_ms=48.3022; lexical_ms=4889.0056; total_ms=5005.8139`.
Driver wait reached its five-second boundary first (wall **5002.2805 ms**), so
stdout error was not received in v5; stderr and exit **1** were retained.
The first warmup failed, the second warmup and all 120 formal cases are NOT_RUN.
There is no valid resident-query distribution or FULL retrieval quality result.

Read-only EXPLAIN confirmed selective entry-value/alias indexes and document /
entry-evidence indexes, but correlated FTS membership uses a virtual-table scan
on UNINDEXED `document_id` / `entry_id` fields. No sound equivalent local SQL rewrite was
established. Original pin eligibility SQL remains:
`EXISTS(SELECT 1 FROM documents d WHERE d.entry_id=e.id AND FULL_DOCUMENT_TRUST
AND EXISTS(SELECT 1 FROM search_fts f WHERE f.document_id=d.id AND
f.entry_id=e.id AND f.text=d.search_text))`, driven by the existing exact
`e.value=?1` / alias `a.text=?1` candidate predicates. `FULL_DOCUMENT_TRUST`
requires unconflicted non-episode entries, eligible document policy and
source-backed entry evidence. Original BM25 remains MATCH-driven, joining
`d.id=search_fts.document_id` and checking `search_fts.entry_id=e.id`,
`search_fts.text=d.search_text` and the same trust predicate before the unchanged
ranking limit. No proposed rewrite was adopted: selective candidate driving was
already present, and no indexed equivalent for real FTS membership was proven.
Pins consumed the five-second query budget; BM25 was **NOT_RUN in that request**,
not separately allowed an extra five seconds. FTS rowid is not a document-ID contract. No index/schema/cache
rebuild, weakened membership/pins, early candidate truncation or relaxed deadline
was attempted. Further structural performance work requires explicit scope.

Frozen gold: `reports/P4/retrieval-gold.json`, SHA256
`ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba`,
120 unchanged cases (30 lexical, 40 semantic, 30 crosslingual, 20 ambiguous/negative).
The runner retains the existing v2 metrics/gates and same-FULL-population lexical
baseline, not pilot rankings. Semantic/crosslingual R10 requires
`min(1, baseline + .10)` with no MRR/nDCG decline; lexical losses remain bounded
by 1/30 R10 and .03 MRR/nDCG. Identity error must remain zero with per-response
source verification. These checks are **NOT_RUN on formal FULL responses**;
fixture regression does not establish real-source identity/provenance success.
FULL exact-dense overlap is separately NOT_RUN because its oracle is unavailable.
Gold is non-exhaustive engineering relevance, not full human source-fact review.

Independent actual P2/P3 regression: **151/151 P2 + 55/55 gold comparisons PASS**,
runner exit **0**, timeout **0**, exact JSON/error/source contracts preserved.
Evidence: `build/p4-existing-assets-a19f919-legacy-v2/evaluation.json` and all
206 stdout/stderr pairs. G51 wall **4.0611941 seconds** belongs to this legacy
run, not FULL semantic resident performance.

## Failed attempts and limitations

- Initial full pytest invocation used nonexistent `sknow_rs.exe` instead of
  actual `sknow-rs.exe`; failed, then corrected and rerun successfully. It was
  not interpreted as PASS.
- Evaluation v1 rejected inherited `git_blob_sha1` metadata in strict live file
  bindings before runtime. Projection was corrected and tested. v2 assembled
  successfully but its runner continued against a dead driver: the 120 Err22
  records are wrapper failures, not 120 retrieval measurements. v3–v5 abort
  transport failure and keep remaining cases NOT_RUN. All result directories
  were retained, not overwritten or discarded.
- Legacy old module imports / coupled Cargo-cache reservation and an adapter
  missing-helper error blocked early invocations before cases. Corrected v2
  actually executed all 206 cases. Failed v1 directory was retained.
- Same-session asset hashes were reused across assembly/manifest/response checks.
  Separate diagnostic processes necessarily created fresh sessions and rehashed;
  no persisted stat cache was substituted for actual content verification.
- A worker accidentally overwrote two pre-existing untracked diagnostics:
  `p4-owned-pytest-diagnostic.log` and `p4-owned-ruff-diagnostic.log`.
  Their original contents were not recoverable; no guessed restoration was made.
  They are not staged. This is an execution-boundary violation, not a product
  validation result. Other unknown files were not intentionally cleaned.
- **MSVC_REQUIRED_FOR_PYTHON_REBUILD YES**: the real Python rebuild chain still
  needs the patched native extension; it was neither built nor verified. No
  MSVC/SDK installation was attempted. Existing Rust asset opening works without
  that rebuild but the current FULL query/quality route remains blocked above.
