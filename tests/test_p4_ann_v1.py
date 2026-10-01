"""Synthetic ANN policy and execution tests; no USearch import required."""
from types import SimpleNamespace

import pytest

from tools import p4_ann_v1 as ann


def mapping_rows(count=512):
    return [{'entry_key': {'kind': 'term', 'namespace': 'test', 'value': str(i)},
             'chunk_id': f'chunk-{i}', 'document_id': str(i),
             'source_id': 'source', 'evidence_id': 'evidence'} for i in range(count)]


def hits():
    return ann.entry_hits(list(range(512)), [i / 1024 for i in range(512)], mapping_rows())


def test_grid_is_four_builds_sixteen_candidates():
    rows = ann.grid()
    assert len(rows) == len(set(rows)) == 16
    assert len({(m, add) for m, add, _ in rows}) == 4
    assert rows[0] == (16, 128, 32)
    assert rows[-1] == (32, 256, 256)
    assert ann.POLICY['threads'] == 8


def test_first_chunk_wins_and_typed_namespaces_remain_distinct():
    mapping = mapping_rows()
    mapping[1]['entry_key'] = mapping[0]['entry_key'].copy()
    mapping[2]['entry_key'] = {**mapping[0]['entry_key'], 'namespace': 'other'}
    result = ann.entry_hits(range(512), [i / 1024 for i in range(512)], mapping)
    assert len(result) == 100
    assert result[0]['chunk_id'] == 'chunk-0'
    assert result[1]['chunk_id'] == 'chunk-2'
    assert result[1]['score'] == 1 - 2 / 1024
    assert [row['rank'] for row in result] == list(range(1, 101))


@pytest.mark.parametrize('problem', ['short', 'duplicate', 'range', 'nan', 'unordered', 'few_entries'])
def test_bad_matches_fail_without_backfill(problem):
    mapping = mapping_rows()
    keys, distances = list(range(512)), [i / 1024 for i in range(512)]
    if problem == 'short':
        keys.pop()
    elif problem == 'duplicate':
        keys[-1] = keys[0]
    elif problem == 'range':
        keys[-1] = 512
    elif problem == 'nan':
        distances[-1] = float('nan')
    elif problem == 'unordered':
        distances[-1] = -1
    else:
        for row in mapping:
            row['entry_key'] = mapping[0]['entry_key']
    with pytest.raises(ValueError):
        ann.entry_hits(keys, distances, mapping)


def test_recall_uses_typed_sets_not_order():
    reference = hits()
    actual = [dict(row) for row in reference]
    actual[0], actual[1] = actual[1], actual[0]
    for i, row in enumerate(actual, 1):
        row['rank'] = i
    assert ann.recall_rows(actual, reference) == {'10': 1, '20': 1, '100': 1}
    actual[0]['entry'] = {**actual[0]['entry'], 'namespace': 'different'}
    assert ann.recall_rows(actual, reference) == {'10': .9, '20': .95, '100': .99}


def test_approximation_macro_and_minimum_are_independent():
    rows = [{'10': .98, '20': .98, '100': .95} for _ in range(120)]
    assert all(row['pass'] for row in ann.approximation(rows).values())
    rows = [{'10': 1, '20': 1, '100': 1} for _ in range(120)]
    rows[0] = {'10': .7, '20': .75, '100': .89}
    gates = ann.approximation(rows)
    assert all(not row['pass'] for row in gates.values())
    assert gates['10']['macro'] > .98
    with pytest.raises(ValueError):
        ann.approximation(rows[:-1])


def candidate(name, latency, size, m=16, add=128, ef=32, status='PASS'):
    return {'id': name, 'p95_ms': latency, 'index_bytes': size,
            'M': m, 'Eadd': add, 'ef': ef, 'status': status}


def test_selection_uses_global_fastest_window_not_chained_ties():
    rows = [candidate('fastest', 1, 300), candidate('near', 1.04, 200),
            candidate('outside', 1.08, 100), candidate('failed', .1, 1, status='FAIL')]
    assert ann.choose(rows) == 'near'
    assert ann.choose(list(reversed(rows))) == 'near'
    assert ann.choose([rows[-1]]) is None


def test_selection_inclusive_window_and_parameter_ties():
    rows = [candidate('fastest', 1, 500), candidate('edge', 1.05, 100),
            candidate('m', 1.02, 100, m=32), candidate('add', 1.02, 100, add=256),
            candidate('ef', 1.02, 100, ef=64)]
    assert ann.choose(rows) == 'edge'


