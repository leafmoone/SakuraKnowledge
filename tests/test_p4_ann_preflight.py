"""Synthetic retry/preflight regression tests; never import the real ANN backend."""
import copy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import numpy as np
import pytest

from tools import p4_ann_preflight as preflight
from tools import p4_ann_v1 as ann


class FakeIndex:
    instances: ClassVar[list] = []
    size = 8
    fail = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.instances.append(self)

    def __len__(self):
        return self.size

    def contains(self, keys):
        self.calls.append(('contains', len(keys)))
        return np.ones(len(keys), dtype=bool)

    def add(self, keys, vectors, **kwargs):
        self.calls.append(('add', len(keys), kwargs))
        if self.fail == 'add':
            raise RuntimeError('add failed')

    def search(self, query, **kwargs):
        self.calls.append(('search', kwargs))
        if self.fail == 'search':
            raise RuntimeError('search failed')
        return SimpleNamespace(keys=np.array([0, 1, 2, 3, 5, 6, 7, 4]),
                               distances=np.array([0, 1, 1, 1, 1, 1, 1, 2]))

    def save(self, path):
        self.calls.append(('save', path))
        if self.fail == 'save':
            raise RuntimeError('save failed')
        Path(path).write_bytes(b'synthetic-index')

    def load(self, path):
        self.calls.append(('load', path))
        if self.fail == 'load':
            raise RuntimeError('load failed')

    @property
    def memory_usage(self):
        raise RuntimeError('memory property unsupported')

    @property
    def hardware_acceleration(self):
        raise AttributeError('hardware property unsupported')


@pytest.fixture(autouse=True)
def isolated_fake():
    FakeIndex.instances = []
    FakeIndex.size = 8
    FakeIndex.fail = None


def missing_psutil():
    raise ModuleNotFoundError("No module named 'psutil'")


def test_optional_telemetry_independent_and_serializable(monkeypatch):
    monkeypatch.setattr(ann.exact, 'rss', missing_psutil)
    result = ann.diagnostics(FakeIndex())
    assert set(result) == {'memory', 'index_memory_bytes', 'hardware_acceleration'}
    assert all(v['status'] == 'NOT_AVAILABLE' and v['reason'] and v['error'] for v in result.values())
    assert 'psutil' in result['memory']['error']
    assert 'RuntimeError' in result['index_memory_bytes']['error']
    assert 'AttributeError' in result['hardware_acceleration']['error']
    assert ann.optional_telemetry(lambda: 12) == {'status': 'AVAILABLE', 'value': 12}
    assert ann.optional_telemetry(lambda: float('nan'))['status'] == 'NOT_AVAILABLE'


def test_build_is_pass_before_optional_diagnostics(monkeypatch, tmp_path):
    FakeIndex.size = 52664
    monkeypatch.setattr(ann.exact, 'rss', missing_psutil)
    index, build = ann.build_index(FakeIndex, np.arange(52664), None,
                                   tmp_path / 'index.usearch', 16, 128)
    assert build['status'] == 'PASS' and 'error' not in build
    assert build['index_bytes'] > 0 and len(build['index_sha256']) == 64
    assert build['memory']['status'] == build['index_memory_bytes']['status'] == 'NOT_AVAILABLE'
    assert index.kwargs == {'ndim': 1024, 'metric': 'cos', 'dtype': 'f32', 'connectivity': 16,
                            'expansion_add': 128, 'expansion_search': 32, 'multi': False}
    assert index.calls[0] == ('add', 52664, {'threads': 8, 'copy': True})


@pytest.mark.parametrize('failure', ['add', 'keys', 'save', 'hash'])
def test_required_build_operations_still_fail(monkeypatch, tmp_path, failure):
    FakeIndex.size = 8 if failure == 'keys' else 52664
    FakeIndex.fail = failure
    if failure == 'hash':
        monkeypatch.setattr(ann.exact, 'sha', lambda path: (_ for _ in ()).throw(OSError('hash failed')))
    _, build = ann.build_index(FakeIndex, np.arange(52664), None, tmp_path / 'index', 16, 128)
    assert build['status'] == 'FAIL' and 'error' in build
    assert 'memory' not in build


def test_build_existing_file_is_preserved(tmp_path):
    FakeIndex.size = 52664
    path = tmp_path / 'index'
    path.write_bytes(b'old')
    _, result = ann.build_index(FakeIndex, np.arange(52664), None, path, 16, 128)
    assert result['status'] == 'FAIL'
    assert path.read_bytes() == b'old'


