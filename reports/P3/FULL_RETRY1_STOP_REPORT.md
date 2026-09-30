# P3 retry1 — successful build, NOT_READY / STOP after actual P2 S02 timeout

This reports execution evidence, not P3 closure or external approval. Sole writer on dev;
main remains `894dc6a73bfd42f18cc7648e8ab7481aae211ab1`. Normal submission and remote
binding will be verified separately; no self-referential final-commit hash is asserted here.

## Fixed build and publication

- Build code: `9dfa610640eca1e32b6da89f78f3d4aff6062adf`; approved implementation:
  `8a5b3d23695a43970d1902d6d6dea7c9e7dd1882`.
- Exact managed command: `python tools/record_check.py --timeout 0 --out reports/P3/full-retry1-build-command.json -- python -u tools/p3_full_candidate_retry1.py --execute`.
- Actual wrapper exit0/PASS, elapsed13984.489062299952s, stderr empty; outer tool
  timeout0 and inner effective timeoutNone. `full-retry1-build-command.json` retains
  actual argv, encoding environment, stdout/stderr and code/worktree at invocation.
- Retry1 ledger max1/attempt1; historical failed attempt1 unchanged; total formal
  attempts2, automatic retries0. No retry2, resume, alternate output or postbuild patch.
- Published database: `build/p3-full-authorized-retry1/knowledge.sqlite`, 21718736896 bytes,
  SHA256 `61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.
- Manifest33308 bytes, SHA256 `373fcb69731db877929c102b75292142c0ccff1b5f6075310acc03432ddb6b8b`.
- Builder report integrityok/FK0, FTS1295638 equals expected/missing0/invalid0,
  source-account errors[], six sources rejected0; entries3734577. WAL checkpoint
  `[0,0,0]`. Readonly projection352/nativeWiki28/verified entity_tag0/capability1.
  Full details and old partial/lock/snapshot byte protection are in `full-retry1-build.json`.
- OPTIONAL_COVERAGE permits verified0; candidates100/human0 unchanged. No identity
  created from guesses, candidate promotion or invented verified mapping.

## Freeze and actual runtime acceptance

`full-retry1-freeze-command.json` exit0: source-anchored FULL55 and independent Python
P2 expected151 (135 values+16 errors) frozen before Rust. Input cases unchanged;
SQL-backed data expansion declared before runtime. Only P2 historical E18 summary
changes are manifest/page/freelist metadata. No observed Rust output adjusted expected.

1. First gold gate: `full-retry1-gold-command.json` exit1 and
   `full-retry1-gold-accept-STOP.json`, records[]; zero Rust cases. Validator compared
   whole path dictionaries, treating POSIX/Windows slash spelling as mutation.
   Actual size/SHA unchanged. Original validator/frozen bytes remain unchanged.
2. User directly authorized path-wrapper continuation after the question explaining
   the exact scope. NEW `p3_retry1_path_audit.py` compares resolved file identity and
   exact size/SHA;7 targeted tests pass. Corrected command has its own receipt.
3. `full-retry1-real-acceptance.json`: **55 attempted/55 passed**,39positive/16nonresolved,
   wrong resolved0, timeouts0, preservation problems[]. Wrapper exit0/104.099335s.
   These cases were not rerun.
4. First P2 gate: `full-retry1-P2-command.json` exit1/0.1454629s, zero runtime cases;
   readonly Rust left WAL0/SHM32768, but gate rejected any sidecar. Failure stderr/raw
   remains. `full-retry1-P2-sidecar-observation.json` preserves metadata and limitations.
5. User directly instructed `继续执行，修正门禁`. NEW sidecar-only wrapper allows
   stable WAL0/SHM32768 with equal initialized empty-frame headers, no journal, no
   retry1 lock, whole frozen DBsize/SHA, and conservative related-process check.
   Historical original lock is never removed. Process silence is NOT complete
   handle enumeration/no-writer proof; TOCTOU/permission limits are explicit in
   `full-retry1-sidecar-gate.json`. No DB write, sidecar deletion or expected changes.
6. `full-retry1-P2-corrected-command.json`: exit1/152.33744679996744s. Actual
   `full-retry1-P2-compatibility.json`: **151 attempted/150 passed**,134 full values
   compared,16 error contracts verified, preservation problems[]. This is a real
   runtime failure, not a gate pseudo-failure. No additional P2 runtime retry.

## Exact blocking failure

Case **S02**, argv:

```text
D:\SakuraTool\SakuraKnowledge\dist\p3-retry1-9dfa610\source\rust\target\release\sknow-rs.exe search D:\SakuraTool\SakuraKnowledge\build\p3-full-authorized-retry1\knowledge.sqlite "ONE PIECE" --topk 20 --kind episode
```

- Exit2; elapsed5.172278400044888s; inner timeouttrue, outer timeoutfalse.
- Error `{"error":"ValueError","message":"query_budget_exceeded"}`.
- Stdout0 bytes: `reports/P3/raw/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.raw`.
- Stderr57 bytes: `reports/P3/raw/0eaf4a0b226386308aff19088a5d3a77d440e60d8662c9140fb88adbf7982a3a.raw`.
- Frozen independent Python value exists; historical summary unchanged. Failed Rust
  result was not semantically compared, so only134/135 value comparisons completed.
- Unchanged5s operation budget/15s CLI host limit. No increased timeout, retry,
  hot-cache substitution, expected edit or relabeling as PASS.

Static-only investigation suggestion, **not a measured root cause**: `rust/src/search.rs:43-51`
selects filtered bm25 ranking and deterministic sorting over FTS/entry/document joins;
`rows.next()` may execute SQLite work before scan limits reduce results. Compare this
filtered episode query's plan/ranking work and budget coverage only under fresh
explicit diagnostic authorization. No EXPLAIN, query rerun or code repair was executed.

## Truthful unexecuted obligations

- FULL dual-mode performance780 measured+26warmups: **NOT_RUN after P2 failure**.
- Installed wheel/binary source-external FULL runtime validation: **NOT_RUN**.
- Fresh9dfa wheel/venv/release receipts, synthetic ABC10 pairs and owner18/original8
  fixture checks exist; none substitutes for FULL performance/runtime verification.
- New seven-check receipts: first pytest187PASS/121SKIP without Rust test binary;
  separate integration pytest308PASS/0SKIP. Ruff exit1; diff/fmt/Rust6/clippy/release
  exit0. Seven-check ALL_PASS is not claimed. Cancelled unused collector preparation
  files remain excluded/untracked; earlier Ruff syntax/import findings in them are
  not asserted fixed. See `full-retry1-preparation-cancelled.json`.
- New seven-check closure may test code/audit tools, never erase the P2 failure.
  Historical full-authorized RuffFAIL, first path-RuffI001FAIL, sidecar-RuffI001/SIM102FAIL
  remain; corrected lint outcomes have separate receipts. Original stop collector
  failure and retry mock-test failures remain historical evidence.
- No Linux/Pi/Pool/SakuraTool/live refresh/full human fact review/dbstat/RSS claim.

## WAL diagnosis and A-only experiment

`full-retry1-readonly-diagnostic.json` transcribes actual CPU/IO/file/disk fields and
bounded WAL-tail diagnostics; no invented local full raw-stream archive. Physical-tail
salt/checksum not validated; no consistent DB view or exact live SQL/ETA claim. The
initial no-explicit-commit therefore one large transaction explanation was corrected:
outermost SAVEPOINT RELEASE can commit. Frequent releases with a pinned SELECT and
repeated page versions supported WAL amplification. Empty sidecars afterward are
separate from the large build WAL.

User chose **A** (isolated repair/tests while original retry1 continued), not B
(terminate/rebuild). `build/p3-wal-batch-repair-A/` has original9dfa archive, isolated
diff,11+55 tests, before/after WAL2507records28,411,552 versus650,992 bytes sampled
pre-checkpoint peak; semantic rows/order/accounts/rejection match. It was **not
applied to dev or this snapshot**. Every1000 checkpoint is not a byte-size/full-throughput
bound; final DROP/FTS work and frequentcheckpoint cost remain limitations. Initial
CRLF archive assertion failure and receipt-only recovery retained. Source raw bytes
unchanged. This ignored experiment is not formal FULL acceptance or committed production repair.

## Authority and submission boundary

This controller received the direct user messages for isolatedA, path continuation,
and sidecar continuation in sequence; root recorded their transcriptions, not direct
receipt of those user events. New real S02 failure terminates the authorized sequence.
Root instructed only NOT_READY/STOP evidence delivery: no new diagnostic query,
revalidation, larger budget, newbuild or A merge. Existing historical reports and old
snapshot/failed staging remain protected. Completion is not proposed as successful P3;
fixed-SHA review request will cover truthful STOP reporting only after normal push
and independent remote dev=HEAD/main894 checks.
