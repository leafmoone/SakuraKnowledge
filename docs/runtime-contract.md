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
  Evidence: `reports/P2/snapshot-compatibility-20bf5b3.json`,
  `tests/test_evidence.py::test_readonly_open_blocks_writes`.

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

## Retrieve Top-K public evidence

Internal bounded lexical/ANN hits retain their original depth and participate in
unchanged RRF/fusion. The public candidate Top-K ordering is not a wire-size tuning
parameter. After final selection, `documents` contains only documents supporting
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
- Budget: every public operation enforces 5 s wall time; a breach is a
  runtime error `ValueError: query_budget_exceeded` (never a silent
  timeout, never a partial result). A breach is a **failure** in all
  evidence receipts — see `tools/check_parity.py`
  (`RUST_BUDGET_EXCEEDED`, overall FAIL).

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
emits one `opened` event, then reads one request per line. Every read request line
has one final complete business response while the output channel remains usable.
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
| stdin I/O error or stdout write/flush error | Fatal nonzero exit; diagnostics only on stderr |

Classification uses explicit request/error types, not substring guesses from SQLite,
ORT or USearch error messages. A query timeout is not automatically recoverable:
without demonstrated statement cleanup and intact engine state, it remains fatal.
The existing five-second query budget is unchanged. Invalid requests are rejected
before encoding; a subsequent valid request uses the same loaded model/session and
ANN handles. stdout contains JSONL protocol messages only; diagnostics use stderr.

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

Acceptance and remaining limitations: [Tool interface receipt](tool-integration.md).

## Encoding

- stdout/stderr are reconfigured to UTF-8 at CLI entry (Python); Rust
  emits UTF-8 bytes natively. Output must be byte-identical across console
  code pages (GBK sample: `p2-wheel-cli-20bf5b3.json`
  `gbk_env_lookup`).

## Parity evidence

- Locked expected values: `tools/parity_cases.py` (151 cases, v2 table).
- Harness: `tools/check_parity.py` (value + error + cli modes, budget
  handling, attempt trails).
- Latest receipt: `reports/P2/rust-parity-20bf5b3-v6.json`.
