# Continuation development notes (not acceptance)

- User-authorized trusted-text scope replaces the old four-source requirement;
  old coverage FAIL/STOP/DELIVERY are retained byte-for-byte.
- Existing selection/fusion/performance JSON values compared to e9ffff87 and
  unchanged before inference; quota sum50000, census sum1295638 verified.
- Initial exact-pilot synthetic tests passed12; parent metrics+exact tests70
  passed, but Ruff found12 errors. Separate lint correction is in progress.
- Parent inspection found exact-pilot summary initially used nearest-rank
  percentiles despite frozen linear (n-1)*p contract. Fix before execution.
- Initial CPU worker times embedding+exact search together and loads full index;
  user requires separate query-embedding timings. Add stage timing rather than
  mislabel total as query embedding; report fresh end-to-end scope accurately.
- Initial reused setup-failure handling fabricates30 per-case sample records from
  one failed process. Must instead disclose setup failure and NOT_RUN remaining
  samples; formal attempt count cannot be inflated. Fix before execution.
- Read-only critic confirmed these timing defects and additionally flagged:
  default30 cycling samples vs frozen each-case-once protocol; post-query RSS
  mislabeled as peak; absent bulk throughput/model/index byte totals; all-chunk
  Python mapping memory growth; count-only raw/HF tokenizer correspondence and
  missing model-summary/chunk-manifest hashes in authorization. These need
  correction and synthetic tests before real embedding authorization.
- Gold50 distinct anchor documents additionally checked for exact FTS text equality
  against d.search_text: all50 matched, no failures. First auxiliary invocation
  failed before SQL on GBK default decoding; corrected to JSON from UTF-8 bytes.
- Corpus fixes applied by parent: FTS text equality, final manifest publication
  after post-read verification, required mandatory input. Tests24 passed/5 skipped,
  Ruff PASS. Complete new audit running, not yet an observed census PASS.
- uv.lock reappeared during delegated work; exact10550 bytes and SHA256
  4fa7064f8c5b811e35a52130e4e8ae85ffd7e1806d38f4a3614c06099a922eaf.
  Preserved separately under ../SakuraKnowledge-p4-local-preserve-e9ffff/
  continuation-reappeared-1/uv.lock with external manifest; original untouched.
  Producer not conclusively attributed; use python commands, not uv run.
- No findings here authorize model execution or alter quality thresholds.
