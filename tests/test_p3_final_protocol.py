"""Synthetic protocol tests only: no artifact build, resolver, SQLite or formal checks."""
import copy
import json
import sys
import zipfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import p3_final_artifacts as artifacts
import p3_final_validate as final


@pytest.fixture(autouse=True)
def forbid_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('synthetic protocol tests must not launch a process or open SQLite')

    monkeypatch.setattr(artifacts.subprocess, 'run', forbidden)
    monkeypatch.setattr(final.helpers.prior.sqlite3, 'connect', forbidden)
    monkeypatch.setattr(final.helpers, 'capture', final.helpers.capture)
    monkeypatch.setattr(final.helpers, 'RAW', final.helpers.RAW)


def test_create_new_marker_and_receipt_never_overwrite(tmp_path):
    for name in ('final-gold-start.json', 'final-gold.json'):
        path = tmp_path / name
        artifacts.create_new(path, {'status': 'FAIL'})
        before = path.read_bytes()
        with pytest.raises(FileExistsError):
            artifacts.create_new(path, {'status': 'PASS'})
        assert path.read_bytes() == before


@pytest.mark.parametrize('override', ['--target-dir', '--target-dir=elsewhere'])
def test_cargo_target_must_be_inside_knowledge_archive(tmp_path, monkeypatch, override):
    monkeypatch.setattr(artifacts, 'ROOT', tmp_path)
    directory = tmp_path / 'dist/p3-final-synthetic'
    target = directory / 'source/rust/target'
    env = artifacts.environment(target)
    assert artifacts.assert_target(['cargo', 'build'], env, directory) == target.resolve()
    with pytest.raises(ValueError, match='cargo target'):
        artifacts.assert_target(['cargo', 'build', override], env, directory)
    env['CARGO_TARGET_DIR'] = str(tmp_path / 'outside')
    with pytest.raises(ValueError, match='cargo target'):
        artifacts.assert_target(['cargo', 'build'], env, directory)


def test_module_provenance_recurses_and_detects_installed_mutation(tmp_path):
    source, site, wheel = tmp_path / 'source', tmp_path / 'site', tmp_path / 'fake.whl'
    modules = {'sakura_knowledge/__init__.py': b'',
               'sakura_knowledge/sub/package.py': b'value = 42\n'}
    with zipfile.ZipFile(wheel, 'w') as zipped:
        for name, data in modules.items():
            archive_file, installed = source / 'src' / name, site / name
            archive_file.parent.mkdir(parents=True, exist_ok=True)
            installed.parent.mkdir(parents=True, exist_ok=True)
            archive_file.write_bytes(data)
            installed.write_bytes(data)
            zipped.writestr(name, data)
    rows = artifacts.module_provenance(source, wheel, site)
    assert {r['module'] for r in rows} == set(modules)
    assert all(r['bytes_equal_archive_wheel_installed'] for r in rows)
    (site / 'sakura_knowledge/sub/package.py').write_bytes(b'mutated')
    with pytest.raises(ValueError, match='module mismatch'):
        artifacts.module_provenance(source, wheel, site)


def test_archive_traversal_is_refused(tmp_path):
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('../escape.py', b'not extracted')
    with pytest.raises(ValueError, match='unsafe git archive'):
        artifacts.extract_archive(archive, tmp_path / 'source')
    assert not (tmp_path / 'escape.py').exists()


@pytest.mark.parametrize('optin', [False, True])
def test_profile_is_disabled_except_explicit_s02(tmp_path, monkeypatch, optin):
    sink = tmp_path / 'fresh-profile.json'
    monkeypatch.setattr(final, 'PROFILE_SINK', sink)
    monkeypatch.setenv(artifacts.PROFILE, str(sink))
    seen = []

    def fake_capture(argv, cwd, **kwargs):
        seen.append(kwargs['env'])
        return {}, None

    monkeypatch.setattr(final, '_BASE_CAPTURE', fake_capture)
    rec, _ = final.capture(['synthetic-only'], tmp_path, s02_profile=optin)
    assert seen[0].get(artifacts.PROFILE) == (str(sink) if optin else None)
    assert rec['environment']['PYTHONUTF8'] == '1'


