# P4 FULL semantic clean-room preflight contract (implementation draft)

## Source and historical execution bytes

Git filtered source OID and blob SHA are separate from asset raw-byte pins.
Historical job raw SHA must be supplied by an independently exact-pinned PASS
receipt, not arbitrary mutable JSON or a normalized checkout. The Rust pilot
receipt authorizes 614bc6e6… CRLF job bytes; its LF Git source remains 53ee8132….
The model-B job retains 6e4e975e… with historical tokenizer parity receipt proof.
Any unknown raw authority or tampered receipt blocks. These historical anchors
never replace the fixed current runtime/source SHA guard.

## Reviewed split execution (not yet formally executed)

The tracked interfaces are `count_preflight`, `disk_preflight`, and
`smoke_preflight`. `preflight` performs one new count and stops at
`WAITING_COUNT_REVIEW`; it never automatically resumes a receipt or initializes
GPU. Direct count derives necessary resource reservations from the trusted
1,295,638-document lower bound and authenticated pilot mapping/ANN observations,
not a guessed caller staging budget. Disk uses reviewed actual chunk N and
measured mapping pages to derive minima. Insufficient disk or resource caps block.

The one count stream retains 512 hash-ranked document references and the first
512 FULL-only chunk references excluding the approved 50,000 pilot documents.
Later phases only look up those IDs, validate text/token/boundary digests, and
repeat the bounded projection; they do not search a second FULL stream. Sample
shortage blocks without fallback scan, truncation, skipped census, or retry.

Each resume requires root-reviewed `expected_sha256`, separate
`expected_capture_sha256`, and exact `expected_argv`. The capture binds actual
exit, cwd, zero retries, stdout/stderr bytes and hashes, and the output receipt.
These externally reviewed digests and fixed-code execution logs are the trust
source: a receipt's own JSON hash or count stream digest does not independently
prove execution or reconstruct every chunk. Partial or changed code/config,
snapshot/tokenizer/chunker/inventory bindings cannot resume. Count and capture
must be published create-new by the authorized caller; do not overwrite prior
attempts. Exceptions retain failure receipts; finally guards remain fatal.

Disk PASS is reviewed and fresh free space is checked immediately before encoder
creation and after smoke. GPU, 128 approved pilot vectors, and 512 FULL-only chunk
smokes require explicit separate authorization. No phase authorizes FULL build.

The legacy regression CLI now requires explicit runtime SHA, run-id and a new
contained target. Its historical baseline anchor remains immutable; runtime
source and captured actual binary build provenance are independent bindings.
151/55 expected records and comparison policy remain unchanged.

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

## Appendix — FULL executor implementation revision (WAITING_REVIEW)

The original 139-line preflight contract above is retained unchanged. Its prior
no-builder rule is a **historical preflight-stage boundary superseded for code
implementation only; FULL remains unauthorized**. Historical stage statements are
not current executor limitations or new execution permission. Root resolved frozen
`build_entry=false` as declarative, not an implementation blocker; canonical config
and declaration remain unchanged. Existing preflight interfaces and reviewed phases
are unchanged; their historical evidence is not rebound to today's executor HEAD.

`implementation_origin=clean_room_reimplementation_after_untracked_source_loss`,
`recovered_original_source=false`, and receipt
`executor_origin=clean_room_full_build_executor_v1` identify this implementation.
Reference sources remain the committed Rust pilot, approved FULL requirements/P3
snapshot and pinned tokenizer/chunker/model/ANN contracts. No formal run, native
GPU/USearch qualification, runtime activation, commit or merge is claimed by this
revision. FULL attempts remain **0**, actual pack **NOT_RUN**. Synthetic attempts
are isolated fixtures, never FULL authorization or evidence.

### CLI modes and exact authorization

`python -m tools.p4_full_build` requires exactly one mode:

- `--validate` or `--dry-run`: source/config validation only; no inventory, snapshot,
  disk, GPU, model initialization, reservation or product directory.
