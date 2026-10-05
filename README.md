# SakuraKnowledge

Independent offline knowledge core: Python 3.11+ and a read-only Rust CLI. Basic structured queries need no model/GPU/service/Pool. Optional semantic retrieval uses the locally prepared CPU model and evidence-preserving hybrid pack. Current dev delivery: **runtime120 PASS / quality FAIL** (semantic Recall@10 .975 < original target1); usable with that known limitation, not independently generalized.

## Adding a source

Core discovers valid installed pack manifests, not four source names. Future adapters
can build standalone normalized packs without importing the mother DB or rebuilding
other sources. See [adding a source](docs/adding-a-source.md),
[pack contract](docs/source-pack-contract.md), and [copyable example](examples/source_pack/README.md).
Generic semantic preparation is implemented; this stage validates synthetic tiny
native fixtures, not a new real source or production BGE embedding run.

## Modular Windows x64 local candidate

The modular layout separates **Core + optional source packs + one optional shared model**.
Core contains the launcher, native binaries and shared runtime DLLs, but no knowledge data
or model. Copy source directories into `packs/`; copy the shared model into `model/bge-m3/`.
Discovery uses `packs/*/manifest.json`, so removing a source directory takes effect on restart.

| Component | Capabilities | Shared model required |
|---|---|---|
| Danbooru | structured, lexical, semantic | BGE-M3 for retrieve only |
| Bangumi | structured, lexical, semantic | BGE-M3 for retrieve only |
| Moegirl | structured, exact/alias lexical | no |
| tag-wiki | structured, exact/alias lexical | no |

Moegirl has no source documents in the frozen mother DB. The new tag-wiki text candidate
adds 66,979 independently Wiki-backed generated text documents to lexical FTS; old
`no_reference`/`unverified_draft` documents remain unchanged and untrusted. This proves
text provenance, not native tag identity or verified tag/page mappings. See
[`docs/tag-wiki-provenance.md`](docs/tag-wiki-provenance.md). Neither pack
creates an ANN or needs a model. These inherited trust rules are not changed by packaging.
Source membership and actual per-source counts are in [`docs/source-groups.json`](docs/source-groups.json).

```powershell
./sknow.ps1 packs
./sknow.ps1 lookup '初音未来' --key --kind character --namespace moegirl.character --source moegirl
./sknow.ps1 search 'blue_hair' --source tag-wiki
./sknow.ps1 retrieve 'blue hair' --source danbooru,bangumi --topk 10
```

`--source` accepts repeated arguments or comma-separated IDs. Omission selects all installed
packs. Basic queries never open the model; selecting semantic retrieval without the model
reports `semantic_model_missing`, without download or substitution. Both semantic packs share
one tokenizer/model session and one query embedding per resident request.

Local assembly commands (new outputs only, no archive or asset upload):

```powershell
python -m tools.source_pack list-sources --mother build/p3-full-authorized-retry1/knowledge.sqlite
python -m tools.source_pack build --source danbooru --mother build/p3-full-authorized-retry1/knowledge.sqlite --mapping build/p4-full-semantic-v1-retry1/chunks.sqlite --output NEW_DANBOORU
# Build the native I8 graph from the existing FP32 NPY and NEW_DANBOORU/positions.u64le,
# then finalize the source manifest; no embedding encoding or new vectors.npy.
# Semantic build leaves prepared assets unpublished until the graph is present.
python -m tools.source_pack finalize --source danbooru --output NEW_DANBOORU --index-prepared
python -m tools.modular_components assemble-root --core CORE --model MODEL --pack DANBOORU --pack BANGUMI --output NEW_ROOT
```

Local components are in `build/modular-components/`; the all-source relocated root is
`D:/Sakura 模块化 测试/Core 可选 来源 G`. The frozen 120 runtime/source-closure/byte/deadline
checks passed. **Ranking is not equivalent to the monolithic candidate:** semantic Recall@10
remains .975; corrected global cosine-distance fusion restores MRR@10 from the old
modular .61458 to .89375 (monolithic .90833). Compatible semantic packs contribute
one global dense branch, while each source retains an independent lexical rank branch
under RRF60; raw BM25 values are never compared across sources. Single-source ordering
is unchanged. Crosslingual R10/MRR10 remain .53333/.25889 (monolithic .53333/.29976).
This is not a quality-PASS replacement or generalization result. Candidate
`global_semantic_rank`, `best_distance` and source-qualified `backend_ranks` are bounded
ranking diagnostics, not identity verification; public evidence/typed identities retain
their existing trust boundary. ANN raw pools are internal, not complete public rankings.
Exact results, commands and limitations are consolidated in `docs/STAGE_STATUS.md`. Public redistribution
rights remain **NOT_CLEARED**. The previous monolithic candidate below is retained unchanged
as the saved-response comparison baseline.

## Previous portable Windows x64 CPU candidate

Current assembled local directory: `D:/Sakura 发行/知识 CPU 可移动 包`.
It is a directory package (no installer/ZIP/public upload), with its own `sknow-config.json`,
`bin`, runtime DB/mapping/membership/I8 ANN and ONNX model assets. No Python/toolchain is
needed to query it. From that directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./sknow.ps1 lookup hatsune_miku
powershell -NoProfile -ExecutionPolicy Bypass -File ./sknow.ps1 retrieve 'blue hair' --limit 5
'{"case_id":"one","query":"miku","limit":5}' | powershell -NoProfile -File ./sknow.ps1 serve
```

Package I8 is explicit (encoder still FP32):1024/Cos/M16/add256/search2048. Its120-case
source/identity/runtime validation passed; quality remains FAIL semanticR10 .975<1.
Crosslingual Recall@10 is .5333 vs saved FP32 .6000: additional2/30 loss, not a claim that
quantization preserves every result. Repo default stays FP32; smaller portable is a known-
limits candidate. Model assets/licenses/DLLs are local; queries never fetch/build anything.
Actual Chinese/spaces directory relocation worked with PATH only Windows system directories;
this is **same-machine relocation**, not a fresh-machine test. RSS/Pi integration NOT_RUN.
Export/build commands and exact sizes are in `docs/STAGE_STATUS.md`; original mother DB,
FP32 vectors/index/mapping remain protected and absent from the package.

## Repository Windows local entry (PowerShell 5.1+)

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
Pi integration is **NOT_RUN**. Portable packaging is separately validated above.

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
