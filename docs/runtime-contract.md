# Runtime Contract (Python ↔ sknow-rs)

Normative surface that the Rust runtime (`rust/`) implements 1:1 over the
published snapshot. Both CLIs print JSON only on stdout.

## Response/deadline and projection invariants

- One five-second basic-operation deadline covers nested queries, projections, bounded
  JSON-size calculation and success/error paths, including inspect. Titles project256
  Unicode characters; identity values/keys never truncate. Semantic single cold startup
  is separate; semantic single/resident wire budget2MiB UTF-8 including newline.
  The local Moegirl refresh increased the historical1MiB bound based on an actual
  1,342,138-byte normal response. Clients must use the matching updated reader/Core;
  larger responses fail explicitly without candidate/body/proof truncation. The
  structured-v3 response bound is a separate unchanged contract.
- Latin-start continuation uses Unicode16 ALNUM; Kana punctuation/combining marks are
  not words merely because of codepoint block. Template subjects use Python whitespace
  including U+001C–1F; U+200B/literal identities stay unchanged.
- RawValue skips ignored deep JSON. Displayed containers recurse depth<=4/children<=16;
  source payload limit2million bytes. Display scalar strings<=256 chars, integer domain
  [-2^63,2^64-1], bool/null/finite floats; out-of-domain integer=>null with explicit
  present/truncated. Display subtrees<=2048 UTF-8 JSON bytes. Mother payload preserved.
- Proof display cap100 explicitly marks all four source_fields_truncated names; absence
  must not imply complete evidence. Ordering independent of insertion order.
- Open verifies actual virtual FTS5 hidden columns and prepares MATCH/BM25/rank LIMIT0
  without corpus scans; failed open closes. Test harness validates success/error shape
  before field access and retains failures rather than converting them to pass.

## Open mode

- Both runtimes open the snapshot **read-only**
  (Python `sqlite3` `mode=ro`; Rust `rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY`).
- Any write attempt must fail (`attempt to write a readonly database`).

## Platform runtime binding

Native semantic queries support Windows and Linux with ONNX Runtime **1.24.1**,
API 24, CPUExecutionProvider, intra/inter threads 8/1 and sequential execution.
The BGE-M3 revision, CLS pooling, normalized float32 1024-dimensional embeddings,
tokenizer, graph interface and source/index contracts are unchanged.

A `sakura-shared-model-v1` model manifest may declare `ort_libraries`, an object
keyed by Rust OS/architecture names, for example `linux-x86_64`, `linux-aarch64`
or `windows-x86_64`. Each selected entry is `{path, size, sha256}`. Paths resolve
relative to the configured `bin_directory`, must remain inside it, and must not
contain symlinks. Size and SHA-256 are checked before loading. An example binding
for the official Linux x64 CPU 1.24.1 release is in
`configs/shared-model-runtime.example.json` (also preserving the existing Windows
x64 binding); merge its `ort_libraries` field into
the prepared shared-model manifest, retaining every model/tokenizer/tensor binding.
Other platforms need their own official binary and measured binding.

When `ort_libraries` is present, the current platform entry is required; an invalid
or missing entry never falls back to a different runtime. For a dual-platform
package, include both entries and both matching binary files. Without this field,
Windows retains the legacy pathless `ort_dll` binding to `bin/onnxruntime.dll`.
Linux requires an explicit platform binding. The runtime always passes the verified
canonical path to ORT and reads `GetVersionString` from that already-loaded module;
there is no runtime discovery through environment variables or system search paths.
No query downloads, installs or builds anything. Missing assets fail explicitly.

For Linux deployment, copy the actual versioned file from the official CPU package
to a regular package-local `libonnxruntime.so` file. Keep the required standard
C/C++ system runtime and upstream license notices. Do not substitute a raw upstream
ONNX model for the prepared graph: the required two inputs are `input_ids` and
`attention_mask`, with one normalized `embeddings` output. Source ANN assets must
remain compatible with the exact prepared encoder. Historical Windows-only legacy
pack bindings remain unchanged; portable monolithic `artifacts.ort_dll` retains its
historical field name but may explicitly bind a Linux shared library.

## Preparing the official BGE ONNX output

Prefer the existing prepared model and its exact bindings when available.
`tools.prepare_bge_model` is an explicit, offline preparation command for the
official `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`.
It pins the upstream graph, external tensors, repository-root tokenizer and
platform runtime identities, and creates a new directory and manifest only.
Preparation requires `onnx==1.20.1`; native queries do not need Python.

