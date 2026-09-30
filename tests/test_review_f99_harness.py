"""Malformed but legal JSON must fail one case, never abort a formal run."""
import pytest
from test_parity_harness import harness


@pytest.mark.parametrize("body", [None, [], 7, "error"])
def test_error_json_shape_fails_and_next_case_runs(monkeypatch, body):
    def capture(*_args, **_kwargs):
        return {"exit": 2, "error": body, "timeout": False, "stdout": "",
                "stderr": "raw retained", "stderr_base64": "cmF3IHJldGFpbmVk"}

    monkeypatch.setattr(harness, "capture", capture)
    first = harness.run_case(("shape", "cli", {"argv_py": [], "argv_rs": []},
                              {"exit_py": 2, "exit_rs": 2, "stderr_py_error": "UsageError",
                               "stderr_rs_error": "UsageError"}, "cli"), harness.ROOT / "dummy")
    assert not first["passed"]
    assert first["python"]["stderr_base64"] == "cmF3IHJldGFpbmVk"
    second = harness.run_case(("next", "lookup", {"query": "x"}, {}, "value"), harness.ROOT / "dummy")
    assert not second["passed"]


@pytest.mark.parametrize("body", [None, [], 7, "value"])
def test_success_json_shape_fails_and_next_case_runs(monkeypatch, body):
    monkeypatch.setattr(harness, "capture", lambda *_a, **_k: {"exit": 0, "value": body})
    monkeypatch.setattr(harness, "DB", harness.ROOT / "fixture.sqlite")
    result = harness.run_case(("shape", "lookup", {"query": "x"}, {"status": "found"}, "value"),
                              harness.ROOT / "dummy")
    assert not result["passed"] and not result["semantic_compared"]
    monkeypatch.setattr(harness, "capture", lambda *_a, **_k: {"exit": 0, "value": {"status": "found"}})
    result = harness.run_case(("next", "lookup", {"query": "x"}, {"status": "found"}, "value"),
                              harness.ROOT / "dummy")
    assert result["passed"]