def test_s02_leaves_profile_reservation_to_same_child(tmp_path, monkeypatch):
    sink = tmp_path / 'fresh-profile.json'
    monkeypatch.setattr(final, 'PROFILE_SINK', sink)
    expected = {'warnings': [], 'query': '中文'}
    case = {'case_id': 'S02', 'expected_json': expected}
    profile = {'query_invocations': 1, 'profile': {'fts_skipped_kind_not_indexed': True}}
    calls = []

    def no_mkdir(*args, **kwargs):
        pytest.fail('S02 must not create directories, even when its parent exists')

    def fake_capture(argv, cwd, **kwargs):
        assert sink.parent.is_dir()
        assert not sink.exists()
        assert argv == ['synthetic-only']
        assert cwd == tmp_path
        assert kwargs == {'s02_profile': True}
        calls.append(argv)
        # Simulate Rust's exclusive reservation and profile write in this invocation.
        with sink.open('xb') as stream:
            stream.write(json.dumps(profile).encode('utf-8'))
        return {'exit': 0, 'stderr': {'bytes': 0}}, expected

    monkeypatch.setattr(Path, 'mkdir', no_mkdir)
    monkeypatch.setattr(final, 'capture', fake_capture)
    monkeypatch.setattr(final.helpers, 'commands', lambda *args: ['synthetic-only'])
    monkeypatch.setattr(final.helpers.prior, 'frozen_value', lambda ref: ref)
    monkeypatch.setattr(final.helpers, 'evidence', lambda data: {'bytes': len(data)})
    result = final.s02('not-executed', tmp_path / 'not-SQLite', {'cases': [case]}, tmp_path)
    assert result['status'] == 'PASS'
    assert result['profile'] == profile
    assert result['profile_raw']['bytes'] == sink.stat().st_size
    assert result['profile_environment'] == {artifacts.PROFILE: str(sink)}
    assert len(calls) == 1


@pytest.mark.parametrize('state', ['missing-parent', 'parent-file', 'existing-sink'])
def test_s02_rejects_unready_sink_without_capture_or_mkdir(tmp_path, monkeypatch, state):
    sink = tmp_path / 'parent/profile.json'
    if state == 'parent-file':
        sink.parent.write_bytes(b'not a directory')
    elif state == 'existing-sink':
        sink.parent.mkdir()
        sink.write_bytes(b'keep this profile')
    monkeypatch.setattr(final, 'PROFILE_SINK', sink)

    def forbidden(*args, **kwargs):
        pytest.fail('S02 must reject an unready sink without capture or mkdir')

    monkeypatch.setattr(Path, 'mkdir', forbidden)
    monkeypatch.setattr(final, 'capture', forbidden)
    error = FileExistsError if state == 'existing-sink' else NotADirectoryError
    with pytest.raises(error):
        final.s02('not-executed', tmp_path / 'not-SQLite',
                  {'cases': [{'case_id': 'S02'}]}, tmp_path)
    if state == 'missing-parent':
        assert not sink.parent.exists()
    elif state == 'parent-file':
        assert sink.parent.read_bytes() == b'not a directory'
    else:
        assert sink.read_bytes() == b'keep this profile'


def test_performance_is_not_a_phase(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['p3_final_validate.py', 'performance'])
    with pytest.raises(SystemExit) as exc:
        final.main()
    assert exc.value.code == 2
    assert final.PHASES == ('S02', 'P2', 'gold', 'external')


def test_runplan_maps_one_gold_to_both_deliverables():
    plan = final.runplan({'source_commit': 'synthetic'}, {}, {}, {}, {}, {})
    assert plan['gold55_invocations'] == plan['G42_gold_count'] == 1
    assert plan['gold55_serves'] == ['D', 'E']
    assert plan['performance_rerun'] == 'NO'
    assert plan['external_queries'] == plan['database_write_probes'] == 0