The official graph exposes `token_embeddings` and `sentence_embedding`. The latter
already gathers token zero (CLS) and L2-normalizes it. Preparation changes only the
public output selection/name to `embeddings`; it never applies another pooling or
normalization layer, changes weights, or rebuilds an ANN. The root tokenizer is
retained literally, rather than assuming the ONNX-folder tokenizer has identical
bytes. The derived graph's actual digest and provenance are recorded separately
from any historical custom export whose exact artifact identity is unavailable.

Supply `--ort-library PLATFORM=FILE` for each deployed runtime and place those
regular files, under their declared basenames, in the configured `bin_directory`.
Supported preparation bindings are `linux-x86_64` and `windows-x86_64` with the
pinned runtime files. Adding a platform does not change the BGE encoder contract,
source proof semantics, existing index rows or query/resident deadline behavior.

## Commands (identical argv surface)

```
lookup  DB QUERY | DB VALUE --key --kind K --namespace N [--kind K --namespace N]
search  DB QUERY [--limit N] [--kind K] [--namespace N]
related DB VALUE --kind K --namespace N [--relation R] [--limit N]
        DB KIND NAMESPACE VALUE [--relation R] [--limit N]      (sknow-rs legacy form)
ask     DB QUERY [--kind K --namespace N --target-tag-namespace T]
inspect DB
```

- `--limit` is the result cap for both `search` and `related`
  (Python surface; Rust maps it onto the same parameter).
- `--kind`/`--namespace` after `ask` filter only the lookup fallback;
  `--target-tag-namespace` is a template argument, never a source namespace
  and never a candidate.

## Modular CLI parameter contract

The native modular entry is `sknow-rs --config CONFIG COMMAND ...`. Each command
validates its supported options before opening query assets; unknown/misspelled
options, missing values, illegal limits and options belonging to another command
are `UsageError` (stderr JSON, exit 2, empty stdout), not silently ignored.

- `related --direction out` is the default outgoing one-hop operation;
  `--direction in` calls the existing incoming operation. This does not change
  relation membership, identity trust or traversal depth.
- `resolve-tag --target-namespace T` and `--target-tag-namespace T` are aliases.
  Conflicting values are rejected; a requested target remains distinct from the
  source `--namespace` and does not verify a candidate mapping.
- `--source` accepts repeated options and comma-separated pack IDs. Omission
  selects all installed packs. An explicitly empty source or empty list member
  is invalid; it never silently selects all packs or zero packs.
- Existing valid commands retain their business JSON semantics. This parser
  tightening does not change the structured query/identity algorithms.

## Session embedding cache

A shared BGE encoder owns an exact, unnormalized query-string LRU with at most
64 entries and 512 KiB of accounted key/vector/container storage (allocator
bookkeeping and process RSS are separate). Only shape-checked, finite, normalized
vectors are inserted. A new encoder/session starts empty; models never share a
cache. Invalid encoder inputs and failed encodings are not inserted. A later
retrieval failure does not turn a valid embedding into a cached failure. No search response,
identity proof or deadline is cached: every request still ranks current prepared
assets, validates its proofs and observes its own five-second deadline.

`timings_ms.query_encodings` and `process_query_encodings` count actual encoder
calls, so a hit contributes zero. `embedding_cache_hit` explicitly marks a hit;
`process_embedding_cache_hits` is session cumulative. Raw spellings, case and
whitespace remain distinct cache keys; filters can reuse the same embedding.
Request-local proof reuse is bound to one database connection and query, and
includes the complete typed key, match type, source ID and evidence ID.

## Structured search projection

Exact/alias trust and ambiguity are determined from up to 101 lightweight
identities before descriptions are assembled. Search assembles only its requested
Top-K; `candidate_limit_reached` still records more than 100 trusted identities.
The 512 KiB structured response bound applies to the returned projection.
`response_budget_truncated` no longer reports an oversized discarded lookup
intermediate when the requested search Top-K itself fits. Final-response overflow
continues to use the existing truncation/error contract.

Filtered Python FTS consumes rank-ordered complete tie groups. If its 10,000-row
scan cap is exhausted it retries the historical fully ordered query, preserving
the selected tie subset and scan-limit warning; this fallback can cost an extra
scan rather than improve latency.

## Retrieve Top-K public evidence

