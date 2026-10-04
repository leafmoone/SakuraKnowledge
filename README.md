# SakuraKnowledge

Independent offline knowledge core: Python 3.11+ and a read-only Rust CLI. Basic structured queries need no model/GPU/service/Pool. Optional semantic retrieval uses the locally prepared CPU model and evidence-preserving hybrid pack. Current dev delivery: **runtime120 PASS / quality FAIL** (semantic Recall@10 .975 < original target1); usable with that known limitation, not independently generalized.

## Windows local entry (PowerShell 5.1+)

From this repository (not a portable standalone distribution):

```powershell
$env:PATH='C:/msys64/ucrt64/bin;'+$env:PATH
$env:CARGO_TARGET_DIR='build/p4-usearch-native-fix/rust-target'
cargo build --release --manifest-path rust/Cargo.toml --features semantic --bin sknow-rs --bin semantic_pilot
./scripts/sknow.ps1 --help
./scripts/sknow.ps1 lookup '初音ミク'
./scripts/sknow.ps1 search '中文 日本語' --limit 5
./scripts/sknow.ps1 resolve-tag '初音ミク' --target-namespace danbooru.tag
./scripts/sknow.ps1 retrieve 'blue hair character' --limit 5
./scripts/sknow.ps1 retrieve '中文 日本語 "quoted words"' --limit 5
```

Launcher defaults are explicit in `scripts/sknow.ps1`: DB
`build/p3-full-authorized-retry1/knowledge.sqlite`, pack
`build/p4-dev-2048-1mib-3ee34e2-v1/manifest.json`, release executables in the Cargo target above.
It resolves paths relative to itself and forwards native arguments, UTF-8 and exit codes;
queries **never** compile/download/build indexes. Basic commands need only the executable
and frozen DB; `retrieve`/`serve` additionally require the manifest-bound BGE-M3 CPU model,
tokenizer, ONNX Runtime DLL, frozen mapping/ANN and prepared membership. These local assets
are not shipped by git. See `python -m tools.p4_full_build --help` for explicit create-new
preparation commands; source/model preparation is a separate operation, not automatic.
The build needs the existing Rust/native toolchain (including local UCRT64 tools); no
installer or global environment changes are performed. Missing paths produce explicit errors.
For custom paths use the native CLI directly: `sknow-rs retrieve DB MANIFEST QUERY`.

Resident mode amortizes model/index opening, accepts one JSON object per line, emits an
`opened` event then one complete result per request, and exits naturally on stdin EOF:

```powershell
# UTF-8 input stream (ASCII JSON escapes also preserve Japanese on older shells).
'{"case_id":"one","query":"\u521d\u97f3\u30df\u30af","limit":5}' |
  powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/sknow.ps1 serve
```

For interactive/multiple requests start `powershell -NoProfile -File ./scripts/sknow.ps1 serve`
and send JSONL on stdin. `lookup/search/related/ask/resolve-tag` are structured exact/alias/
FTS/template operations, not arbitrary semantic QA; descriptive prompts belong to `retrieve`.
Results retain source/evidence IDs and typed keys: candidates are not verified tag mappings.
Semantic single and resident responses share **1MiB serialized UTF-8 including newline**;
clients must match this budget. Oversize returns explicit FAIL, never a truncated success.
Single-query startup cost is additional to retrieval; resident5s evidence does not claim a
cold single process finishes under5s. Default ef2048/wanted512/entity100, no reranker.
Pi integration and portable asset packaging are **NOT_RUN**.

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
