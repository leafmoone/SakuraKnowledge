"""Tiny arithmetic and mocked resident tests; no real assets/runtime loaded."""
import io
from dataclasses import replace

import pytest

from tools import p4_existing_assets_evaluate as runner
from tools import p4_retrieval_metrics as metrics

KEY = {'kind': 'page', 'namespace': 'test', 'value': 'one'}
CASE = {'case_id': 'P4-001', 'query': 'one', 'subset': 'semantic',
        'accepted_targets': [{'entry_key': KEY}]}
MANIFEST = {'contract': {}, 'pack_version': 'test'}


def response():
    hit = {'entry': KEY, 'rank': 1}
    candidate = {'entry': KEY, 'hybrid_rank': 1}
    return {'status': 'PASS', 'case_id': CASE['case_id'], 'query': CASE['query'],
            **MANIFEST, 'identity_status': 'not_asserted', 'promoted_identities': [],
            'canonical': None, 'entity_tag': None, 'timings_ms': {'total': 1},
            'lexical_hits': [hit], 'dense_hits': [hit], 'trusted_pins': [],
            'hybrid': [candidate], 'candidates': [candidate]}


def test_rust_failure_envelope_preserves_actual_stage():
    response = {'status': 'FAIL', 'error': 'full_lexical: BM25 SQL: interrupted', 'retries': 0}
    with pytest.raises(runner.RustFailure, match='BM25 SQL: interrupted'):
        runner.require_success_response(response)
    with pytest.raises(ValueError, match='invalid Rust failure envelope'):
        runner.require_success_response({'status': 'FAIL', 'retries': 1})
    runner.require_success_response({'status': 'PASS'})


def test_independent_branch_scoring_and_negative_denominators():
    result = runner.score_response(CASE, response(), MANIFEST)
    assert set(result) == {'lexical', 'dense', 'final'}
    assert result['final'].metrics.recall_at_10 == 1
    negative = {**CASE, 'subset': 'ambiguous/negative', 'accepted_targets': []}
    scored = runner.score_response(negative, response(), MANIFEST)['final']
    assert scored.subset == 'ambiguous_negative'
    aggregate = metrics.aggregate_cases([scored])['overall']
    assert aggregate.metrics['recall_at_10'].value is None
    assert aggregate.negative_nonempty_rate.value == 1
    assert aggregate.identity_promotion_error_rate.value == 0


@pytest.mark.parametrize('field,value', [
    ('promoted_identities', [KEY]), ('canonical', 'one'), ('query', 'other'),
    ('candidates', []), ('timings_ms', {'total': float('nan')}),
    ('contract', {'wrong': True}),
])
def test_response_fails_closed(field, value):
    wire = response()
    wire[field] = value
    with pytest.raises(ValueError):
        runner.score_response(CASE, wire, MANIFEST)


def test_same_population_gate_and_exact_boundaries():
    baseline = []
    for group in ('lexical', 'semantic', 'crosslingual'):
        baseline.append(metrics.evaluate_case(group, group, [metrics.EntryKey(**KEY)],
                                              [metrics.EntryKey(**KEY)]))
    aggregates = metrics.aggregate_cases(baseline)
    assert runner.quality_gate(aggregates, aggregates)['status'] == 'PASS'
    changed = dict(aggregates)
    lexical = changed['lexical']
    means = dict(lexical.metrics)
    means['recall_at_10'] = metrics.Mean(1 - 1 / 30, 1)
    changed['lexical'] = replace(lexical, metrics=means)
    assert runner.quality_gate(aggregates, changed)['status'] == 'PASS'
    means['recall_at_10'] = metrics.Mean(1 - 1 / 30 - 1e-9, 1)
    assert runner.quality_gate(aggregates, changed)['status'] == 'FAIL'
    means['recall_at_10'] = metrics.Mean(1, 1)
    changed['semantic'] = replace(changed['semantic'], metrics={
        **changed['semantic'].metrics, 'mrr_at_10': metrics.Mean(.99, 1)})
    assert runner.quality_gate(aggregates, changed)['status'] == 'FAIL'


