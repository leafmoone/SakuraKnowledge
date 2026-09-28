# P1 baseline handoff — NOT_READY / WAITING_REVIEW (full pipeline now runs end-to-end)

## SHA binding (three roles, recorded separately)

| Role | SHA | Note |
|---|---|---|
| Converter (adapter + normalized JSONL) | `7afe7fb0e234455f070cf0311619d86423e55d87` | normalized inputs `build/real-full-7afe7fb/`; manifest SHA256 `7e1592a61452d437ae46fab589317d2ac7b10c5a02c6c966097fa679a963a57c` |
| Builder (schema/index/verification) | `20bf5b315e47f1c7038af06307424bb734efcc10` | built `build/snapshot-full-20bf5b3/` (21,516,320,768 bytes) from the unmodified 7afe normalized inputs — no reconversion was needed because adapters did not change |
| Query API + wheel | `20bf5b315e47f1c7038af06307424bb734efcc10` | wheel `build/wheel-20bf5b3/sakura_knowledge-0.1.1-py3-none-any.whl`, SHA256 `fbb9333990d4fc32f1eb2f681914faad5f7bd953c47acc1839f22d6d98794e7a`, 21,683 bytes |

History retained, never amended: `573947f` (first hardening), `7afe7fb` (source isolation + full-text fidelity + FTS verify), `c65f19d` (target-tag API semantics), `20bf5b3` (full-scale indexes + distinct target cardinality). The earlier 7afe full snapshot (`build/snapshot-full-7afe7fb/`, 21,071,904,768 bytes) built and verified EXIT 0 but **failed a real query** (`query_budget_exceeded` on `ask`, root cause: `SCAN documents`, missing `documents.entry_id` index). It is retained as failing-query evidence, not migrated, not relabeled.

## Commands and results (20bf5b3)

- `python -m pytest -q`: **32 passed, 1.13s, EXIT 0**. `python -m ruff check src tests tools`: PASS. `git diff --check`: PASS.
- Real sample at the fixed SHA: `build/real-sample-20bf5b3-snapshot` — build + `verify` EXIT 0 (145 entries, FTS 44/44).
- Full build: `python -m sakura_knowledge.cli build build/real-full-7afe7fb/manifest.json build/snapshot-full-20bf5b3` — **EXIT 0, 10,483.5s, peak RSS 153,587,712 bytes** (`build/build-full-20bf5b3.json`). Process temp env verified before spawn: TMP/TEMP/TMPDIR/SQLITE_TMPDIR all actually resolved to `build/build-temp-20bf5b3` (D: project area, not global); sampled temp-directory peak 30,541,848 bytes (`build/build-full-20bf5b3-temp.json`). D: free 463.4 GB before / 443.4 GB after.
- Full verify (standalone, read-only, own D: temp): **EXIT 0** — `ok`, integrity ok, FTS 1,295,638/1,295,638, 0 missing/invalid, ledger clean, entries 3,734,547, rejected 0, conflicted 0, unresolved {missing_endpoint 15,901, unresolved_wiki_link 78,995} (`build/verify-full-20bf5b3.json`).
- Reconciliation (machine-readable): `reports/P1/full-reconciliation-20bf5b3.json`. Key closures: Danbooru 79,947 converter unresolved − 952 byte-identical duplicate rows = 78,995; wiki links 1,022,285 − 24,445 duplicates = 997,840 (24,445 + 952 = 25,397 duplicate lines); tag_wiki 193,494 candidate lines = 2 × 96,747 byte-identical pairs (frozen `tag_evidence` table itself stores each candidate twice; dataset_id is NULL in all rows; no dataset/evidence/locator lost); missing_endpoint 15,901 = Bangumi 15,892 (credit_person 7,749 / subject_relation 7,304 / features_character 832 / character_relation 7; endpoints absent from the same archive cut, checked ID-scheme consistent) + mapping 9 (bangumi character IDs absent from cut).
- Query performance on the 21.5 GB snapshot (`build/query-perf-20bf5b3.json`, 5 reps/workload, per-op 5 s budget): **0 budget failures**. p50/p95 ms: local-tag ask 0.037/0.047, ask with danbooru target 0.038/0.043, exact-key lookup 0.062/0.069, value lookup 0.038/0.045, alias lookup 0.062/0.068, CJK 2-char search 0.52/0.54 and 0.80/0.80, English search 16.6/18.2, high-degree related (subject 975, 2,017 trusted outgoing links) limit 100 5.6/6.1 and limit 10 4.4/4.5, page-without-tag ask 0.077/0.079. ORDER BY/GROUP BY temp B-trees remain a documented spill risk at larger fan-out; nothing claims constant memory.
- Wheel: offline `python -m build --wheel --no-isolation` (local setuptools; an earlier isolated build attempt failed only on PyPI network for setuptools and was not used). Fresh venv `build/isolated-20bf5b3`, `pip install --no-index --no-deps`, executed outside the source tree with PYTHONPATH unset: package file under site-packages, version 0.1.1, `api.py` hash equals the git source hash (`e43ed94f...c91`); real-snapshot `ask` from the wheel returns `target_unmapped`/null for the danbooru target and `local_identity_only` without a target; `sknow` CLI EXIT 0.

