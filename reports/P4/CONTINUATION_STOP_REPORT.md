# P4 trusted-text continuation: quality gate STOP

P4_RESULT=NOT_READY
MODEL_SELECTION=NONE
STOP_STATE=WAITING_REVIEW (effective only after final dev push/SHA verification)
FULL_SEMANTIC_BUILD_ATTEMPTS=0
FULL_SEMANTIC_PACK=NOT_RUN

This continuation supersedes the four-source coverage requirement, not the
preserved earlier STOP/DELIVERY receipts. P1/P2/P3 remain CLOSED_AND_MERGED;
P4 remains IN_PROGRESS, blocked at frozen pilot model-selection quality gate.
Final exact commit and remote equality must be reported after normal push.
Final checks: pytest910 PASS/143 SKIP exit0 (skips not integration evidence),
Ruff exit0; command receipts retained. Snapshot final SHA check exit0,
21718736896 bytes unchanged; WAL0/SHM32768/no journal. Protected historical
reports and production src/rust comparison checks exit0.

## Frozen scope and evidence

- Base: `269e34eeeac920c29f2d684cfe37c93a95c73057`.
- Snapshot: `build/p3-full-authorized-retry1/knowledge.sqlite`, 21718736896 bytes,
  SHA256 `61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.
  This is a frozen local cut, not a live upstream refresh.
- Trusted census: 1295638 documents. Bangumi subject690068, character221960,
  person102338; Danbooru wiki281272. Moegirl/local aggregate tags contribute zero
  semantic documents; structured/exact/alias access remains unchanged.
- Deterministic50000 pilot quotas: subject26630, character8566, person3949,
  wiki10855. Includes all50 anchored documents. Seed and strata were frozen
  before embedding; no raw supplementation or identity promotion.
- Pilot SHA256 `19f8e7bf18e55a5d1587a10fb0f743d0cd0a65c16a1fcefaf8aa391a28bab1fe`;
  manifest `reports/P4/continuation-pilot-manifest.json`.
- Gold120: lexical30, semantic40, crosslingual30, ambiguous/negative20;
  155 anchor occurrences across50 documents. Gold SHA256
  `ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba`.
  Not exhaustive human source-fact review. Empty-relevance cases have N/A
  relevance metrics: overall scored denominator110, ambiguous denominator10.
- Approved behavior baseline: P2 151/151, P3 55/55, zero wrong_resolved,
  timeouts, retries. It is NOT original P3 oracle recovery (original0/55).
  See continuation-approved-baseline.json and adjacent summary.

## Model execution

Official MIT assets frozen at A revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3` and B revision
`5617a9f61b028005a4858fdac845db406aefb181`; exact inventories/contracts in
model-freeze-summary.json. A=intfloat/multilingual-e5-small (384 dimensions,
mean/L2, query/passage prefixes); B=BAAI/bge-m3 (1024 dimensions, CLS/L2).
Each tokenizer-specific projection has52664 nonempty chunks,384/64 boundaries.

Initial A build failed raw/HF ID equality before first forward. Transformers
5.12.1 AutoTokenizer reconstructed the serialized backend and dropped trailing
space ID6. Failure directory and command receipt preserved. Generic serialized
fast-tokenizer loader fix retains backend identity and per-input ID/budget
checks. Full scans A/B each passed52664 chunks and120 queries, with frozen
inputs verified before/after. No stripping, rechunking, or silent truncation.

A corrected build and B first build exited0, CUDA float32 batch8 threads8.
A226.412284s /232.602221 chunks/s; B1492.727052s /35.280395 chunks/s.
Shapes52664x384 and52664x1024. Independent hash/provenance/shape/finite/L2
checks exited0. Both query commands exited0, each120 unique cases all PASS.
These GPU measurements are NOT CPU qualification.

## Five-route quality outcome

`continuation-pilot-quality-command.json`: exit0.
`continuation-pilot-quality.json`: complete five-route/subset Recall5/10/20,
MRR10, nDCG10, paired deltas, anchor recall, and input bindings.
Same50000 corpus BM25; exact normalized dense, no ANN; RRF k60, depth100,
source-backed exact/alias pins, source-key deterministic ordering.

| Route | Semantic Recall10 | Crosslingual Recall10 | Overall Recall10 |
|---|---:|---:|---:|
| BM25 | .975 | .100000 | .718182 |
| Exact A | .975 | .066667 | .695455 |
| Hybrid A | 1.000 | .100000 | .745455 |
| Exact B | .975 | .866667 | .895455 |
| Hybrid B | 1.000 | .733333 | .913636 |

Both hybrids fail the pre-embedding minimum semantic Recall10 gain of .10:
actual gain .025. Baseline .975 would require1.075; no capped threshold was
specified. This benchmark/threshold ceiling is disclosed, not repaired after
observing embeddings. A additionally fails crosslingual Recall10 gain and
crosslingual MRR10/nDCG10 nonregression. B's crosslingual gains do not override
its failed semantic gate. Selection therefore STOP/NONE, not B by discretion.
Gold, thresholds, fusion, and quotas remain unchanged.

## Downstream NOT_RUN and limitations

CPU reused/fresh query qualification and genuine hybrid-total: NOT_RUN after
quality STOP. Exact total_retrieve excludes lexical/fusion and cannot substitute.
ANN tuning/quality/5s gate: NOT_RUN. Rust production semantic feature/retrieve:
NOT_RUN. FULL build and semantic pack: NOT_RUN, attempts0. Wheel: NOT_BUILT for
this continuation. Pi Skill runtime, Pool integration, full human source-fact
review: NOT_RUN. No performance/model-selection claim from synthetic tests.

No edits to production src/rust relative to approved base. No main merge,
Pool/global configuration edits, upstream mutation, or snapshot overwrite.
Unknown uv.lock preserved externally unchanged at both documented preservation
paths (SHA2564fa7064f8c5b811e35a52130e4e8ae85ffd7e1806d38f4a3614c06099a922eaf).
See continuation-development-notes.md for failed auxiliary commands, encoding
and unavailable-shell attempts; no failures are reclassified as PASS.

Next step requires review/explicit authorization of any revised benchmark or
threshold contract; this run does not retune, run FULL, or silently select B.
