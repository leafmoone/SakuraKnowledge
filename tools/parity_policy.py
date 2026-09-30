"""Pure formal acceptance policy; missing values never establish equality.

EQUAL means a full value comparison and independent assertions completed.
EXPECTED_ERROR_PASS validates only the error contract, not value semantics.
Timeouts (including both sides) and incomplete values always fail.
"""
from __future__ import annotations


def classify(py: dict, rs: dict, mode: str, expect: dict, diff, check_expect) -> dict:
    problems = []
    compared = False
    error_verified = False
    timeout = [bool(r.get("timeout") or r.get("budget_exhausted")
                    or "query_budget_exceeded" in str(r.get("error", "")))
               for r in (py, rs)]
    if any(timeout):
        status = "BOTH_TIMEOUT" if all(timeout) else "SINGLE_TIMEOUT"
        problems.append({"kind": status, "python": timeout[0], "rust": timeout[1]})
    elif any("value" in r and not isinstance(r["value"], dict) for r in (py, rs)):
        status = "MISMATCH"
        problems.append({"kind": "invalid_success_json_shape"})
    elif any(isinstance(r.get("value"), dict) and "warnings" in r["value"] and
             not isinstance(r["value"]["warnings"], list) for r in (py, rs)):
        status = "MISMATCH"
        problems.append({"kind": "invalid_warnings_json_shape"})
    elif any(isinstance(r.get("value"), dict) and any(
            w in (r["value"].get("warnings") or []) for w in
            ("search_document_scan_limit", "response_budget_truncated")) for r in (py, rs)):
        status = "PARTIAL"
        problems.append({"kind": "incomplete_response"})
    elif mode == "error":
        for side, result in (("python", py), ("rust", rs)):
            error = result.get("error")
            message = error.get("message") if isinstance(error, dict) else error
            if (not isinstance(error, dict) or "value" in result or
                    message != expect["error"] or result.get("exit") != 2):
                problems.append({"kind": "expected_error", "side": side,
                                 "want": expect["error"], "actual": result})
        error_verified = not problems
        status = "EXPECTED_ERROR_PASS" if error_verified else "EXPECTED_ERROR_FAIL"
    elif "value" in py and "value" in rs and py.get("exit") == rs.get("exit") == 0:
        compared = True
        problems.extend(diff(py["value"], rs["value"]))
        problems.extend(check_expect(py["value"], expect))
        problems.extend(check_expect(rs["value"], expect))
        status = "EQUAL" if not problems else "MISMATCH"
    else:
        status = "NOT_COMPARED"
        problems.append({"kind": "missing_actual_value"})
    return {"status": status, "problems": problems, "semantic_compared": compared,
            "error_contract_verified": error_verified,
            "passed": status in ("EQUAL", "EXPECTED_ERROR_PASS")}


def summarize(cases: list[dict], required_count: int) -> dict:
    complete = len(cases) == required_count
    passed = sum(c.get("passed", False) for c in cases)
    compared = sum(c.get("semantic_compared", False) for c in cases)
    return {"required": required_count, "attempted": len(cases), "passed": passed,
            "actually_compared": compared, "not_compared": len(cases) - compared,
            "error_contract_verified": sum(c.get("error_contract_verified", False)
                                           for c in cases),
            "overall": "PASS" if complete and passed == required_count else "FAIL"}