## What the data says (not acceptance language)

- Counts (build_report): Bangumi 6,695,782 input → 6,679,889 accepted (duplicate 1, unresolved 15,892); moegirl 51,591 → 51,557 (duplicate 34); mapping 97,279 → 97,270 (unresolved 9); Danbooru 1,397,729 → 1,293,337 (duplicate 25,397, unresolved 78,995); tag_wiki 1,543,062 → 1,446,315 (duplicate 96,747).
- **Knowledge gap, stated as-is:** the audited local sources contain no native `danbooru.tag` identities. The seven tag-occurrence tables are preserved as `local.tag_aggregate` with dataset occurrences; a spelling match, wiki title, confidence value or candidate link never promotes a local tag into `danbooru.tag`. `ask(..., target_tag_namespace="danbooru.tag")` returns `target_unmapped` with `tag_key=null` — that is the honest answer, not a test to be gamed.
- Tag-wiki `tag_evidence` confidence=1.0 / exact_title and model `annotations` are retained as candidate/unverified material only; verified entity_tag edges do not exist in this cut.

## Mandatory gaps / follow-up

- `real_small_evaluation`: NOT_RUN — no curated golden set of expected mappings scored against retrieved `tag_key`s yet.
- `pi_skill_integration`: NOT_RUN (Skill file updated; actual Pi runtime never exercised).
- `human_fact_review`: NOT_RUN; no model synthesis used.
- High-fan-out ORDER BY temp-B-tree spill and O(F) index-set memory at scales beyond the tested node are documented risks, not measured at that scale.
- Remote repository: none configured; nothing pushed. Main branch not touched.

## Final status

- ENGINE_TESTS: PASS (32)
- BANGUMI_INTEGRATION: LOCAL_AUDITED_AND_BUILT (real cut, read-only; upstream refresh not re-verified this session)
- MOEGIRL_INTEGRATION: LOCAL_AUDITED_AND_BUILT
- DANBOORU_WIKI_INTEGRATION: LOCAL_AUDITED_AND_BUILT (native tag identities absent — gap, see above)
- TAG_WIKI_INTEGRATION: LOCAL_AUDITED_AND_BUILT (frozen byte-backup; live source never written; candidate duplication documented)
- CROSS_SOURCE_MAPPING_AUDIT: LOCAL_BUILT, 97,270 candidate links, 9 unresolved, zero promotion to verified
- FULL_PIPELINE_ON_FIXED_INPUTS: PASS (convert→build→verify→query→wheel, all receipts above)
- PI_SKILL_INTEGRATION: NOT_RUN
- HUMAN_FACT_REVIEW: NOT_RUN
- REMOTE_DEV_VERIFIED: NO
- MAIN_MODIFIED: NO
- SAKURAPOOL_MODIFIED: NO
- P1_RESULT: NOT_READY (awaiting reviewer sign-off on `20bf5b3` + the NOT_RUN items above)
- STOP_STATE: WAITING_REVIEW
