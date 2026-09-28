# P1 baseline handoff — NOT_READY / WAITING_REVIEW

## Exact implementation and package evidence

Code baseline: `30dc5695d16a6be45f36fbf977cc028882086582` on dev. Report-only commit follows; its SHA is the final handoff HEAD, not the wheel source SHA. No code changed between baseline commit and wheel tests. Wheel: `dist/sakura_knowledge-0.1.0-py3-none-any.whl`, SHA256 `9d7c78e0f0ad37b89e87a78238e6af38a90df72e9818b18f4873e3247ab3bf35`, 12495 bytes, built and installed in project-local `.venv-wheel`. Runtime Python 3.14.5, SQLite 3.50.4; CPU recorded in validation.json. The wheel is local ignored output, not checked into Git.

Implemented files: src/sakura_knowledge/{model,storage,api,cli,safety,mapping}.py; tests/test_core.py and test_mapping.py; docs; README; independent Skill; example config; explicit audit tools. Schema includes all requested table names. Implemented normalized-contract JSONL fixture pipeline with input SHA locking, row transactions, basic verification, new-directory publication, read-only lookup/search/related/ask, CJK tokenization, candidate isolation and defensive ZIP extraction. **No real-source adapter is implemented or claimed compatible.**

## Commands and results

- `git init -b main; git switch -c dev`: empty independent repository. Main remains unborn, with no main commit/ref created. No historical baseline exists here.
- `git -C ../SakuraPool remote -v`: read-only account clue leafmoone.
- `git ls-remote https://github.com/leafmoone/SakuraKnowledge.git refs/heads/main refs/heads/dev`: repository not found. No origin configured, no push attempted, no remote review SHA.
- Workspace globs found no Bangumi JSONL, char_index, tag_wiki/Danbooru inputs or handoff file. Pool rules read; no large image SQLite/TAR opened. Pool files were not edited.
- `PYTHONPATH=src python -m sakura_knowledge.cli sources check --output metadata/bangumi-latest.json`: actual HTTP 200; upstream name/digest/time retained. Actual recorded latest asset is 441318128 bytes. No guessed user-date cutoff. No full dump download in this bounded run.
- `python tools/audit_public.py`: public tree 200; two initially guessed source paths 404. `python tools/audit_tree_sources.py` fetched corrected paths at fixed tree revision. Original failed request evidence retained. No upstream Python executed.
- `python -m pytest -q`: **12 passed, 0.23s**.
- `python -m ruff check --isolated --select E4,E7,E9,F src tests tools`: **PASS**. Initial ambient stricter lint found 7 issues; strict lint compliance is not claimed.
- `python -m pip wheel . --no-deps -w dist`; `python -m venv --system-site-packages .venv-wheel`; local wheel install; `.venv-wheel/Scripts/python -m pytest -q -o pythonpath=`: **12 passed, 0.23s**. Imported module path verified inside local venv site-packages, not src. Development pytest/ruff inherited from host; wheel runtime has no dependencies.
- `.venv-wheel/Scripts/sknow --help`: PASS. Initial editable install was made in the current host interpreter before local wheel validation; no SakuraPool-specific environment was opened or targeted. This host-interpreter side effect is disclosed, not represented as isolated packaging validation.

Behavior tests cover four same-number Bangumi identities, original-site isolation, image/Archive namespace separation, seven group constant, candidate multiplicity/empty/reverse inconsistency and character-space audit, missing candidate targets, entity without tag, draft isolation, episode key/no FTS, punctuation/SQL/FTS input, readonly writes, atomic existing-output/digest refusal, duplicate accounting, unresolved links and unsafe ZIP paths/hash. These are fixture tests, not source existence proof or human factual review.

## Mandatory gaps / follow-up

Four real source integrations BLOCKED by missing delivered input files and unfinished real adapters. Public Moegirl data availability does not equal local validated integration. Need inspect all nine Bangumi file schemas, person_type codes, raw relation fields, date/tag/infobox fidelity; Moegirl actual structure/body and category semantics; both wiki schemas/namespaces; actual mapping missing/redirect/conflict reconciliation. No real formal build or small factual evaluation ran. No complete coverage of the user-required test matrix. No inferred tag for 孤独摇滚: unknown or entity_found_tag_unmapped with null tag_key, depending on actual entity presence.

Engineering gaps documented in architecture/data-contract: bounded-memory dedup, per-type reconciliation, durable rejection reports, metadata typing/inventory validation, conflict quarantine, same-entry source-version history, alias-only top-level citations, streaming link resolution independent of input order, complete FTS verification/token boundaries and stricter public result contracts. Example TOML is intentionally non-buildable until real metadata is supplied. Source package sdist and CLI end-to-end JSON subprocess tests NOT_RUN. Performance peakRAM/p50/p95 and real SHA/count/FTS measurements NOT_RUN, not fabricated.

## Final status

- ENGINE_TESTS: PASS (12 baseline tests only)
- BANGUMI_INTEGRATION: BLOCKED
- MOEGIRL_INTEGRATION: BLOCKED
- DANBOORU_WIKI_INTEGRATION: BLOCKED
- TAG_WIKI_INTEGRATION: BLOCKED
- CROSS_SOURCE_MAPPING_AUDIT: PARTIAL (pinned source inspection + fixture auditor; actual mapping statistics NOT_RUN)
- SOURCE_REFRESH_STATUS: Bangumi METADATA_CHECKED_HTTP_200_DUMP_NOT_FETCHED; Moegirl CODE_TREE_AND_TWO_PINNED_SOURCES_CHECKED_DATA_NOT_FETCHED; Danbooru wiki/tag_wiki LOCAL_FILES_NOT_FOUND_REMOTE_NOT_CHECKED
- PI_SKILL_INTEGRATION: NOT_RUN
- REMOTE_DEV_VERIFIED: NO
- MAIN_MODIFIED: NO (unborn)
- SAKURAPOOL_MODIFIED: NO
- SAKURATOOL_INTEGRATION_STARTED: NO
- P1_RESULT: NOT_READY
- STOP_STATE: WAITING_REVIEW

This is a local incomplete baseline for handoff, not a completed P1 acceptance or remote submission. Remaining blockers are explicit and do not retroactively negate authorization for local work.
