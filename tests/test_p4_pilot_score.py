"""Synthetic offline fixtures only: no DB, model or benchmark calls."""
import json
from copy import deepcopy
from dataclasses import asdict

import pytest

from tools import p4_pilot_score as score


def fixture():
    docs = []
    for i in range(1, 5):
        docs.append({"document_id": i, "entry_id": i + 100,
                     "entry_key": {"kind": "page", "namespace": "source", "value": f"name{i}"},
                     "source_id": "source", "evidence_id": f"evidence{i}"})
    cases = [{"case_id": str(i), "query": f"q{i}", "subset": subset,
              "accepted_targets": [docs[i - 1]] if i < 4 else []}
             for i, subset in enumerate(("lexical", "semantic", "crosslingual", "ambiguous/negative"), 1)]
    gold = {"schema_version": "p4-source-gold-v1", "status": "FROZEN_PRE_EMBEDDING",
            "base_snapshot_sha256": "snapshot", "cases": cases}
    config = {"fusion": deepcopy(score.FUSION), "selection": deepcopy(score.SELECTION),
              "snapshot_sha256": "snapshot", "pilot_documents": 4,
              "case_counts": {s: 1 for s in score.metrics.SUBSETS}}
    bindings = {"gold": "goldhash", "corpus": "corpushash", "summary": "summaryhash"}
    metadata = {"config": {"document_depth": 100, "depth_before_entry_dedup": True},
                "gold": {"sha256": bindings["gold"]}, "corpus": {"sha256": bindings["corpus"]},
                "snapshot": {"sha256": "snapshot"}, "document_count": 4}
    metadata["config_sha256"] = score.digest(score.canonical(metadata["config"]))
    metadata["binding_sha256"] = score.digest(score.canonical(metadata))
    lex = {"schema": "p4-pilot-lexical-v1", "metadata": metadata, "cases": []}
    summary = {"status": "PASS", "models": {}}
    dense = {}
    for model in ("a", "b"):
        frozen = {"repository": model, "revision": "rev" + model,
                  "obtained_receipt": {"inventory_sha256": "inventory" + model},
                  "contract": {"file_sha256": "contract" + model}}
        summary["models"][model] = frozen
        provenance = {"model": model, "repository": model, "revision": frozen["revision"],
                      "model_inventory_sha256": frozen["obtained_receipt"]["inventory_sha256"],
                      "contract_sha256": frozen["contract"]["file_sha256"],
                      **{k + "_sha256": v for k, v in bindings.items()}}
        dense[model] = {"schema": "p4-exact-results-v2", "exact_reference": True,
                        "setup": {"status": "PASS"}, "depth": 100,
                        "aggregation": "maximum chunk dot score per typed entry",
                        "provenance": provenance, "cases": []}
    for case, doc in zip(cases, docs):
        hit = {"entry": doc["entry_key"], "rank": 1, "score": .8,
               "document_id": str(doc["document_id"]), "source_id": doc["source_id"],
               "evidence_id": doc["evidence_id"]}
        # BM25 misses semantic/crosslingual, allowing quality gates to qualify.
        hits = [hit] if case["subset"] not in ("semantic", "crosslingual") else []
        lex["cases"].append({**{k: case[k] for k in ("case_id", "query", "subset")},
                             "mode": "BM25_ONLY", "raw_hits": hits, "trusted_pins": [],
                             "ranking": [h["entry"] for h in hits], "identity_status": "not_asserted",
                             "promoted_identities": []})
        for model in dense:
            dense[model]["cases"].append({"case_id": case["case_id"], "status": "PASS",
                                           "elapsed_ms": .01, "hits": [{**hit, "chunk_id": "chunk"}]})
    return gold, docs, lex, dense, summary, config, bindings


def test_adapter_five_modes_negative_and_paired():
    report, details = score.score(*fixture())
    assert len(report["metrics"]) == 5
    assert report["selection"]["status"] == "PENDING_CPU_HYBRID_EVIDENCE"
    assert report["selection"]["quality_gate_failures"] == {"a": [], "b": []}
    dense = report["metrics"]["EXACT_DENSE_MODEL_A"]
    assert dense["overall"]["metrics"]["recall_at_10"] == {"value": 1, "denominator": 3}
    assert dense["ambiguous_negative"]["metrics"]["mrr_at_10"]["value"] is None
    assert report["candidate_counts"]["EXACT_DENSE_MODEL_A"]["4"] == 1
    assert report["paired_vs_bm25"]["RRF_HYBRID_MODEL_A"]["semantic"]["recall_at_10"]["mean_delta"] == 1
    assert report["document_anchor_recall"]["EXACT_DENSE_MODEL_A"]["overall"]["recall_at_5"]["value"] == 1
    fused = details[0]["fused"]["RRF_HYBRID_MODEL_A"][0]
    assert fused["entry"]["value"] == "101"  # Explicit arithmetic bridge, not source value name1.
    assert len(fused["provenance"]) == 2
    assert asdict(score.typed(fixture()[1][0])) == {"namespace": "source", "kind": "page", "entry_id": "101"}


