"""Pure arithmetic, typed-boundary and frozen selection-policy regression tests."""

import importlib.util
import json
import sys
from dataclasses import asdict, replace
from math import log2
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "p4_retrieval_metrics", Path(__file__).resolve().parents[1] / "tools/p4_retrieval_metrics.py"
)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def key(value, namespace="source", kind="entry"):
    return m.EntryKey(kind=kind, namespace=namespace, value=value)


def test_key_dict_contract_and_order():
    payload = {"kind": "tag", "namespace": "source", "value": "actual typed value"}
    entry = m.EntryKey(**payload)
    assert asdict(entry) == payload
    assert entry == m.EntryKey("tag", "source", "actual typed value")
    with pytest.raises(TypeError):
        m.EntryKey(kind="tag", namespace="source", entry_id=123)
    for value in (123, True, None, "", " "):
        with pytest.raises(ValueError, match="nonempty"):
            key(value)
    # Kind precedes namespace, and value is lexical text, never a numeric row ID.
    entries = [key("b", "a", "z"), key("b", "z", "a"), key("a", "z", "a")]
    expected = [entries[2], entries[1], entries[0]]
    assert sorted(entries) == expected
    assert [c.entry for c in m.reciprocal_rank_fusion(
        {"bm25": [m.Hit(e, 1) for e in entries]}
    )] == expected
    assert [c.entry for c in m.reciprocal_rank_fusion(
        {}, [m.TrustedPin(e, "exact", "s", "e") for e in entries]
    )] == expected


def test_metrics_known_math_and_duplicate_targets():
    a, b, c, d = map(key, "abcd")
    metrics = m.ranking_metrics([d, a, b], [a, b, c, a])
    assert metrics.recall_at_5 == pytest.approx(2 / 3)
    assert metrics.recall_at_10 == pytest.approx(2 / 3)
    assert metrics.recall_at_20 == pytest.approx(2 / 3)
    assert metrics.mrr_at_10 == 0.5
    assert metrics.ndcg_at_10 == pytest.approx(
        (1 / log2(3) + 1 / log2(4)) / (1 + 1 / log2(3) + 1 / log2(4))
    )


def test_cutoffs_and_binary_ideal_cap():
    entries = [key(f"typed-value-{i}") for i in range(22)]
    metrics = m.ranking_metrics(entries, entries)
    assert metrics.recall_at_5 == pytest.approx(5 / 22)
    assert metrics.recall_at_10 == pytest.approx(10 / 22)
    assert metrics.recall_at_20 == pytest.approx(20 / 22)
    assert metrics.ndcg_at_10 == 1
    assert metrics.mrr_at_10 == 1
    outside = m.ranking_metrics(entries, [entries[10]])
    assert outside.mrr_at_10 == outside.ndcg_at_10 == 0
    assert outside.recall_at_10 == 0
    assert outside.recall_at_20 == 1
    assert m.ranking_metrics(entries, [entries[20]]).recall_at_20 == 0


def test_entry_dedup_compacts_before_metric_cutoffs():
    a, b = key("a"), key("b")
    assert m.deduplicate_ranking([a, a, b, a]) == (a, b)
    result = m.ranking_metrics([a] * 100 + [b], [b])
    assert result.recall_at_5 == 1
    assert result.mrr_at_10 == 0.5
    assert result.ndcg_at_10 == pytest.approx(1 / log2(3))


@pytest.mark.parametrize("ranking", [[], [key("wrong")]])
def test_no_relevant_or_no_results(ranking):
    result = m.ranking_metrics(ranking, [key("gold")])
    assert all(getattr(result, name) == 0 for name in m.METRICS)


@pytest.mark.parametrize("ranking", [[], [key("anything")]])
def test_empty_target_metrics_are_na(ranking):
    result = m.ranking_metrics(ranking, [])
    assert all(getattr(result, name) is None for name in m.METRICS)


def test_typed_keys_do_not_collapse_namespace_or_kind():
    entries = [key("same"), key("same", "other"), key("same", kind="tag")]
    assert len(m.deduplicate_ranking(entries)) == 3
    assert m.ranking_metrics(entries, [entries[2]]).mrr_at_10 == pytest.approx(1 / 3)
    for untyped in ("same", 123, asdict(entries[0])):
        with pytest.raises(ValueError, match="typed"):
            m.ranking_metrics([untyped], entries)


