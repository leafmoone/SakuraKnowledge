# b7547a A-C response-boundary repair

Only A-C of this review are reopened; prior nine fixes and R4 remain closed.
Storage/search-text v2, response v3, source raw, identity, five-second deadline,
S18 OR/topk10 and production snapshot remain unchanged.

A. Evidence JSON uses a local bounded parse_int callback. It converts at most20
characters to int; longer or out-of-domain integers use a constant small numeric
marker outside [-2^63,2^64-1]. Projection emits null/truncated=true/state=present.
Ignored numbers cannot trigger CPython's digits guard. The global digits guard is
never disabled or changed. Stored raw bytes are never rewritten.

B. Floats are parsed as binary64 after JSON syntax validation. Source lexeme length
is not a projected-value budget: 1. followed by2050zeroes projects to1.0 without
truncation. Finite floats (including underflow to signed zero) are retained; finite
binary64 JSON serialization is far below2048bytes. Overflow to infinity becomes
null/truncated=true/state=present, recursively inside field containers. Invalid
JSON literals such as NaN/Infinity, leading-zero integers and incomplete exponents
are rejected rather than accepted as legitimate observations. Python rejects JSON
extension constants explicitly; Rust's RawValue validates syntax before float parsing.

C. Rust outer operation success passes through bound_response for every public
query, including inspect. The gate handles irreducible inspect objects without
candidate/relation/warning arrays: an oversized snapshot identity yields explicit
response_budget_exceeded, never truncates identity and never panics. Normal inspect
retains identical JSON. Deadline/error checks remain shared.

Independent tests: tests/test_review_b754.py (17 parameterized cases):
- test_a_5001_digit_integer: positive/negative × projected/ignored, guard unchanged,
  raw unchanged and independent null/simple/truncated/state expectations.
- test_b_float_projected_budget: long positive/negative decimals, long exponent,
  decimal+exponent, overflow±, underflow; raw unchanged.
- test_b_invalid_json_rejected: NaN,Infinity,1e,01.
- test_c_inspect_total_response_cap:600000-character snapshot and normal control.

Failure-first evidence: review-b754-before.json is an INVALID FIXTURE RUN retained
as FAIL: the writer connection was not closed/checkpointed before immutable Python
reads, so it is not credited as defect reproduction. Corrected fixture connections
close before both runtimes. review-b754-before-v2.json then reproduces13fail/4pass
on unchanged b7547a runtime, including A digits guard, B float differences and C cap.
review-b754-after-v1.json:17pass after implementation. No historical receipt overwritten.

All new review-b754 JSON is -text byte-verbatim. Final binding hashes exact committed
Git blobs, separately observing worktree bytes, without a self-referential commit hash.
Fixture success is not human source-fact validation; existing NOT_RUN boundaries stay.