- `--synthetic`: explicit isolated temporary directory, twenty documents/dimension
  four; actual orchestration through reservation, projection, mapping read-only
  reopen, sample, embeddings, independent reference parity, ANN save/read-only reload,
  inventory, finalization, manifest and durable terminal receipt before cleanup.
  The actual FULL validator runs with only explicit fixture authorities substituted.
- `--execute-full`: future interface requiring `--authorization`,
  `--expected-authorization-sha256`, and `--fixed-head`. Missing authorization rejects
  before attempts0 changes or inventory/snapshot/disk/model/output work.

Authorization schema `p4-full-build-authorization-v1` has exactly **12 keys**:
`schema`, `operation=execute_full`, `fixed_code_sha`, `preflight_producer_sha`,
`preflight_evidence_sha`, `reviewed_source_bindings`, `output=build/p4-full-semantic-v1`,
integer `max_attempts=1`, `count_review`, `disk_review`, `smoke_review`,
`executor_bindings`. The three provenance fields distinguish historical production,
evidence publication, and phase source-inventory hashes:

- `preflight_producer_sha`: reviewed producer
  `ccc80fd8d2d700654a9003cc70e3785628275f99`.
- `preflight_evidence_sha`: evidence publication
  `51346b2b338d3c803f1210219e12dd4af6b508c9`.
- `reviewed_source_bindings`: exactly `count`, `disk`, `smoke`, each an independently
  reviewed SHA256 of that phase's source inventory, authenticated against producer
  Git blobs and the receipt. Shared implementation must still match current source.

`fixed_code_sha` independently fixes the current executor; it is not the historical
producer or evidence SHA. Reviews bind authenticated receipt plus independent capture
SHA/argv; receipt bytes must match the evidence-publication Git blob. Executor bindings
contain exact raw SHA256 for only executor, executor tests, this document and
`docs/STAGE_STATUS.md`; each matches its path-filtered fixed Git blob. Duplicate JSON
keys, NaN, unknown fields, wrong hashes/source/output and boolean attempts reject.
Authorization is independently reauthenticated before publication.

### Ordered phases and reservation

1. **Activation**: reviewed count, matching disk PASS and matching
   READY_FOR_BUILD_REVIEW smoke; fresh snapshot size/SHA, authenticated inventory/DLL,
   fresh disk, actual CUDA availability, fixed source/config/authorization, absent
   output and sibling lock. Config/source guards exit before reservation; activation
   errors attach attempt0 FAIL reports without disk writes.
2. **Reservation**: exclusive `xb` sibling `p4-full-semantic-v1.attempt1.lock`,
   write/flush/fsync, then product mkdir. The lock records activation facts. Mkdir is
   not the claim; post-claim write/fsync/mkdir failure consumes the attempt. The lock
   is never removed, even if no product directory exists.
3. **Projection/mapping**: immutable read-only approved snapshot, ordered trusted
   eligibility and pinned tokenizer projection; exact count/census/strata/digest,
   SQLite unique chunk identities, never guessed N.
4. **Mapping integrity**: commit/close all writers, independently reopen immutable/
   read-only; check integrity, count and contiguous positions before embedding
   initialization or vector-file creation.
5. **Sample preselection**: persisted `sample.json` before embeddings; FULL first100
   and last100 positions plus1000 lowest SHA256 ranks of `p4-full-sample-v1:<chunk_id>`,
   boundary positions excluded. Require1200 unique positions, no fallback/truncation/
   retry. Small synthetic fixtures explicitly use all available boundary positions.
6. **Embedding**: deferred actual CUDA FP32 LocalEncoder, bounded batches<=1024,
   token/finite/dtype/shape/norm checks, NPY writes and flush/close. Independently scan
   every saved vector in bounded batches for finite/unit-norm validity before reference
   initialization or ANN construction.
7. **Reference parity**: read-only vectors and separately initialized pinned CPU FP32
   LocalEncoder, not ONNX; actual identity recorded as `reference_encoder`. Component
   error<=1e-4, cosine>=.99999, norm error<=1e-5; measured aggregate extrema recorded.