def test_rrf_best_raw_rank_depth_and_preserved_provenance():
    a, b, c = map(key, "abc")
    duplicate = m.Hit(a, 2, 0.3, "doc2", "chunk2", "src", "ev")
    result = m.reciprocal_rank_fusion({
        "semantic": [duplicate, m.Hit(b, 100), m.Hit(c, 101)],
        "bm25": [m.Hit(a, 1, -500), m.Hit(a, 3), m.Hit(b, 4, 100000)],
    })
    assert [item.entry for item in result] == [a, b]
    assert result[0].rrf_score == pytest.approx(1 / 61 + 1 / 62)
    assert result[1].rrf_score == pytest.approx(1 / 64 + 1 / 160)
    assert result[0].backend_ranks == (("bm25", 1), ("semantic", 2))
    assert len(result[0].provenance) == 3
    assert m.Provenance("semantic", duplicate) in result[0].provenance
    assert result[0].trusted_pins == ()
    assert result[0].warnings == (m.RELEVANCE_WARNING,)


def test_rrf_ties_and_permutations_are_deterministic():
    a, b, c = key("2"), key("10"), key("2", kind="tag")
    first = {"z": [m.Hit(a, 2), m.Hit(b, 1), m.Hit(c, 1)],
             "a": [m.Hit(a, 1), m.Hit(b, 2), m.Hit(c, 2)]}
    second = {name: list(reversed(hits)) for name, hits in reversed(list(first.items()))}
    result = m.reciprocal_rank_fusion(first)
    assert result == m.reciprocal_rank_fusion(second)
    assert [item.entry for item in result] == [b, a, c]
    assert [item.hybrid_rank for item in result] == [1, 2, 3]


def test_pins_precede_fusion_without_implicit_score_or_reference_trust():
    a, b, c = map(key, "abc")
    pins = [m.TrustedPin(c, "exact", "src", "ev"), m.TrustedPin(b, "alias", "s", "e")]
    result = m.reciprocal_rank_fusion(
        {"exact": [m.Hit(a, 1, 1e30, source_id="s", evidence_id="e"), m.Hit(b, 90)]},
        pins,
    )
    assert [item.entry for item in result] == [b, c, a]
    assert result[0].backend_ranks == (("exact", 90),)
    assert result[1].rrf_score == 0
    assert result[2].trusted_pins == ()
    assert result == m.reciprocal_rank_fusion(
        {"exact": [m.Hit(a, 1, 1e30, source_id="s", evidence_id="e"), m.Hit(b, 90)]},
        reversed(pins),
    )


@pytest.mark.parametrize("rank", [0, -1, 1.5, True, float("nan"), float("inf"), "1"])
def test_invalid_ranks(rank):
    with pytest.raises(ValueError, match="Rank"):
        m.Hit(key("a"), rank)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf"), True, "0"])
def test_invalid_scores(score):
    with pytest.raises(ValueError, match="finite"):
        m.Hit(key("a"), 1, score)


def test_invalid_pins_and_empty_fusion():
    with pytest.raises(ValueError, match="exact/alias"):
        m.TrustedPin(key("a"), "semantic", "s", "e")
    with pytest.raises(ValueError, match="nonempty"):
        m.TrustedPin(key("a"), "exact", "", "e")
    with pytest.raises(ValueError, match="TrustedPin"):
        m.reciprocal_rank_fusion({}, [key("a")])
    assert m.reciprocal_rank_fusion({}) == ()
    assert m.reciprocal_rank_fusion({"bm25": [m.Hit(key("a"), 101)]}) == ()


def test_negative_behavior_and_macro_denominators():
    a = key("a")
    cases = [
        m.evaluate_case("p1", "lexical", [a], [a]),
        m.evaluate_case("p2", "semantic", [], [a]),
        m.evaluate_case("n1", "ambiguous_negative", [], []),
        m.evaluate_case("n2", "ambiguous_negative", [a], []),
        m.evaluate_case("n3", "ambiguous_negative", [a], [],
                        promoted_identities=[a], trusted_identity_keys=[a]),
    ]
    report = m.aggregate_cases(cases)
    overall = report["overall"]
    assert (overall.case_count, overall.positive_count, overall.negative_count) == (5, 2, 3)
    assert overall.metrics["recall_at_5"] == m.Mean(0.5, 2)
    assert overall.negative_nonempty_rate.value == pytest.approx(2 / 3)
    assert overall.negative_nonempty_rate.denominator == 3
    assert overall.negative_identity_promotion_error_rate.value == pytest.approx(1 / 3)
    assert overall.identity_promotion_error_rate == m.Mean(0.2, 5)
    assert not cases[3].identity_promotion_error
    assert report["lexical"].metrics["mrr_at_10"] == m.Mean(1, 1)
    assert report["ambiguous_negative"].metrics["ndcg_at_10"] == m.Mean(None, 0)
    assert report["crosslingual"].case_count == 0
    assert report["crosslingual"].negative_nonempty_rate == m.Mean(None, 0)


