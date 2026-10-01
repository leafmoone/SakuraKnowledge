# P4 preparation limitations (not acceptance)

Base: 269e34eeeac920c29f2d684cfe37c93a95c73057.

- Initial whole FULL hash/size check passed; no rebuild or source SQLite write.
- Initial pytest with no explicit Rust fixture binary: 654 passed, 130 skipped.
  This was NOT legacy regression evidence. After contained default release/examples
  compilation and explicit SKNOW_RS_TEST_BIN: 783 passed, 1 skipped (Windows
  symlink creation privilege). These dirty-preparation checks are not the final
  fixed-code matrix. Their original receipts remain intact.
- Default compilation explicitly overrides inherited external CARGO_TARGET_DIR
  with project build/p4-cargo-target and local command environment compiler paths.
  No global configuration change and no Pool directory inspection/write performed.
- Early p4_snapshot_check Ruff ISC004 and gold/audit/corpus lint failures were real
  preparation failures, corrected separately; do not imply first-attempt all PASS.
- Source-gold authoring initially compared entire stat_result, including atime;
  a read can change that metadata. Draft authoring used a size/mtime-only wrapper;
  helper subsequently changed to those explicit invariants. Draft remains draft,
  not a fully verified reusable gold freeze pipeline or full human fact review.
- Gold draft has 120 cases but reuses 40 primary targets and related passages;
  case count is not independent entity count. Missing required source coverage
  is explicitly disclosed in that draft. Do not benchmark it as fully approved gold.
- A new untracked uv.lock appeared during delegated preparation. Its producer is
  not yet proven; it is preserved and not staged or deleted as incidental output.
- Model API inspection resolves exact revisions but is not completed asset/hash
  freezing. Mutable README fetches were discovery only, not pinned asset evidence.
- No original external P3 preservation bytes are accessed. Any historical expected
  reconstruction must independently match the original byte count and SHA256;
  accepted Rust output alone is not a new independent oracle.
- Corpus coverage cannot be created by interpreting raw JSON status claims,
  promoting unverified_draft, embedding candidate mappings or patching FULL.
- CPU/GPU configurable interfaces and replaceable model contracts are design and
  preparation requirements, not implemented production semantic runtime evidence.