Internal bounded lexical/ANN hits retain their original depth and participate in
unchanged RRF/fusion. The public candidate Top-K ordering is not a wire-size tuning
parameter. Full document bodies are fetched after final selection and proof
closure; ranking metadata and trust checks retain their original depth.
After final selection, `documents` contains only documents supporting
selected typed keys, plus necessary proof for independently retained trusted pins.
`sources`, `evidence` and `citations` retain that dependency closure, including
source-backed identity proofs where no document is needed. Unselected FTS matches
are not public answer evidence merely because they were internal ranking hits.

One candidate may have multiple documents and multiple source proofs. Document
identity is source-qualified (`pack_id`, `document_id`); equal numeric IDs in
separate packs never establish equality. Typed key, status, text provenance,
ambiguity and source/evidence bindings remain unchanged. Trusted pins remain
independently visible even when they do not fit the candidate Top-K. No retrieval
candidate, generated text or candidate mapping is promoted to a verified identity.

## Error contract

| Class | stdout | stderr | exit |
|---|---|---|---|
| usage error (unknown command, bad option, missing value) | empty | `{"error":"UsageError","message":"…"}` JSON | 2 |
| runtime error (invalid topk/limit/key, not-a-snapshot, budget) | empty | `{"error":"<ExcType>","message":"…"}` JSON | 2 |
| help (`-h`/`--help`) | usage text | empty | 0 |
| success | result JSON (UTF-8, `ensure_ascii=False`) | empty | 0 |

- Validation messages are byte-identical across runtimes:
  `query must contain 1..4096 characters`, `query_budget_exceeded`,
  `topk must be 1..100`, `limit must be 1..100`,
  `target_tag_namespace must contain 1..256 characters`.
- Structured query operations enforce a five-second query budget. A breach is
  `query_budget_exceeded`, not a silent successful partial result. Native semantic
  request and transport deadlines follow the resident/single-query rules below.

## Output values

- `status ∈ {found, ambiguous, not_found, …}`; `ambiguous` requires
  `candidates`; `not_found` requires empty candidates.
- Identity: `kind` + `namespace` + `value` only. `source_fields` is a
  **bounded projection** of identity-evidence raw payloads
  (`raw_attributes`, `raw_subject_categories`, `raw_cv_names`,
  `raw_gender`) with per-field citations; raw payloads stay preserved in
  `entry_evidence`. Spelling/title/confidence/cross-namespace similarity
  never establish identity; candidate mappings are never silently promoted
  (`unknown` / `ambiguous` / `target_unmapped`).
- Trust: `IDENTITY_TRUSTED = source_backed` only;
  `TEXT_TRUSTED = source_backed + generated_from_evidence`.

## Resident JSONL lifecycle and errors

Both `semantic_pilot DATABASE MANIFEST` and `semantic_pilot --config CONFIG` use
the same request/error semantics. Initialization opens assets and the model once,
emits one `opened` event, then reads one request per line. Each read request line
has at most one final complete business response. Recoverable requests have exactly
one while the output is usable and the deadline permits completion. Fatal timeout
or broken output can prevent a complete response; neither permits a second frame.
Recoverable failure is not EOF, a retry, or permission to restart the engine.
Natural stdin EOF exits 0 even if earlier requests had recoverable failures.

A valid `case_id` is returned verbatim, including Unicode and whitespace. Malformed
JSON, a non-object request, or a missing/invalid ID uses `"case_id":null`; the driver
never regex-extracts an ID from invalid JSON. These are protocol input failures.
A valid ID is a nonempty string whose JSON-string encoding (including quotes and
escape expansion) occupies at most `MAX_RESPONSE_BYTES - 1024` bytes. The reserved
space guarantees a complete failure envelope; overlong IDs are `invalid_case_id`
with null, not truncated IDs. Whitespace-only IDs within the bound remain valid.
Successful and failed responses share the **2,097,152-byte serialized UTF-8 plus
newline** bound. Serialization finishes before writing, so an oversize success is
replaced with one complete `response_too_large` failure, never a partial success.
Actual output write/flush failure is fatal: it cannot be claimed as a delivered FAIL.

Example recoverable response (not automatically retried):

```json
{"case_id":"q2","status":"FAIL","error":"invalid_limit","message":"limit must be integer","retries":0}
```