@pytest.mark.parametrize('field', ['source_commit', 'artifacts', 'frozen_gold', 'frozen_P2',
                                   'database', 'performance_prerequisite'])
def test_phase_prerequisites_bound_to_current_inputs(tmp_path, monkeypatch, field):
    monkeypatch.setattr(final, 'REPORTS', tmp_path)
    plan = final.runplan({'source_commit': 'synthetic'}, {}, {}, {}, {}, {})
    artifacts.create_new(tmp_path / 'final-runplan.json', plan)
    receipt = {**plan, 'status': 'PASS', 'phase': 'P2',
               'runplan': artifacts.binding(tmp_path / 'final-runplan.json')}
    receipt[field] = 'changed'
    artifacts.create_new(tmp_path / 'final-P2.json', receipt)
    with pytest.raises(ValueError, match='binding differs'):
        final.require_pass('P2', plan)


def test_performance_prerequisite_binds_old_receipt_and_policy_without_executor(tmp_path, monkeypatch):
    monkeypatch.setattr(final, 'REPORTS', tmp_path)
    monkeypatch.setattr(final, 'ROOT', tmp_path)
    (tmp_path / 'tools').mkdir()
    policy = tmp_path / 'tools/p3_measure_resolver.py'
    policy.write_bytes(b'synthetic policy; never imported')
    old = tmp_path / 'close-performance.json'
    artifacts.create_new(old, {'source_commit': final.RUNTIME, 'status': 'FAIL'})
    receipt = {'status': 'PASS', 'performance_rerun': 'NO', 'structure_errors': [],
               'formal_counts': {'attempted': 900, 'success': 900, 'failed': 0},
               'old_receipt': artifacts.binding(old), 'policy': artifacts.binding(policy)}
    names = ('p3_final_recompute.py', 'p3_retry1_acceptance.py', 'check_parity.py',
             'p3_evidence.py', 'p3_accept_resolver.py', 'p3_resolver_oracle.py')
    for name in names:
        (tmp_path / 'tools' / name).write_bytes(b'synthetic dependency')
    receipt['verifier_bindings'] = [artifacts.binding(p) for p in
                                    sorted((tmp_path / 'tools').glob('*.py'))]
    path = tmp_path / 'final-performance-recomputed-repair1.json'
    artifacts.create_new(path, receipt)
    assert final.performance_prerequisite() == artifacts.binding(path)
    verifier = tmp_path / 'tools/p3_final_recompute.py'
    verifier.write_bytes(b'mutated verifier')
    with pytest.raises(ValueError, match='changed'):
        final.performance_prerequisite()
    verifier.write_bytes(b'synthetic dependency')
    policy.write_bytes(b'mutated policy')
    with pytest.raises(ValueError, match='changed'):
        final.performance_prerequisite()


@pytest.mark.parametrize('missing_proof', [False, True])
def test_static_description_references_come_from_frozen_facts(monkeypatch, missing_proof):
    cases = [{'id': f'G{i:02}', 'expected': {'status': 'resolved'},
              'oracle_json': {'status': 'resolved'}} for i in range(1, 56)]
    cases[2]['expected'].update(description=True, evidence_assertions=[{'role': 'description'}])
    cases[2]['oracle_json'].update(descriptions=[{'text': 'source'}],
                                   evidence_chain=[] if missing_proof else [{'role': 'description'}])
    cases[4]['expected'].update(status='canonical_unknown', descriptions_empty=True)
    cases[4]['oracle_json'].update(status='canonical_unknown', descriptions=[])
    p2 = {'cases': [{'case_id': f'SYN{i:03}', 'args': {'query': '中文'}, 'mode': 'value'}
                    for i in range(151)]}
    p2['cases'][9]['mode'] = 'error'
    monkeypatch.setattr(final.helpers.prior, 'frozen_value', lambda ref: ref)
    before = copy.deepcopy(cases)
    if missing_proof:
        with pytest.raises(ValueError, match='frozen source facts not verified: G03'):
            final.static_coverage({'cases': cases}, p2)
    else:
        coverage = final.static_coverage({'cases': cases}, p2)
        assert coverage['description_source_positive_ids'] == ['G03']
        assert coverage['non_resolved_empty_description_cases'] == [
            {'case_id': 'G05', 'status': 'canonical_unknown'}]
        assert coverage['P2_error_contract_ids'] == ['SYN009']
    assert cases == before


