# b7547a A-C evidence mapping

Review base b7547a0cf5344b073c73232b479741a1703c7ce3 was CHANGES_REQUIRED.
Reference/implementation/clean artifact source:42fa24810040349d05c0f8f0e10f9c7b3363e0b7.
This evidence proposes review readiness, not external approval.

| Finding | Implementation | Independent test IDs | Actual receipts |
|---|---|---|---|
| A 5001-digit integer | Python response.projected_integer caps conversion at20characters, preserves global digits guard; overflow marker projects null/true/present, ignored values cannot block identity | test_a_5001_digit_integer (positive/negative × projected/ignored; raw and guard unchanged) | review-b754-before-v2.json FAIL, review-b754-after-v1.json PASS, review-b754-artifact-abc.json A pairs |
| B long float lexeme | Rust parses syntactically valid RawValue float to binary64 then budgets projection, not source spelling; Python finite check; overflow null/true/present, finite underflow0 retained, invalid constants rejected | test_b_float_projected_budget (long decimals±/exponent/combined/overflow±/underflow); test_b_invalid_json_rejected (NaN,Infinity,1e,01) | before-v2/after-v1; artifact-abc B pairs |
| C inspect cap | Rust operation applies outer successful-response cap to every public operation including inspect; irreducible identity reports response_budget_exceeded without assuming candidate arrays | test_c_inspect_total_response_cap[False/True] (normal control and600000-character metadata) | before-v2/after-v1; artifact-abc Cnormal/Chuge |

All test IDs are in tests/test_review_b754.py. A-C adds17 cases. Full checks are
review-b754-check-{pytest,ruff,diff,fmt,rust-test,clippy,release}.json:167 pytest,
5 Rust tests, all seven command exits0. Aggregate totals are not substitutes for
these independent assertions. Contract:docs/p2-review-b754-contract.md.

## Failure preservation

- review-b754-before.json FAIL is an invalid initial fixture run: fixture writer
  connection was not closed/checkpointed before immutable Python read, causing stale
  fixture pages. It is **not credited as defect reproduction**; retained unchanged.
- review-b754-before-v2.json uses the corrected fixture with unchanged baseline
  runtime:13 failed,4 passed. Explicit digits-guard/float/cap failures reproduced.
- review-b754-after-v1.json:17 passed after implementation. No selective parity retry.
- All previous f99/bd99 receipts and original151 case inputs remain unchanged.

## Independent validation boundaries

- Formal151 accepted=135 full JSON comparisons+16 error contracts, no retries or
  timeouts; review-b754-output-verification.json verifies604 raw stream hashes.
- New wheel/standalone Rust built from clean source42fa248; local-only manifest and
  empty-working-tree build logs are separate from final documentation commits.
- Fresh offline wheel installation,8 real frozen-source CLI pairs plus help/error
  checks:review-b754-artifact-cli.json. These preserve S18 query/OR/topk10 semantics.
- Source-external A-C validation:review-b754-artifact-abc.json,10 independent fixture
  pairs,20 actual child commands/40 verified raw streams; command receipt exit0 is
  review-b754-artifact-abc-command.json. C error is an expected contract, not success
  JSON. UTF-8 explicitly set, raw retained, no console encoding failure in this run.
- Normalized finite binary64 values are not arbitrary precision. Raw spelling and
  full stored payload remain unchanged. Invalid JSON fixtures are deliberately
  invalid runtime robustness tests, not accepted source records.
- Final performance, snapshot hash and exact committed-byte binding are separate
  delivery receipts; no historical run is relabeled as a new-code execution.

Old nine fixes/R4 remain closed. No P1/main/production snapshot modifications;
no Pool/P3/refresh work. Linux/Pi/full human facts/dbstat/Pool/live refresh NOT_RUN.