def test_measure_122_single_searches_and_search_only_clock():
    calls, clock_calls = [], []
    matches = SimpleNamespace(keys=list(range(512)), distances=[i / 1024 for i in range(512)])
    class FakeIndex:
        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return matches
    def clock():
        clock_calls.append(len(calls))
        return len(clock_calls) / 1000
    cases = [{'case_id': str(i), 'hits': hits()} for i in range(120)]
    warmups, rows = ann.measure(FakeIndex(), list(range(120)), cases, mapping_rows(), clock)
    assert [query for query, _ in calls] == [0, 1, *range(120)]
    assert all(kwargs == {'count': 512, 'threads': 8, 'exact': False} for _, kwargs in calls)
    assert clock_calls == [value for i in range(2, 122) for value in (i, i + 1)]
    assert len(warmups) == 2 and len(rows) == 120
    assert all(row['status'] == 'PASS' and row['search_ms'] == pytest.approx(1) for row in rows)


def test_formal_search_failure_is_retained_without_retry():
    calls = []
    matches = SimpleNamespace(keys=list(range(512)), distances=[i / 1024 for i in range(512)])
    class FakeIndex:
        def search(self, query, **kwargs):
            calls.append(query)
            if len(calls) == 10:
                raise RuntimeError('synthetic failure')
            return matches
    cases = [{'case_id': str(i), 'hits': hits()} for i in range(120)]
    _, rows = ann.measure(FakeIndex(), list(range(120)), cases, mapping_rows())
    assert len(calls) == 122 and len(rows) == 120
    assert rows[7]['status'] == 'FAIL' and 'synthetic failure' in rows[7]['error']
    assert sum(row['status'] == 'FAIL' for row in rows) == 1


def metric_fixture():
    result = {}
    for mode in ann.selection.MODES:
        result[mode] = {}
        for subset, (count, positives, negatives) in ann.selection.COUNTS.items():
            result[mode][subset] = {
                'case_count': count, 'positive_count': positives, 'negative_count': negatives,
                'metrics': {name: {'value': 1.0, 'denominator': positives}
                            for name in ann.selection.METRICS},
                'identity_promotion_error_rate': {'value': 0, 'denominator': count},
                'negative_identity_promotion_error_rate': {
                    'value': 0 if negatives else None, 'denominator': negatives},
                'negative_nonempty_rate': {'value': 1 if negatives else None, 'denominator': negatives}}
    return result


def test_quality_reuses_v2_cap_regression_and_dense_identity_checks():
    baseline, actual = metric_fixture(), metric_fixture()
    assert ann.quality_result(actual, baseline)['failures'] == []
    actual['RRF_HYBRID_MODEL_B']['overall']['metrics']['ndcg_at_10']['value'] = .98
    actual['EXACT_DENSE_MODEL_B']['overall']['identity_promotion_error_rate']['value'] = .01
    result = ann.quality_result(actual, baseline)
    assert 'regression.overall.ndcg_at_10' in result['failures']
    assert 'dense.overall.identity_promotion_error_rate' in result['failures']
    assert set(result['metrics']) == {'ANN_DENSE_B', 'ANN_HYBRID_B'}


def test_contract_binds_exactly_six_fixed_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(ann.exact, 'bound', lambda path, digest: calls.append((path, digest)))
    config = {'schema': 'p4-ann-contract-v1', 'output': ann.OUTPUT, 'raw_directory': ann.RAW,
              'inputs': {name: {'path': path, 'sha256': 'a' * 64} for name, path in ann.INPUTS.items()}}
    ann.validate_contract(config)
    assert len(calls) == 6
    config['inputs']['queries']['path'] = 'elsewhere.npy'
    with pytest.raises(ValueError, match='wrong binding'):
        ann.validate_contract(config)


def test_backend_version_rejected_before_import(monkeypatch):
    monkeypatch.setattr(ann.importlib.metadata, 'version', lambda name: '0.0.0')
    with pytest.raises(ValueError, match='2.26.2'):
        ann.load_backend()


