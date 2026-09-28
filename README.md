# SakuraKnowledge — P1 incomplete baseline

Python 3.11+ standard-library offline knowledge core; no models, GPU, ORM, services or Pool imports. **NOT_READY / WAITING_REVIEW**: only the explicit normalized JSONL contract adapter is implemented. Real-source integration is not claimed.

## Installation and CLI

```
python -m pip install .
sknow inspect manifest.json
sknow sources check --output metadata/bangumi-latest.json
sknow build manifest.json new-snapshot-directory
sknow verify new-snapshot-directory/knowledge.sqlite
sknow lookup snapshot/knowledge.sqlite 1 --key --kind character --namespace bangumi.character
sknow search snapshot/knowledge.sqlite 中文 --limit 20 --kind character
sknow related snapshot/knowledge.sqlite 1 --kind character --namespace bangumi.character --relation character_of --limit 20
sknow ask snapshot/knowledge.sqlite 孤独摇滚
```

Only `sources check` performs network I/O, fetching Bangumi latest metadata, never a dump. All queries are read-only and offline. JSON results go to stdout; operation errors to stderr, exit 2. Failed metadata checks / verification exit 1; business not_found/ambiguous exits 0. Argument help follows argparse conventions.

`lookup` accepts exact values or reliable aliases, with optional kind/namespace; `--key` requires both filters. `search` uses exact-first, FTS BM25 and deterministic ties, limit 1..100. `related` is outgoing one-hop, default 20, max 100. `ask` is deterministic exact-entity-to-explicit-tag lookup, **not natural language question interpretation**. Missing mappings remain null, never inferred from names or a model.

Build inputs: JSON manifest (supports explicit nulls) plus UTF-8 JSONL, see `docs/data-contract.md`. Existing output directories are never overwritten. Tests generate clearly labeled fixtures and are not real-source evidence.

```
python -m pytest -q
python -m ruff check --isolated --select E4,E7,E9,F src tests tools
```

See `reports/P1/P1_REPORT.md` for evidence, source blockers and incomplete requirements.