@pytest.mark.parametrize('refusal_error,exit_code,stdout_bytes,passed', [
    ({'error': 'UsageError', 'message': "sknow: argument command: invalid choice: 'resolve-tag'"},
     2, 0, True),
    ({'error': 'ValueError', 'message': "invalid choice: 'resolve-tag'"}, 2, 0, False),
    ({'error': 'UsageError', 'message': "unknown command: 'resolve-tag'"}, 2, 0, False),
    ({'error': 'UsageError', 'message': "invalid choice: 'other'"}, 2, 0, False),
    ({'error': 'UsageError', 'message': "invalid choice: 'resolve-tag'"}, 1, 0, False),
    ({'error': 'UsageError', 'message': "invalid choice: 'resolve-tag'"}, 2, 1, False),
])
def test_external_python_refusal_uses_json_usage_error_contract(
        tmp_path, monkeypatch, refusal_error, exit_code, stdout_bytes, passed):
    directory = tmp_path / 'installed'
    modules = {name: str(directory / 'venv' / name) for name in
               ('sakura_knowledge/api.py', 'sakura_knowledge/cli.py')}
    art = {'directory': str(directory), 'python': 'not-executed-python',
           'binary': {'path': 'not-executed-rust'},
           'modules': [{'module': name, 'installed': {'path': path}}
                       for name, path in modules.items()]}
    info = {'modules': modules, 'resolve_tag': False, 'public_api': {},
            'prefix': str(directory / 'venv'), 'path': [str(directory / 'venv')],
            'encoding': 'utf-8', 'utf8': 1}
    coverage = {'description_source_positive_ids': ['G03'],
                'non_resolved_empty_description_cases': [{'case_id': 'G05', 'status': 'unknown'}],
                'P2_UTF8_case_ids': ['SYN000'], 'P2_error_contract_ids': ['SYN009']}
    receipts = {
        'gold': {'records': [{'case_id': f'G{i:02}', 'passed': True} for i in range(1, 56)]},
        'P2': {'records': [{'case_id': f'SYN{i:03}', 'passed': True, 'installed_python_passed': True}
                          for i in range(151)]},
    }
    monkeypatch.setattr(final, 'require_pass', lambda phase, plan: (receipts[phase], {'phase': phase}))
    monkeypatch.setattr(final, 'verify', lambda ref: ref['data'])
    calls = []

    def fake_capture(argv, cwd):
        calls.append(argv)
        assert cwd == tmp_path
        if len(calls) == 1:
            assert argv[:5] == [art['python'], '-X', 'utf8', '-I', '-c']
            return {'exit': 0, 'stderr': {'bytes': 0}}, info
        if len(calls) in (2, 3):
            assert argv[-1] == '--help'
            return {'exit': 0, 'stdout': {'data': b'usage: synthetic help\n'},
                    'stderr': {'bytes': 0}}, None
        assert len(calls) == 4
        assert argv == [art['python'], '-X', 'utf8', '-I', '-m',
                        'sakura_knowledge.cli', 'resolve-tag']
        return {'exit': exit_code, 'timeout': False, 'stdout': {'bytes': stdout_bytes},
                'error': refusal_error}, None

    monkeypatch.setattr(final, 'capture', fake_capture)
    result = final.external(art, {'coverage': coverage}, tmp_path)
    assert result['status'] == ('PASS' if passed else 'FAIL')
    assert result['source_external_verified'] is passed
    assert result['extra_query_probes'] == 0
    assert result['processes'][-1]['error'] == refusal_error
    assert len(calls) == 4


