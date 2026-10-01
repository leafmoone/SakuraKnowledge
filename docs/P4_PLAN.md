# P4 — Hybrid Retrieval / RAG Context Layer

State: IN_PROGRESS. Base: `269e34eeeac920c29f2d684cfe37c93a95c73057`.
P1/P2/P3 are CLOSED_AND_MERGED by user authorization. This plan is not acceptance.

## Boundaries

Develop only on dev with ordinary named-file commits and normal pushes. Main is
reserved for externally approved fixed SHA. No Pool changes, Tool integration,
global configuration edits, or access to the external P3 preservation directory.
Historical reports are immutable. Keep failed commands and NOT_RUN explicit.
Contain Cargo targets, compiler paths, temporary files and Python environments
inside this project; never inherit an external Cargo output destination.

The existing FULL `build/p3-full-authorized-retry1/knowledge.sqlite` is immutable:
21718736896 bytes, SHA256
`61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.
No rebuild, ALTER, overlay, VACUUM, embedding columns or write-mode database open.
Hash before corpus extraction and again at protection/acceptance boundaries.
Before immutable SQLite reads, reject nonempty WAL or rollback journal; record
sidecar state rather than deleting it. Source inputs remain read-only.

## Ordered gates

1. Verify base branches and clean tree; switch dev; establish FULL hash baseline.
2. Freeze corpus projection, deterministic pilot rule and source-anchored gold.
3. Freeze official model repositories, exact revisions, downloaded file hashes,
   license metadata and tokenizer/pooling/prefix/normalization contracts.
4. Generate a 50,000-document pilot and tokenizer-based chunks. Run the same frozen
   gold for BM25, dense A/B and fixed-RRF hybrid A/B. Do not adjust queries using hits.
5. Select a model only on meaningful semantic/cross-lingual gains without major
   lexical regression, prioritizing CPU latency/RSS/storage for comparable quality.
   If neither qualifies, STOP; production semantic runtime and FULL remain NOT_RUN.
6. Only after pilot PASS: implement feature-gated Rust inference/ANN and independent
   retrieve interface; validate offline Windows CPU reused and CLI paths.
7. Run P2 151, P3 FULL55, S02 and resolver regression with unchanged legacy JSON.
8. Only after every K gate passes at a clean fixed commit: permit exactly ONE FULL
   semantic sidecar build. Failure preserves staging and receipts, then STOP.
9. Verify FULL manifest/hashes, references/counts/orphans/duplicates, model identity,
   snapshot binding, read-only offline open; rerun frozen retrieval benchmark and
   legacy regressions. Execute default and semantic check matrices.
10. Push dev normally, verify remote dev equals submitted HEAD, report exact fields
    and limitations, and stop WAITING_REVIEW. Never self-merge or start a next phase.

## Corpus, chunk and benchmark contracts

Use existing trusted searchable FTS/document membership, source-backed identity,
and trusted source-backed/generated-from-evidence document text only. Continue
`index_episodes=false`. Embed title and original, not evidence JSON, candidate
mappings, draft annotations or untrusted identities. Preserve source/evidence IDs.

Chunking v1 is paragraph-aware and uses the frozen model tokenizer, maximum 384
chunk tokens and 64 overlap tokens. Account separately for prefixes and special
tokens against model sequence capacity; never silently truncate source chunks.
Each chunk binds chunk_id, entry_id, document_id, chunk_index, text_sha256,
source_id, evidence_id, kind and namespace. Different tokenizer identities may
produce different chunk boundaries, recorded separately against the same documents.

Gold has at least 120 cases: 30 lexical/name, 40 semantic paraphrase/description,
30 Chinese/Japanese/English cross-lingual, 20 ambiguous/negative. Targets bind typed
entry keys, document IDs or accepted sets and source/evidence references before
embedding execution. Empty-target negatives need explicit reasoning; ranking
metrics with undefined denominators are N/A, not invented perfect scores. Report
negative behavior separately. This is an engineering retrieval benchmark, NOT
full human source-fact review; the embedding models never create their own labels.

Pilot selection freezes a seed/hash rule, covers Bangumi/Moegirl/Danbooru/tag,
languages and kinds, retains hard negatives, and reports strata and selection
limitations. No selection based on future vector performance. Publish a small
manifest/hash; full projected text and vectors remain local-only.

## Models, devices and packaging

Pilot A: official `intfloat/multilingual-e5-small` (CPU baseline).
Pilot B: official `BAAI/bge-m3` (quality reference, not automatic production choice).
Resolve and record exact revisions before downloading model assets; do not infer
revisions from mutable README URLs or use unrecorded latest. All model downloads
and conversions reside under project `model/`, excluded from Git. Pin dependencies
in an isolated project environment, not the baseline production package.

Runtime must accept a model location/configuration and explicit device selection.
CPU remains required; optional GPU is caller-selected, never a silent dependency
or fallback. An unavailable requested provider returns an explicit error. Record
requested and actual providers in diagnostics. CPU and GPU measurements remain
separate. No production Python API additions or query-time network/model downloads.

A semantic pack contains manifest.json, model identity/location metadata under
model/, chunks.sqlite and vectors.*. The downloaded bytes remain in the project
model store; the pack model reference is explicitly relocatable and hash-verified,
not an unrestricted automatic download. Runtime validates all required assets.
Changing model/revision/tokenizer/pooling/prefix/dimension invalidates incompatible
vectors and requires a separately built matching pack. Runtime does not hard-code
the two pilot repository names; supported inference contracts are explicit.

Manifest binds base_snapshot_sha256, model identifier/exact revision, file and
tokenizer SHA256, license metadata, embedding dimension, pooling, normalization,
query/passage prefixes, chunking version, ANN backend/version/parameters, corpus
count/hash and creation source SHA. Runtime checks the base snapshot SHA before
queries; mismatch is `semantic_pack_snapshot_mismatch`, with no continued search.
Do not claim a directory has a native SHA256: define a canonical artifact inventory
and hash that inventory as the pack identity, with every file independently bound.

## Retrieval and measurements

Only retrieve lazy-loads semantic assets. Existing lookup/search/related/ask/
resolve-tag must work without models and retain their exact semantics/JSON.
Trusted exact/alias identity candidates are pinned ahead of ordinary fixed-RRF
BM25/ANN competition. Semantic distance indicates relevance, NEVER verified
identity, canonical tag changes or entity_tag promotion. resolve-tag alone retains
its current tag identity decision role.

Evidence bundles expose status/query/candidates/entry_key/hybrid_rank/bm25_rank/
semantic_rank/semantic_distance/matched_chunks/matched_documents/citations,
source/evidence references, warnings and semantic_pack_identity.

Report Recall@5/10/20, MRR@10, nDCG@10 overall and by subset, with explicit
aggregation/accepted-target rules. Freeze RRF and selection thresholds before
measuring. Report reused query embedding, fresh-process query, index search and
total retrieval p50/p95, peak RSS, model/index bytes and build throughput.
Query operation hard budget <=5s, CLI outer <=15s, response <=524288 bytes.
No retry of formal samples. Fixed warmups are recorded separately, excluded only
from formal percentiles; failures remain visible. Do not claim disk-cold absent
actual cache eviction. Model/index can be reused across runtime requests.

## Implementation and acceptance

Prefer ort/tokenizers/usearch subject to measured Windows CPU feasibility. Native
semantic dependencies are optional under Cargo feature `semantic`; default P3
build must not require them. GPU provider support must also preserve CPU/default
build independence. No chat LLM, generated answers, HTTP/vector services or GPU
requirement. Product output is a RAG Evidence Bundle.

Required default checks: pytest -q; ruff check src tests tools; git diff --check;
cargo fmt --all -- --check; cargo test --locked; cargo clippy --all-targets
--locked -- -D warnings; cargo build --release --locked (all Cargo commands use
--manifest-path rust/Cargo.toml and contained output environment).
Repeat test/clippy/release with --features semantic after that feature exists.
Record exact commands, exits and source SHA, not inferred PASS.

FULL gate also requires selected model/tokenizer/chunker/ANN frozen, Rust pilot
PASS, legacy PASS, disk capacity PASS, clean fixed SHA and exact FULL DB hash.
Before that: FULL_SEMANTIC_BUILD_ATTEMPTS=0, FULL_SEMANTIC_PACK=NOT_RUN,
P4_RESULT=NOT_READY. No static document or fixture substitutes for these gates.
