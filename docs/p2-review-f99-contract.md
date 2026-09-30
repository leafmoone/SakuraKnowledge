# f99a115 directed review repair contract

This supplements response v3 only; storage/search text remain version 2. No
production snapshot migration, R4 reopening or upstream refresh is performed.

1. One five-second operation deadline covers nested queries, field projection,
   streaming JSON-size calculation, linear tail removal and final/error paths.
   Python inspect participates. Document titles are projected at 256 Unicode
   characters before response construction, with `title_truncated: true` only
   when shortened. Identity values/keys are never truncated. Whole-response
   serialization is no longer repeated for each removed candidate.
2. Rust Latin-start continuation uses Unicode16 ALNUM only. Kana punctuation and
   combining marks do not become word characters merely by occupying a CJK block.
3. Introduce/tag subjects trim Python-equivalent whitespace, including U+001C–1F.
   Nonwhitespace U+200B and literal identity strings remain unchanged.
4. Rust uses serde RawValue for unprojected JSON: deep ignored containers are
   skipped, not recursively materialized. Only displayed field subtrees recurse,
   at depth <=4 with <=16 children per container. SQLite payload byte limit remains
   two million. No unlimited-recursion feature is enabled.
5. Field scalar contract: strings <=256 characters; integers in [-2^63,2^64-1],
   booleans/null and finite JSON floats retained. Integers outside that interoperable
   domain become value=null, truncated=true, value_state=present. Every projected
   value remains <=2048 UTF-8 JSON bytes; containers recursively apply the rule.
   Stored source payload/raw is unchanged, including arbitrarily large integers.
6. Identity proof display remains capped at100. When proofs are capped, all four
   field names are explicitly present in source_fields_truncated: field absence
   cannot be mistaken for complete evidence. Ordering is independent of insert order.
7. Open checks virtual-table identity, actual hidden FTS5 rank/table columns and
   prepares MATCH/BM25/rank together with LIMIT0. No data scan; failed open closes.
8. Harness validates success/error JSON shape before .get. Malformed shapes fail
   that case with retained raw, never abort the run or block the next case.
9. New receipt binding hashes exact `git show COMMIT:PATH` bytes. Checkout hashes
   are separate observations, not substituted. Historical f99 receipt_index is
   superseded by review-f99-historical-binding.json, which binds all28 historical
   JSON files without rewriting any historical receipt. New review-f99 JSON has
   -text attributes to preserve exact bytes. Metadata correction alone is not an
   artifact rebuild; new runtime artifacts require their own clean code commit.

Independent fixtures: tests/test_review_f99.py, test_review_f99_harness.py,
 test_review_f99_binding.py; Rust review_f99_forced_deadline_covers_errors_inspect_and_projection.
Before/after receipts are separate new paths. These tests establish synthetic
contract behavior, not human validation of upstream source facts.
