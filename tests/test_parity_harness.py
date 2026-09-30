"""Synthetic harness results, independent of runtime correctness or snapshot."""
import base64
import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location("parity_policy", TOOLS / "parity_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
spec = importlib.util.spec_from_file_location("check_parity", TOOLS / "check_parity.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def difference(a, b):
    return [] if a == b else [{"kind": "value"}]


def expected(value, want):
    return [] if value == want else [{"kind": "expect"}]


def classify(a, b, mode="value", want=None):
    return policy.classify(a, b, mode, want or {}, difference, expected)


def value(v):
    return {"exit": 0, "value": v}


ERROR = {"exit": 2, "error": {"message": "invalid"}}
TIMEOUT = {"exit": 2, "error": {"message": "query_budget_exceeded"}}


def test_error_first():
    result = classify(ERROR, ERROR, "error", {"error": "invalid"})
    assert result["status"] == "EXPECTED_ERROR_PASS"
    assert not result["semantic_compared"]
    assert result["error_contract_verified"]


def test_error_after_failure():
    failed = classify(value(1), value(2))
    passed = classify(ERROR, ERROR, "error", {"error": "invalid"})
    assert failed["status"] == "MISMATCH"
    assert passed["status"] == "EXPECTED_ERROR_PASS"
    assert policy.summarize([failed, passed], 2)["overall"] == "FAIL"


def test_both_timeout():
    result = classify(TIMEOUT, TIMEOUT, "budget_limited")
    assert result["status"] == "BOTH_TIMEOUT"
    assert policy.summarize([result], 1)["overall"] == "FAIL"


@pytest.mark.parametrize("a,b", [(TIMEOUT, value({})), (value({}), TIMEOUT)])
def test_single_timeout(a, b):
    result = classify(a, b, "budget_limited")
    assert result["status"] == "SINGLE_TIMEOUT"
    assert not result["semantic_compared"]
    assert not result["passed"]


def test_one_side_only_value():
    result = classify(value({}), {})
    assert result["status"] == "NOT_COMPARED"
    assert not result["passed"]


def test_expected_error_success():
    result = classify(ERROR, ERROR, "error", {"error": "invalid"})
    summary = policy.summarize([result], 1)
    assert summary["overall"] == "PASS"
    assert summary["actually_compared"] == 0
    assert summary["error_contract_verified"] == 1


def test_mismatch():
    assert classify(value({"a": 1}), value({"a": 2}))["status"] == "MISMATCH"


def test_array_order_difference():
    result = classify(value([1, 2]), value([2, 1]), want=[1, 2])
    assert result["status"] == "MISMATCH"


def test_missing_required_case_fails():
    assert policy.summarize([], 1)["overall"] == "FAIL"


def test_expected_error_cannot_accept_value():
    assert not classify(value({}), ERROR, "error", {"error": "invalid"})["passed"]


def test_full_recursive_diff_keeps_array_order_and_types():
    assert harness.diff({"a": [1, 2]}, {"a": [2, 1]})
    assert harness.diff({"a": True}, {"a": 1})
    assert not harness.diff({"a": [1, 2]}, {"a": [1, 2]})


def test_capture_full_large_streams_no_pipe_deadlock():
    rec = harness.capture([sys.executable, "-c",
                           ("import sys;sys.stdout.write('x'*100000);"
                            "sys.stderr.write('y'*90000)")])
    assert base64.b64decode(rec["stdout_base64"]) == b"x" * 100000
    assert base64.b64decode(rec["stderr_base64"]) == b"y" * 90000
    assert rec["other_error"] == 1  # malformed JSON cannot count as success
    assert not rec["timeout"]


def test_capture_outer_timeout_is_bounded():
    rec = harness.capture([sys.executable, "-c", "import time;time.sleep(30)"],
                          timeout_s=0.2)
    assert rec["outer_timeout"] and rec["timeout"]
    assert rec["elapsed_s"] < 5
    assert rec["attempted"] == 1 and rec["succeeded"] == 0


@pytest.mark.parametrize("warning", ["search_document_scan_limit", "response_budget_truncated"])
def test_equal_partial_is_not_pass(warning):
    result = classify(value({"warnings": [warning]}), value({"warnings": [warning]}))
    assert result["status"] == "PARTIAL" and not result["passed"]


def test_real_error_first_child():
    rec = harness.capture([sys.executable, "-c",
                           ("import sys,json;print(json.dumps(dict(error='ValueError',"
                            "message='invalid')),file=sys.stderr);sys.exit(2)")])
    assert classify(rec, rec, "error", {"error": "invalid"})["passed"]
