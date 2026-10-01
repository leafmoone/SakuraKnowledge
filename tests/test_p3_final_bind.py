"""Synthetic evidence tests: no database, runtime, build or real Git commands."""
import base64
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p3_final_bind as final


@pytest.fixture(autouse=True)
def no_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(final, 'ROOT', tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail('synthetic tests must not execute processes or open SQLite')

    monkeypatch.setattr(final.subprocess, 'check_output', forbidden)
    monkeypatch.setattr(final.subprocess, 'run', forbidden)
    monkeypatch.setattr(final.helpers.prior.sqlite3, 'connect', forbidden)


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value).encode() if not isinstance(value, bytes) else value)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': final.sha(path.read_bytes())}


def test_stream_hash_memoized_but_each_reference_checked(tmp_path, monkeypatch):
    ref = put(tmp_path / 'synthetic-large', b'x' * (1024 * 1024 + 7))
    evidence = final.Evidence()
    original, reads = Path.open, []

    def counted(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', counted)
    for _ in range(20):
        evidence.verify(ref)
    assert len(reads) == 1
    for changed in ({**ref, 'bytes': True}, {**ref, 'sha256': '0' * 64}):
        with pytest.raises(ValueError, match='changed byte binding'):
            evidence.verify(changed)
    assert len(reads) == 1


@pytest.mark.parametrize('command', ['commit', 'push', 'reset', 'checkout'])
def test_git_mutation_rejected_before_process(command):
    with pytest.raises(ValueError, match='unsafe Git'):
        final.git(command)


def fake_inventory(monkeypatch, tmp_path, ref, *, tracked=True, md=False, stream=None):
    receipt = {'nested': [ref, {'duplicate': ref}]}
    if stream:
        receipt.update(stream)
    name = 'reports/P3/receipt.json'
    blob = json.dumps(receipt).encode()
    put(tmp_path / name, blob)
    names, blobs = {name: 'receipt-oid'}, {'receipt-oid': blob}
    if tracked:
        raw_name = Path(ref['path']).relative_to(tmp_path).as_posix()
        names[raw_name] = 'raw-oid'
        blobs['raw-oid'] = Path(ref['path']).read_bytes()
    if md:
        names['reports/P3/report.md'] = 'md-oid'
        blobs['md-oid'] = b'one\ntwo\n'
        put(tmp_path / 'reports/P3/report.md', b'one\r\ntwo\r\n')
    monkeypatch.setattr(final, 'tree', lambda commit: names)
    monkeypatch.setattr(final, 'git', lambda command, oid: blobs[oid])
    return names, blobs


def test_inventory_closes_nested_raw_and_embedded_streams(tmp_path, monkeypatch):
    ref = put(tmp_path / 'reports/P3/final-raw/value.raw', b'value')
    stream = {'stdout_base64': base64.b64encode(b'hello').decode(),
              'stdout_sha256': final.sha(b'hello'), 'stdout_bytes': 5}
    fake_inventory(monkeypatch, tmp_path, ref, md=True, stream=stream)
    evidence = final.Evidence()
    rows, raw, streams = final.inventory('synthetic', evidence)
    assert len(rows) == 3 and len(raw) == 1 and len(streams) == 1
    assert raw[0]['path'] == 'reports/P3/final-raw/value.raw'
    assert rows[-1]['MD_EOL_equivalence_only'] is True
    assert evidence.cache[Path(ref['path'])]['sha256'] == ref['sha256']


@pytest.mark.parametrize('directory', ['final-raw', 'close-raw'])
def test_new_raw_requires_tracked_blob(tmp_path, monkeypatch, directory):
    ref = put(tmp_path / ('reports/P3/' + directory + '/value.raw'), b'value')
    fake_inventory(monkeypatch, tmp_path, ref, tracked=False)
    with pytest.raises(ValueError, match='not tracked'):
        final.inventory('synthetic')


def test_old_raw_local_only_allowed(tmp_path, monkeypatch):
    ref = put(tmp_path / 'reports/P3/raw/value.raw', b'value')
    fake_inventory(monkeypatch, tmp_path, ref, tracked=False)
    assert len(final.inventory('synthetic')[1]) == 1


@pytest.mark.parametrize('fault', ['embedded', 'checkout', 'outside', 'raw-binding'])
def test_inventory_rejects_tampering(tmp_path, monkeypatch, fault):
    name = 'outside.raw' if fault == 'outside' else 'reports/P3/final-raw/value.raw'
    ref = put(tmp_path / name, b'value')
    if fault == 'raw-binding':
        ref['sha256'] = '0' * 64
    stream = {'stderr_base64': 'aGk=', 'stderr_sha256': '0' * 64} if fault == 'embedded' else None
    fake_inventory(monkeypatch, tmp_path, ref, stream=stream)
    if fault == 'checkout':
        put(tmp_path / 'reports/P3/receipt.json', b'{}\r\n')
    with pytest.raises(ValueError):
        final.inventory('synthetic')


@pytest.fixture
def check_data(tmp_path):
    artifacts = {'source_commit': 'a' * 40, 'source': str(tmp_path / 'dist/final/source'),
                 'directory': str(tmp_path / 'dist/final'),
                 'environment': {'CARGO_TARGET_DIR': str(tmp_path / 'dist/final/source/rust/target')}}
    put(tmp_path / 'reports/P3/final-artifacts-retry1.json', artifacts)
    raw = put(tmp_path / 'reports/P3/final-raw/empty.raw', b'')
    rec = {'status': 'PASS', 'head': artifacts['source_commit'], 'exit': 0, 'retries': 0,
           'argv': ['python', '-m', 'pytest', '-q'], 'artifacts': artifacts,
           'stdout': raw, 'stderr': raw, 'environment': artifacts['environment']}
    return rec, artifacts


@pytest.mark.parametrize('name,argv', [
    ('pytest', ['python', '-m', 'pytest', '-q']),
    ('ruff', ['python', '-m', 'ruff', 'check', '.']),
    ('ruff', ['python', '-m', 'ruff', 'check', 'src', 'tests', 'tools']),
    ('diff', ['git', 'diff', '--check']),
    ('fmt', ['cargo', 'fmt', '--manifest-path', 'rust/Cargo.toml', '--all', '--', '--check']),
    ('rust-test', ['cargo', 'test', '--manifest-path', 'rust/Cargo.toml', '--locked']),
    ('clippy', ['cargo', 'clippy', '--manifest-path', 'rust/Cargo.toml', '--all-targets',
                '--locked', '--', '-D', 'warnings']),
    ('release', ['cargo', 'build', '--manifest-path', 'rust/Cargo.toml', '--release', '--locked']),
])
def test_exact_checks_accepted_without_execution(check_data, name, argv):
    rec, artifacts = check_data
    rec['argv'] = argv
    final.check_receipt(name, rec, artifacts, final.Evidence())


@pytest.mark.parametrize('field,value', [
    ('status', 'FAIL'), ('exit', True), ('exit', 1), ('head', 'b' * 40),
    ('artifacts', None), ('argv', ['python', '-m', 'pytest', 'tests/one.py']),
    ('timeout', True), ('retries', 1),
])
def test_check_receipts_fail_closed(check_data, field, value):
    rec, artifacts = check_data
    rec[field] = value
    with pytest.raises(ValueError):
        final.check_receipt('pytest', rec, artifacts, final.Evidence())


def test_cargo_external_target_rejected(check_data, tmp_path):
    rec, artifacts = check_data
    rec['argv'] = ['cargo', 'test', '--manifest-path', 'rust/Cargo.toml', '--locked']
    external = tmp_path / 'external-Pool'
    rec['environment'] = {'CARGO_TARGET_DIR': str(external)}
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))
    assert not external.exists()
    with pytest.raises(ValueError, match='^Cargo check target escaped Knowledge or final artifact archive$'):
        final.check_receipt('rust-test', rec, artifacts, final.Evidence())
    # The autouse fixture forbids subprocess/Cargo execution; no external files appear.
    assert not external.exists()
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*')) == before


