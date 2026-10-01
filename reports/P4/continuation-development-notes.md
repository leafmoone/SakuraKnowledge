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
- After all gold/pilot/chunk prerequisites, model A bulk attempt1 explicitly
  requested CUDA/float32/batch8. Command exit1 during first-batch token-ID check
  after weights loaded, before encoder forward. Raw/HF tokenizer ID mismatch
  is retained in continuation-embedding-a-command.json. Partial dense-a-v1
  artifacts are failure evidence, not usable vectors; do not overwrite/delete.
  Tokenizer-only diagnosis reproduced AutoTokenizer 5.12.1 backend reconstruction:
  row6 document325809 loses trailing whitespace ID6. Serialized-backend generic
  wrapper preserves all backend fields and passes first batch plus11 probes;
  see continuation-tokenizer-a-diagnostic.json. Serialization-preserving fix
  committed32429fcc141d8a378bc2cecc4d2393c40fa41096; ID/budget guards retained.
  Full tokenizer-only scans now PASS:52664 chunks and120 queries per model,
  max passage tokens A388/B386, elapsed A56.551444s/B60.108494s. Both verify
  frozen bindings before/after and load no models; see parity-a/b JSON receipts.
  Scan-helper worker server error produced no files; parent implemented helper.
  Two pwsh launch attempts failed (shell unavailable), no scan executed; actual
  scans used bash with python -X utf8. A explicit corrected build exit0 into
  continuation-dense-a-retry1:52664x384 float32 CUDA vectors,226.412284s,
  232.602221 chunks/s. Original failure retained; B build now running.
  Independent A index hash/shape/finite/normalization verification exit0;
  first auxiliary verification exited1 due to nonexistent DiskMapping.close
  after checks; corrected connection.close run has separate command receipt.
  Build writes index/index.json, not job.output (initial read of latter failed).
  No threshold changes or automatic retry loops.
- Both model-specific chunk projections passed52664 chunks/0 empty each; equal
  counts do not imply identical inventories. BM25 prepare and120-case query
  commands passed against same frozen50000 documents. No quality score claimed.
- No findings here authorize FULL execution or alter quality thresholds.