def test_counts_distinguish_failures_from_not_run():
    candidate = {}
    ann.counts(candidate)
    assert candidate == {'formal_samples': 0, 'formal_failures': 0, 'formal_not_run': 120,
                         'warmup_samples': 0, 'warmup_failures': 0, 'warmup_not_run': 2}
    ann.counts(candidate, [{'status': 'FAIL'}, {'status': 'PASS'}],
               [{'status': 'PASS'}, {'status': 'FAIL'}, {'status': 'PASS'}])
    receipt = {'candidates': [candidate]}
    ann.aggregate(receipt)
    assert receipt['formal_query_attempts'] == 3
    assert receipt['formal_query_failures'] == 1
    assert receipt['formal_query_not_run'] == 1917
    assert receipt['warmup_query_attempts'] == 2
    assert receipt['warmup_query_failures'] == 1
    assert receipt['warmup_query_not_run'] == 30
    empty = {'candidates': []}
    ann.aggregate(empty)
    assert empty['formal_query_attempts'] == empty['formal_query_failures'] == 0
    assert empty['formal_query_not_run'] == 1920 and empty['warmup_query_not_run'] == 32


def test_all_search_errors_are_actual_attempts_without_retry():
    class Broken:
        calls = 0

        def search(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError('search failed')

    index = Broken()
    warmups, rows = ann.measure(index, range(120), [{'case_id': str(i)} for i in range(120)], [])
    candidate = {}
    ann.counts(candidate, warmups, rows)
    assert index.calls == 122
    assert candidate == {'formal_samples': 120, 'formal_failures': 120, 'formal_not_run': 0,
                         'warmup_samples': 2, 'warmup_failures': 2, 'warmup_not_run': 0}


def test_preflight_exercises_real_api_shape_without_real_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(ann.exact, 'rss', missing_psutil)
    result = preflight.exercise(FakeIndex, tmp_path)
    assert all(v == 'PASS' for v in result['checks'].values())
    index, loaded = FakeIndex.instances
    assert index.kwargs['ndim'] == 4 and index.kwargs['metric'] == 'cos' and index.kwargs['dtype'] == 'f32'
    assert sum(c[0] == 'search' for obj in FakeIndex.instances for c in obj.calls) == 1
    assert ('search', {'count': 8, 'threads': 8, 'exact': False}) in index.calls
    assert loaded.calls[0][0] == 'load'
    assert result['diagnostics']['memory']['status'] == 'NOT_AVAILABLE'


@pytest.mark.parametrize('failure', ['add', 'search', 'save', 'load'])
def test_preflight_core_failure_is_blocking(tmp_path, failure):
    FakeIndex.fail = failure
    with pytest.raises(RuntimeError, match=failure):
        preflight.exercise(FakeIndex, tmp_path)


def test_backend_real_import_api_is_mocked(monkeypatch):
    package, module = ModuleType('usearch'), ModuleType('usearch.index')
    module.Index = FakeIndex
    monkeypatch.setitem(sys.modules, 'usearch', package)
    monkeypatch.setitem(sys.modules, 'usearch.index', module)
    monkeypatch.setattr(ann.importlib.metadata, 'version', lambda name: '2.26.2')
    assert ann.load_backend() is FakeIndex


def test_preflight_create_new_and_source_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(ann.exact, 'local', lambda path: tmp_path / path)
    monkeypatch.setattr(ann, 'snapshot', lambda paths: {'harness': 'digest'})
    monkeypatch.setattr(ann, 'load_backend', lambda: FakeIndex)
    monkeypatch.setattr(ann.exact, 'rss', missing_psutil)
    receipt = preflight.run()
    assert receipt['status'] == 'PASS' and receipt['source_sha256_before'] == receipt['source_sha256_after']
    output = tmp_path / ann.PREFLIGHT
    before = output.read_bytes()
    with pytest.raises(ValueError, match='overwrite'):
        preflight.run()
    assert output.read_bytes() == before


def retry_fixture(monkeypatch):
    inputs = {name: {'path': path, 'sha256': 'a' * 64} for name, path in ann.INPUTS.items()}
    config = {'schema': 'p4-ann-contract-v1-retry1', 'output': ann.RETRY_OUTPUT,
              'raw_directory': ann.RETRY_RAW, 'inputs': inputs,
              'retry_of': {'path': ann.OUTPUT, 'sha256': 'b' * 64},
              'retry_command': {'path': 'reports/P4/ann-v1-command.json', 'sha256': 'c' * 64},
              'retry_reason': ann.RETRY_REASON, 'previous_formal_query_attempts': 0,
              'preflight': {'path': ann.PREFLIGHT, 'sha256': 'd' * 64}}
    old = {'schema': 'p4-ann-v1', 'status': 'FAIL', 'selected': None, 'config_sha256': 'e' * 64,
           'builds': [{'status': 'FAIL', 'error': "ModuleNotFoundError: No module named 'psutil'"}
                      for _ in range(4)],
           'candidates': [{'id': f'M{m}-Eadd{add}-ef{ef}', 'formal_samples': 0, 'formal_failures': 120}
                          for m, add, ef in ann.grid()]}
    previous = {'schema': 'p4-ann-contract-v1', 'inputs': copy.deepcopy(inputs)}
    raw = {}
    monkeypatch.setattr(ann.exact, 'local', Path)
    monkeypatch.setattr(ann.exact, 'bound', lambda *args: None)
    monkeypatch.setattr(ann.exact, 'load', lambda path: old if path == Path(ann.OUTPUT) else
                        previous if path == Path(ann.CONFIG) else raw)
    monkeypatch.setattr(ann, 'validate_preflight', lambda binding: None)
    return config, old, previous, raw


def test_retry_accepts_old_inflated_failure_count_but_no_actual_samples(monkeypatch):
    config, _, _, _ = retry_fixture(monkeypatch)
    ann.validate_contract(config)


@pytest.mark.parametrize('mutation', ['sample', 'raw', 'warmup', 'old_pass', 'build', 'input', 'reason',
                                      'count', 'output', 'raw_directory', 'command', 'missing_preflight'])
def test_retry_validation_fails_closed(monkeypatch, mutation):
    config, old, previous, raw = retry_fixture(monkeypatch)
    if mutation == 'sample':
        old['candidates'][0]['formal_samples'] = 1
    elif mutation in ('raw', 'warmup'):
        raw['queries' if mutation == 'raw' else 'warmups'] = [{'status': 'FAIL'}]
    elif mutation == 'old_pass':
        old['status'] = 'PASS'
    elif mutation == 'build':
        old['builds'][0]['error'] = 'disk full'
    elif mutation == 'input':
        previous['inputs']['vectors']['sha256'] = 'changed'
    elif mutation == 'reason':
        config['retry_reason'] = 'retry a query'
    elif mutation == 'count':
        config['previous_formal_query_attempts'] = 1
    elif mutation in ('output', 'raw_directory'):
        config[mutation] = ann.OUTPUT if mutation == 'output' else ann.RAW
    elif mutation == 'command':
        config['retry_command']['path'] = 'elsewhere'
    else:
        del config['preflight']
    with pytest.raises((ValueError, KeyError)):
        ann.validate_contract(config)


def test_run_setup_failure_reports_zero_attempts_and_preserves_old(monkeypatch, tmp_path):
    monkeypatch.setattr(ann.exact, 'local', lambda path: tmp_path / path)
    monkeypatch.setattr(ann.exact, 'bound', lambda *args: None)
    monkeypatch.setattr(ann.exact, 'load', lambda path: {'schema': 'p4-ann-contract-v1-retry1'})
    monkeypatch.setattr(ann, 'validate_contract', lambda config: (_ for _ in ()).throw(ValueError('setup')))
    old = tmp_path / ann.OUTPUT
    old.parent.mkdir(parents=True)
    old.write_bytes(b'old-receipt')
    result = ann.run(ann.RETRY_CONFIG, 'digest')
    assert result['status'] == 'FAIL' and 'setup' in result['error']
    assert result['formal_query_attempts'] == result['formal_query_failures'] == 0
    assert result['formal_query_not_run'] == 1920
    assert result['warmup_query_attempts'] == result['warmup_query_failures'] == 0
    assert result['warmup_query_not_run'] == 32
    assert old.read_bytes() == b'old-receipt'
    with pytest.raises(ValueError, match='overwrite'):
        ann.run(ann.RETRY_CONFIG, 'digest')


def test_preflight_hash_and_pass_are_required(monkeypatch):
    monkeypatch.setattr(ann.exact, 'bound', lambda *args: None)
    monkeypatch.setattr(ann.exact, 'load', lambda path: {'schema': 'p4-ann-preflight-v1', 'status': 'FAIL'})
    with pytest.raises(ValueError, match='PASS preflight'):
        ann.validate_preflight({'path': ann.PREFLIGHT, 'sha256': 'a' * 64})
    with pytest.raises(ValueError, match='wrong binding'):
        ann.validate_preflight({'path': ann.PREFLIGHT})


def test_post_run_binding_change_invalidates_selection(monkeypatch, tmp_path):
    config = {'schema': 'p4-ann-contract-v1-retry1', 'preflight': {'path': ann.PREFLIGHT, 'sha256': 'p'},
              'retry_of': {}, 'retry_command': {}, 'retry_reason': ann.RETRY_REASON,
              'previous_formal_query_attempts': 0}
    monkeypatch.setattr(ann.exact, 'local', lambda path: tmp_path / path)
    monkeypatch.setattr(ann.exact, 'bound', lambda *args: None)
    monkeypatch.setattr(ann.exact, 'load', lambda path: config if path == tmp_path / ann.RETRY_CONFIG else
                        {key: 'input' for key in ann.selection.BINDINGS.values()})
    monkeypatch.setattr(ann, 'validate_contract', lambda config: None)
    monkeypatch.setattr(ann, 'validate_preflight', lambda binding: None)
    snapshots = iter([{'preflight': 'before'}, {'preflight': 'after'}])
    monkeypatch.setattr(ann, 'snapshot', lambda paths: next(snapshots))
    monkeypatch.setattr(ann, 'execute', lambda config, receipt, raw: receipt.update(status='PASS', selected='x'))
    result = ann.run(ann.RETRY_CONFIG, 'digest')
    assert result['status'] == 'FAIL' and result['selected'] is None
    assert result['input_validations'] == {'before': 'PASS', 'after': 'FAIL'}
