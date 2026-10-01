"""Synthetic byte/metadata tests only: no SQL, processes or FULL hashes."""
import copy
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import p3_final_protection as protection


@pytest.fixture(autouse=True)
def no_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('protection tests must not execute processes, SQL or real snapshot gates')

    monkeypatch.setattr(protection.subprocess, 'run', forbidden)
    monkeypatch.setattr(protection.helpers.prior.sqlite3, 'connect', forbidden)
    monkeypatch.setattr(protection, 'verify_snapshot', forbidden)


@pytest.fixture
def full():
    return {'path': str(protection.TARGET), 'bytes': protection.FULL_BYTES,
            'sha256': protection.FULL_SHA256}


@pytest.fixture
def sidecars():
    return {'-wal': {'exists': True, 'bytes': 0, 'mtime_ns': 100},
            '-shm': {'exists': True, 'bytes': 32768, 'mtime_ns': 200, 'sha256': 'a' * 64,
                     'header_copies_equal': True, 'version': 3007000,
                     'initialized': 1, 'mx_frame': 0},
            '-journal': {'exists': False}}


def test_shm_mtime_only_pass_is_diagnostic_and_does_not_mutate(sidecars, full, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('pure compare must not resolve/stat/open filesystem paths')

    monkeypatch.setattr(Path, 'resolve', forbidden)
    monkeypatch.setattr(Path, 'stat', forbidden)
    monkeypatch.setattr(Path, 'open', forbidden)
    after = copy.deepcopy(sidecars)
    after['-shm']['mtime_ns'] += 1
    original = copy.deepcopy((sidecars, after, full))
    result = protection.compare(sidecars, after, full, full)
    assert result['status'] == 'PASS'
    assert result['excluded_invariant_fields'] == ['-shm.mtime_ns']
    assert result['SHM_content_SHA_strict'] is True
    assert result['diagnostics'][0]['before'] == 200
    assert result['diagnostics'][0]['after'] == 201
    assert (sidecars, after, full) == original


def test_unchanged_and_absent_sidecars(sidecars, full):
    assert protection.compare(sidecars, sidecars, full, full)['diagnostics'] == []
    absent = {suffix: {'exists': False} for suffix in sidecars}
    assert protection.compare(absent, absent, full, full)['status'] == 'PASS'
    with pytest.raises(ValueError, match='changed'):
        protection.compare(sidecars, absent, full, full)


@pytest.mark.parametrize('suffix,field,value', [
    ('-wal', 'mtime_ns', 101), ('-wal', 'bytes', 1), ('-shm', 'sha256', 'b' * 64),
    ('-shm', 'bytes', 123), ('-shm', 'header_copies_equal', False),
    ('-shm', 'version', 123), ('-shm', 'initialized', 0), ('-shm', 'mx_frame', 1),
    ('-shm', 'sha256', None), ('-shm', 'mx_frame', False),
    ('-shm', 'initialized', True), ('-shm', 'header_copies_equal', 1),
    ('-shm', 'extra', 'unknown'), ('-wal', 'extra', 'unknown'),
    ('-journal', 'exists', True),
])
@pytest.mark.parametrize('which', ['before', 'after'])
def test_unsafe_or_changed_metadata_rejects(sidecars, full, suffix, field, value, which):
    changed = copy.deepcopy(sidecars)
    changed[suffix][field] = value
    before, after = (changed, sidecars) if which == 'before' else (sidecars, changed)
    with pytest.raises(ValueError):
        protection.compare(before, after, full, full)


@pytest.mark.parametrize('suffix,field', [
    ('-shm', 'sha256'), ('-shm', 'header_copies_equal'), ('-shm', 'mx_frame'),
    ('-shm', 'version'), ('-shm', 'initialized'), ('-shm', 'mtime_ns'),
    ('-wal', 'bytes'), ('-wal', 'mtime_ns'), ('-journal', 'exists'),
])
def test_missing_exact_sidecar_evidence_rejects(sidecars, full, suffix, field):
    del sidecars[suffix][field]
    with pytest.raises(ValueError):
        protection.compare(sidecars, sidecars, full, full)


def test_unknown_sidecar_and_shm_without_wal_reject(sidecars, full):
    sidecars['-unknown'] = {'exists': False}
    with pytest.raises(ValueError, match='unknown'):
        protection.compare(sidecars, sidecars, full, full)
    del sidecars['-unknown']
    sidecars['-wal'] = {'exists': False}
    with pytest.raises(ValueError, match='SHM/WAL'):
        protection.compare(sidecars, sidecars, full, full)


@pytest.mark.parametrize('field,value', [
    ('sha256', None), ('sha256', 'a' * 64), ('bytes', 1), ('bytes', True),
    ('path', 'not-the-fixed-FULL.sqlite'), ('extra', 0),
])
@pytest.mark.parametrize('which', ['before', 'after'])
def test_fixed_full_evidence_rejects(sidecars, full, field, value, which):
    bad = dict(full, **{field: value})
    before, after = (bad, full) if which == 'before' else (full, bad)
    with pytest.raises(ValueError, match='FULL'):
        protection.compare(sidecars, sidecars, before, after)


@pytest.mark.parametrize('field', ['path', 'bytes', 'sha256'])
def test_missing_full_evidence(sidecars, full, field):
    del full[field]
    with pytest.raises(ValueError, match='FULL'):
        protection.compare(sidecars, sidecars, full, full)


@pytest.fixture
def recorded(tmp_path, sidecars, full, monkeypatch):
    def raw(name, value):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        path = tmp_path / name
        path.write_bytes(data)
        return data, protection.binding(path)

    expected = {'query': 'ONE PIECE', 'results': [], 'warnings': ['not indexed']}
    stdout, expected_ref = raw('expected.raw', expected)
    profile = {'query_invocations': 1, 'query_succeeded': True, 'query_error': None,
               'profile': {'fts_skipped_kind_not_indexed': True}}
    profile_bytes, _ = raw('profile.raw', profile)
    case = {'case_id': 'S02', 'mode': 'cli', 'args': {'argv_rs': [
        'search', 'DB', 'ONE PIECE', '--topk', '20', '--kind', 'episode']},
            'expected_json': expected_ref}
    plan = {'source_commit': protection.ARTIFACT_SOURCE,
            'artifacts': {'binary': {'path': str(tmp_path / 'never-executed')}},
            'frozen_gold': {}, 'frozen_P2': {}, 'database': full,
            'performance_prerequisite': {}, 'S02_profile_invocations': 1,
            'S02_profile_sink': str(tmp_path / 'original-profile.json'), 'retries': 0}
    receipt = {**copy.deepcopy(plan), 'phase': 'S02', 'status': 'FAIL', 'retries': 0,
               'protection_exception': {'type': 'ValueError',
                                        'message': protection.PROTECTION_MESSAGE},
               'readonly_gate_before': {'database': full, 'sidecars_before': sidecars,
                                        'sidecars_after': copy.deepcopy(sidecars)},
               'rust': {'argv': protection.helpers.commands(
                   Path(plan['artifacts']['binary']['path']), Path(full['path']), case),
                        'attempted': 1, 'succeeded': 1, 'exit': 0, 'timeout': False,
                        'outer_timeout': False,
                        'environment': {'SKNOW_SEARCH_PROFILE_OUT': plan['S02_profile_sink']}},
               'profile': profile,
               'profile_environment': {'SKNOW_SEARCH_PROFILE_OUT': plan['S02_profile_sink']},
               'source_git': {'validation_source_commit': protection.VALIDATOR_COMMIT}}
    # Pure synthetic source: never bind the later current checkout as historical code.
    source = (b"            check_binding(binding_ref)\n"
              b"            after = metadata(db)\n"
              b"            validate_metadata(after)\n"
              b"            if after != gate['sidecars_after']:\n"
              b"                raise ValueError('database sidecars changed during phase')\n")
    oid = protection.hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
    monkeypatch.setattr(protection, 'VALIDATOR_BLOB', oid)
    return receipt, case, plan, stdout, b'', profile_bytes, source


@pytest.mark.parametrize('fault', ['none', 'invalid_utf8', 'related_writer', 'nonzero', 'stderr'])
def test_process_gate_explicit_utf8_retains_bytes_and_rejects_errors(monkeypatch, fault):
    rows = [{'Name': '程序.exe', 'CommandLine': '无关进程'}]
    if fault == 'related_writer':
        rows[0]['CommandLine'] = str(protection.TARGET.parent) + ' writer'
    data = b'\xc9' if fault == 'invalid_utf8' else json.dumps(rows, ensure_ascii=False).encode()
    seen, retained = [], []

    class Proc:
        returncode = 1 if fault == 'nonzero' else 0
        stdout = data
        stderr = b'error' if fault == 'stderr' else b''

    def fake_run(argv, **kwargs):
        seen.append(argv)
        assert kwargs == {'capture_output': True, 'timeout': 30, 'check': False}
        return Proc()

    def fake_store(stream, **kwargs):
        retained.append(stream)
        return {'bytes': len(stream), 'path': 'synthetic', 'sha256': 'synthetic'}

    monkeypatch.setattr(protection.subprocess, 'run', fake_run)
    monkeypatch.setattr(protection, 'store', fake_store)
    if fault == 'none':
        result = protection.process_observation(protection.TARGET)
        assert result['exit'] == 0 and result['matched_related_processes'] == []
    else:
        with pytest.raises((ValueError, UnicodeDecodeError)):
            protection.process_observation(protection.TARGET)
    assert seen[0][3].startswith('[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false;')
    assert retained == [data, Proc.stderr]


def test_review_never_retroactively_passes_protection(recorded):
    before = copy.deepcopy(recorded)
    result = protection.review_s02(*recorded)
    assert result['status'] == 'QUERY_PASS_PROTECTION_FAIL'
    assert result['original_exact_after_metadata'] == 'NOT_SAVED'
    assert result['historical_protection_PASS'] is False
    assert result['SHM_mtime_only_historical_cause'] == 'NOT_PROVEN'
    assert result['query_rerun'] == 'NO'
    assert 'check_binding returned before comparison exception' in result['historical_FULL_after_evidence']
    assert recorded == before


@pytest.mark.parametrize('change', ['timeout', 'exit', 'argv', 'attempted', 'outer_timeout',
                                    'original_status', 'protection_message', 'after_receipt',
                                    'source_commit', 'profile_environment', 'retries'])
def test_review_rejects_bad_recorded_contract(recorded, change):
    receipt = recorded[0]
    if change in ('timeout', 'outer_timeout'):
        receipt['rust'][change] = True
    elif change == 'exit':
        receipt['rust']['exit'] = 2
    elif change == 'argv':
        receipt['rust']['argv'].append('second-query')
    elif change == 'attempted':
        receipt['rust']['attempted'] = 2
    elif change == 'original_status':
        receipt['status'] = 'PASS'
    elif change == 'protection_message':
        receipt['protection_exception']['message'] = 'different failure'
    elif change == 'after_receipt':
        receipt['readonly_gate_after'] = {}
    elif change == 'source_commit':
        receipt['source_git']['validation_source_commit'] = 'e' * 40
    elif change == 'profile_environment':
        receipt['profile_environment'] = {}
    else:
        receipt['retries'] = 1
    with pytest.raises(ValueError):
        protection.review_s02(*recorded)


@pytest.mark.parametrize('index,value', [
    (3, b'{"query":"different full JSON"}'), (4, b'unexpected stderr'),
    (5, b'{"query_invocations":2}'), (6, b'current source is not historical source'),
])
def test_review_rejects_raw_or_source_mismatch(recorded, index, value):
    args = list(recorded)
    args[index] = value
    with pytest.raises(ValueError):
        protection.review_s02(*args)


def test_baseline_uses_only_full_gate_and_records_current_scope(tmp_path, monkeypatch, sidecars, full):
    frozen_gold, frozen_p2, artifact_path = [tmp_path / n for n in ('gold', 'P2', 'artifact')]
    for path in (frozen_gold, frozen_p2, artifact_path):
        path.write_bytes(b'synthetic immutable input')
    monkeypatch.setattr(protection.helpers.prior, 'GOLD', frozen_gold)
    monkeypatch.setattr(protection.helpers.prior, 'P2', frozen_p2)
    artifact_ref = protection.binding(artifact_path)
    monkeypatch.setattr(protection, '_artifacts', lambda: ({}, artifact_ref))
    monkeypatch.setattr(protection, '_inputs', lambda: ({}, {}, full))
    monkeypatch.setattr(protection, 'verify_artifacts', lambda report: None)
    seen = []

    def gate(db, expected):
        seen.append((db, expected))
        return db, {'database': expected, 'sidecars_before': sidecars,
                    'sidecars_after': copy.deepcopy(sidecars), 'limitations': ['TOCTOU remains'],
                    'process_observation': {'exit': 0, 'matched_related_processes': []}}

    monkeypatch.setattr(protection, 'verify_snapshot', gate)
    result = protection.readonly_baseline()
    assert seen == [(Path(full['path']), full)]
    assert result['status'] == 'PASS'
    assert result['whole_FULL_hash_verified_now'] is True
    assert result['historical_protection_PASS'] is False
    assert result['SQL_queries'] == result['write_probes'] == 0
    assert result['finished_ns'] >= result['started_ns']
    assert result['readonly_gate']['process_observation']['exit'] == 0


@pytest.mark.parametrize('mode', ['baseline', 'review', 'workflow'])
def test_cli_exclusive_once_and_preserves_original_fail(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(protection, 'REPORTS', tmp_path)
    original = tmp_path / 'final-S02.json'
    original.write_bytes(b'{"status":"FAIL","preserve":"original"}')
    before = original.read_bytes()
    calls = []
    monkeypatch.setattr(protection, 'readonly_baseline',
                        lambda: calls.append('baseline') or {'status': 'PASS'})
    monkeypatch.setattr(protection, 'independent_review',
                        lambda: calls.append('review') or {'status': 'QUERY_PASS_PROTECTION_FAIL'})
    assert protection.main([mode]) == 0
    expected = ['baseline', 'review'] if mode == 'workflow' else [mode]
    assert calls == expected
    assert original.read_bytes() == before
    with pytest.raises(FileExistsError):
        protection.main([mode])
    assert calls == expected
    assert original.read_bytes() == before


def test_failed_baseline_stays_reserved_without_review(tmp_path, monkeypatch):
    monkeypatch.setattr(protection, 'REPORTS', tmp_path)

    def fail():
        raise ValueError('unsafe WAL; STOP')

    monkeypatch.setattr(protection, 'readonly_baseline', fail)
    monkeypatch.setattr(protection, 'independent_review', lambda: pytest.fail('must stop'))
    assert protection.main(['workflow']) == 1
    report = json.loads((tmp_path / 'final-protection-baseline.json').read_bytes())
    assert report['status'] == 'FAIL'
    assert report['exception']['message'] == 'unsafe WAL; STOP'
    with pytest.raises(FileExistsError):
        protection.main(['workflow'])


@pytest.mark.parametrize('mode', ['S02', 'P2', 'gold', 'performance', 'runtime', 'build', 'Pool'])
def test_no_runtime_modes(mode):
    with pytest.raises(SystemExit) as exc:
        protection.main([mode])
    assert exc.value.code == 2