def test_protect_exclusive_and_no_db_open(tmp_path, monkeypatch):
    reports = tmp_path / 'reports/P3'
    reports.mkdir(parents=True)
    ref = put(tmp_path / 'not-a-database', b'database bytes only')
    put(reports / 'close-preconditions.json', {'preserved_cancelled_prep': []})
    put(reports / 'final-artifacts-retry1.json', {'source_commit': 'a' * 40})
    monkeypatch.setattr(final, 'protected_refs', lambda: [ref])
    monkeypatch.setattr(final.helpers, 'validate_inputs', lambda: None)
    monkeypatch.setattr(final, 'verify_artifacts', lambda report: None)
    monkeypatch.setattr(final, 'performance', lambda evidence: {'synthetic': 'performance'})
    final.protect()
    before = (reports / 'final-protection.json').read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        final.protect()
    assert (reports / 'final-protection.json').read_bytes() == before


def test_prepare_requires_gates_and_exclusive_output(tmp_path, monkeypatch):
    (tmp_path / 'reports/P3').mkdir(parents=True)
    monkeypatch.setattr(sys, 'argv', ['p3_final_bind.py', 'prepare'])
    monkeypatch.setattr(final, 'git', lambda *args: b'parent\n')
    monkeypatch.setattr(final, 'gates', lambda *args: {'protection_receipt': 'retained'})
    monkeypatch.setattr(final, 'tree', lambda *args: {final.REPORT: 'report-oid'})
    monkeypatch.setattr(final, 'inventory', lambda *args: ([], [], []))
    final.main()
    rec = final.load(final.OUT)
    assert rec['P3'] == 'READY' and rec['status'] == 'READY_FOR_REVIEW'
    assert rec['approval'] == 'NONE' and rec['code_review'] == 'WAITING_REVIEW'
    with pytest.raises(FileExistsError):
        final.main()