@pytest.mark.parametrize("model", ["a", "b"])
@pytest.mark.parametrize("change", ["missing", "duplicate", "fail", "not_run", "schema", "hash", "model"])
def test_fail_closed_cases_and_schema(model, change):
    args = fixture()
    artifact = args[3][model]
    if change == "missing":
        artifact["cases"].pop()
    elif change == "duplicate":
        artifact["cases"].append(artifact["cases"][0])
    elif change in ("fail", "not_run"):
        artifact["cases"][0]["status"] = change.upper()
    elif change == "schema":
        artifact["schema"] = "unknown"
    elif change == "hash":
        artifact["provenance"]["gold_sha256"] = "changed"
    else:
        artifact["provenance"]["model_inventory_sha256"] = "changed"
    with pytest.raises(ValueError):
        score.score(*args)


def test_anchor_id_is_not_source_value_and_config_is_not_tunable():
    args = fixture()
    args[0]["cases"][0]["accepted_targets"] = [deepcopy(args[1][0])]
    args[0]["cases"][0]["accepted_targets"][0]["entry_id"] = 999
    with pytest.raises(ValueError, match="anchor entry ID"):
        score.score(*args)
    args = fixture()
    args[5]["selection"]["min_semantic_recall10_gain"] = .01
    with pytest.raises(ValueError, match="frozen numeric"):
        score.score(*args)


def test_dense_dedup_and_raw_branch_depth():
    args = fixture()
    hit = args[3]["a"]["cases"][0]["hits"][0]
    args[3]["a"]["cases"][0]["hits"].append({**hit, "rank": 2})
    with pytest.raises(ValueError, match="deduplicated"):
        score.score(*args)
    mapping = score.Mapping(args[1])
    hits = [{**hit, "rank": i} for i in range(1, 101)]
    assert len(mapping.hits(hits)) == 100
    fused = score.metrics.reciprocal_rank_fusion({"bm25": mapping.hits(hits)})
    assert len(fused) == 1 and len(fused[0].provenance) == 100
    assert fused[0].backend_ranks == (("bm25", 1),)
    with pytest.raises(ValueError, match="raw depth"):
        mapping.hits([*hits, {**hit, "rank": 101}])


def test_pins_only_from_lexical_do_not_promote():
    args = fixture()
    doc = args[1][1]
    args[2]["cases"][0]["trusted_pins"] = [{"entry": doc["entry_key"], "match": "alias",
                                               "source_id": "source", "evidence_id": "identity-evidence"}]
    args[2]["cases"][0]["ranking"].insert(0, doc["entry_key"])
    # Dense-side pin-looking data is never a trust attestation.
    args[3]["a"]["cases"][0]["trusted_pins"] = [{"garbage": True}]
    report, details = score.score(*args)
    assert details[0]["fused"]["RRF_HYBRID_MODEL_A"][0]["entry"]["value"] == "102"
    assert report["metrics"]["RRF_HYBRID_MODEL_A"]["overall"]["identity_promotion_error_rate"]["value"] == 0


def test_actual_cpu_receipt_and_wrong_scope():
    args = fixture()
    cpu = {"schema": "p4-score-cpu-v1", "models": {}}
    for m in ("a", "b"):
        cpu["models"][m] = {"provenance": args[3][m]["provenance"], "scope": "hybrid_total_retrieve",
                            "device": "cpu", "status": "PASS", "peak_rss": 100,
                            "model_plus_index_bytes": 1000,
                            "samples": [{"case_id": str(i), "status": "PASS",
                                         "elapsed_ms": i * (1 if m == "a" else 2)} for i in range(1, 5)]}
    report, _ = score.score(*args, cpu=cpu)
    assert report["selection"]["selected"] is None
    assert report["selection"]["cpu_evidence"]["status"] == "NOT_QUALIFIED"
    cpu["models"]["a"]["scope"] = "total_retrieve"
    report, _ = score.score(*args, cpu=cpu)
    assert report["selection"]["cpu_evidence"]["status"] == "NOT_QUALIFIED"


