# P4 ANN V1: frozen FP32 USearch pilot

Baseline dev256e2f1c4aac224ed3b94aa8df6fc715cf973010; main/base
269e34eeeac920c29f2d684cfe37c93a95c73057. Offline engineering only; production
src/rust/dependencies remain unchanged. No new embeddings, ONNX export, native
reference, quantization, gold/BM25/RRF changes, FULL build or integration.

## Inputs and representation

configs/p4-ann-v1.json binds six inputs by actual SHA256:52664x1024 native FP32
passage matrix, mapping SQLite,120x1024 approved ONNX query matrix, existing
ONNX exact typed-entry ranks, ONNX quality and residentCPU receipts. Validate
all before and after execution. Never recompute another exact reference.
Model BAAI/bge-m3 revision5617a9f61b028005a4858fdac845db406aefb181,
representation BGE-M3_ONNX_FP32. USearch2.26.2 offline environment .venv-p4-ann;
explicit dimensions1024,cos,f32,multi=false,chunk row keys0..52663.

## Finite grid and timing

M=[16,32], expansion_add=[128,256], expansion_search=[32,64,128,256].
Exactly4 builds and16 candidates, no additions after observation. Build threads8.
Single-query search,512 chunk candidates, distance-order typed EntryKey dedup
(kind,namespace,value), first occurrence establishes rank; take100 unique entries.
No identity promotion. Two warmups (first2 queries once each), then120 sorted
frozen queries once per candidate, retries0. Latency measures index.search only,
not query embedding or mapping/dedup. Report p50/p95/max, failures, build time,
index bytes, actual memory_usage and hardware_acceleration when available.
No official performance invocation before contract/tools commit pushed and dev
remote verified. Outputs create-new; indexes/raw results local-only build/p4/ann-v1.

## Acceptance and selection

Entry overlap divided by K versus existing ONNX exact reference, K10/20/100.
Macro minimum .98/.98/.95; per-case minimum .80/.80/.90. No rounding for gates.
For approximation-passing candidates evaluate complete120 gold with unchanged
frozen BM25,pins,RRF60,depth100. All benchmark-v2 gates must pass. For overall,
lexical,semantic,crosslingual,ambiguous_negative Recall10/MRR10/nDCG10 delta
against approved ONNX_HYBRID_B must be>=-.01. Identity promotion errors0 and
formal search failures0 required. All relevance metrics5/10/20 and MRR/nDCG10
reported with negative denominator semantics unchanged.

Select minimum search p95 among passing candidates. Candidates within .05ms of
that global minimum form tie group: smallest index bytes then M,expansion_add,
expansion_search. No discretion for larger parameters. No candidate passing
means FAIL/NOT_READY without new grid/backend/quantization.

PASS is ANN PILOT only. Stop after result commit/push and remote/main/clean
verification for review. Rust semantic runtime NOT_STARTED, FULL attempts0.
Fresh startup diagnostic122/122 timeouts occurred in setup/provenance before
tokenizer/session/query: FAIL_SETUP_VALIDATION, product cold start NOT_MEASURED.
Resident CPU120/120 PASS does not change this limitation.