8. **ANN**: only after reference PASS, pinned USearch cosine/f32/M16/Eadd256/ef128;
   position keys, disk-backed complete unique census for duplicates/range/missing keys.
   Save `vectors.usearch`, independently read-only `view` reopen and repeat full census.
   Build seconds and saved byte/SHA binding recorded. RSS, memory_usage and
   hardware_acceleration are optional/best effort (`NOT_AVAILABLE` on errors), never
   blockers. Native owners receive supported reset/close best effort.
9. **Runtime validation/inventory**: existing strict seven-artifact FULL validator,
   canonical origin, sorted role inventory, transient checks.
10. **Final guards/publication**: recheck inventory/auth/source/canonical bytes; work
    and finalization guards exit before create-new manifest and terminal receipt.
    COMPLETE means BUILD_COMPLETE_WAITING_REVIEW, not activation or acceptance.

Capacity is checked before expensive phases/batches. No retry, resume, overwrite,
alternate output or automatic partial cleanup. SQLite/NPY owners close on failure;
original error type/message propagates.

### Products, inventory and terminal failures

- `chunks.sqlite`: `chunks(position INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE,
  document_id, entry_id, kind, namespace, value, source_id, evidence_id, text_sha256,
  token_start, token_end, metadata)` with nonnull fields; typed Rust `entry_key` and
  all provenance IDs retained. Indexes cover document_id and (kind,namespace,value).
  Disk-backed projection holds canonical text/token rows for bounded inference.
- `corpus.jsonl`: actual eligible documents, not chunk list/placeholder; IDs/typed
  keys match mapping provenance. Manifest binds corpus/mapping/ANN exact size/SHA.
- `vectors.npy`: FP32 N x declared dimension, build-only, never eighth runtime key.
- `vectors.usearch`: native position-keyed ANN. `sample.json`: build-only preselection.
- `manifest.json`: strict `p4-rust-semantic-full-pack-v1` / runtime_pack, exact
  declaration, dynamic positive full_chunk_count, canonical binding, clean-room
  origin, approved snapshot and runtime projection.
- `execution-receipt.json`: terminal evidence; sibling
  `<output>.execution-receipt.json` when product mkdir fails.

Runtime artifacts are exactly `model`, `external_data`, `tokenizer`, `ort_dll`,
`index`, `mapping`, `corpus`. Authenticated existing model/tokenizer/ONNX external
 tensors/DLL are referenced, never copied. No pilot lexical or mixed declarations;
`..` stays within ROOT except independently pinned external ORT DLL.

Sorted top-level inventory records carry path, role (`runtime_required`/`build_only`),
artifact, byte count and raw SHA256. Snapshot and canonical bindings are distinct
runtime_required records alongside the seven runtime artifacts. `inventory_sha256`
is canonical JSON SHA256 of that array alone; `FULL_SEMANTIC_PACK_SHA256` is its exact
named alias. Manifest/receipt self bytes are excluded. Receipt top-level build_only
`receipt_binding` explicitly requires external postwrite digest binding; `tempstate`
records SQLite journal/WAL/SHM. Manifest checks terminal transient existence.

Failure receipts preserve phase/history, attempt, initial error type/message,
completed document/chunk/embedding/ANN counts, last position, artifact existence,
input hashes, activation bindings, snapshot after-hash status and retained_partial.
Terminal snapshot `CHANGED` or `HASH_FAILED` makes the result **FAIL**, not COMPLETE;
receipt persistence failure likewise makes the attached report **FAIL**. Terminal
errors are recorded separately without replacing the initial error or failed phase.
The complete phase is published only after terminal receipt persistence succeeds.
The durable lock blocks subsequent retries, including after immediate test cleanup.

### Verification and scope

Current executor tests: **78 passed**. Controller's final full matrix: **12 commands,
all exit0**; full pytest **1639 passed, 21 skipped, 67 subtests passed**. Skips remain
NOT_RUN, not native qualification. Cargo/pytest targets were repository-contained
and process-local isolated; no global environment change or installation. These are
reported implementation results, not fresh tests run for this docs-only correction.