def test_interrupted_phase_stays_reserved_without_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(final, 'REPORTS', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['p3_final_validate.py', 'gold'])
    artifacts.create_new(tmp_path / 'final-gold-start.json', {'phase': 'gold'})
    with pytest.raises(FileExistsError, match='no retry'):
        final.main()
    assert json.loads((tmp_path / 'final-gold-start.json').read_bytes()) == {'phase': 'gold'}
    assert not (tmp_path / 'final-gold.json').exists()


@pytest.mark.parametrize('phase', final.PHASES)
def test_every_phase_bytechecks_before_inputs_or_runtime(tmp_path, monkeypatch, phase):
    monkeypatch.setattr(final, 'REPORTS', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['p3_final_validate.py', phase])
    artifacts.create_new(tmp_path / 'final-artifacts-retry1.json', {'synthetic': True})

    def changed(report):
        raise ValueError('synthetic changed artifact')

    def forbidden():
        pytest.fail('inputs must not be touched after artifact rejection')

    monkeypatch.setattr(final, 'verify_artifacts', changed)
    monkeypatch.setattr(final.helpers, 'validate_inputs', forbidden)
    with pytest.raises(ValueError, match='changed artifact'):
        final.main()
    assert not (tmp_path / ('final-' + phase + '-start.json')).exists()


def test_clean_git_status_precedes_raw_evidence_creation(monkeypatch):
    calls = []
    commit = 'a' * 40

    def fake_run(argv, env, cwd):
        calls.append(argv)
        output = (commit + '\n').encode() if argv[1] == 'rev-parse' else b''
        return {'exit': 0}, output

    monkeypatch.setattr(artifacts, 'run', fake_run)
    assert artifacts.source_git(commit)['clean_source']
    assert calls[0][1] == 'status'
    assert calls[-1][-2:] == ['src', 'rust']


def test_failed_child_still_protects_hashes_and_cannot_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(final, 'REPORTS', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['p3_final_validate.py', 'S02'])
    monkeypatch.setattr(final, 'PROFILE_SINK', tmp_path / 'profile.json')
    gold, p2 = tmp_path / 'frozen-gold.json', tmp_path / 'frozen-p2.json'
    gold.write_bytes(b'synthetic gold')
    p2.write_bytes(b'synthetic p2')
    db = tmp_path / 'synthetic.bin'
    db.write_bytes(b'not SQLite')
    art = {'source_commit': 'synthetic', 'binary': {'path': 'not-executed'}}
    artifacts.create_new(tmp_path / 'final-artifacts-retry1.json', art)
    monkeypatch.setattr(final, 'verify_artifacts', lambda report: None)
    monkeypatch.setattr(final, 'source_git', lambda *args, **kwargs: {})
    monkeypatch.setattr(final, 'performance_prerequisite', lambda: artifacts.binding(gold))
    monkeypatch.setattr(final.helpers, 'validate_inputs', lambda: ({}, {}, artifacts.binding(db)))
    monkeypatch.setattr(final.helpers.prior, 'GOLD', gold)
    monkeypatch.setattr(final.helpers.prior, 'P2', p2)
    monkeypatch.setattr(final, 'static_coverage', lambda *args: {})
    monkeypatch.setattr(final, 'verify_snapshot', lambda *args: (db, {'sidecars_after': {}}))
    monkeypatch.setattr(final, 'metadata', lambda *args: {})
    monkeypatch.setattr(final, 'compare', lambda *args: {'status': 'PASS', 'diagnostics': []})

    def failed_child(*args):
        raise OSError('synthetic child failure')

    monkeypatch.setattr(final, 's02', failed_child)
    assert final.main() == 1
    receipt = final.load(tmp_path / 'final-S02.json')
    assert receipt['status'] == 'FAIL'
    assert receipt['readonly_gate_after']['hash_unchanged'] is True
    with pytest.raises(FileExistsError, match='no retry'):
        final.main()
