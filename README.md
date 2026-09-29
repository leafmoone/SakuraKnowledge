# SakuraKnowledge

Python 3.11+ standard-library offline knowledge core. It uses no models, GPU, ORM, services, or Pool imports. The current P1 state is **NOT_READY / WAITING_REVIEW**.

## Local audited sources

The fixed local Bangumi Archive, Moegirl, Danbooru Wiki, and tag-wiki inputs were audited, normalized, and built into the frozen snapshot. These are `LOCAL_AUDITED_AND_BUILT` claims for the recorded local cuts, not claims of a live refresh or complete upstream truth.

The audited cut contains no native `danbooru.tag` identities and zero verified `entity_tag` links. Local aggregate tags, wiki titles, exact spellings, and candidate links therefore never become Danbooru tags. `ask` reports `target_unmapped` or `entity_ambiguous` rather than guessing. Pi runtime integration and full human fact review are **NOT_RUN**.

## Installation and CLI

```text
python -m pip install .
sknow inspect manifest.json
sknow sources check --output metadata/bangumi-latest.json
sknow build manifest.json new-snapshot-directory
sknow verify new-snapshot-directory/knowledge.sqlite
sknow lookup snapshot/knowledge.sqlite 1 --key --kind character --namespace bangumi.character
sknow search snapshot/knowledge.sqlite 中文 --limit 20 --kind character
sknow related snapshot/knowledge.sqlite 1 --kind character --namespace bangumi.character --relation character_of --limit 20
sknow ask snapshot/knowledge.sqlite "孤独摇滚 的 Danbooru tag 是什么"
```

Only `sources check` performs network I/O. All query commands are read-only and offline. JSON results go to stdout; operation errors go to stderr and exit 2. Failed metadata checks and verification exit 1. Business `not_found` and `ambiguous` results exit 0. Set `PYTHONIOENCODING=utf-8` on Windows when stdout must preserve non-ASCII JSON.

`lookup` accepts exact values or reliable aliases, with optional kind/namespace; `--key` requires both filters. `search` uses exact-first, FTS BM25, deterministic ties, and limit 1..100. `related` is an outgoing one-hop query, default 20 and max 100. `ask` supports bounded deterministic templates (`X 的 Danbooru tag 是什么`, `X 的标签是什么`, `介绍一下 X`) as well as direct entity names. The Danbooru template selects the `danbooru.tag` target but does not bypass source ambiguity. Missing mappings remain null and are never inferred from names, titles, candidates, or a model.

## Verification

```text
python -m pytest -q
python -m ruff check src tests tools
git diff --check
```

See `docs/source-adapters.md`, `docs/data-contract.md`, `docs/architecture.md`, and `reports/P1/P1_REPORT.md` for the frozen-source evidence, trust boundaries, unresolved knowledge gaps, and remaining NOT_RUN items. The normalized JSONL files are an internal audited ingestion boundary for this local build, not a substitute for source inspection or human fact review.