Coverage includes nineteen parameterized failure-first lifecycle cases, reservation
before mkdir/after-claim failure/exclusive claim, no retry/overwrite, closed mapping
before inference, disjoint sample boundaries, duplicate SQLite identities, missing/
duplicate ANN keys, read-only reload, strict7/build-only and pilot-mixed rejection,
immediate Windows owner cleanup, terminal snapshot/persistence failures and complete
synthetic orchestration using the actual FULL validator. Native GPU/USearch and formal
FULL remain unexecuted. Earlier failures remain historical, never relabeled PASS.

Approved snapshot/census, historical preservation and reviewed count/disk/smoke
interfaces remain unchanged. No helper/config/Rust/public API/Pool/preservation edits,
installation, global environment change, commit or main merge is in scope. Final
fixed-source submission/review remains pending; controller owns that submission.

## Appendix — final-review corrections / final6 pending

All preceding history is preserved. Old matrix3 is supplanted for current-source
qualification after reviewer runtime `pack_version`, durable receipt fsync and
cancellation bugs. Historical results are not relabeled. Running matrix5 was
invalidated by source changes; final6 is pending, not a final matrix PASS. The
reported base91 plus six added cases gives **91 + 6 = 97 expected**, not an actual
final count until final6 completes and its output is reviewed.

Generated manifests carry `pack_version=p4-full-semantic-v1`. Receipt publication
uses `fsynced_stage_then_exclusive_hard_link`: staging write/flush/fsync precedes
exclusive hard-link creation of the receipt, never overwriting an existing receipt.
`receipt_publication.directory_durability` remains explicitly
`NOT_GUARANTEED; directory fsync unavailable on some platforms`. File fsync is not
directory durability. Every `BaseException`, including `GeneratorExit` and custom
subclasses, preserves original reraising and finally accounting after claim.
Secondary errors remain in the error registry; stderr is a best-effort additional
accounting channel when receipt persistence fails, not a durability guarantee.

Root approved fifth file `rust/src/semantic.rs` for `cfg(test)` changes only,
superseding earlier no-Rust-edit scope only for tests. Actual Python synthetic
mapping/corpus products are exported to shared Rust `validate_mapping`,
`dense_hits_for`, `full_artifact` and `validate_manifest` coverage. Manifest coverage
uses a TEST-authority derivative with frozen authority substitutions, not production
FULL authority. JSONL provenance joins are fixture-only, not a production corpus
parser. Three actual direct-binary consumer version checks pass expected gates:
generated version reaches subsequent FULL artifact-size rejection; missing/empty
versions reject `missing/nontext pack_version`. This does not prove FULL opening.

Exact authorization fields remain `schema`, `operation`, `fixed_code_sha`,
`preflight_producer_sha`, `preflight_evidence_sha`, `reviewed_source_bindings`,
`output`, `max_attempts`, `count_review`, `disk_review`, `smoke_review`,
`executor_bindings`. The latter binds only the four original owned paths:
`tools/p4_full_build.py`, `tests/test_p4_full_build.py`, `docs/p4-full-semantic-v1.md`,
`docs/STAGE_STATUS.md`. Rust test source is covered by existing authenticated Rust
source inventory/guards, not a fifth executor-binding key; fixed-source review must
cover the root-approved test change. Native ORT/GPU and 21,718,736,896-byte FULL
snapshot/pack opening remain **NOT_RUN**; FULL attempts **0**, actual pack **NOT_RUN**.
This append changes docs only; final6 evidence and fixed-source review are pending.

### Authorization closure correction — supersedes historical four-file claims

