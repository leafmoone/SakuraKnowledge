"""Pure arithmetic and temporary-file provenance tests; never run the real verifier."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("p4_selection_v2", ROOT / "tools/p4_selection_v2.py")
v2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v2)


def load(path):
    return json.loads((ROOT / path).read_bytes())


@pytest.fixture
def inputs():
    return (load(v2.SOURCE), load("reports/P4/model-freeze-summary.json"), load(v2.CONFIG))


def test_config_exact_diff_and_v1_preserved():
    original = (ROOT / "configs/p4-benchmark-v1.json").read_bytes()
    assert v2.digest(original) == "2c687060ac1c50201ae8aee685f05526b88fbb447c441f5fb1d1240800e4ef85"
    v2.validate_config(json.loads(original), load(v2.CONFIG))
    assert v2.digest((ROOT / v2.SOURCE).read_bytes()) == v2.SOURCE_SHA256
    changed = load(v2.CONFIG)
    changed["fusion"]["k"] = 61
    with pytest.raises(ValueError, match="differ only"):
        v2.validate_config(json.loads(original), changed)


@pytest.mark.parametrize("baseline,target", [(0, .1), (.1, .2), (.9, 1), (.975, 1), (1, 1)])
def test_cap_independent_of_model(baseline, target):
    assert v2.recall_target(baseline) == target


def test_frozen_metric_arithmetic_only(inputs):
    receipt, summary, config = inputs
    before = copy.deepcopy(receipt)
    result = v2.recompute(receipt, summary, config)
    assert receipt == before
    assert result["models"]["a"]["failures"] == [
        "crosslingual.recall_at_10", "crosslingual.mrr_at_10", "crosslingual.ndcg_at_10"]
    assert result["models"]["b"]["pass"]
    assert result["quality_only_selected_model"] == {
        "label": "b", "repository": summary["models"]["b"]["repository"],
        "revision": summary["models"]["b"]["revision"]}
    assert result["frozen_limitations"]["semantic"]["baseline_recall10"] == .975
    gap = result["frozen_limitations"]["dense_to_hybrid_crosslingual"]["B"]
    assert gap["dense_recall10"] == pytest.approx(26 / 30)
    assert gap["hybrid_recall10"] == pytest.approx(22 / 30)
    assert "FINAL_SELECTED_MODEL" not in json.dumps(result)


@pytest.mark.parametrize("label", ["a", "b"])
@pytest.mark.parametrize("subset,metric,loss", [
    ("lexical", "recall_at_10", 1 / 30),
    ("lexical", "mrr_at_10", .03), ("lexical", "ndcg_at_10", .03),
    ("semantic", "recall_at_10", None), ("crosslingual", "recall_at_10", None),
    ("semantic", "mrr_at_10", 0), ("semantic", "ndcg_at_10", 0),
    ("crosslingual", "mrr_at_10", 0), ("crosslingual", "ndcg_at_10", 0)])
def test_each_gate_boundary(inputs, label, subset, metric, loss):
    receipt, summary, config = inputs
    base = receipt["metrics"]["BM25_ONLY"][subset]["metrics"][metric]["value"]
    target = v2.recall_target(base) if loss is None else base - loss
    row = receipt["metrics"][f"RRF_HYBRID_MODEL_{label.upper()}"][subset]["metrics"][metric]
    row["value"] = target
    result = v2.recompute(receipt, summary, config)
    assert result["models"][label]["gates"][f"{subset}.{metric}"]["pass"]
    row["value"] = target - 1e-8
    result = v2.recompute(receipt, summary, config)
    assert not result["models"][label]["gates"][f"{subset}.{metric}"]["pass"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1.01, None, True, "1"])
def test_invalid_metric_fails_closed(inputs, value):
    receipt, summary, config = inputs
    receipt["metrics"]["RRF_HYBRID_MODEL_B"]["semantic"]["metrics"]["recall_at_10"]["value"] = value
    with pytest.raises(ValueError):
        v2.recompute(receipt, summary, config)


@pytest.mark.parametrize("denominator", [0, 39, 40.0, True, None])
def test_denominator_fails_closed(inputs, denominator):
    receipt, summary, config = inputs
    row = receipt["metrics"]["RRF_HYBRID_MODEL_B"]["semantic"]["metrics"]["recall_at_10"]
    row["denominator"] = denominator
    with pytest.raises(ValueError, match="denominator"):
        v2.recompute(receipt, summary, config)


def test_identity_errors_and_unique_selection(inputs):
    receipt, summary, config = inputs
    receipt["metrics"]["RRF_HYBRID_MODEL_A"] = copy.deepcopy(
        receipt["metrics"]["RRF_HYBRID_MODEL_B"])
    assert v2.recompute(receipt, summary, config)["quality_only_selected_model"] is None
    for label in ("A", "B"):
        receipt["metrics"][f"RRF_HYBRID_MODEL_{label}"]["overall"][
            "identity_promotion_error_rate"]["value"] = 1 / 120
    result = v2.recompute(receipt, summary, config)
    assert result["quality_only_selected_model"] is None
    assert all(not row["pass"] for row in result["models"].values())


def test_summary_provenance(inputs):
    receipt, summary, config = inputs
    summary["models"]["b"]["revision"] = "0" * 40
    with pytest.raises(ValueError, match="provenance"):
        v2.recompute(receipt, summary, config)


@pytest.mark.parametrize("raw", ['{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', '{'])
def test_malformed_json(raw):
    with pytest.raises(ValueError):
        v2.parse(raw)


@pytest.mark.parametrize("binding", list(v2.BINDINGS))
def test_every_input_binding_tamper(tmp_path, binding):
    job = {"output": v2.SOURCE}
    receipt = {"bindings": {}}
    for name, key in v2.BINDINGS.items():
        job[key] = name + ".json"
        raw = json.dumps({"fixture": name}).encode()
        (tmp_path / job[key]).write_bytes(raw)
        receipt["bindings"][name] = v2.digest(raw)
    validated = v2.validate_bindings(tmp_path, job, receipt)
    assert set(validated) == set(v2.BINDINGS)
    (tmp_path / job[v2.BINDINGS[binding]]).write_bytes(b"tamper")
    with pytest.raises(ValueError, match="input hash mismatch"):
        v2.validate_bindings(tmp_path, job, receipt)


def test_rewritten_source_rejected_before_inputs(tmp_path):
    source = tmp_path / v2.SOURCE
    source.parent.mkdir(parents=True)
    source.write_text('{"bindings": {}, "metrics": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="frozen quality receipt SHA256"):
        v2.verify(tmp_path)
    assert not (tmp_path / v2.OUTPUT).exists()


def test_output_exclusive_and_fixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / v2.OUTPUT
    output.parent.mkdir(parents=True)
    monkeypatch.setattr(v2, "verify", lambda root: {"fixture": True})
    v2.main([])
    before = output.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        v2.main([])
    assert output.read_bytes() == before
    with pytest.raises(SystemExit):
        v2.main(["--output", "elsewhere.json"])
