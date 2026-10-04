# AGENTS.md

## Project Rules

- SakuraKnowledge is an independent offline knowledge core. Do not modify SakuraPool, SakuraTool global configuration, or unrelated repositories.
- Work on the current branch with ordinary commits only. Do not amend, rebase, reset, force-push, or modify/create `main` without explicit authorization.
- Before review, push the intended `dev` commit normally and verify `git ls-remote origin refs/heads/dev` equals the local HEAD. A failed push or SHA mismatch blocks review.
- Preserve user or other-agent work in the working tree. Inspect existing changes before editing and stage only named intended files.

## Entry Points

- Package metadata and CLI entry point: `pyproject.toml`, `sknow` -> `sakura_knowledge.cli:main`.
- Source modules: `src/sakura_knowledge/`.
- Tests: `tests/`; normal checks are `python -m pytest -q`, `python -m ruff check src tests tools`, and `git diff --check`.
- Design and contract: `docs/architecture.md`, `docs/data-contract.md`, and `docs/source-adapters.md`.
- Current delivery status: `docs/STAGE_STATUS.md`; portable export/assembly: `tools/portable_export.py`, `tools/portable_pack.py`. Keep gold/reference evidence; do not replace receipts with claims.

## Evidence Boundaries

- Inputs are read-only. Freeze and hash source bytes before ingestion; do not mutate upstream datasets in place.
- Publish snapshots atomically only after integrity, foreign-key, FTS, ledger, input-digest, and source-account checks. Never overwrite an existing output snapshot.
- Keep real-source observations, normalized records, fixtures, candidates, verified links, and human review distinct. Fixture success is not real-source validation.
- `kind`, `namespace`, and `value` are a typed identity boundary. A spelling, title, confidence score, candidate link, or cross-namespace similarity does not establish identity.
- Identity trust is source-backed only. Generated evidence may support text/FTS under a source-backed identity, but must not create an identity or verified mapping alone.
- Local aggregate tags are not native `danbooru.tag` identities. Candidate mappings are never silently promoted; report `unknown`, `ambiguous`, or `target_unmapped` when evidence is insufficient.
- Preserve source/evidence IDs, raw payloads, locators, and unresolved reasons. Do not infer `character_of`, Bangumi person joins, or tag membership from raw names alone.

## Integration Boundaries

- Basic core has no models/GPU/services/ORM/Pool. Optional CPU semantic runtime uses explicit frozen local model/index assets; queries never build/download. Runtime exports/I8 builds create new outputs only; preserve mother DB, original mapping, FP32 vectors/index and valid older packs.
- Pi Skill runtime integration, SakuraPool integration, and full human source-fact review require explicit execution and evidence; do not mark them complete from static files or unit tests.
- Do not claim a live upstream refresh when only a frozen local cut was audited and built.

## Reporting

- State exact commit, snapshot, manifest, wheel, command, exit code, and limitation where relevant.
- Keep `NOT_RUN`, `BLOCKED`, and knowledge gaps explicit. Never convert an ambiguous or failed command into PASS by interpretation.
- For Windows CLI JSON with non-ASCII text, use an explicitly verified UTF-8 environment and retain stderr/exit-code evidence.
