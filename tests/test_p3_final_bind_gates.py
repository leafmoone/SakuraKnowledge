"""Full synthetic gate receipts, never invoke Git, SQLite or runtime artifacts."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p3_final_bind as final


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value).encode() if not isinstance(value, bytes) else value)
    return final.Evidence().binding(path)


@pytest.fixture
def gates(tmp_path, monkeypatch):
    monkeypatch.setattr(final, 'ROOT', tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail('no actual process, SQLite, or whole database read allowed')

    monkeypatch.setattr(final.subprocess, 'check_output', forbidden)
    monkeypatch.setattr(final.subprocess, 'run', forbidden)
    monkeypatch.setattr(final.helpers.prior.sqlite3, 'connect', forbidden)
    monkeypatch.setattr(final.helpers, 'validate_inputs', forbidden)
    source = 'a' * 40
    policy_bytes = b'policy byte binding'
    put(tmp_path, final.POLICY, policy_bytes)
    monkeypatch.setattr(final, 'boundaries', lambda head: 123)
    monkeypatch.setattr(final, 'tree', lambda head: {final.REPORT: 'report-oid'})

    def git(*args):
        if args[0] == 'merge-base':
            return source.encode()
        if args[0] == 'diff':
            return b''
        if args[0] == 'show':
            return policy_bytes
        if args[0] == 'log':
            return ('b' * 40).encode()
        pytest.fail('unexpected Git command')

    monkeypatch.setattr(final, 'git', git)
    artifacts = {'source_commit': source, 'directory': str(tmp_path / 'dist/final'),
                 'source': str(tmp_path / 'dist/final/source'),
                 'environment': {'CARGO_TARGET_DIR': str(tmp_path / 'dist/final/source/rust/target')}}
    artifact_ref = put(tmp_path, 'reports/P3/final-artifacts.json', artifacts)
    database = {'path': str(tmp_path / 'database-MUST-NOT-OPEN'), 'bytes': 21718736896, 'sha256': '0' * 64}
    put(tmp_path, 'reports/P3/close-performance.json', {'database': database})
    perf = put(tmp_path, 'reports/P3/final-performance-recomputed.json', {'status': 'PASS'})
    monkeypatch.setattr(final, 'performance', lambda evidence: perf)
    monkeypatch.setattr(final, 'protected_refs', lambda: [database])
    protection = {'status': 'PASS', 'source_commit': source, 'whole_binary_hashes_actual': [database],
                  'artifacts': artifact_ref, 'performance': perf, 'performance_reused': 'YES',
                  'performance_rerun': 'NO'}
    protection.update({k: True for k in ('frozen_inputs_unchanged', 'prep_moved_bytes_unchanged',
                                       'artifacts_unchanged', 'no_SQL_or_query', 'no_snapshot_rebuild')})
    put(tmp_path, final.PROTECTION, protection)
    plan = {'source_commit': source, 'artifacts': artifacts, 'database': database,
            'performance_prerequisite': perf, 'phases': ['S02', 'P2', 'gold', 'external'],
            'performance_rerun': 'NO', 'retries': 0, 'gold55_invocations': 1,
            'G42_gold_count': 1, 'gold55_serves': ['D', 'E'],
            'frozen_gold': put(tmp_path, 'gold-freeze.json', {}),
            'frozen_P2': put(tmp_path, 'p2-freeze.json', {})}
    plan_ref = put(tmp_path, 'reports/P3/final-runplan.json', plan)
    prerequisites = {}
    for phase in plan['phases']:
        rec = {k: plan[k] for k in ('source_commit', 'artifacts', 'database', 'frozen_gold',
                                    'frozen_P2', 'performance_prerequisite')}
        rec.update(status='PASS', phase=phase, runplan=plan_ref, prerequisites=copy.deepcopy(prerequisites),
                   performance_rerun='NO', snapshot_scope='FULLSNAPSHOT', source_external_cwd=True, retries=0)
        if phase == 'S02':
            rec.update(rust={'exit': 0, 'timeout': False}, profile={
                'query_invocations': 1, 'profile': {'fts_skipped_kind_not_indexed': True}})
        elif phase in ('P2', 'gold'):
            count = 151 if phase == 'P2' else 55
            rows = [{'case_id': ('P' + str(i)) if phase == 'P2' else f'G{i + 1:02}',
                     'passed': True, 'problems': [], 'rust': {'timeout': False},
                     'semantic_compared': i < 135, 'error_contract_verified': i >= 135,
                     'installed_python_passed': True, 'installed_python': {'timeout': False}}
                    for i in range(count)]
            rec.update(attempted=count, passed=count, records=rows, timeouts=0, wrong_resolved=0)
            if phase == 'P2':
                rec['summary'] = final.helpers.prior.summarize(rows, count)
        else:
            rec.update(extra_query_probes=0, source_external_verified=True, gold55_serves=['D', 'E'],
                       G42_gold_count=1, FULL_151_receipt=prerequisites['P2'], FULL_55_receipt=prerequisites['gold'])
        prerequisites[phase] = put(tmp_path, 'reports/P3/final-' + phase + '.json', rec)
    raw = put(tmp_path, 'reports/P3/final-raw/empty.raw', b'')
    commands = {'pytest': ['python', '-m', 'pytest', '-q'], 'ruff': ['python', '-m', 'ruff', 'check', '.'],
                'diff': ['git', 'diff', '--check'],
                'fmt': ['cargo', 'fmt', '--manifest-path', 'rust/Cargo.toml', '--all', '--', '--check'],
                'rust-test': ['cargo', 'test', '--manifest-path', 'rust/Cargo.toml', '--locked'],
                'clippy': ['cargo', 'clippy', '--manifest-path', 'rust/Cargo.toml', '--all-targets',
                           '--locked', '--', '-D', 'warnings'],
                'release': ['cargo', 'build', '--manifest-path', 'rust/Cargo.toml', '--release', '--locked']}
    for name, argv in commands.items():
        put(tmp_path, 'reports/P3/final-check-' + name + '.json', {
            'status': 'PASS', 'head': source, 'exit': 0, 'argv': argv, 'artifacts': artifact_ref,
            'stdout': raw, 'stderr': raw, 'environment': artifacts['environment']})
    put(tmp_path, 'reports/P3/final-F-user-waiver.json', {
        'status': 'WAIVED_BY_USER', 'audit_completion': 'NOT_COMPLETED',
        'SAKURAPOOL_TRACKED_SOURCE_MODIFIED': 'UNVERIFIED', 'historical_BUILD_ARTIFACTS_WRITTEN': 'YES'})
    return tmp_path


def test_all_gates_pass_without_reading_any_database(gates):
    facts = final.gates('head', final.Evidence())
    assert facts['historical_reports_unchanged'] == 123
    assert facts['PERF_HARNESS_FIX_SHA'] == 'b' * 40
    assert facts['runtime_artifact_source'] == 'a' * 40
    assert facts['Pool_verified_clean_claim'] is False and facts['audit_required'] is False
    assert facts['performance_reused'] == 'YES' and facts['performance_rerun'] == 'NO'


@pytest.mark.parametrize('name,field,value', [
    ('final-protection', 'whole_binary_hashes_actual', []),
    ('final-protection', 'performance_reused', 'NO'),
    ('final-S02', 'status', 'FAIL'),
    ('final-P2', 'attempted', 150),
    ('final-P2', 'timeouts', 1),
    ('final-gold', 'wrong_resolved', 1),
    ('final-gold', 'retries', 1),
    ('final-external', 'source_commit', 'c' * 40),
    ('final-external', 'FULL_55_receipt', {}),
    ('final-check-release', 'status', 'FAIL'),
    ('final-F-user-waiver', 'SAKURAPOOL_TRACKED_SOURCE_MODIFIED', 'NO'),
    ('final-F-user-waiver', 'audit_completion', 'COMPLETED'),
])
def test_failed_gate_never_promoted(gates, name, field, value):
    path = 'reports/P3/' + name + '.json'
    rec = final.load(path)
    rec[field] = value
    put(gates, path, rec)
    with pytest.raises(ValueError):
        final.gates('head', final.Evidence())
    assert not (gates / final.OUT).exists()


def test_missing_final_parent_report_blocks_prepare(gates, monkeypatch):
    monkeypatch.setattr(final, 'tree', lambda head: {})
    with pytest.raises(ValueError, match='parent report missing'):
        final.gates('head', final.Evidence())