`executor_bindings` now requires exactly `tools/p4_full_build.py`,
`tests/test_p4_full_build.py`, `docs/p4-full-semantic-v1.md`, `docs/STAGE_STATUS.md`,
and `rust/src/semantic.rs`: reviewed exact raw SHA256 and each path-filtered Git
blob at `fixed_code_sha`. Earlier four-file claims above are superseded.
Historical producer receipts, inventories and evidence bindings remain unchanged.
The only allowed Rust difference is the contiguous `#[test]` /
`builder_synthetic_reader_interop` block inside `#[cfg(test)] mod tests`, ending
before `full_paths_controlled_assets_receipt_exception_and_aliases`'s test attribute.
Its LF Git-byte SHA256 is pinned to
`8a5306d202fe4a7ee87a14d5cf05407a7b28ed18951ecf5a55c18566af876a78`.
Removing exactly that block must yield producer Git bytes byte-for-byte; arbitrary
test or production changes reject. Real temporary-Git fixture tests cover a legal
five-file closure and missing Rust, altered production, unapproved harness, and
uncommitted/fixed-Git mismatch. Finalmatrix6 is superseded; finalmatrix7 is pending.
No formal count/disk/GPU/FULL execution is authorized; attempts remain0.

## Attempt1 harness authority-domain remediation (no retry)

Historical implementation-stage attempts0 statements above are superseded by the
single authorized attempt recorded in `d5c7c1b0bc900af1f547c544e8fd95309e1a9395`.
Attempt1 is FAIL_HARNESS_AUTHORITY_DOMAIN_MISMATCH, consumed1, reservation phase,
all completed counts0, snapshot-after UNCHANGED. Original output, persistent lock,
authorization and receipts remain unchanged; no second attempt is authorized.

The defect compared raw CRLF job bytes to the Git source SHA. These are distinct:
source `53ee8132288252713b5ccdcd36acfa6f4aee455e95e552eafca0676a91e0cf14`, historical
raw execution `614bc6e64641a8ee718e30760d3acb4a03e7a8672d91224726446bf0eb38baf0`.
Acceptance now calls the existing `historical_job_bindings(root=ROOT)` lazily,
which authenticates HEAD source bytes, filtered checkout identity, historical
receipt exact bytes/PASS/job raw SHA, and raw job bytes independently. Then the
job binds frozen pack bytes, which bind approved DLL path/size/SHA and actual file.
Activation calls the same external authority primitive used by work inventory,
before reservation, and compares resolved DLL path and actual size/SHA with the
verified inventory. No normalized job bytes, changed pins or generic path exception.

Repair/future authorization requires exactly seven executor bindings: original
five (`tools/p4_full_build.py`, `tests/test_p4_full_build.py`, this document,
`docs/STAGE_STATUS.md`, `rust/src/semantic.rs`) plus `tools/p4_full_acceptance.py`
and `tests/test_p4_full_acceptance.py`. All require reviewed raw SHA/fixed Git blob.
Original attempt1 authorization retains its five keys and is not reusable.
Shared acceptance production changes are only accepted for independently pinned
old producer Git SHA `21583b2b2a38afee54bddccbdbbbbdf7f369dff23cc2946495d62d602e721c8c`
and exact repaired Git SHA `1210800f6e56f8ff91f07fbcb5577ff5720f085bfba35341bba6ee88b90e42a0`.
These pin only removal of the wrong-domain import/comparison, shared historical
binding resolution, and actual DLL verification; any additional code rejects.
Historical preflight receipts/producer identities are never migrated.

Synthetic real-Git LF/CRLF authority tests cover source/raw mismatches, receipt
bytes/status/job, pack hash, actual DLL size/hash, inventory path mismatch, and
activation rejection before reservation. No FULL projection, embeddings or ANN
execution forms part of this remediation. Full pack remains NOT_CREATED;
runtime qualification and quality acceptance remain NOT_RUN. STOP=WAITING_REVIEW.

## Explicit Attempt2/retry1 envelope (implementation only)

This section implements a future, separately authorized policy exception, not an
execution authorization. Historical Attempt1 is consumed1, FAIL/reservation,
all completed0 and snapshot UNCHANGED. It is never deleted, moved, rewritten or
reused as an output. Canonical configuration retains `build.max_attempts=1`.
Old `p4-full-build-authorization-v1` field/operation/output/max_attempts semantics
and `full.assert_no_product` remain intact. They do not authorize retry.