@pytest.mark.parametrize("pinned", [False, True])
def test_hybrid_source_key_order_preserves_snapshot_identity(pinned):
    args = fixture()
    a, z = args[1][:2]
    for doc, value, entry_id in ((a, "a", 2), (z, "z", 1)):
        doc["entry_key"]["value"] = value
        doc["entry_id"] = entry_id

    def hit(doc, rank):
        return {
            "entry": doc["entry_key"], "rank": rank, "score": .8,
            "document_id": str(doc["document_id"]),
            "source_id": doc["source_id"], "evidence_id": doc["evidence_id"],
        }

    lexical = args[2]["cases"][0]
    lexical["raw_hits"] = [hit(z, 1), hit(a, 2)]
    lexical["trusted_pins"] = [
        {"entry": doc["entry_key"], "match": "alias",
         "source_id": doc["source_id"], "evidence_id": doc["evidence_id"]}
        for doc in (z, a)
    ] if pinned else []
    lexical["ranking"] = [doc["entry_key"] for doc in ((a, z) if pinned else (z, a))]
    for model in ("a", "b"):
        args[3][model]["cases"][0]["hits"] = [hit(a, 1), hit(z, 2)]
    report, details = score.score(*args)
    for model in ("A", "B"):
        fused = details[0]["fused"][f"RRF_HYBRID_MODEL_{model}"]
        assert [c["entry"]["value"] for c in fused] == ["2", "1"]
        assert [c["hybrid_rank"] for c in fused] == [1, 2]
        assert fused[0]["rrf_score"] == fused[1]["rrf_score"]
        assert all(len(c["provenance"]) == 2 for c in fused)
        assert all(bool(c["trusted_pins"]) == pinned for c in fused)
    bm25 = report["metrics"]["BM25_ONLY"]["lexical"]["metrics"]
    assert bm25["mrr_at_10"]["value"] == (1 if pinned else .5)


@pytest.mark.parametrize("cpu", [None, {"schema": "p4-score-cpu-v1", "models": {}}])
def test_both_quality_gates_fail_stops_without_cpu_selection(cpu):
    args = fixture()
    for artifact in args[3].values():
        for case in artifact["cases"]:
            case["hits"] = []
    report, _ = score.score(*args, cpu=cpu)
    selection = report["selection"]
    assert selection["status"] == "STOP"
    assert selection["selected"] == "NONE"
    assert all(selection["quality_gate_failures"].values())
    assert selection["cpu_evidence"]["status"] == (
        "NOT_RUN" if cpu is None else "NOT_QUALIFIED"
    )
    assert report["full"] == "NOT_RUN"


@pytest.mark.parametrize("qualified", ["a", "b"])
def test_one_qualifying_model_still_requires_hybrid_cpu_evidence(qualified):
    args = fixture()
    failing = "b" if qualified == "a" else "a"
    for case in args[3][failing]["cases"]:
        case["hits"] = []
    report, _ = score.score(*args)
    selection = report["selection"]
    assert selection["quality_gate_failures"][qualified] == []
    assert selection["quality_gate_failures"][failing]
    assert selection["status"] == "PENDING_CPU_HYBRID_EVIDENCE"
    assert selection["selected"] is None
    assert selection["cpu_evidence"]["status"] == "NOT_RUN"
    assert report["full"] == "NOT_RUN"


def test_local_create_new_and_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        score.local("../escape.json")
    args = fixture()
    names = ("gold", "corpus", "lexical", "dense", "model_summary", "config", "bindings")
    data = dict(zip(names, args))
    job = {name: name + ".json" for name in ("gold", "lexical", "model_summary", "config")}
    job.update(corpus="corpus.jsonl", dense_a="dense_a.json", dense_b="dense_b.json",
               output="summary.json", details="details.json")
    for name in ("gold", "model_summary", "config"):
        score.save(job[name], data[name])
    corpus_raw = b"".join(score.canonical(d) + b"\n" for d in args[1])
    (tmp_path / job["corpus"]).write_bytes(corpus_raw)
    bindings = {"gold": score.load(job["gold"])[1], "summary": score.load(job["model_summary"])[1],
                "corpus": score.digest(corpus_raw)}
    metadata = args[2]["metadata"]
    for k in ("gold", "corpus"):
        metadata[k]["sha256"] = bindings[k]
    metadata["binding_sha256"] = score.digest(score.canonical({k: v for k, v in metadata.items() if k != "binding_sha256"}))
    score.save(job["lexical"], args[2])
    for m in ("a", "b"):
        args[3][m]["provenance"].update({k + "_sha256": v for k, v in bindings.items()})
        score.save(job["dense_" + m], args[3][m])
    score.save("job.json", job)
    score.main(["--job", "job.json"])
    report = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert report["selection"]["status"] == "PENDING_CPU_HYBRID_EVIDENCE"
    assert (tmp_path / "details.json").exists()
    with pytest.raises(ValueError, match="already exists"):
        score.main(["--job", "job.json"])
