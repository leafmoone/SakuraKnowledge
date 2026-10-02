# P4 FULL clean-room preflight recovery

Implementation: `clean_room_reimplementation_after_untracked_source_loss`.
`recovered_original_source=false`. This is new source, not recovery of the lost drafts.
Baseline clean dev HEAD: `471829644b32eecc10aa30d9d3b71979500a3117`.

## Authority and references

Approved FULL requirements are the P4_FULL_CLEAN_ROOM_PREFLIGHT_RECOVERY instruction:
1,295,638 trusted documents (690,068 subjects, 221,960 characters, 102,338 persons,
281,272 Danbooru wiki pages); moegirl/local_tag zero; episodes excluded.
Committed references are `tools/p4_rust_pilot.py`, `tools/p4_chunks.py`,
`configs/p4-trusted-text-v1.json`, `docs/p4-rust-semantic-contract-v1.md`, and
`docs/p3-full-coverage-contract.md`. These are references, not replacement evidence.
The P3 snapshot is `build/p3-full-authorized-retry1/knowledge.sqlite`,
21,718,736,896 bytes, SHA256
`61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.

Phase 0–2 preservation is external:
`D:/SakuraTool/SakuraKnowledge-p4-full-loss-preserve-20261002/preserve`.
Inventory SHA256: `26d7f147be8aca7d715f35d839f3758dd247eae9a573a7e3e3b0057c564879e1`.
Old drafts remain disabled outside the repository. Historical **30 errors and
3 failures** remain historical failures, not rerun successes or erased evidence.

## Implemented scope / review gate

`configs/p4-full-semantic-v1.json` declares `p4-full-semantic-contract-v1` with a
required `declarative_contract`. Python preflight and acceptance consume it.
Preflight exposes readonly snapshot verification, ordered trusted document scan,
count-only projection using the committed paragraph/model-tokenizer chunker,
deterministic 512-document smoke, 512 FULL-only chunks and an injected exact
encoder callback for 128-pilot FP32 parity plus FULL-only embedding smoke.
SQLite handles explicitly close, including error paths; SQL temporary storage
is memory. No FULL product corpus, mapping, vectors, ANN, locks or attempt is created.
No Index.add/save or memmap is used. There is no build entry or execution CLI.

Disk estimation requires actual chunk count, actual pilot mapping file bytes and
an actual schema sample size. Raw bytes are N*4096+header (default128); ANN bytes
are N*(223537008/52664)*1.1; mapping uses the larger of actual pilot bytes/52664
and actual schema sample bytes/chunk, inflated1.25. Temporary space is explicit;
peak is final+temporary; required free is ceil(peak*1.25). This function is an
estimate, not a disk availability PASS or permission to execute.

**Implemented code, not fixed-stage validation or authorization:** Rust FULL native
snapshot FTS, independent readonly handles and dynamic pack contract have synthetic
coverage; pilot retains its original fixed contract and mode. Acceptance verifies
actual controlled canonical bytes, closed artifact inventory, source-backed pins and
snapshot provenance. Preflight orchestration uses the committed tokenizer/chunker and
LocalEncoder, complete pinned model/tokenizer/ONNX external/DLL inventory, bounded
temporary collision audit and measured mapping sample. These are implementation
claims backed by preparation tests, not completed real FULL count/GPU qualification.
The source remains an unfixed working tree. All preparation histories, including
v4/v6 complete matrices and v5 failure, are retained; none is fixed-stage evidence.
Every source/configuration change invalidates earlier preparation matrices; each
reported matrix binds its own exact source bytes. No future result is presumed PASS,
and preparation evidence never substitutes for fixed-stage real qualification.

Do not run FULL count or GPU/inference until code review. No actual preflight,
FULL corpus census, chunk count, capacity, embedding parity, runtime readiness,
or product acceptance PASS is claimed. Tests use synthetic data only.

## Remaining requirements

Remaining execution: root-reviewed implementation commit/push, then actual fixed-SHA
count/disk/tokenizer/GPU, formal pilot120, P2151/P355 and all required matrices. No
such actual qualification is claimed from synthetic fixtures. Product-root/lock
absence, source/remote/canonical/snapshot guards and bounded resource cleanup are
implemented. An initial staging gate uses only the necessary >=1295638 chunk lower
bound (every required nonempty document emits at least one), current pilot mapping
bytes and approved ANN per-row formula, audit reservation and free-space safety. It
rejects impossible positive budgets before inventory/count; it is not an upper bound
or an exact count. Actual header, measured expanded mapping and exact-count budgets
remain mandatory after scanning, and caller budgets may only increase minima.
Direct and nested deleted Rust source files are audited from the fixed Git tree.
Symlink tests lacking Windows privilege remain explicit NOT_RUN; junction/path escape
synthetic execution is reported separately. No synthetic PASS implies build approval.

Never recreate `tools/p4_full_semantic.py` or `tools/p4_full_build.py`. Never create
`build/p4-full-semantic-v1` in this implementation. No main, Pool, global, historical
receipt or committed pilot artifact changes; no destructive Git; no commit yet.