New `p4-full-build-retry-authorization-v1` requires exactly these sixteen keys:
`schema`, `operation`, `fixed_code_sha`, `attempt_number`, `max_total_attempts`,
`retry_of`, `failure_class`, `preflight_producer_sha`, `preflight_evidence_sha`,
`reviewed_source_bindings`, `output`, `previous_output`, `count_review`,
`disk_review`, `smoke_review`, `executor_bindings`.
Operation is `execute_full_retry`, attempt_number and max_total_attempts are both
integer2, failure_class is `HARNESS_AUTHORITY_DOMAIN_MISMATCH`, previous_output is
`build/p4-full-semantic-v1`, output is exclusively
`build/p4-full-semantic-v1-retry1`. New lock is exclusively
`build/p4-full-semantic-v1-retry1.attempt2.lock`. No Attempt3 is representable.

`retry_of` is an exact object containing result_sha `d5c7c1b0bc900af1f547c544e8fd95309e1a9395`,
implementation_sha `3eeda16b4f1c99b01430979819e5c079243d1f08`, and five `{path,size,sha256}`
bindings (`authorization`, `attempt1_lock`, `execution_receipt`, `command_receipt`,
`handoff`) pinned by `ATTEMPT1_BINDINGS` in the reviewed executor. It also contains
integer0 `completed_documents`, `completed_chunks`, `completed_embeddings`,
`completed_ann` and `snapshot_after_hash_status: UNCHANGED`.
Those independent pins include raw Windows bytes, not normalized JSON. Actual
old files are size/hash-checked, receipt FAIL/attempts1/reservation/four0/UNCHANGED
is parsed, and old output must contain exactly execution-receipt.json, no manifest.
`validate_retry_history_and_no_retry_product` requires that complete history and
absence of the new output/lock; it never weakens the old no-product guard.

Activation order, entirely before reserve2: (1) current fixed HEAD and origin/dev;
(2) independently hashed retry envelope; (3) Attempt1 history; (4) canonical
contract; (5) source closure, same exact seven paths plus strict source_guard;
(6) current inventory; (7) historical source/raw authority; (8) shared activation
DLL validation; (9) reviewed count/disk/smoke evidence; (10) fresh disk capacity;
(11) full snapshot size/SHA; (12) available GPU; (13) new output absent;
(14) new attempt2 lock absent. All final input guards and source/authorization
closure are rechecked before publication. No count/projection is rerun at activation.

The new lock records attempt2, retry_of, fixed_code_sha, authorization_sha256.
Cumulative `attempts` starts at historical1; separate `attempt_reserved=False`
controls terminal publication/retained_partial. Only successful exclusive lock
creation consumes2. Before-claim failures retain total1 and create no retry receipt,
output or lock. After-claim failures retain total2, lock and partial state. Success
also reports2. Retry receipts include
`BUILD_POLICY_EXCEPTION: EXPLICIT_ATTEMPT2_AFTER_VERIFIED_HARNESS_DEFECT`.
Manifest adds only `build_provenance` (attempt_number2, prior_attempt_resultFAIL,
prior_failure_class, retry_authorization_sha256, attempt1_execution_receipt_sha256,
attempt1_result_sha). Runtime contract and inventory/FULL pack digest algorithm
are unchanged; provenance is not a new runtime identity.

Implementation is committed normally first, then one real read-only readiness
probe uses that fixed implementation HEAD and verified origin/dev. It reads all
old bindings, historical job authorities, approved DLL, full inventory, full
snapshot SHA, fresh disk and GPU presence, never reserve/project/embed/ANN.
Its small receipt is a separate ordinary evidence commit, not an amended or
self-referential implementation SHA. Probe coverage is the implementation HEAD,
not the later evidence/submission HEAD. Any future authorization must pin the
then-current execution HEAD; source_guard HEAD equality is never waived.
Probe failures remain FAIL with later gates NOT_RUN; after-read errors and
cancellation preserve structured evidence (cancellation propagates).

No real retry authorization/output/lock is created by this implementation task.
Formal FULL attempts remain1, second attempt NOT_STARTED/NOT_AUTHORIZED, FULL pack
NOT_CREATED, runtime/quality NOT_RUN; stop WAITING_REVIEW even if readiness PASS.
