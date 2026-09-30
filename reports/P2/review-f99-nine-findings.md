# Fixed-SHA f99a115 nine-finding repair evidence map

Review base: `f99a11529b0f244c6b8c59f3e66cbf51d269b0a4`.
Runtime/reference/artifact source: `5305e48bcc0f7d794bc21155cb834033256911d4`.
This maps independent expectations, not approval inferred from aggregate totals.
All new JSON receipts use byte-verbatim Git attributes. Historical raw is unchanged.

## Independent failure-first evidence

`review-f99-independent-before.json`: command exit1, **24 failed / 5 passed** on
unmodified f99 runtime/harness. This includes concrete failures for findings1–8;
normal numbers and tag whitespace controls were retained successful controls.
`review-f99-index-counterexample.json`: finding9 independently confirms **24/26**
old index entries differ from committed bytes. It does not invalidate base64 stream hashes.
`review-f99-independent-after-v2.json`: 41 new regression tests pass.
The later precise in-memory title fixture and reset assertion are covered by
`review-f99-check-pytest.json`: 150 tests pass, with Rust integration enabled.

| Finding | Actual implementation | Independent test IDs (tests/test_review_f99.py unless stated) |
|---|---|---|
| 1 R1 deadline/title/inspect | Python api/response and Rust lib/response share one deadline through field projection, streaming JSON sizing, linear tail clipping and error/final checks; titles bounded in SQL before body construction | test_r1_huge_titles_many_candidates_bounded_before_serialization[python/rust]; test_r1_reviewer_inmemory_100_titles; test_r1_inspect_final_deadline (includes next-operation reset); test_r1_error_path_checks_same_deadline; test_r1_field_and_serialization_deadline_checks; Rust review_f99_forced_deadline_covers_errors_inspect_and_projection |
| 2 R2 ALNUM continuation | rust/src/lib.rs removes CJK-block escape from Latin continuation | test_r2_separator_tokens_match_and_nonempty_fts: a・b, a\\u3099b, 256a+・; explicit tokens/MATCH, then nonempty FTS response |
| 3 R3 subject trim | introduce/tag extraction uses trim_matches(is_ws), not identity normalization | test_r3_control_whitespace_subject: U+001C–1F × both templates; test_r3_non_whitespace_not_stripped: U+200B × both templates |
| 4 R5 deep raw | RawValue skips unprojected values; only selected field containers recurse at depth4 and16 items; no unbounded_depth feature | test_r5_legal_raw_scalar_projection[deep_ignored]: actual build→insert_record accepts ignored raw list nesting130; simple field survives both runtimes |
| 5 R5 scalars | explicit interoperable integer domain, out-of-domain null/truncated, recursive2048-byte projection; stored raw unchanged | test_r5_legal_raw_scalar_projection[huge_integer/normal_numbers]; test_r5_scalar_domain_independent: signed/unsigned boundaries, adjacent out-of-domain values, float/bool/null |
| 6 R5 proof101 | cap remains bounded100, but all field names now explicitly flagged potentially truncated when identity evidence is capped | test_r5_field_after_identity_display_cap[False/True]: sole field in evidence101, forward/reverse insertion |
| 7 R6 fakeFTS | validate virtual table, hidden rank/table columns, prepare MATCH+BM25+rank LIMIT0, close on failure | test_r6_fake_fts_table_rejected: ordinary table DEFAULT 'using fts5' rejected by Python open and Rust inspect |
| 8 Harness shapes | check dict shape before get, reject malformed success/error independently and continue | tests/test_review_f99_harness.py::test_error_json_shape_fails_and_next_case_runs and test_success_json_shape_fails_and_next_case_runs: null/list/int/string through run_case; raw retained, next case executes |
| 9 Receipt binding | tools/bind_committed_receipts.py hashes exact git show COMMIT:PATH bytes; worktree measurements separate | tests/test_review_f99_binding.py::test_r9_committed_byte_binding_distinguishes_crlf; historical28-file binding; index24/26 mismatch counterexample |

## Contract decisions and limits

- Full contract: `docs/p2-review-f99-contract.md`.
- Displayed title cap256 Unicode characters; `title_truncated=true` only if shortened.
  Identity keys remain literal; irreducible oversized responses still error explicitly.
- JSON integers outside [-2^63,2^64-1] become value=null, truncated=true, state=present;
  this includes 10**2100. Raw is not rewritten. Existing finite JSON float behavior
  is retained; this is not arbitrary-precision numeric identity normalization.
- Evidence101 fix is an explicit completeness warning, not an unbounded evidence
  scan or a claim that the101st field is now displayed.
- Streamed size checking and bounded field construction avoid repeated whole-tree
  serialization. Host scheduling is not a real-time guarantee; the inner deadline
  remains5s, with failure paths checked and subprocess hard limits separate.
- Deep raw is source storage, not trusted identity or a generated mapping.
- R4 was accepted in this review and is not reopened. Main, P1, original151 cases,
  historical receipts and production snapshot are untouched.

## Separate acceptance evidence

- Formal: `review-f99-parity-v1.json`:151 accepted=135 full-value pairs+16 expected
  error contracts, zero retries; `review-f99-parity-verification.json` independently
  verifies604 raw streams. Aggregate success does not substitute for tests above.
- Seven real checks: `review-f99-check-{pytest,ruff,diff,fmt,rust-test,clippy,release}.json`.
- Clean build: `review-f99-{release,wheel}-build.json` each records empty working tree.
- Local-only new artifact bytes: `review-f99-artifact-manifest.json`; fresh offline
  install and source-external8 paired CLI checks: `review-f99-artifact-cli.json`.
- Historical hash correction: `review-f99-historical-binding.json` supersedes ONLY
  old index hash/size authority, not historical runtime outcomes. It does not claim
  to rebuild historical artifacts. New artifacts were built because runtime changed.

Performance/final snapshot/post-commit binding and final push are independently
reported in the final delivery, not inferred from the implementation tests here.
Linux/Pi/full human facts/dbstat/Pool/live upstream refresh remain NOT_RUN.
