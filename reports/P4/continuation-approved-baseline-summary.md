# P4_APPROVED_P3_BEHAVIOR_BASELINE_V1

Status: PASS. This is a **new P4 regression baseline captured from externally approved P3 fixed behavior; NOT original P3 oracle recovery**. Original FULL55 recovery remains **0/55**.

## Source and isolation

- Built source HEAD: `e9ffff87acceb9fa16798a0db76597b605997282`.
- Externally approved source: `269e34eeeac920c29f2d684cfe37c93a95c73057`.
- Approved-to-HEAD and HEAD-to-working `src rust` diffs were empty before build, before formal execution, after capture, and at final verification. No production files were edited by this work.
- Fresh explicit `CARGO_TARGET_DIR=build/p4-approved-baseline-target` (absolute repository path in the receipt), never inherited Pool target. MSYS UCRT gcc/g++ environment follows `tools/p3_final_artifacts.py`; that old runner was not imported or executed.
- Snapshot opened through `file:///.../knowledge.sqlite?mode=ro&immutable=1`. Before/after snapshot SHA-256 `61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`, bytes `21718736896`. Sidecar hashes also unchanged.
- Binary SHA-256 `7dfb4ffa9c09747ec9769a5d2a4bc62e2c4983e3a9e7caf29d6bff404250c65d`, bytes `5149588`.

## Formal results

- P2: **151/151**, comprising **135 independent full values** reconstructed to original expected byte hashes and **16 exact error contracts**.
- Gold: **55/55** source assertions; **39 resolved**, **16 nonresolved**, **0 wrong resolved**. Assertions cover status, tag/source key, matched_by, canonical status, candidates, descriptions, and evidence where specified by the tracked source cases.
- Each formal case executed **once**, retries **0**, timed-out cases **0**. Historical **15-second outer deadlines** retained; runtime query-budget errors are counted as timeouts, not ordinary passing errors. The unchanged runtime retains its internal budget.
- No expected outputs regenerated after mismatches; no mismatches occurred. Gold full outputs are newly captured regression values, not claims of recovered historical oracle equality.
- Exact stdout/stderr bytes, full actual JSON, exit codes, elapsed times, source assertions/results, and a complete local corpus inventory are under `build/p4-approved-baseline/`. The manageable repository report is `continuation-approved-baseline.json` and includes all formal argv/stream hashes and source provenance.
- Baseline corpus manifest SHA-256: `f5cf6bce10c2d192bb2fbdf2e432d01e90d8e00e25f4aad7530e99b361e396ed` (61574 bytes).

## Commands and verification

Commands were invoked through the available bash shell / Python subprocess wrapper on Windows to retain UTF-8 output reliably:

```text
git diff --exit-code 269e34eeeac920c29f2d684cfe37c93a95c73057 HEAD -- src rust
git diff --exit-code HEAD -- src rust
git ls-files --others --exclude-standard -- src rust
git rev-parse HEAD
git status --short
python -m pytest tests/test_p4_approved_baseline.py tests/test_p4_legacy_baseline.py -q
python -m ruff check tools/p4_approved_baseline.py tests/test_p4_approved_baseline.py
python tools/p4_approved_baseline.py --execute
cargo build --manifest-path D:\SakuraTool\SakuraKnowledge\rust\Cargo.toml --locked --release --bin sknow-rs
```

The helper also runs `git ls-files -z` through the reused legacy-freeze validator. All 206 full formal command arrays are retained in the JSON report; none were rerun for validation. Build stdout/stderr receipts are in that report as well.

Final tests: **30 passed**. Final Ruff: **All checks passed**. An initial helper test failed because its temporary corpus root was outside the repository root; fixed the test fixture and reran only unit tests. Initial lint found import ordering, exception type, and broad-catch annotation issues; fixed these. After successful formal capture, helper-only lint fixes reordered imports, changed rejection of a non-object JSON from ValueError to TypeError (both already caught), and documented the failure-receipt catch. No formal cases were rerun.

No commits, staging, Pool/Tool processes, external P3 preservation reads, P3 report writes, or model work were performed. New repository files remain unstaged for the owning agent. Local corpus files must be preserved alongside the repository manifest; hashes attest observed bytes, not protection against a future writer.
