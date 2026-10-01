"""Offline/synthetic legacy preflight tests; no runtime or database access."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'p4_legacy_baseline', Path(__file__).parents[1] / 'tools/p4_legacy_baseline.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_historical_formats_exact_hash_and_size(newline):
    value = {'unicode': '桜😀', 'nested': [None, True, {'z': 1, 'a': 2}]}
    raw = (json.dumps(value, ensure_ascii=True) + newline).encode('utf-8')
    data, attempts = MODULE.reconstruct(value, MODULE.binding(raw))
    assert data == raw
    assert attempts[-1]['sha256'] == MODULE.binding(raw)['sha256']


@pytest.mark.parametrize('raw', [b'{"a":1}\n', b'{"a": 1}', b'{"a": 2}\n'])
def test_no_silent_alternative_serialization(raw):
    data, attempts = MODULE.reconstruct({'a': 1}, MODULE.binding(raw))
    assert data is None
    assert len(attempts) == 2


def test_size_is_required_even_when_hash_matches():
    ref = MODULE.binding(b'{"a": 1}\n')
    ref['bytes'] += 1
    assert MODULE.reconstruct({'a': 1}, ref)[0] is None


@pytest.mark.parametrize('raw', [b'"\xff"', b'NaN', b'Infinity', b'-Infinity'])
def test_strict_utf8_finite_json(raw):
    with pytest.raises(ValueError):
        MODULE.strict_json(raw)


@pytest.mark.parametrize('path', [
    '../reports/P3/final-raw/x.raw', '/reports/P3/final-raw/x.raw',
    'reports/P3/final-raw/../x.raw', 'E:/preservation/x.raw',
    'reports/P3/raw/x.raw', 'reports/P3/final-raw-other/x.raw',
])
def test_reject_untrusted_raw_paths_before_read(tmp_path, path):
    with pytest.raises(ValueError):
        MODULE.verify_raw(tmp_path, {'path': path, **MODULE.binding(b'')}, {path})


def test_tracked_hash_size_containment(tmp_path):
    raw = b'{"ok": true}\r\n'
    ref = MODULE.binding(raw)
    relative = 'reports/P3/final-raw/' + ref['sha256'] + '.raw'
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    ref['path'] = MODULE.HISTORICAL_ROOT + relative
    assert MODULE.verify_raw(tmp_path, ref, {relative}) == raw
    with pytest.raises(ValueError, match='untracked'):
        MODULE.verify_raw(tmp_path, ref, set())
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='mismatch'):
        MODULE.verify_raw(tmp_path, ref, {relative})


def test_duplicate_and_wrong_count_rejected():
    with pytest.raises(ValueError):
        MODULE.unique_rows([{'id': 'x'}, {'id': 'x'}], 'id', 2)
    with pytest.raises(ValueError):
        MODULE.unique_rows([{'id': 'x'}], 'id', 2)


def test_source_assertions_not_merely_status():
    expected = {'status': 'resolved', 'description': True,
                'evidence_assertions': [{'role': 'proof', 'source_id': 1}]}
    assert MODULE.source_checks({'status': 'resolved'}, expected) == [
        'description', 'evidence_assertion']
    assert MODULE.source_checks({'status': 'resolved', 'descriptions': ['text'],
                                 'evidence_chain': [{'role': 'proof', 'source_id': 1}]},
                                expected) == []


def test_retained_preflight_freezes_exact_151_and_55_without_runtime():
    manifest = MODULE.freeze()
    for suite, count, name, key in (
        ('P2', 151, 'full-retry1-P2-frozen-expected.json', 'case_id'),
        ('gold', 55, 'full-retry1-real-gold.json', 'id'),
    ):
        frozen = MODULE.strict_json((MODULE.ROOT / 'reports/P3' / name).read_bytes())
        result = manifest['suites'][suite]
        assert result['case_count'] == result['unique_ids'] == count
        assert [r['case_id'] for r in result['cases']] == [r[key] for r in frozen['cases']]
        assert [r['original_case'] for r in result['cases']] == frozen['cases']
    p2, gold = manifest['suites']['P2'], manifest['suites']['gold']
    assert (p2['recoverable_original_values'], p2['blocked_original_values'],
            p2['error_contract_cases']) == (135, 0, 16)
    assert (gold['recoverable_original_values'], gold['blocked_original_values']) == (0, 55)
    assert p2['verified_retained_raw_reference_occurrences'] == 604
    assert gold['verified_retained_raw_reference_occurrences'] == 110
    assert all(not r['source_assertion_problems'] for r in gold['cases'])
    assert manifest['status'] == 'BLOCKED_original_oracle_recovery'
    assert manifest['original_raw_reference_audit']
