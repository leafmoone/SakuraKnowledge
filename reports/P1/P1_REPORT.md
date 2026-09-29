# P1 baseline handoff — NOT_READY / WAITING_REVIEW (full pipeline now runs end-to-end)

## SHA binding (three roles, recorded separately)

| Role | SHA | Note |
|---|---|---|
| Converter (adapter + normalized JSONL) | `7afe7fb0e234455f070cf0311619d86423e55d87` | normalized inputs `build/real-full-7afe7fb/`; manifest SHA256 `7e1592a61452d437ae46fab589317d2ac7b10c5a02c6c966097fa679a963a57c` |
| Builder (schema/index/verification) | `20bf5b315e47f1c7038af06307424bb734efcc10` | built `build/snapshot-full-20bf5b3/` (21,516,320,768 bytes) from the unmodified 7afe normalized inputs — no reconversion was needed because adapters did not change |
| Query API + wheel | `3cad90cce7d415f21e470a222cf26a2c85da159b` | wheel `build/wheel-fix-3cad90c/sakura_knowledge-0.1.1-py3-none-any.whl`, SHA256 `e0041b73eac3e37009fb6680f2b06b84bdf1cea5fbb12e3b05770b36dc9082d7`, 23,026 bytes |

History retained, never amended: `573947f` (first hardening), `7afe7fb` (source isolation + full-text fidelity + FTS verify), `c65f19d` (target-tag API semantics), `20bf5b3` (full-scale indexes + distinct target cardinality). The earlier 7afe full snapshot (`build/snapshot-full-7afe7fb/`, 21,071,904,768 bytes) built and verified EXIT 0 but **failed a real query** (`query_budget_exceeded` on `ask`, root cause: `SCAN documents`, missing `documents.entry_id` index). It is retained as failing-query evidence, not migrated, not relabeled.

## Commands and results (20bf5b3)

- `python -m pytest -q`: **34 passed, 1.82s, EXIT 0**. `python -m ruff check src tests tools`: PASS. `git diff --check`: PASS. New coverage includes bounded ask templates and identity/text trust separation.
- Real sample at the fixed SHA: `build/real-sample-20bf5b3-snapshot` — build + `verify` EXIT 0 (145 entries, FTS 44/44).
- Full build: `python -m sakura_knowledge.cli build build/real-full-7afe7fb/manifest.json build/snapshot-full-20bf5b3` — **EXIT 0, 10,483.5s, peak RSS 153,587,712 bytes** (`build/build-full-20bf5b3.json`). Process temp env verified before spawn: TMP/TEMP/TMPDIR/SQLITE_TMPDIR all actually resolved to `build/build-temp-20bf5b3` (D: project area, not global); sampled temp-directory peak 30,541,848 bytes (`build/build-full-20bf5b3-temp.json`). D: free 463.4 GB before / 443.4 GB after.
- Full verify (standalone, read-only, own D: temp): **EXIT 0** — `ok`, integrity ok, FTS 1,295,638/1,295,638, 0 missing/invalid, ledger clean, entries 3,734,547, rejected 0, conflicted 0, unresolved {missing_endpoint 15,901, unresolved_wiki_link 78,995} (`build/verify-full-20bf5b3.json`).
- Reconciliation (machine-readable): `reports/P1/full-reconciliation-20bf5b3.json`. Key closures: Danbooru 79,947 converter unresolved − 952 byte-identical duplicate rows = 78,995; wiki links 1,022,285 − 24,445 duplicates = 997,840 (24,445 + 952 = 25,397 duplicate lines); tag_wiki 193,494 candidate lines = 2 × 96,747 byte-identical pairs (frozen `tag_evidence` table itself stores each candidate twice; dataset_id is NULL in all rows; no dataset/evidence/locator lost); missing_endpoint 15,901 = Bangumi 15,892 (credit_person 7,749 / subject_relation 7,304 / features_character 832 / character_relation 7; endpoints absent from the same archive cut, checked ID-scheme consistent) + mapping 9 (bangumi character IDs absent from cut).
- Query performance on the 21.5 GB snapshot (`build/query-perf-20bf5b3.json`, 5 reps/workload, per-op 5 s budget): **0 budget failures**. p50/p95 ms: local-tag ask 0.037/0.047, ask with danbooru target 0.038/0.043, exact-key lookup 0.062/0.069, value lookup 0.038/0.045, alias lookup 0.062/0.068, 2-char alias search 0.52/0.54 and 0.80/0.80, English search 16.6/18.2, high-degree related (subject 975, 2,017 trusted outgoing links) limit 100 5.6/6.1 and limit 10 4.4/4.5, page-without-tag ask 0.077/0.079. ORDER BY/GROUP BY temp B-trees remain a documented spill risk at larger fan-out; nothing claims constant memory.
  - **Receipt defect, disclosed (P2, report-only correction):** the two CJK rows were measured with mixed ASCII+CJK alias terms `\u0030\u4eba` (0人) and `\u0030\u53f7` (0号) — the v1 receipt file itself stores correct UTF-8; only the console rendering was mojibake — and its timestamps were second-precision local time, so started_at equals completed_at because the whole suite ran in under a second. The terms above are recovered from the v1 receipt bytes (archived at `build/query-perf-20bf5b3.v1-defective.json`); per instruction the workload was **not** re-measured and no times or terms were invented. These rows therefore evidence 2-char alias search, not pure-CJK prose search. Independent reviewer cross-check on the same snapshot: `search('孤独摇滚')` = 499.9 ms, `found`, 20 candidates, all with citations. `tools/measure_queries.py` was fixed for future receipts (sub-second UTC ISO times, deterministic pure-CJK term filter, `ensure_ascii=True`).