def test_relevant_is_not_trusted_identity_and_ambiguous_may_be_positive():
    a = key("a")
    untrusted = m.evaluate_case("p", "ambiguous_negative", [a], [a], promoted_identities=[a])
    trusted = m.evaluate_case("t", "crosslingual", [a], [a],
                              promoted_identities=[a], trusted_identity_keys=[a])
    assert untrusted.metrics.recall_at_5 == 1
    assert untrusted.identity_promotion_error
    assert not trusted.identity_promotion_error
    assert m.aggregate_cases([untrusted])["ambiguous_negative"].positive_count == 1


def test_empty_aggregate_and_input_errors():
    assert m.aggregate_cases([])["overall"].metrics["recall_at_5"] == m.Mean(None, 0)
    case = m.evaluate_case("p", "lexical", [], [])
    with pytest.raises(ValueError, match="Duplicate"):
        m.aggregate_cases([case, case])
    with pytest.raises(ValueError, match="Unknown subset"):
        m.evaluate_case("p", "typo", [], [])
    with pytest.raises(ValueError, match="nonempty"):
        key("value", namespace="")


def gate_cases(lexical=(0.8, 0.8, 0.8), semantic=(0.5, 0.5, 0.5),
               crosslingual=(0.5, 0.5, 0.5)):
    # Synthetic macro inputs isolate policy arithmetic, not measured retrieval.
    cases = []
    for subset, values in zip(m.SUBSETS, (lexical, semantic, crosslingual), strict=False):
        recall, mrr, ndcg = values
        metrics = m.RankingMetrics(recall, recall, recall, mrr, ndcg)
        cases.append(m.CaseResult(subset, subset, metrics, 2, 10, False))
    cases.append(m.evaluate_case("negative", "ambiguous_negative", [], []))
    return tuple(cases)


def measurement(cases=None, p95=1, rss=100, size=100):
    return m.ModelMeasurement(
        gate_cases(semantic=(0.6, 0.5, 0.5), crosslingual=(0.6, 0.5, 0.5))
        if cases is None else cases, p95, rss, size,
    )


def test_frozen_policy_config():
    config = json.loads((Path(__file__).resolve().parents[1]
                         / "configs/p4-benchmark-v1.json").read_text())
    assert config["selection"] == {
        "min_semantic_recall10_gain": 0.10,
        "min_crosslingual_recall10_gain": 0.10,
        "min_semantic_crosslingual_mrr10_gain": 0.0,
        "min_semantic_crosslingual_ndcg10_gain": 0.0,
        "max_lexical_macro_recall10_loss": {"numerator": 1, "denominator": 30},
        "max_lexical_mrr10_loss": 0.03,
        "max_lexical_ndcg10_loss": 0.03,
        "max_comparable_subset_recall10_gap": 0.025,
        "max_comparable_overall_ndcg10_gap": 0.03,
        "quality_leader_order": ["mean_semantic_crosslingual_recall10_desc",
                                 "mean_semantic_crosslingual_ndcg10_desc",
                                 "overall_ndcg10_desc", "model_identifier_asc"],
        "tie_break_order": ["cpu_total_retrieve_p95", "peak_rss",
                            "model_plus_index_bytes", "model_identifier_asc"],
    }


def test_gate_inclusive_boundaries_and_stop():
    boundary = gate_cases(lexical=(0.8 - 1 / 30, 0.8 - 0.03, 0.8 - 0.03),
                          semantic=(0.6, 0.5, 0.5), crosslingual=(0.6, 0.5, 0.5))
    result = m.choose_model(gate_cases(), {"A": measurement(boundary)})
    assert (result.selected, result.quality_leader, result.qualifying) == ("A", "A", ("A",))
    assert result.failures == {"A": ()}
    result = m.choose_model(gate_cases(), {"A": measurement(gate_cases())})
    assert result.selected is result.quality_leader is None
    assert result.failures["A"] == ("semantic.recall_at_10", "crosslingual.recall_at_10")
    assert m.choose_model(gate_cases(), {}).selected is None


@pytest.mark.parametrize("subset", ["lexical", "semantic", "crosslingual"])
@pytest.mark.parametrize("metric", ["recall_at_10", "mrr_at_10", "ndcg_at_10"])
def test_each_gate_threshold_just_outside_fails(subset, metric):
    boundary = gate_cases(lexical=(0.8 - 1 / 30, 0.77, 0.77),
                          semantic=(0.6, 0.5, 0.5), crosslingual=(0.6, 0.5, 0.5))
    cases = tuple(replace(c, metrics=replace(c.metrics, **{
        metric: getattr(c.metrics, metric) - 1e-8
    })) if c.subset == subset else c for c in boundary)
    result = m.choose_model(gate_cases(), {"A": measurement(cases)})
    assert result.selected is None
    assert result.failures["A"] == (f"{subset}.{metric}",)


