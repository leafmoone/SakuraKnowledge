from types import SimpleNamespace

import numpy as np
import pytest

from tools import p4_onnx_agreement as agreement


def unit():
    result = np.zeros((1, 1024), dtype=np.float32)
    result[0, 0] = 1
    return result


def test_numerical_pass_and_failures():
    reference = unit()
    assert agreement.numerical(reference, reference)['status'] == 'PASS'
    scaled = reference * 1.00002
    assert 'max_norm_error' in agreement.numerical(scaled, reference)['failures']
    changed = reference.copy()
    changed[0, 1] = .0002
    assert 'max_component_error' in agreement.numerical(changed, reference)['failures']
    assert 'min_cosine' in agreement.numerical(-reference, reference)['failures']
    changed[0, 0] = np.nan
    record = agreement.numerical(changed, reference)
    assert 'finite' in record['failures']
    assert record['max_component_error'] is None
    assert 'shape' in agreement.numerical(reference[:, :3], reference)['failures']
    assert 'dtype' in agreement.numerical(reference.astype('float64'), reference)['failures']
    assert 'min_cosine' in agreement.numerical(np.zeros_like(reference), reference)['failures']


def test_numpy_padding():
    tokenizer = SimpleNamespace(padding_side='right', pad_token_id=1)
    batch = agreement.pad_batch({'input_ids': [[0, 9, 2], [0, 2]],
                                 'attention_mask': [[1, 1, 1], [1, 1]]}, tokenizer)
    assert batch['input_ids'].tolist() == [[0, 9, 2], [0, 2, 1]]
    assert batch['attention_mask'].tolist() == [[1, 1, 1], [1, 1, 0]]
    assert all(v.dtype == np.int64 for v in batch.values())
    tokenizer.padding_side = 'left'
    with pytest.raises(ValueError, match='right padding'):
        agreement.pad_batch({'input_ids': [[2]], 'attention_mask': [[1]]}, tokenizer)


def hits():
    return [{'entry': {'kind': 'entry', 'namespace': 'test', 'value': str(i)}, 'score': .5}
            for i in range(100)]


def test_rank_order_ties_typed_ids_and_scores():
    reference = hits()
    assert agreement.rank_agreement(hits(), reference)['status'] == 'PASS'
    actual = hits()
    actual[1], actual[2] = actual[2], actual[1]
    assert agreement.rank_agreement(actual, reference)['status'] == 'FAIL'
    actual = hits()
    actual[99]['entry']['value'] = 99
    record = agreement.rank_agreement(actual, reference)
    assert record['gates']['ordered_typed_ids_at_10']
    assert not record['gates']['ordered_typed_ids_at_100']
    actual = hits()
    actual[0]['score'] += .0002
    assert agreement.rank_agreement(actual, reference)['failures'] == ['matching_score_error']


class FakeORT:
    GraphOptimizationLevel = SimpleNamespace(ORT_ENABLE_ALL=99)
    SessionOptions = SimpleNamespace
    __version__ = 'fake'

    def __init__(self, providers=None):
        self.providers = providers or ['CPUExecutionProvider']
        self.disabled = False

    def InferenceSession(self, path, sess_options, providers):
        assert providers == ['CPUExecutionProvider']
        self.options = sess_options
        return self

    def disable_fallback(self):
        self.disabled = True

    def get_providers(self):
        return self.providers

    def get_session_options(self):
        return self.options

    def get_inputs(self):
        return [SimpleNamespace(name=n, type='tensor(int64)', shape=['batch', 'sequence'])
                for n in ('input_ids', 'attention_mask')]

    def get_outputs(self):
        return [SimpleNamespace(name='embeddings', type='tensor(float)', shape=['batch', 1024])]


def test_cpu_exclusivity_and_options():
    ort = FakeORT()
    assert agreement.session('unused.onnx', ort) is ort
    assert ort.disabled
    assert ort.options.intra_op_num_threads == ort.options.inter_op_num_threads == 8
    assert ort.options.graph_optimization_level == 99
    with pytest.raises(ValueError, match='nonexclusive'):
        agreement.session('unused.onnx', FakeORT(['CUDAExecutionProvider', 'CPUExecutionProvider']))


def test_static_input_rejected():
    ort = FakeORT()
    ort.get_inputs = lambda: [SimpleNamespace(name=n, type='tensor(int64)', shape=[1, 20])
                              for n in ('input_ids', 'attention_mask')]
    with pytest.raises(ValueError, match='dynamic int64'):
        agreement.session('unused.onnx', ort)


def test_exclusive_output_and_fail_receipt(tmp_path, monkeypatch):
    import json

    output = tmp_path / 'receipt.json'
    calls = []

    def fail(job, directory, receipt):
        calls.append(True)
        receipt['queries'].append({'status': 'FAIL', 'failures': ['min_cosine']})
        raise ValueError('numeric failure')

    monkeypatch.setattr(agreement, 'execute', fail)
    assert agreement.run('configs/x', 'build/x', output) == 1
    record = json.loads(output.read_text())
    assert record['status'] == 'FAIL'
    assert record['queries'][0]['failures'] == ['min_cosine']
    original = output.read_bytes()
    assert agreement.run('configs/x', 'build/x', output) == 1
    assert output.read_bytes() == original
    assert calls == [True]
