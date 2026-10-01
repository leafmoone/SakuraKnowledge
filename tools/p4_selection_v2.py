"""Offline, quality-only gate recomputation from the pinned P4 v1 receipt."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
from pathlib import Path

SOURCE = "reports/P4/continuation-pilot-quality.json"
SOURCE_COMMIT = "ffff13b"
# Derived from subprocess.check_output(['git', 'show', 'ffff13b:' + SOURCE]), raw bytes.
SOURCE_SHA256 = "05c44cfffab21235fd584c1fa289b976179a1b7ae92bfd06875b79c449ee2284"
JOB = "configs/p4-pilot-score-job.json"
CONFIG = "configs/p4-benchmark-v2.json"
OUTPUT = "reports/P4/selection-v2-recompute.json"
RULE_KEY = "semantic_crosslingual_recall10_target_rule"
RULE = "min(1, baseline + 0.10)"
BINDINGS = {name: name for name in ("gold", "corpus", "lexical", "dense_a", "dense_b", "config")}
BINDINGS["summary"] = "model_summary"
COUNTS = {"overall": (120, 110, 10), "lexical": (30, 30, 0),
          "semantic": (40, 40, 0), "crosslingual": (30, 30, 0),
          "ambiguous_negative": (20, 10, 10)}
METRICS = ("recall_at_5", "recall_at_10", "recall_at_20", "mrr_at_10", "ndcg_at_10")
MODES = ("BM25_ONLY", "EXACT_DENSE_MODEL_A", "EXACT_DENSE_MODEL_B",
         "RRF_HYBRID_MODEL_A", "RRF_HYBRID_MODEL_B")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


def parse(raw):
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)


def local(root, name):
    require(isinstance(name, str), "path must be a string")
    path = (root / name).resolve()
    require(path.is_relative_to(root), "path escapes repository")
    return path


def validate_config(v1, v2):
    expected = copy.deepcopy(v1)
    expected["contract_version"] = "p4-retrieval-engineering-v2"
    expected["selection"][RULE_KEY] = RULE
    require(v2 == expected, "v2 must differ only in version and explicit recall cap rule")


def validate_bindings(root, job, receipt):
    require(set(receipt["bindings"]) == set(BINDINGS), "unexpected or missing input bindings")
    require(job["output"] == SOURCE, "job does not point to original receipt")
    validations = {}
    for binding, key in BINDINGS.items():
        expected = receipt["bindings"][binding]
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                f"invalid {binding} hash")
        path = local(root, job[key])
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        require(actual == expected, f"input hash mismatch: {binding}")
        validations[binding] = {"path": job[key], "expected_sha256": expected,
                                "actual_sha256": actual, "valid": True}
    return validations


def measure(row, denominator):
    require(isinstance(row, dict) and set(row) == {"value", "denominator"},
            "malformed metric")
    require(type(row["denominator"]) is int and row["denominator"] == denominator,
            "metric denominator mismatch")
    value = row["value"]
    if denominator == 0:
        require(value is None, "zero-denominator metric must be null")
    else:
        require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1,
                "metric must be finite and within [0,1]")
    return value


def validate_metrics(metrics):
    require(set(metrics) == set(MODES), "missing or unexpected retrieval modes")
    for mode in MODES:
        require(set(metrics[mode]) == set(COUNTS), "missing or unexpected subsets")
        for subset, (cases, positives, negatives) in COUNTS.items():
            row = metrics[mode][subset]
            for key, expected in zip(("case_count", "positive_count", "negative_count"),
                                     (cases, positives, negatives)):
                require(type(row[key]) is int and row[key] == expected, "case count mismatch")
            require(set(row["metrics"]) == set(METRICS), "missing or unexpected metrics")
            for metric in METRICS:
                measure(row["metrics"][metric], positives)
            measure(row["identity_promotion_error_rate"], cases)
            measure(row["negative_identity_promotion_error_rate"], negatives)
            measure(row["negative_nonempty_rate"], negatives)


def recall_target(baseline):
    require(type(baseline) in (int, float) and math.isfinite(baseline)
            and 0 <= baseline <= 1, "invalid baseline recall")
    return min(1.0, baseline + .10)


def quality_gates(baseline, candidate):
    gates = {}
    for subset in ("lexical", "semantic", "crosslingual"):
        for metric in ("recall_at_10", "mrr_at_10", "ndcg_at_10"):
            base = baseline[subset]["metrics"][metric]["value"]
            value = candidate[subset]["metrics"][metric]["value"]
            if subset == "lexical":
                target = base - (1 / 30 if metric == "recall_at_10" else .03)
            else:
                target = recall_target(base) if metric == "recall_at_10" else base
            gates[f"{subset}.{metric}"] = {
                "baseline": base, "value": value, "minimum": target, "pass": value >= target}
    for subset, (_, _, negatives) in COUNTS.items():
        for metric in ("identity_promotion_error_rate", "negative_identity_promotion_error_rate"):
            if metric.startswith("negative_") and negatives == 0:
                continue
            value = candidate[subset][metric]["value"]
            gates[f"{subset}.{metric}"] = {"value": value, "maximum": 0, "pass": value == 0}
    return gates


def recompute(receipt, summary, config):
    """Pure metric arithmetic; caller must authenticate bytes before using this result."""
    require(receipt["schema"] == "p4-pilot-score-v1", "wrong source schema")
    require(summary["schema"] == "p4-model-freeze-summary-v1" and summary["status"] == "PASS",
            "invalid frozen model summary")
    require(set(summary["models"]) == {"a", "b"}, "invalid model labels")
    for model in config["models"]:
        frozen = summary["models"][model["label"][-1].lower()]
        require(frozen["repository"] == model["repo"] and frozen["revision"] == model["revision"]
                and re.fullmatch(r"[0-9a-f]{40}", frozen["revision"]), "model provenance mismatch")
    metrics = receipt["metrics"]
    validate_metrics(metrics)
    baseline = metrics["BM25_ONLY"]
    models = {}
    for label in ("a", "b"):
        gates = quality_gates(baseline, metrics[f"RRF_HYBRID_MODEL_{label.upper()}"])
        failures = [name for name, gate in gates.items() if not gate["pass"]]
        models[label] = {"gates": gates, "failures": failures, "pass": not failures}
    passing = [label for label, result in models.items() if result["pass"]]
    selected = None
    if len(passing) == 1:
        label = passing[0]
        frozen = summary["models"][label]
        selected = {"label": label, "repository": frozen["repository"],
                    "revision": frozen["revision"]}
    limitations = {}
    for subset in ("semantic", "crosslingual"):
        base = baseline[subset]["metrics"]["recall_at_10"]["value"]
        limitations[subset] = {"baseline_recall10": base, "uncapped_target": base + .10,
                               "capped_target": recall_target(base), "cap_active": base + .10 > 1}
    limitations["dense_to_hybrid_crosslingual"] = {
        label: {"dense_recall10": metrics[f"EXACT_DENSE_MODEL_{label}"]["crosslingual"]
                ["metrics"]["recall_at_10"]["value"],
                "hybrid_recall10": metrics[f"RRF_HYBRID_MODEL_{label}"]["crosslingual"]
                ["metrics"]["recall_at_10"]["value"]} for label in ("A", "B")}
    return {"schema": "p4-selection-v2-recompute", "scope": "quality_only",
            "models": models, "quality_only_selected_model": selected,
            "status": "UNIQUE_QUALITY_PASS" if selected else "NO_UNIQUE_QUALITY_PASS",
            "frozen_limitations": limitations, "retrieval_rerun": False,
            "embedding_rerun": False, "gold_changed": False, "fusion_changed": False,
            "fusion_rerun": False, "cpu_evidence": "NOT_RUN", "full_build": "NOT_RUN"}


def verify(root):
    root = Path(root).resolve()
    raw = local(root, SOURCE).read_bytes()
    source_sha = digest(raw)
    require(source_sha == SOURCE_SHA256, "original frozen quality receipt SHA256 mismatch")
    receipt = parse(raw)
    job_raw = local(root, JOB).read_bytes()
    job = parse(job_raw)
    validations = validate_bindings(root, job, receipt)
    v1 = parse(local(root, job["config"]).read_bytes())
    v2_raw = local(root, CONFIG).read_bytes()
    v2 = parse(v2_raw)
    validate_config(v1, v2)
    summary = parse(local(root, job["model_summary"]).read_bytes())
    result = recompute(receipt, summary, v2)
    result.update(source_receipt_sha256=source_sha,
                  source={"path": SOURCE, "commit": SOURCE_COMMIT,
                          "sha256": source_sha, "expected_sha256": SOURCE_SHA256, "valid": True},
                  input_hash_validations=validations, score_job_sha256=digest(job_raw),
                  v2_config_sha256=digest(v2_raw))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    root = Path.cwd().resolve()
    output = local(root, OUTPUT)
    require(not output.exists(), "output already exists")
    result = verify(root)
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


if __name__ == "__main__":
    main()
