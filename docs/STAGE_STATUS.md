# Current stage status

## Product status

- SakuraKnowledge remains an offline knowledge core. Typed identity, source/evidence
  provenance, ambiguity and refusal behavior remain product requirements.
- Existing P2/P3 snapshots and P4 corpus, mapping, sample, embeddings, ANN index,
  models and tokenizer assets are retained. Historical build failures do not
  establish successful publication or acceptance of a FULL semantic pack.
- The retained P4 embeddings passed whole-vector checks and a 1200-position CPU
  comparison. The saved ANN index passed a read-only diagnostic buffer audit and
  subsequent patched Rust metadata/path-view, full-key and fixed-sample checks.
  These are reader/product diagnostics, not FULL runtime or quality acceptance.
- Windows USearch 2.26.2 needed two native fixes: full-width mapping lengths and
  64-bit metadata seek/tell. The project-local vendor patch and native boundary
  regressions are retained; the index format and semantic parameters are unchanged.
- The patched Python extension has not been built. Whether its missing compiler
  blocks the current Python build/reload path: **MSVC_REQUIRED_FOR_CURRENT_P4 YES**.
  `execute -> build_stream -> index_factory -> usearch.index.Index` still performs
  construction/add/keys/length/save and reopened `view`. Rust runtime and saved-result
  scoring do not require that Python extension. Using a Rust-only builder would be a
  separate functional change, not a compiler-free completion established here.

## Verification maintenance

Historical commit/source-byte authorization chains, permanent attempt gates and
redundant delivery receipts were removed from the maintained P3/FULL builder and
pilot runtime paths. Git history
retains past development records; normal product operation must not require an old
commit, an old failure directory, or a historical report to exist.

Current product configuration and manifests remain authoritative for asset paths,
model/tokenizer compatibility, snapshot/index identity and actual content checks.
A validation session may share verified assets; stat observations are not a
substitute for a content digest. Normal concurrency protection, atomic publication
and refusal to overwrite existing products remain required.

- **Fast:** related functional tests with small inputs and relevant lint/format checks.
- **Regression:** retained Python tests, Rust default/semantic tests and static checks
  once per completed functional block, using a project-local shared Cargo target.
- **Acceptance:** explicit real-data validation for a changed candidate or reader;
  no full embeddings, ANN construction or quality benchmark in routine pytest.

Documentation-only changes do not require another model/native matrix. Failed
functional tests must be investigated, not removed or silently skipped to obtain
PASS. The cleanup regression results and remaining limits are recorded below.

## Not completed by this maintenance task

No new FULL build, ANN construction, continuation, FULL runtime qualification,
FULL quality acceptance or release optimization is authorized by this cleanup.
The main branch is not modified.

## Cleanup verification results

- Test files: 68 previously tracked -> 57 current files (12 obsolete files removed,
  one production-entry regression added). Collected tests: 1808 -> **1147**;
  collection after cleanup took 0.26 s. Subtests are counted separately.
- Final `python -m pytest -q`: **1129 passed, 18 skipped, 55 subtests passed**,
  exit 0, 75.06 s. All 18 skips are symlink fixture privilege limitations on Windows
  (corpus 5, acceptance 4, lexical guards 7, model assets 1, exact pilot 1).
  Junction/reparse coverage and configured Rust interop ran; skipped cases are not PASS.
- Rust default tests: 7 library + 1 CLI passed. Semantic tests: 29 library +
  2 dependency-probe + 1 CLI passed, exit 0. `python -m ruff check src tests tools`
  and `git diff --check`: exit 0.
- Earlier commands failed: initial Cargo build exit 101 because existing GCC was
  absent from process PATH; adding `C:/msys64/ucrt64/bin` produced build exit 0
  (3m42s). First Python Regression stopped at collection with exit 2 because a
  historical legacy wrapper referenced deleted source-inventory authority; the
  wrapper was simplified before the successful run. Initial semantic test run had
  28 passed/1 failed from an obsolete fixed configuration digest assertion; standard
  SHA vectors and actual product/config binding tests remain and the rerun passed.
- Removed 204 tracked historical report files: **17,597,410 measured bytes**.
  Separately removed six inactive local authorization/permanent-reservation files:
  **102,702 bytes**; all six paths were then confirmed absent. Snapshot input ledgers,
  formal products, original review datasets and P1 receipts were retained.
- No installation, Python native-extension build, FULL GPU/ANN rebuild or quality
  acceptance was performed. The patched Python-native path remains unvalidated.

Reproduce Regression with process-local `PYTHONUTF8=1`,
`PYTHONIOENCODING=utf-8`, UCRT64 compiler PATH and
`CARGO_TARGET_DIR=D:/SakuraTool/SakuraKnowledge/build/p4-usearch-native-fix/rust-target`;
set `SKNOW_RS_TEST_BIN` to that target's `debug/sknow-rs.exe`. Run
`python -m pytest -q`, `cargo test --manifest-path rust/Cargo.toml`,
`cargo test --manifest-path rust/Cargo.toml --features semantic`, Ruff and diff checks.
Acceptance is a separately authorized real-product operation, not another routine matrix.
