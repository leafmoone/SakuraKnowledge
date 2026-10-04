# Current P4 semantic builder and acceptance

## Product authority

`configs/p4-current-assets.json` supplies current model revision, tokenizer/model inventory,
ONNX export manifest, external-weight inventory, runtime interface, and the exact ORT DLL.
Python preflight and acceptance and Rust semantic loading use this configuration. Historical
Git/source closure, authorization captures, review handoffs, and permanent attempt records
are not product authority. Parsed configuration comparisons remain type-sensitive; cosmetic
JSON formatting is not a historical gate. Manifest configuration byte bindings remain real.

The optional pilot artifact pins were transferred from existing product metadata, not
rehashed as a new real-source acceptance in this cleanup. They are not mandatory inputs to
the FULL builder. Optional pilot evaluation still scores saved query/gold/baseline data and
checks typed identity, fusion, numerical agreement, quality and latency. Its `job` command
creates ordinary evaluation configuration; it does not authorize another operation.

## Ordinary builder

`tools.p4_full_build.execute(output=...)` performs real snapshot/tokenizer validation,
readonly count and bounded collision audit, local encoding, `build_stream`, manifest
assembly, and final acceptance. Outputs must be new. `.build.lock` is an ordinary owned
concurrency mutex, released on success or failure; retained partial products prevent
accidental overwrite, not future work at a new destination. Atomic create-new publication,
first-error handling, cancellation and owned-resource cleanup remain required.

CPU reference parity uses one fresh process over the deterministic saved-vector sample,
with actual CPU/FP32 and eight intra/inter-op Torch threads. Mapping positions, token counts,
shape, finite values, unit norms and numerical parity are checked. Whole-vector validation
is readonly. Chunk identifiers, order, census, snapshot/FTS integrity, complete ANN keys,
index count/dimension/metric/dtype/connectivity and saved-index reopen remain product gates.

Acceptance hashes each unique immutable asset once per verification session and shares
that verified context; size, containment, actual content SHA and subsequent mutation checks
are not replaced by matching self-declarations or Rust metadata/view success.

## Validation frequency and limits

Use focused Fast tests during edits; run one complete Regression at the final acceptance
boundary, plus Ruff and diff checks. All Cargo invocation, including subprocess-triggered
builds, must set process-local `CARGO_TARGET_DIR` to
`build/p4-usearch-native-fix/rust-target`; use the resulting semantic binary for interop tests.
Do not silently skip those tests because an environment variable was omitted.

This cleanup does not execute a FULL embedding/ANN/quality rebuild, resume previous partial
products, install MSVC/Windows SDK, build the Python native extension, or refresh upstream
sources. Existing model, tokenizer, ONNX/external weights, snapshot, corpus, chunks, vectors
and saved indexes are preserved. Fixture success is not real-source acceptance.

## Python-native USearch impact

The actual builder still calls `index_factory()` -> `usearch.index.Index` -> construct/add/
keys/length/save and reopened `view`. The Windows native fixes are therefore still necessary
for that Python build/reload path. Rust runtime and saved-result scoring do not require the
Python extension. The patched cp314 Python extension remains unbuilt/unvalidated; a Rust
large-file loader pass does not establish Python-native readiness.
