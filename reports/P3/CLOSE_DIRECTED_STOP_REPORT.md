# P3 A-L directed closure — NOT_READY / STOP

No P3 success or self-approval is claimed. Baseline STOP evidence442cad was approved
only as STOP reporting; this new code/evidence requires a separate fixed-SHA review.
Runtime/artifact code is `9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102`.
Main baseline is `894dc6a73bfd42f18cc7648e8ab7481aae211ab1`. Parent/final submission
closure requires `close-committed-binding.json` and successful `p3_close_bind.py verify`
after normal dev push; this parent report does not self-certify those later operations.

## A-F actual preparation

BaselineHEAD=origin/dev442cad, main894; FULL initial whole-byte hash matched21718736896B/
`61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.
Three cancelled unfinished files were recorded by path/size/SHA, moved with original
basenames to ignored `build/p3-retry1-cancelled-prep/` without overwriting and rehashed.
`close-preconditions.json` gives all exactbindings. These files were not repaired,
compiled as products or discarded. No third snapshot build, DB modification or A repair merge.

A single read-only metadata/EXPLAIN diagnostic returned `index_episodes='false'`.
Builder storage.py281-282 excludes episode FTS under false. SQL/parameters/plan are
retained in `close-diagnosis.json`: FTS scan, joins and temporary ORDER BY B-tree.
This did **not** execute S02, and EXPLAIN alone is not measured query/rootcause evidence.

Minimal Rust change: exact/alias lookup first, same topk sufficiency and short-query
semantics, then only explicitfalse plus kindepisode skips FTS. True/missingmetadata
and other kinds follow existing FTS. No ONEPIECE hardcode/OR/token/BM25/ranking/kind
or budget change. Profile `fts_skipped_kind_not_indexed=true` is evidence of that
branch, not missing facts. Python public API and source/storage/resolver unchanged.

Explicit opt-in `SKNOW_SEARCH_PROFILE_OUT` uses create_new before query, no directory
creation/overwriting. That invocation searches once; last_search_profile serialized
within unchanged5s and CLI15s total. Reservation/write failures surface nonzero;
post-query write failures retain actual result or original error, defaultstdout/error
unchanged. Synthetic independent fixtures verify exact/alias retained, no-hit skip,
trueFTS/missingmeta/non-episode, multiplequeries, envdisabled/existingsink/newbadparent/
originalqueryerror; injected Rust sinkwritefailure tested. Newpytest8profiletests PASS,
Rust7library+1binarytests PASS. Lint changed only line-specific BLE001 explanations and
TRY004 TypeError; `validate_inputs` reverses exactly these edits to verify original
frozen bytehash, without altering cases/expected or historical FAIL.

Preparation clippyFAIL (`items_after_test_module`) and corrected separatePASS remain;
initial preparation re.S/RUF100 lint failures were actual tool observations, not formal
K outcomes. Scope-specific corrections happened before fixedcode/G.

## Cross-repository output exception

Initial preparatory cargo inherited host `CARGO_TARGET_DIR` pointing at
`D:/SakuraTool/SakuraPool-P4-work/rust-target`; actual cargo test output identifies
that directory and thus **Pool build artifacts were written**. See
`close-target-environment-incident.json` for observed paths/argv and bounded claims.
No Pool source edits were performed by this controller; external repository contents
were not independently audited, no globalconfig changed and no external cleanup.
**SAKURAPOOL_MODIFIED=YES_BUILD_ARTIFACTS_ONLY**, not unconditionalNO and not integration.
All subsequent cargo/test environments explicitly confine resolvedtarget to Knowledge
or each archive target; helper rejects external target/--target-dir override.

## Fixed source artifacts and G/H success

Clean9d7bd50 archived once; actual commands exit0 for release/examples, offline wheel,
venvcreate/install. `close-artifacts.json` contains argv/elapsed/raw/env/allartifactSHA
and12 module archive=wheel=installed bytes. Binary:
`dist/p3-close-9d7bd507/source/rust/target/release/sknow-rs.exe`,5144490B,
SHA256 `d36a00efd44bd3faa8c911a0416bad2d09dabe339b113b23039a8496a9d2972e`.
Reusedbench5118230B/SHA `a86ec7058ace48c621a1cddc7733f171fc6b5446029aa131e74d59535762ae8c`.
Wheel `dist/p3-close-9d7bd507/sakura_knowledge-0.2.0-py3-none-any.whl`,33641B,
SHA `84c34d2bcd93e9bd0e484a938e0d2a0158092ddd63852e0dc0c0dc8a36604b6b`.
No snapshot build occurs in artifact creation.

G samebinary exactly once S02: `search FULLDB "ONE PIECE" --topk20 --kindepisode`,
exit0/not_found/candidates0/timeoutfalse/outerfalse. CLI elapsed0.19701919999988604s;
profile queryelapsed0.0043481s, exact0.0042331s/scanned0/materialized0/skiptrue/
query_invocations1. `close-S02.json` retains stdout/stderr/profile raw plus opt-in env.
Original5.172s budgetFAIL preserved. This new authorized execution is not relabeled
historical success and is not a profilequery rerun.

H once151 Rust cases and once151 installedPython comparisons from temporary source-
external cwd (`-I -Xutf8`, no PYTHONPATH): **151/151 PASS,135values+16errors**,0timeouts/
0retries; all151 installedPython match independent frozenexpected. Originalcases,
expectedJSON and sourceproof frozen before any observed newRustoutput, unchanged.
No outcome-driven refreeze. Old55/55 remains separate historical9dfa evidence.

## I actual performance failure — do not discard warmup

`close-performance.json` and commandreceipt exit1/251.28364839999995s.
Fixed predeclared13 resolver cases plus S02/S18,30measured rounds+one warmup per mode;
15cases×30×2=**900measured**,15×2=**30warmups**. All900measuredPASS;29warmupsPASS,
**one warmupFAIL**: reused_connection G42 round-1/requestindex4:

```json
{"case_id":"G42","elapsed_s":5.0000352,"error":"query_budget_exceeded"}
```

Reused batch exit0/emptystderr134.64001980000012s; per-case error is real even though
batchprocess succeeds. Its wrapper `succeeded=0/other_error=1` fields reflect generic
single-JSON decoder on JSONL, not a separate processfailure; entireJSONL is independently
decoded and per-request evaluated by protocol. Original fields are preserved, not
silently overwritten. Raw1,823,820B SHA
`1359f540e1afc5df4f31d04b19b76d24a27b98b32dba7b2230c2e35a3c63aa11` in committed
`close-raw/`. Exact465input requests retained too. Failure has no profilerunningsecond
query; no additional phaseprofile was collected. Rootcause of G42 timeout **UNKNOWN**.

Nearest-rank successful measuredpercentiles (seconds; all30attempts each):

| Case | Reused p50 / p95 | Independent CLI p50 / p95 |
|---|---|---|
| G42 |0.3955825 /0.4380207|0.3552313 /0.4012721|
| S02 |0.0002081 /0.0004839|0.0343464 /0.0429963|
| S18 |0.2372747 /0.2685192|0.2292829 /0.2595561|

All30mode/case summaries and930failureinclusive rows retained. These timings are
not performancePASS, coldcache or RSS claims.5s internal/CLI15s/reused600s unchanged;
no droppedwarmup/retry/resampling/hotcache substitute/budgetincrease.

## J stopped, K code checks, L preservation

Newcode FULL55 and final externalenvironment/help/resolver validation **NOT_RUN**
after IFAIL; chainedcommands were never launched. H installed151/sourceexternal
facts do not imply whole JPASS. Old55PASS/wrong0 is historicalonly, not newcodePASS.

K seven exact commands actualexit0 at fixed9d7bd50source (only receiptfiles untracked
at checks, no trackedcode changes):

1. `python -m pytest -q`:324PASS,0SKIP; SKNOW_RS_TEST_BIN points at freshartifact.
2. `python -m ruff check src tests tools`.
3. `git diff --check`.
4. `cargo fmt --manifest-path rust/Cargo.toml --all -- --check`.
5. `cargo test --manifest-path rust/Cargo.toml --locked`:7library+1binaryPASS.
6. `cargo clippy --manifest-path rust/Cargo.toml --all-targets --locked -- -D warnings`.
7. `cargo build --manifest-path rust/Cargo.toml --release --locked`.

`close-check-*` exactargv/exit/env/raw retained. Beforepytest static test grep showed
no FULL runtime work; fixtures/tmp only. Tests do not substitute for J. Later evidence-
only binder is independentlylinted in `close-binder-lint-initial.json`, not misattributed
to those earlier checks. Its actualargv `python -m ruff check tools/p3_close_bind.py`
returned exit0. Existing collector was covered by fixedcodeKruff, not a new rerun.
L actual `python tools/p3_close_bind.py protect` exit0/53.18402969999988s recorded
in `close-protection-command.json`; whole FULL/oldP2 and oldpartial/privatebytes match
in `close-protection.json`. OldP2 is21516320768B/SHA256
`4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073`;
filehashing only, no additional SQL/query/checkpoint/cleanup. Final delivery is contingent
on normal dev push, remote=HEAD/main unchanged, empty porcelain and successful final
binder verification. Parent/child byte closure must verify newraw committed byteverbatim;
old shared `reports/P3/raw/` content-addressed bytes are locally protected (oldcontract's
independentraw wording is historicalinconsistent; no claim it was used). Historical report
blob equality is checked against442cad. This report does not declare these pending
operations complete before their receipts and final verification exist.
Verified0OPTIONAL/candidate100/human0 remain, no guessed identities/mapping promotion.
Linux/Pi/Poolruntime/live refresh/full human factreview NOT_RUN. Aisolatedrepair never
merged. **NOT_READY / WAITING_REVIEW; approvalNONE for this fixed submission**.
