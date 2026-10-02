# P4 FULL semantic clean-room preflight contract (implementation draft)

implementation_origin: `clean_room_reimplementation_after_untracked_source_loss`
recovered_original_source: **false**
reference_sources: committed Rust pilot `471829644b32eecc10aa30d9d3b71979500a3117`,
approved FULL requirements, approved P3 snapshot, committed pilot tokenizer/chunk/ANN/runtime.
This is new code, not recovered original source or an equivalence claim.

## Distinct contract objects

- Canonical configuration: `configs/p4-full-semantic-v1.json`, schema
  `p4-full-semantic-contract-v1`, object_type `canonical_contract`. Required
  `declarative_contract` fixes the trusted corpus, model/tokenizer/chunker/ANN/hybrid/
  CPU-runtime and create-new, read-only, max_attempts1 policy.
- Future FULL runtime pack: schema `p4-rust-semantic-full-pack-v1`, object_type
  `runtime_pack`, top-level positive integer `full_chunk_count`, required
  `declarative_contract`, and `canonical_contract` containing schema, controlled config
  path, exact byte size and SHA256. Activation/preflight and startup verify actual
  canonical bytes, not merely equality between two manifest claims. Runtime `contract`
  is a deterministic projection with dynamic ANN rows equal to top-level count.
  A runtime pack is not the canonical configuration. FULL rejects pilot lexical
  artifact/metadata and mixed declarations. Existing assets are referenced relative
  to the pack, including `..` only when the resolved path remains in Knowledge ROOT;
  links/junctions and duplicate resolved paths fail. The only external exception is
  the exact `ort_dll` path authenticated through the approved pinned pilot job and
  frozen pack, with pinned size/SHA. Missing authority blocks; other kinds cannot
  use that exception. No artifact copies or actual FULL pack are created here.
- Pilot pack remains `p4-rust-semantic-pack-v1`, original `pilot_sidecar` fixed contract,
  52664 rows, pinned lexical artifact/metadata. No legacy public runtime/API changes.

## Execution and review boundaries

Only preflight primitives and synthetic tests are authorized during implementation.
Real count/disk/tokenizer/GPU and formal pilot/P2/P3 qualification are coordinated by
root after an implementation SHA is fixed and pushed. Changed code/config invalidates
that fixed-stage evidence. Initial receipt code is NOT_FIXED_YET; no real PASS is claimed.

The only future preflight operations are contract validation, read-only snapshot
verification, trusted document census, count-only deterministic chunk projection,
disk estimation, tokenizer/embedding smoke, complete inventory and output absence.
No builder entry, vectors writer, memmap w+, ANN add/save, product chunks database,
FULL output lock or attempt1 is present or permitted. Guard product absence before and
after operations. Final success is only READY_FOR_BUILD_REVIEW / WAITING_REVIEW.

The FULL snapshot is 21718736896 bytes, SHA256
`61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.
Expected trusted documents1295638: subjects690068, characters221960, persons102338,
Danbooru wiki281272; Moegirl/local-tag0, episodes excluded. Census/count must report
empty/duplicate documents/chunk identities, paragraph splits, total/max tokens and
ordered positions. No estimated chunk count can replace actual count.

Global chunk identity collisions are checked with a temporary SQLite UNIQUE audit
index, not an unbounded RAM set or a cryptographic collision assumption. The audit
lives under `build/p4-preflight-audit-temporary`, never the FULL product directory;
16MiB page cache, batches <=1024, explicit disk cap (default1GiB), SQLite max_page_count
and per-batch actual pages/journal/free-space checks bound resources. Insufficient
space/SQLITE_FULL yields BLOCKED_AUDIT_DISK and incomplete count, attempts0. A default
16MiB per-document UTF-8 gate limits chunker input; this is a blocking policy, not a
proved chunk-count estimate. Connections close before immediate temporary cleanup.
Audit cap is conservatively included in peak accounting even after cleanup.

Use exact committed paragraph/model-tokenizer projection and pinned LocalEncoder.
At least512 deterministic FULL documents and512 FULL-only chunks;128 pilot passages
must match approved FP32 vectors within1e-4 component error, .99999 cosine,1e-5 norm.
Inventory closure precedes loading and remains read-only, including all ONNX external
tensors and pinned ORT DLL. Record actual GPU/device/framework/batching, not capability
claims from static configuration.

Disk safety uses actual count, measured NPY header, approved ANN per-row bytes with10%
cushion, actual pilot mapping and measured expanded schema with25% overhead. Include
explicit construction/staging/final/receipt temporary budgets, referenced model/runtime
bytes without double-copy accounting, and actual free bytes >= peak*1.25. Otherwise
BLOCKED_DISK with attempts0. No disk estimate itself authorizes execution.

## Historical evidence and protection

External preservation remains read-only:
`D:/SakuraTool/SakuraKnowledge-p4-full-loss-preserve-20261002/preserve`;
manifest SHA256 `26d7f147be8aca7d715f35d839f3758dd247eae9a573a7e3e3b0057c564879e1`.
Original untracked implementation LOST, not recoverable; original30 errors/3 failures
and compiler/UNION development failures remain historical. No receipt relabeling.

Every SQLite owner closes in finally, including exceptions and generator/cursor
cleanup; immediate directory removal tests may not sleep, gc, skip or ignore errors.
Every Cargo/pytest child uses process-local approved GCC/G++/dlltool PATH and a resolved
Knowledge-contained target. No global environment changes, install/download or Pool.
No commit yet: root reviews implementation/matrices and owns implementation commit.
The authorized preflight binds HEAD and live remote dev, rejects related tracked/index
changes and untracked implementation, and compares fixed Git blobs with path-aware
CRLF filters while recording independent exact checkout bytes. Start/end guards repeat
source, canonical and snapshot checks; unrelated evidence reports may remain dirty.
The formal preflight return, if every actual gate later passes, is explicitly
READY_FOR_BUILD_REVIEW / WAITING_REVIEW with builder_authorized=false, not build approval.
No FULL product build regardless of preflight success.