@pytest.mark.parametrize('fault', ['merge', 'other-child-file', 'remote', 'inventory', 'approval'])
def test_verify_child_remote_and_inventory_fail_closed(tmp_path, monkeypatch, fault):
    binding = {'evidence_commit': 'parent', 'status': 'READY_FOR_REVIEW', 'P3': 'READY',
               'code_review': 'WAITING_REVIEW', 'approval': 'NONE', 'main': final.MAIN,
               'files': [], 'raw_inventory': [], 'embedded_streams': []}
    if fault == 'approval':
        binding['approval'] = 'APPROVED'
    ref = put(tmp_path / final.OUT, binding)
    binding_bytes = Path(ref['path']).read_bytes()

    def git(*args):
        if args == ('rev-parse', 'HEAD'):
            return b'child\n'
        if args == ('rev-parse', 'child^@'):
            return b'parent\nother\n' if fault == 'merge' else b'parent\n'
        if args[0] == 'diff':
            return ('A\t' + final.OUT + ('\nM\tother' if fault == 'other-child-file' else '')).encode()
        if args[0] == 'show':
            return binding_bytes
        if args[0] == 'ls-remote':
            return (('wrong' if fault == 'remote' else 'child') + '\trefs/heads/dev\n' +
                    final.MAIN + '\trefs/heads/main\n').encode()
        pytest.fail('unexpected Git command')

    monkeypatch.setattr(sys, 'argv', ['p3_final_bind.py', 'verify'])
    monkeypatch.setattr(final, 'git', git)
    monkeypatch.setattr(final, 'gates', lambda *args: {})
    monkeypatch.setattr(final, 'inventory', lambda *args: (['changed'] if fault == 'inventory' else [], [], []))
    with pytest.raises(ValueError):
        final.main()
    assert Path(ref['path']).read_bytes() == binding_bytes


def test_boundaries_reject_historical_oid_and_compiler_changes(monkeypatch):
    def git(*args):
        if args[0] == 'status':
            return b''
        if args[0] == 'rev-parse':
            return final.MAIN.encode()
        if args[0] == 'merge-base':
            return final.BASE.encode()
        if args[0] == 'diff':
            return b'tools/p3_compile_inputs.py' if args[2] == final.BASE else b''
        pytest.fail('unexpected Git command')

    monkeypatch.setattr(final, 'git', git)
    old = {'reports/P3/old.json': 'old-oid'}
    monkeypatch.setattr(final, 'tree', lambda commit, *args: old)
    with pytest.raises(ValueError, match='unauthorized'):
        final.boundaries('head')
    changed = copy.deepcopy(old)
    changed['reports/P3/old.json'] = 'changed-oid'
    monkeypatch.setattr(final, 'tree', lambda commit, *args: old if commit == final.BASE else changed)
    with pytest.raises(ValueError, match='historical report changed'):
        final.boundaries('head')