- Wheel CLI smoke receipt: `reports/P1/cli-wheel-smoke-3cad90c.json`. Using the already-built wheel in `build/isolated-fix-3cad90c`, outside the source tree, with `PYTHONIOENCODING=utf-8` and no traceback: `sknow --help`, real Moegirl lookup, and the requested Danbooru ask all exited 0 with empty stderr. The ask template and `target_namespace=danbooru.tag` were correct, but the real result was `entity_ambiguous` before target mapping, not `target_unmapped`; `tag_key=null`, and no tag was fabricated. Therefore `CLI_WHEEL_SMOKE=NOT_READY`, not acceptance PASS evidence.

## What the data says (not acceptance language)

- Counts (build_report): Bangumi 6,695,782 input → 6,679,889 accepted (duplicate 1, unresolved 15,892); moegirl 51,591 → 51,557 (duplicate 34); mapping 97,279 → 97,270 (unresolved 9); Danbooru 1,397,729 → 1,293,337 (duplicate 25,397, unresolved 78,995); tag_wiki 1,543,062 → 1,446,315 (duplicate 96,747).
- **Knowledge gap, stated as-is:** the audited local sources contain no native `danbooru.tag` identities. The seven tag-occurrence tables are preserved as `local.tag_aggregate` with dataset occurrences; a spelling match, wiki title, confidence value or candidate link never promotes a local tag into `danbooru.tag`. `ask(..., target_tag_namespace="danbooru.tag")` returns `target_unmapped` with `tag_key=null` — that is the honest answer, not a test to be gamed.
- Tag-wiki `tag_evidence` confidence=1.0 / exact_title and model `annotations` are retained as candidate/unverified material only; verified entity_tag edges do not exist in this cut.

## Mandatory gaps / follow-up

- `real_small_evaluation`: PASS — 26/26 contract cases remain unchanged in `reports/P1/real-small-eval.json`; this is a small real-data behavior check, not a full-database factual review.
- `MOEGIRL_STRUCTURED_FIELD_EVAL`: PASS — `moegirl.character/"加特"` fields `raw_attributes`, `raw_subject_categories`, `raw_cv_names`, and `raw_gender` match normalized line 1 and snapshot payload exactly; no Danbooru tag, `character_of`, or Bangumi person inference.
- `pi_skill_integration`: NOT_RUN (Skill file updated; actual Pi runtime never exercised).
- `human_fact_review`: NOT_RUN; no model synthesis used.
- High-fan-out ORDER BY temp-B-tree spill and O(F) index-set memory at scales beyond the tested node are documented risks, not measured at that scale.
- Trust split audit: snapshot has 0 `generated_from_evidence` rows, 0 entries with generated-only trusted evidence, 0 generated aliases without identity evidence, and 0 verified `entity_tag` edges; no 21.5GB rebuild was required. Full counts are in `reports/P1/trust-stats-20bf5b3.json`.
- `FULL_REBUILD_PERFORMED=NO`: current work uses the fixed snapshot only.
- Remote repository: private `https://github.com/leafmoone/SakuraKnowledge`; final SHA verification is recorded after the report commit. Main branch not touched.

## Final status

- ENGINE_TESTS: PASS (34)
- BANGUMI_INTEGRATION: LOCAL_AUDITED_AND_BUILT (real cut, read-only; upstream refresh not re-verified this session)
- MOEGIRL_INTEGRATION: LOCAL_AUDITED_AND_BUILT
- DANBOORU_WIKI_INTEGRATION: LOCAL_AUDITED_AND_BUILT (native tag identities absent — gap, see above)
- TAG_WIKI_INTEGRATION: LOCAL_AUDITED_AND_BUILT (frozen byte-backup; live source never written; candidate duplication documented)
- CROSS_SOURCE_MAPPING_AUDIT: LOCAL_BUILT, 97,270 candidate links, 9 unresolved, zero promotion to verified
- FULL_PIPELINE_ON_FIXED_INPUTS: PASS (convert→build→verify→query→wheel, all receipts above)
- PI_SKILL_INTEGRATION: NOT_RUN
- HUMAN_FACT_REVIEW: NOT_RUN
- ASK_TEMPLATES: PASS (bounded deterministic Chinese templates, verbatim subject extraction, unsupported warning)
- IDENTITY_TEXT_TRUST_SPLIT: PASS (identity source_backed only; text allows generated_from_evidence)
- REAL_SMALL_EVALUATION: PASS (26/26 unchanged)
- MOEGIRL_STRUCTURED_FIELD_EVAL: PASS
- CLI_WHEEL_SMOKE: NOT_READY (commands exit 0, requested ask is entity_ambiguous rather than target_unmapped)
- REMOTE_DEV_VERIFIED: pending final push verification
- MAIN_MODIFIED: NO
- SAKURAPOOL_MODIFIED: NO
- P1_RESULT: NOT_READY (CLI real-question acceptance is blocked by source ambiguity; Pi runtime and human source-fact review remain NOT_RUN)
- STOP_STATE: WAITING_REVIEW