| Failure class | Resident behavior |
|---|---|
| Invalid JSON/object/query/case ID, invalid or out-of-range limit, invalid kind/namespace/source, unsupported option | One complete FAIL, flush, continue |
| Explicitly requested source pack not installed | One complete FAIL, flush, continue |
| Response exceeds the 2MiB wire limit | One complete FAIL, flush, continue; no retry or re-encoding |
| Initialization/asset validation failure | Nonzero exit; no falsely successful opened lifecycle |
| Corrupt model/index/database, unknown internal engine error, or query error without proof that state remains safe | Fatal nonzero exit, never catch-all continuation |
| stdin I/O error or stdout write/flush error | Fatal nonzero exit; no unguarded secondary diagnostic after request-controller teardown |
| Absolute request deadline expires, including blocked write/flush | Native fatal exit124; watchdog does not emit or flush any JSON or diagnostic; incomplete frame is not delivered FAIL/PASS |

Classification uses explicit request/error types, not substring guesses from SQLite,
ORT or USearch error messages. A query timeout is not automatically recoverable:
without demonstrated statement cleanup and intact engine state, it remains fatal.
The engine's existing budget is unchanged, but the native driver also enforces one
**absolute five-second request deadline** starting immediately after a complete
input line has been received, **before JSON parsing**. It covers validation,
retrieval, bounded serialization, write and successful flush (and synchronous
profiling). Cold asset/model opening, the opened event and input-line waiting are
not part of a request. CLI semantic single queries debit argument-validation time,
exclude cold opening, then retain the same absolute deadline through output.

One process-local watchdog thread uses a condition variable and request generations,
not one sleeping thread per request. Expiration hard-terminates only the current
native process with code124, without stdio/destructor cleanup. Earlier runtime fatal
failures exit1 without a secondary unguarded diagnostic or cleanup. The pilot
uses explicit `ExitCode`, not Rust's default `Result` error printing after the
watchdog lifetime. Cold initialization diagnostics remain outside request timing.
It never emits a
concurrent timeout FAIL, changes/reloads assets, or treats an unknown engine timeout
as recoverable. Generic embedding `run_resident`/checked sender APIs check elapsed
time but cannot interrupt arbitrary blocked host I/O; the native entry paths use
`run_native_resident`/the armed watchdog for that boundary. The unchecked legacy
sender wrapper is not used by these native request paths.

Native write/flush completion is checked before disarming the generation. A reader
may have received a full frame before a later flush/profiling timeout kills the
process: that nonzero/session failure is fatal, not a successfully completed
request or permission to continue. Discard incomplete frames and do not infer
successful delivery merely from a prefix or from a hard-exit code. Desktop OS
scheduling is not a hard real-time guarantee; bounded fatal termination is not a
mathematical nanosecond precision guarantee.

Invalid requests are rejected before encoding; a subsequent valid request uses the
same loaded model/session and ANN handles. stdout contains JSONL protocol messages
only; diagnostics use stderr while possible.

Supported request fields are `case_id`, `query`, `limit`, `kind`, `namespace`,
`include_vector` and (modular mode only) `source`. Limit is an integer in 1..100;
query is nonempty, at most4096 Unicode characters and at most256 normalized tokens.
Optional kind/namespace may be absent or null; kind otherwise uses an existing
EntryKey kind, while namespace is nonblank text of at most1024 characters. Source
may be nonempty text (including comma-separated IDs) or a nonempty list of such
strings; explicit null, an empty list or empty member is invalid. Missing source
means all installed packs. Source selection in monolithic mode is unsupported.

Stable recoverable codes: `invalid_json`, `invalid_request`, `invalid_case_id`,
`invalid_query`, `invalid_limit`, `invalid_filter`, `invalid_kind`,
`invalid_namespace`, `invalid_source`, `invalid_option`, `unsupported_option`,
`source_pack_missing`, `response_too_large`. Only explicit `RequestError` values
are recoverable; wrapping one in an unknown internal error does not prove safety.
An engine failure emits `runtime_error` if a complete response can be delivered,
then terminates nonzero. A broken output channel may preclude any complete response.
`opened.open_timings_ms.model_sessions` and response
`timings_ms.process_query_encodings` report actual session/encoder counters;
invalid input leaves the encoder counter unchanged. A lexical-only modular runtime
has zero model sessions and zero encodings, not a synthetic model session.

## Encoding

- Python reconfigures stdout/stderr to UTF-8 at CLI entry; Rust emits UTF-8 bytes
  natively. Console code pages must not change the JSON text. When redirecting on
  Windows, use an explicitly UTF-8 environment.