@pytest.mark.parametrize('failure', ['telemetry', 'build', 'ef', 'query'])
def test_mocked_execute_counts_and_continues_grid(monkeypatch, tmp_path, failure):
    import numpy as np

    # Shape/provenance setup is mocked: no real vectors, backend, or real grid work.
    class Matrix:
        def __init__(self, count):
            self.shape = (count, 1024)
            self._mmap = SimpleNamespace(close=lambda: None)

        def __getitem__(self, i):
            if i >= self.shape[0]:
                raise IndexError(i)
            return i

    class Mapping:
        def __len__(self):
            return 52664

        def __iter__(self):
            return iter(())

    class Disk(Mapping):
        connection = SimpleNamespace(close=lambda: None, execute=lambda sql:
                                     SimpleNamespace(fetchone=lambda: (0, 52663)))

        def __init__(self, path):
            pass

        def block(self, start, end):
            return Mapping()

    searches, additions, ef_settings = [], [], []

    class Index:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.ef = 32

        def __len__(self):
            return 52664

        def contains(self, keys):
            return np.ones(len(keys), dtype=bool)

        def add(self, keys, vectors, **kwargs):
            additions.append(self.kwargs)
            if failure == 'build':
                raise RuntimeError('add failed')

        def save(self, path):
            from pathlib import Path
            Path(path).write_bytes(b'synthetic')

        @property
        def expansion_search(self):
            return self.ef

        @expansion_search.setter
        def expansion_search(self, value):
            ef_settings.append(value)
            if failure == 'ef':
                raise RuntimeError('ef setter failed')
            self.ef = value

        def search(self, query, **kwargs):
            searches.append((query, kwargs))
            if failure == 'query' and query == 7:
                raise RuntimeError('query failed')
            return SimpleNamespace(keys=range(512), distances=[i / 1024 for i in range(512)])

        @property
        def memory_usage(self):
            raise RuntimeError('optional property')

        @property
        def hardware_acceleration(self):
            raise AttributeError('optional property')

    cases = [{'case_id': str(i), 'hits': hits()} for i in range(120)]
    monkeypatch.setattr(ann, 'prepare', lambda config: ([None, None], cases, {}, {}))
    monkeypatch.setattr(ann, 'load_backend', lambda: Index)
    monkeypatch.setattr(np, 'load', lambda path, **kwargs: Matrix(120 if str(path).endswith('queries.npy') else 52664))
    monkeypatch.setattr(ann.exact, 'validate_vectors', lambda *args: None)
    monkeypatch.setattr(ann.exact, 'DiskMapping', Disk)
    monkeypatch.setattr(ann.score, 'Mapping', lambda value: None)
    monkeypatch.setattr(ann.exact, 'rss', lambda: (_ for _ in ()).throw(ModuleNotFoundError('psutil')))
    # Keep real measure/timing/search calls, with only result mapping/scoring mocked.
    monkeypatch.setattr(ann, 'entry_hits', lambda *args: cases[0]['hits'])
    monkeypatch.setattr(ann, 'score_cases', lambda *args: ({'metrics': {}}, {}))
    monkeypatch.setattr(ann, 'quality_result', lambda *args: {'failures': []})
    monkeypatch.setattr(ann, 'relevance_changes', lambda *args: [])
    receipt = {'builds': [], 'candidates': []}
    ann.execute({}, receipt, tmp_path)
    assert len(additions) == len(receipt['builds']) == 4
    assert len(receipt['candidates']) == 16
    assert len(list(tmp_path.glob('*.json'))) == 16
    if failure in ('build', 'ef'):
        assert not searches and receipt['status'] == 'FAIL'
        assert receipt['formal_query_attempts'] == receipt['formal_query_failures'] == 0
        assert receipt['formal_query_not_run'] == 1920
        assert receipt['warmup_query_attempts'] == receipt['warmup_query_failures'] == 0
        assert receipt['warmup_query_not_run'] == 32
        assert all(c['formal_samples'] == c['formal_failures'] == 0 and c['formal_not_run'] == 120
                   for c in receipt['candidates'])
    else:
        assert len(searches) == 1952 and ef_settings == [32, 64, 128, 256] * 4
        assert receipt['formal_query_attempts'] == 1920 and receipt['formal_query_not_run'] == 0
        assert receipt['warmup_query_attempts'] == 32 and receipt['warmup_query_not_run'] == 0
        assert receipt['formal_query_failures'] == (16 if failure == 'query' else 0)
        assert receipt['warmup_query_failures'] == 0
        assert receipt['status'] == ('FAIL' if failure == 'query' else 'PASS')
        assert all(b['status'] == 'PASS' and b['memory']['status'] == 'NOT_AVAILABLE'
                   for b in receipt['builds'])
