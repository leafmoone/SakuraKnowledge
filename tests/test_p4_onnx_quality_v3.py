"""Pure v3 arithmetic/security checks: no model loads or inference."""
import copy
import math

import numpy as np
import pytest

from tools import p4_onnx_quality_v3 as v3


def metrics():
    result = {}
    for mode in v3.selection.MODES:
        result[mode] = {}
        for subset, (cases, positives, negatives) in v3.selection.COUNTS.items():
            result[mode][subset] = {
                'case_count': cases, 'positive_count': positives, 'negative_count': negatives,
                'metrics': {name: {'value': 1.0, 'denominator': positives}
                            for name in v3.selection.METRICS},
                'identity_promotion_error_rate': {'value': 0.0, 'denominator': cases},
                'negative_identity_promotion_error_rate': {
                    'value': 0.0 if negatives else None, 'denominator': negatives},
                'negative_nonempty_rate': {'value': 1.0 if negatives else None,
                                          'denominator': negatives}}
    return result


def hits():
    return [{'entry': {'kind': 'tag', 'namespace': 'source', 'value': str(i)},
             'rank': i + 1, 'score': 1 - i * 1e-7} for i in range(100)]


def test_near_order_change_is_diagnostic_not_quality_gate():
    native = hits()
    actual = copy.deepcopy(native)
    actual[0], actual[1] = actual[1], actual[0]
    for rank, hit in enumerate(actual, 1):
        hit['rank'] = rank
    diagnostic = v3.rank_diagnostics(actual, native)
    assert not diagnostic['ordered']['10']
    assert diagnostic['overlaps']['10']['fraction'] == 1
    assert diagnostic['common_id_score_errors']['10']['maximum'] == 0
    assert diagnostic['first_mismatch']['entries'][0]['onnx_rank'] == 2
    assert v3.quality(metrics(), metrics())['failures'] == []


def test_typed_overlap_not_value_only():
    native = hits()
    actual = copy.deepcopy(native)
    actual[0]['entry']['namespace'] = 'different'
    result = v3.rank_diagnostics(actual, native)
    assert result['overlaps']['10']['count'] == 9
    assert result['first_mismatch']['entries'][0]['onnx_score'] is None


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_nonfinite(bad):
    actual = hits()
    actual[0]['score'] = bad
    with pytest.raises(ValueError, match='nonfinite'):
        v3.rank_diagnostics(actual, hits())
    candidate = metrics()
    candidate['RRF_HYBRID_MODEL_B']['overall']['metrics']['mrr_at_10']['value'] = bad
    with pytest.raises(ValueError, match='finite'):
        v3.quality(candidate, metrics())
    vector = np.zeros((1, 1024), dtype=np.float32)
    vector[0, 0] = bad
    assert v3.agreement.numerical(vector, vector)['status'] == 'FAIL'


def test_regression_rejects_without_rounding_in_every_subset():
    for subset in v3.selection.COUNTS:
        candidate, frozen = metrics(), metrics()
        # Avoid the stricter BM25 gates masking the regression decision.
        for row in frozen['BM25_ONLY'].values():
            for metric in row['metrics'].values():
                metric['value'] = .5
        candidate['RRF_HYBRID_MODEL_B'][subset]['metrics']['mrr_at_10']['value'] = .989999999999
        result = v3.quality(candidate, frozen)
        assert f'regression.{subset}.mrr_at_10' in result['failures']
        candidate['RRF_HYBRID_MODEL_B'][subset]['metrics']['mrr_at_10']['value'] = .990000000001
        assert f'regression.{subset}.mrr_at_10' not in v3.quality(candidate, frozen)['failures']


def test_denominator_and_identity_errors():
    candidate = metrics()
    candidate['RRF_HYBRID_MODEL_B']['overall']['metrics']['recall_at_10']['denominator'] = 120
    with pytest.raises(ValueError, match='denominator'):
        v3.quality(candidate, metrics())
    candidate = metrics()
    candidate['RRF_HYBRID_MODEL_B']['overall']['identity_promotion_error_rate']['value'] = 1 / 120
    assert 'overall.identity_promotion_error_rate' in v3.quality(candidate, metrics())['failures']


def test_capped_gates_still_reject_semantic_loss():
    candidate = metrics()
    candidate['RRF_HYBRID_MODEL_B']['semantic']['metrics']['recall_at_10']['value'] = .999
    assert 'semantic.recall_at_10' in v3.quality(candidate, metrics())['failures']


def test_frozen_contract_source_tamper(tmp_path, monkeypatch):
    path = tmp_path / 'source'
    path.write_text('original', encoding='utf-8')
    digest = v3.exact.sha(path)
    contract = {'schema': 'p4-onnx-representation-contract-v3', 'output': v3.OUTPUT,
                'raw_directory': v3.RAW, 'reexport': False,
                'native_reference_regeneration': False, 'frozen_sha256': {'source': digest}}
    monkeypatch.setattr(v3.exact, 'local', lambda name: tmp_path / name)
    path.write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError):
        v3.verify_frozen(contract)


def test_numeric_tolerances_not_relaxed():
    vector = np.zeros((1, 1024), dtype=np.float32)
    vector[0, 0] = 1
    assert v3.agreement.numerical(vector, vector)['status'] == 'PASS'
    assert v3.agreement.numerical(vector * 1.001, vector)['status'] == 'FAIL'


def test_exclusive_json_keeps_old_receipt(tmp_path):
    path = tmp_path / 'receipt.json'
    v3.save_json(path, {'old': True})
    with pytest.raises(FileExistsError):
        v3.save_json(path, {'old': False})
    assert v3.exact.load(path) == {'old': True}
