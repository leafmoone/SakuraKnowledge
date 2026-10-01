# P4 ONNX representation v3: actual quality, not rank identity

## Authorization and freeze

Commit `configs/p4-onnx-representation-v3.json` **before the real run**. The
runner requires its bytes to equal `HEAD` and records that commit. This change
is additive: v1/v2 contracts, failed receipts, native references, pilot metrics,
and selection receipts remain immutable. No retry, re-export, alternate model,
quantization, native reference regeneration, or BM25 query is authorized.

Reuse only `build/p4/bge-onnx-v2/manifest.json` with SHA256
`b981d9c2b8f02691a200b9b88da8c778abcbaaaa3d49d0376f88590c89fbbb03`.
The v2 `validate_export` authenticates all export files/external data, original
contract, authorized query-reference manifest and payloads, tokenizer/model
inventory, passage sample and source receipts. The v3 config additionally pins
inherited contract and arithmetic/scoring source hashes. The report records
full input SHA256 bindings and their canonical digest; before/after checks
reject mutation. Frozen selection validation authenticates all original scorer
inputs; baseline rescoring must exactly reproduce the frozen metric tables.

All inherited representation settings remain: BAAI/bge-m3 at revision
`5617a9f61b028005a4858fdac845db406aefb181`, frozen tokenizer, CLS normalized
FP32 1024 dimensions, empty prefixes, eager attention, opset 17, exclusive
CPUExecutionProvider, eight intra/inter-op threads, ORT_ENABLE_ALL. Reuse v2
`numerical`, `session`, and `pad_batch` read-only; never call its `execute` or
fail-fast ranking agreement path. Finite values, norm error <= 1e-5, component
error <= 1e-4, and cosine >= .99999 remain blockers.

## Computation and decision

Encode all 120 sorted queries exactly once against the authorized native query
reference. Check the same fixed 128 passages at batch sizes 1 and 8 against
the unchanged native matrix. Rank the ONNX query vectors with unchanged
`exact_rank` over the native 52664 x 1024 matrix, not an ONNX rebuilt corpus.

For **every** query record ordered typed top10/top100 equality, typed EntryKey
set intersections and fractions at 10/20/100, and maximum common-ID score
errors at 10/100 independently of order. The first differing position includes
both identities, their native/ONNX ranks and scores, and ONNX-minus-native
score deltas (null if the identity is absent). These are diagnostic only:
small near-tie reorderings cannot themselves fail v3. Malformed, duplicate or
nonfinite hits remain invalid input, not a tolerated ranking difference.

Replace only dense B cases in memory and call the unchanged `p4_pilot_score.score`.
Its original Mapping, source-backed trusted pins, entry deduplication, RRF k=60,
branch depth 100 and tie ordering remain authoritative. Frozen BM25 and dense A
inputs are never queried or modified. Extract actual `ONNX_DENSE_B` and
`ONNX_HYBRID_B` tables: all five subsets (including overall and
ambiguous_negative), all five relevance metrics, all denominators, and identity
rates. Do not use the scorer's v1 selection result as the v3 decision.

Apply `p4_selection_v2.quality_gates` to actual ONNX hybrid versus original
BM25: capped semantic/crosslingual recall targets and all existing lexical,
MRR, nDCG and zero-identity-error requirements. Additionally, every subset's
hybrid recall@10, MRR@10 and nDCG@10 delta against frozen native hybrid B must
be >= -0.01, using original floating-point values without rounding or epsilon.
Dense identity errors must also remain zero. Explicit per-case native/ONNX
values, deltas and loss flags for both modes and all five metrics are retained;
negative relevance is null, never zero-filled into the positive denominator.

## Outputs and execution

After commit and authorization, run from the repository root:

```sh
python -m tools.p4_onnx_quality_v3
```

Exclusive outputs (existing paths prohibit replacement):

- `reports/P4/onnx-quality-v3.json`: PASS/FAIL, complete ranking diagnostics,
  actual quality tables/gates, per-case relevance losses and input/raw hashes.
- `build/p4/onnx-quality-v3/queries.npy`: the one computed ONNX query matrix.
- `build/p4/onnx-quality-v3/ranks.json`: case order and exact ONNX top100 results,
  bound to the report's input digest for later ANN comparisons.
- `build/p4/onnx-quality-v3/quality-details.json`: unchanged scorer's actual
  in-memory result details including fusion provenance.

Quality failures still preserve all ranks and raw query vectors. Numerical or
provenance failures stop unsafe work and preserve a FAIL receipt; they cannot
claim complete ranking coverage. No worker/model inference is part of unit
validation. Run `python -m pytest tests/test_p4_onnx_quality_v3.py` and
`python -m ruff check tools/p4_onnx_quality_v3.py tests/test_p4_onnx_quality_v3.py`.

## Performance is a separate obligation

Fresh-process initialization is **diagnostic**, not the resident operation gate.
SakuraTool is a persistent process: model/session initialization is amortized;
resident query execution must still pass the inherited measured operation
budget (5000 ms, 120 formal cases per mode after two warmups, no retries).
Record fresh startup separately against the inherited 15000 ms diagnostic
budget, rather than silently deleting it or treating a representation PASS as
latency evidence. This quality runner does not measure or qualify performance.
A later resident performance gate and an actual Rust CLI integration/CPU gate
remain mandatory before ANN/full-build qualification. v3 does not retroactively
turn any v1/v2 FAIL receipt into PASS or authorize model reselection.
