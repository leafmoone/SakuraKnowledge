"""Synthetic offline proof tests; never load/hash the historical performance data."""
import copy
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import p3_final_recompute as verifier


@pytest.fixture(autouse=True)
def forbid_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline verifier must not execute/query/build/write evidence')

    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(verifier.prior, 'oracle', forbidden)
    monkeypatch.setattr(verifier.policy, 'result', forbidden)
    monkeypatch.setattr(verifier.policy, 'main', forbidden)
    monkeypatch.setattr(verifier, 'save', forbidden)


@pytest.fixture(params=('value', 'budget_limited'))
def proof(tmp_path, request):
    evidence = verifier.Evidence()
    serial = 0

    def raw(data):
        nonlocal serial
        path = tmp_path / f'{serial}.raw'
        serial += 1
        path.write_bytes(data)
        return evidence.binding(path)

    def encoded(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')

    expected = {ident: {'case': ident, 'warnings': [], 'payload': ['完全', {'n': 1}]}
                for ident in verifier.IDS}
    gold, p2 = {}, {}
    for ident in verifier.IDS:
        if ident.startswith('G'):
            gold[ident] = {'input': {'id': ident, 'query': ident, 'limit': 20},
                           'oracle_json': raw(encoded(expected[ident]))}
        else:
            p2[ident] = {'case_id': ident, 'args': {'query': ident, 'topk': 10}, 'op': 'search',
                         'mode': request.param, 'expected_json': raw(encoded(expected[ident]))}
    requests, values, _ = verifier.workload(gold, p2, evidence)
    responses = [{'case_id': row['id'], 'elapsed_s': (row['round'] + 2) / 100,
                  'value': expected[row['id']]} for row in requests]
    responses[4] = {'case_id': 'G42', 'elapsed_s': 5.0000352,
                    'error': 'query_budget_exceeded'}
    empty = raw(b'')
    binary, reused, database = 'expected-binary', 'expected-reused', 'expected-db'

    def process(argv, elapsed, stdout, budget):
        return {'argv': argv, 'elapsed_s': elapsed, 'exit': 0, 'stdout': raw(stdout),
                'stderr': empty, 'outer_timeout': False, 'timeout': False,
                'outer_timeout_s': budget, 'inner_budget_s': 5,
                'attempted': 1, 'succeeded': 1, 'other_error': 0}

    batch = process([reused, database], 100.,
                    b'\n'.join(encoded(row) for row in responses) + b'\n', 600)
    batch['input'] = raw(b'\n'.join(encoded(row) for row in requests) + b'\n')
    records = []
    for mode in verifier.MODES:
        for index, sample in enumerate(requests):
            elapsed = responses[index]['elapsed_s'] if mode == verifier.MODES[0] else .1
            row = {'mode': mode, 'case_id': sample['id'], 'round': sample['round'],
                   'warmup': sample['warmup'], 'success': not (mode == verifier.MODES[0]
                                                             and index == 4),
                   'elapsed_s': elapsed}
            if mode == verifier.MODES[0]:
                row['process_row'] = index
            else:
                row['rust'] = process(verifier.commands(binary, database, sample), elapsed,
                                      encoded(expected[sample['id']]), 15)
            records.append(row)
    outcome = verifier.policy.evaluate(records, list(verifier.IDS))
    old = {'records': records, 'status': 'FAIL', 'workloads': list(verifier.IDS),
           'samples': 30, 'measured': 900, 'warmups': 30, 'retries': 0,
           'summary': [{key: value for key, value in row.items() if key != 'failed'}
                       for row in outcome['summary']], 'reused_process': batch,
           'protocol': {'inner_s': 5, 'cli_outer_s': 15, 'reused_batch_outer_s': 600,
                        'cache': 'not claimed cold', 'rss': 'NOT_RUN',
                        'percentile': 'nearest rank on successful samples; failures/attempts explicit'}}
    return old, requests, values, evidence, binary, reused, database, raw, responses


def evaluate(proof):
    return verifier.verify_records(*proof[:7])


def test_complete_offline_proof_preserves_failure_and_percentiles(proof):
    before = copy.deepcopy(proof[0])
    result = evaluate(proof)
    assert proof[0] == before
    assert result['status'] == 'PASS'
    assert result['structure_errors'] == []
    assert result['formal_counts'] == {'attempted': 900, 'success': 900, 'failed': 0}
    assert result['warmup_counts'] == {'attempted': 30, 'success': 29, 'failed': 1}
    assert result['warmup_failure']['record'] == before['records'][4]
    assert result['warmup_failure']['response']['error'] == 'query_budget_exceeded'
    assert result['warmup_failure']['original_status'] == 'FAIL'
    assert len(result['summary']) == 30
    assert result['summary'][4]['p50_s'] == .16
    assert result['summary'][4]['p95_s'] == .30


@pytest.mark.parametrize('mutation', [
    'missing', 'duplicate', 'reordered', 'workload', 'summary', 'failed_counts',
    'record_success', 'response_timing', 'process_row', 'cli_argv', 'cli_exit',
    'cli_timeout', 'cli_outer', 'cli_inner', 'cli_stderr', 'cli_elapsed', 'cli_value',
    'cli_invalid_json', 'batch_timeout', 'batch_outer', 'batch_stderr',
    'input_extra_field', 'input_round', 'response_order', 'response_value',
    'warm_failure', 'original_status',
])
def test_corrupt_proof_fails_closed(proof, mutation):
    old, requests, _, _, _, _, _, raw, responses = proof
    rows, cli, batch = old['records'], old['records'][465]['rust'], old['reused_process']
    if mutation == 'missing':
        rows.pop()
    elif mutation == 'duplicate':
        rows[-1] = copy.deepcopy(rows[-2])
    elif mutation == 'reordered':
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == 'workload':
        old['workloads'].reverse()
    elif mutation == 'summary':
        old['summary'][0]['p95_s'] = 9
    elif mutation == 'failed_counts':
        old['summary'][0]['failed'] = 0
    elif mutation == 'record_success':
        rows[15]['success'] = False
    elif mutation == 'response_timing':
        rows[15]['elapsed_s'] += .01
    elif mutation == 'process_row':
        rows[15]['process_row'] = 16
    elif mutation == 'cli_argv':
        cli['argv'][0] = 'different-binary'
    elif mutation == 'cli_exit':
        cli['exit'] = 2
    elif mutation == 'cli_timeout':
        cli['timeout'] = True
    elif mutation == 'cli_outer':
        cli['outer_timeout_s'] = 16
    elif mutation == 'cli_inner':
        cli['inner_budget_s'] = 6
    elif mutation == 'cli_stderr':
        cli['stderr'] = raw(b'warning')
    elif mutation == 'cli_elapsed':
        cli['elapsed_s'] = .2
    elif mutation == 'cli_value':
        cli['stdout'] = raw(b'{"warnings":[],"case":"wrong"}')
    elif mutation == 'cli_invalid_json':
        cli['stdout'] = raw(b'{} {}')
    elif mutation == 'batch_timeout':
        batch['outer_timeout'] = True
    elif mutation == 'batch_outer':
        batch['outer_timeout_s'] = 601
    elif mutation == 'batch_stderr':
        batch['stderr'] = raw(b'warning')
    elif mutation in ('input_extra_field', 'input_round'):
        changed = copy.deepcopy(requests)
        changed[0]['extra' if mutation == 'input_extra_field' else 'round'] = 0
        batch['input'] = raw(b'\n'.join(json.dumps(row).encode() for row in changed))
    elif mutation in ('response_order', 'response_value', 'warm_failure'):
        changed = copy.deepcopy(responses)
        if mutation == 'response_order':
            changed[0], changed[1] = changed[1], changed[0]
        elif mutation == 'response_value':
            changed[15]['value']['payload'][1]['n'] = True
        else:
            changed[4]['error'] = 'different-error'
        batch['stdout'] = raw(b'\n'.join(json.dumps(row).encode() for row in changed))
    else:
        old['status'] = 'PASS'
    with pytest.raises(ValueError):
        evaluate(proof)


@pytest.mark.parametrize('fault', ['timeout', 'partial', 'missing', 'wrong_expected'])
def test_budget_class_never_accepts_actual_formal_failure(proof, fault):
    old, _, expected, _, _, _, _, raw, _ = proof
    rec = old['records'][465 + 15 + 13]['rust']  # S02 formal round 0, not a warmup.
    if fault == 'timeout':
        rec['exit'] = 2
        rec['timeout'] = True
    else:
        value = copy.deepcopy(expected['S02'])
        if fault == 'partial':
            value['status'] = 'BUDGET_LIMITED_PARTIAL'
        elif fault == 'missing':
            value = None
        else:
            value['payload'][1]['n'] = 999
        rec['stdout'] = raw(json.dumps(value, ensure_ascii=False).encode())
    with pytest.raises(ValueError):
        evaluate(proof)


@pytest.mark.parametrize('field,value', [
    ('mode', 'unknown'), ('mode', 'BUDGET_LIMITED_PARTIAL'),
    ('op', 'resolve'), ('case_id', 'UNKNOWN'),
])
def test_workload_rejects_unknown_class_operation_or_case(proof, field, value):
    _, requests, expected, evidence, _, _, _, raw, _ = proof
    gold, p2 = {}, {}
    for request in requests[:15]:
        ident = request['id']
        ref = raw(json.dumps(expected[ident], ensure_ascii=False).encode())
        if ident.startswith('G'):
            gold[ident] = {'input': {'query': ident}, 'oracle_json': ref}
        else:
            p2[ident] = {'case_id': ident, 'args': {'query': ident}, 'op': 'search',
                         'mode': 'budget_limited', 'expected_json': ref}
    p2['S02'][field] = value
    with pytest.raises(ValueError, match='wrong P2 representative'):
        verifier.workload(gold, p2, evidence)


def test_recursive_references_verified_once_with_each_binding_checked(tmp_path, monkeypatch):
    path = tmp_path / 'proof.raw'
    path.write_bytes(b'proof')
    evidence = verifier.Evidence()
    ref = evidence.binding(path)
    evidence = verifier.Evidence()
    calls = []
    shared_verify = verifier.verify

    def counted(ref):
        calls.append(ref['path'])
        return shared_verify(ref)

    monkeypatch.setattr(verifier, 'verify', counted)
    db = {'path': str(tmp_path / 'must-not-read.sqlite'), 'bytes': 42, 'sha256': 'frozen'}
    evidence.walk({'artifacts': {'nested': [ref, {'stderr': ref}]}, 'database': db}, db)
    assert calls == [str(path.resolve())]
    with pytest.raises(ValueError, match='changed byte binding'):
        evidence.walk({'nested': [{**ref, 'bytes': 99}]}, db)
    with pytest.raises(ValueError, match='database binding differs'):
        evidence.walk({**db, 'sha256': 'changed'}, db)


@pytest.mark.parametrize('data', [b'{"a":1,"a":2}', b'{"n":NaN}', b'{"n":Infinity}',
                                  b'{} trailing', b'\xff'])
def test_strict_full_json_decode(data):
    with pytest.raises(ValueError):
        verifier.decode(data)


def test_output_exists_refused_before_recompute(tmp_path, monkeypatch):
    output = tmp_path / 'existing.json'
    output.write_bytes(b'untouched')
    monkeypatch.setattr(verifier, 'OUT', output)
    monkeypatch.setattr(verifier, 'recompute', lambda: pytest.fail('must refuse before reading'))
    with pytest.raises(FileExistsError):
        verifier.main()
    assert output.read_bytes() == b'untouched'


def test_search_argv_helper_restores_setting():
    previous = verifier.prior.parity.DB
    assert verifier.commands('binary', 'db', {'op': 'search', 'query': '完全', 'topk': 10}) == [
        'binary', 'search', 'db', '完全', '--topk', '10']
    assert verifier.prior.parity.DB == previous