def test_graceful_eof_does_not_kill():
    class Process:
        stdin = io.BytesIO()
        stdout = io.BytesIO()

        def wait(self, timeout):
            assert self.stdin.closed
            return 0

        def kill(self):
            pytest.fail('successful resident must not be killed')

    driver = type('Driver', (), {'process': Process()})()
    report = {}
    runner.finish_driver(driver, report)
    assert report['exit_code'] == 0
    assert driver.process.stdout.closed


def test_freeze_uses_real_small_bytes_only(monkeypatch, tmp_path):
    import hashlib
    import json

    gold = {'base_snapshot_sha256': 'a' * 64, 'base_snapshot_bytes': 10, 'cases': []}
    for group, count in [('lexical', 30), ('semantic', 40), ('crosslingual', 30),
                         ('ambiguous/negative', 20)]:
        for _ in range(count):
            gold['cases'].append({**CASE, 'case_id': f"P4-{len(gold['cases']) + 1:03}",
                                  'subset': group})
    data = json.dumps(gold).encode()
    digest = hashlib.sha256(data).hexdigest()
    names = ('gold.json', 'query.json', 'configs/p4-full-semantic-v1.json')
    (tmp_path / 'configs').mkdir()
    (tmp_path / names[0]).write_bytes(data)
    (tmp_path / names[1]).write_text(json.dumps({'gold': names[0], 'gold_sha256': digest}))
    (tmp_path / names[2]).write_text(json.dumps({'snapshot': {'sha256': 'a' * 64, 'size': 10}}))
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'INPUTS', names)
    monkeypatch.setattr(runner, 'GOLD', names[0])
    monkeypatch.setattr(runner, 'QUERY_CONFIG', names[1])
    monkeypatch.setattr(runner, 'GOLD_SHA', digest)
    monkeypatch.setattr(runner.build.full, 'contained', lambda p, root: root / p)
    cases, _, bindings, records = runner.freeze_inputs()
    assert len(cases) == 120 and len(records) == 3
    assert bindings[names[0]]['sha256'] == digest
    (tmp_path / names[0]).write_bytes(data + b' ')
    with pytest.raises(ValueError, match='gold bytes'):
        runner.freeze_inputs()


def test_evaluate_reserves_without_overwriting(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner.build.full, 'controlled_path', lambda p, root, strict=False: p)
    (tmp_path / 'candidate').mkdir()
    sentinel = tmp_path / 'candidate' / 'unknown'
    sentinel.write_bytes(b'preserve')
    with pytest.raises(ValueError, match='no overwrite'):
        runner.evaluate(binary='unused', output='candidate', results='results')
    assert sentinel.read_bytes() == b'preserve'
    assert not (tmp_path / 'results').exists()


def test_failure_retained_and_same_session(monkeypatch, tmp_path):
    from contextlib import contextmanager

    sessions = []
    class Session:
        def __enter__(self):
            sessions.append(self)
            return self

        def __exit__(self, *args):
            pass

        @contextmanager
        def guard(self, records):
            yield

    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner.build.full, 'controlled_path', lambda p, root, strict=False: p)
    monkeypatch.setattr(runner.build.full, 'contained', lambda p, root: root / p)
    monkeypatch.setattr(runner.acceptance, 'AcceptanceSession', Session)
    monkeypatch.setattr(runner, 'freeze_inputs', lambda: (
        [CASE] * 120, {'snapshot': {'path': 'snapshot'}}, {}, []))
    monkeypatch.setattr(runner.build, 'binding', lambda *a: {})

    def existing_assets(*, output, session):
        assert session is sessions[0]
        raise ValueError('deliberate candidate failure')

    monkeypatch.setattr(runner.build, 'existing_assets', existing_assets)
    report = runner.evaluate(binary='unused', output='candidate', results='results')
    assert report['status'] == 'FAIL'
    assert report['failures'] == ['deliberate candidate failure']
    assert len(report['formal']) == 120
    assert report['dense_overlap']['status'] == 'NOT_RUN'
    assert report['total_quality'] == 'NOT_RUN'
    assert (tmp_path / 'results' / 'evaluation.json').is_file()
