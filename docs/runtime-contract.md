# Runtime Contract (Python ↔ sknow-rs)

Normative surface that the Rust runtime (`rust/`) implements 1:1 over the
published snapshot. Both CLIs print JSON only on stdout.

## Response/deadline and projection invariants

- One five-second basic-operation deadline covers nested queries, projections, bounded
  JSON-size calculation and success/error paths, including inspect. Titles project256
  Unicode characters; identity values/keys never truncate. Semantic single cold startup
  is separate; semantic resident wire budget1MiB UTF-8 including newline.
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
