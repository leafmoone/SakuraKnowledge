"""Synthetic acceptance-policy tests; no resolver, database, or build is run."""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('measure_policy', TOOLS / 'p3_measure_resolver.py')
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)

MODES = ('reused_connection', 'independent_cli')
IDS = ['G01', 'G21']


def complete_records():
    return [{'mode': mode, 'case_id': case_id, 'round': round_, 'warmup': round_ == -1,
             'success': True, 'elapsed_s': 9000.0 if round_ == -1 else (round_ + 1) / 100}
            for mode in MODES for case_id in IDS for round_ in range(-1, 30)]


def test_complete_formal_all_pass_with_warmup_failure_retains_diagnostics(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('pure evaluation must not run a resolver or write evidence')

    for name in ('result', 'save', 'store'):
        monkeypatch.setattr(measure, name, forbidden)
    monkeypatch.setattr(measure.subprocess, 'run', forbidden)
    records = complete_records()
    records[0].update(success=False, elapsed_s=None, stderr='retained warmup failure')
    before = copy.deepcopy(records)
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'PASS'
    assert outcome['structure_errors'] == []
    assert outcome['records'] is records
    assert outcome['records'] == before
    assert outcome['records'][0]['stderr'] == 'retained warmup failure'
    assert outcome['formal_counts'] == {'attempted': 120, 'success': 120, 'failed': 0}
    assert outcome['warmup_counts'] == {'attempted': 4, 'success': 3, 'failed': 1}
    assert outcome['warmup_summary'][0] == {
        'mode': MODES[0], 'case_id': IDS[0], 'attempted': 1, 'success': 0,
        'failed': 1, 'failed_rounds': [-1],
    }


def test_all_warmup_failures_are_diagnostic_only():
    records = complete_records()
    for row in records:
        if row['warmup']:
            row.update(success=False, elapsed_s=None)
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'PASS'
    assert outcome['warmup_counts'] == {'attempted': 4, 'success': 0, 'failed': 4}
    assert sum(not row['success'] for row in outcome['records']) == 4


def test_warmups_excluded_from_percentiles_and_formal_counts():
    outcome = measure.evaluate(complete_records(), IDS)
    assert outcome['status'] == 'PASS'
    assert outcome['measured'] == 120
    assert outcome['warmups'] == 4
    for summary in outcome['summary']:
        assert summary['attempted'] == summary['success'] == 30
        assert summary['failed'] == 0
        assert summary['failed_rounds'] == []
        assert summary['p50_s'] == .15
        assert summary['p95_s'] == .29
    assert all('p50_s' not in row and 'p95_s' not in row for row in outcome['warmup_summary'])


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('round_', [0, 29])
def test_any_formal_failure_fails(mode, round_):
    records = complete_records()
    failed = next(row for row in records
                  if row['mode'] == mode and row['case_id'] == IDS[0] and row['round'] == round_)
    failed.update(success=False, elapsed_s=None)
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'FAIL'
    assert outcome['structure_errors'] == []
    assert outcome['formal_counts'] == {'attempted': 120, 'success': 119, 'failed': 1}
    summary = next(row for row in outcome['summary']
                   if row['mode'] == mode and row['case_id'] == IDS[0])
    assert summary['failed'] == 1
    assert summary['failed_rounds'] == [round_]
    assert summary['success'] == 29


@pytest.mark.parametrize('round_', [-1, 0, 29])
def test_missing_warmup_or_formal_row_blocks(round_):
    records = complete_records()
    records.remove(next(row for row in records if row['round'] == round_))
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'FAIL'
    assert any(f'round {round_}: expected once, got 0' in error
               for error in outcome['structure_errors'])


@pytest.mark.parametrize('records', [[], None, {}, [None]])
def test_empty_or_malformed_records_never_vacuously_pass(records):
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'FAIL'
    assert outcome['structure_errors']
    assert outcome['records'] is records


@pytest.mark.parametrize('round_', [-1, 0, 29])
def test_duplicate_rows_block_even_when_successful(round_):
    records = complete_records()
    records.append(dict(next(row for row in records if row['round'] == round_)))
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'FAIL'
    assert any(f'round {round_}: expected once, got 2' in error
               for error in outcome['structure_errors'])
    assert len(outcome['records']) == 125


def test_duplicate_cannot_replace_missing_row_with_same_total():
    records = complete_records()
    records[-1] = dict(records[-2])
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'FAIL'
    assert any('expected once, got 2' in error for error in outcome['structure_errors'])
    assert any('expected once, got 0' in error for error in outcome['structure_errors'])


@pytest.mark.parametrize('field,value', [
    ('mode', 'other'), ('mode', []), ('case_id', 'unknown'), ('case_id', {}),
    ('round', 30), ('round', -2), ('round', False), ('round', 0.0),
    ('warmup', False), ('warmup', 1), ('success', 'true'), ('success', 1),
    ('elapsed_s', None), ('elapsed_s', True), ('elapsed_s', float('nan')),
    ('elapsed_s', float('inf')), ('elapsed_s', -1), ('elapsed_s', 'fast'),
])
def test_corrupt_successful_record_blocks(field, value):
    records = complete_records()
    records[0][field] = value
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'FAIL'
    assert outcome['structure_errors']


@pytest.mark.parametrize('field', ['mode', 'case_id', 'round', 'warmup', 'success', 'elapsed_s'])
def test_missing_record_field_blocks(field):
    records = complete_records()
    del records[0][field]
    outcome = measure.evaluate(records, IDS)
    assert outcome['status'] == 'FAIL'
    assert outcome['structure_errors']


@pytest.mark.parametrize('samples', [0, 1, 29, 31, True, 30.0, None])
def test_protocol_is_fixed_at_30(samples):
    outcome = measure.evaluate(complete_records(), IDS, samples=samples)
    assert outcome['status'] == 'FAIL'
    assert 'protocol fixed at 30 samples' in outcome['structure_errors']
    assert outcome['samples'] == 30


@pytest.mark.parametrize('ids', [[], None, 'G01', ['G01', 'G01'], [''], [None]])
def test_invalid_workload_grid_blocks(ids):
    outcome = measure.evaluate(complete_records(), ids)
    assert outcome['status'] == 'FAIL'
    assert outcome['structure_errors']