@pytest.mark.parametrize("subset", m.SUBSETS)
def test_any_subset_identity_promotion_disqualifies(subset):
    cases = tuple(replace(c, identity_promotion_error=True) if c.subset == subset else c
                  for c in measurement().cases)
    result = m.choose_model(gate_cases(), {"A": measurement(cases)})
    assert result.selected is None
    assert result.failures["A"] == (f"{subset}.identity_promotion_error",)


def test_all_gate_failures_reported_not_short_circuited():
    cases = tuple(replace(c, identity_promotion_error=True) for c in gate_cases())
    result = m.choose_model(gate_cases(), {"A": measurement(cases)})
    assert len(result.failures["A"]) == 6


def test_quality_leader_tradeoff_uses_mean_not_subset_dominance():
    models = {
        "A": measurement(gate_cases(semantic=(0.8, 0.5, 0.5), crosslingual=(0.6, 0.5, 0.5))),
        "B": measurement(gate_cases(semantic=(0.7, 0.5, 0.5), crosslingual=(0.8, 0.5, 0.5)),
                         p95=10),
    }
    result = m.choose_model(gate_cases(), models)
    assert result.quality_leader == result.selected == "B"
    assert result.qualifying == ("B", "A")


@pytest.mark.parametrize("metric", ["subset_ndcg", "overall_ndcg", "identifier"])
def test_quality_leader_tie_breakers(metric):
    a = measurement()
    if metric == "subset_ndcg":
        b = measurement(gate_cases(semantic=(0.6, 0.5, 0.6), crosslingual=(0.6, 0.5, 0.6)))
    elif metric == "overall_ndcg":
        b = measurement(gate_cases(lexical=(0.8, 0.8, 0.9), semantic=(0.6, 0.5, 0.5),
                                   crosslingual=(0.6, 0.5, 0.5)))
    else:
        b = a
    result = m.choose_model(gate_cases(), {"B": b, "A": a})
    assert result.quality_leader == ("A" if metric == "identifier" else "B")


@pytest.mark.parametrize("outside", [False, True])
@pytest.mark.parametrize("subset", ["semantic", "crosslingual"])
def test_comparable_recall_must_pass_each_subset(subset, outside):
    leader = measurement(gate_cases(semantic=(0.8, 0.5, 0.6), crosslingual=(0.8, 0.5, 0.6)),
                         p95=10)
    cases = tuple(replace(c, metrics=replace(c.metrics, recall_at_10=0.8 - 0.025
                                            - (1e-8 if outside else 0)))
                  if c.subset == subset else c for c in leader.cases)
    result = m.choose_model(gate_cases(), {"leader": leader, "small": measurement(cases)})
    assert result.quality_leader == "leader"
    assert result.selected == ("leader" if outside else "small")


@pytest.mark.parametrize("outside", [False, True])
def test_comparable_overall_ndcg_boundary(outside):
    leader_cases = gate_cases(lexical=(0.8, 0.8, 0.8), semantic=(0.8, 0.8, 0.8),
                              crosslingual=(0.8, 0.8, 0.8))
    cases = tuple(replace(c, metrics=replace(c.metrics, ndcg_at_10=0.8 - 0.03
                                            - (1e-8 if outside else 0)))
                  if c.subset != "ambiguous_negative" else c for c in leader_cases)
    # Lower lexical baseline keeps comparability distinct from qualification.
    baseline = gate_cases(lexical=(0.8, 0.8, 0.7))
    result = m.choose_model(baseline, {
        "leader": measurement(leader_cases, p95=10), "small": measurement(cases),
    })
    assert result.selected == ("leader" if outside else "small")
    assert len(result.qualifying) == 2


@pytest.mark.parametrize("costs", [(0.5, 999, 999), (1, 50, 999), (1, 100, 50)])
def test_comparable_cost_tie_break_order(costs):
    result = m.choose_model(gate_cases(), {"A": measurement(), "B": measurement(None, *costs)})
    assert result.quality_leader == "A"
    assert result.selected == "B"
    tied = m.choose_model(gate_cases(), {"B": measurement(), "A": measurement()})
    assert tied.selected == "A"


def test_gate_rejects_missing_mismatched_or_invalid_inputs():
    with pytest.raises(ValueError, match="Missing"):
        m.choose_model([], {})
    with pytest.raises(ValueError, match="Mismatched"):
        m.choose_model(gate_cases(), {"A": measurement(measurement().cases[:-1])})
    with pytest.raises(ValueError, match="Duplicate"):
        m.choose_model(gate_cases(), {"A": measurement(measurement().cases * 2)})
    with pytest.raises(ValueError, match="invalid"):
        m.choose_model(gate_cases(semantic=(float("nan"), 0.5, 0.5)), {})
    for p95 in (-1, float("inf"), float("nan"), True, "1"):
        with pytest.raises(ValueError, match="p95"):
            measurement(p95=p95)
    for rss in (-1, True, 1.5):
        with pytest.raises(ValueError, match="bytes"):
            measurement(rss=rss)
