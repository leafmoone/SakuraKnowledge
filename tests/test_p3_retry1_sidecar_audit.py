"""Synthetic sidecar gate tests; no production snapshot or runtime execution."""
import hashlib
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('retry1_sidecar_audit', TOOLS / 'p3_retry1_sidecar_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    db = tmp_path / 'published' / 'knowledge.sqlite'
    db.parent.mkdir()
    db.write_bytes(b'synthetic frozen bytes; not SQLite')
    monkeypatch.setattr(audit, 'TARGET', db)
    data = db.read_bytes()
    ref = {'path': str(db), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return db, ref


def valid_sidecars(db):
    Path(str(db) + '-wal').write_bytes(b'')
    header = struct.pack('<III BBH II', 3007000, 0, 0, 1, 0, 0, 0, 0) + bytes(24)
    Path(str(db) + '-shm').write_bytes(header * 2 + bytes(32768 - 96))


def quiet(_):
    return {'matched_related_processes': [], 'scope': 'mock test only'}


def test_absent_sidecars(snapshot):
    db, ref = snapshot
    verified, report = audit.verify_snapshot(db, ref, inspect_process=quiet)
    assert verified == db and report['database'] == ref


def test_empty_valid_stable_sidecars_not_deleted(snapshot):
    db, ref = snapshot
    valid_sidecars(db)
    verified, report = audit.verify_snapshot(db, ref, inspect_process=quiet)
    assert verified == db
    assert report['sidecars_before'] == report['sidecars_after']
    assert Path(str(db) + '-wal').exists()
    assert Path(str(db) + '-shm').stat().st_size == 32768


@pytest.mark.parametrize('suffix,data', [('-wal', b'nonempty'), ('-journal', b''), ('-shm', b'bad')])
def test_rejects_unsafe_sidecars(snapshot, suffix, data):
    db, ref = snapshot
    valid_sidecars(db)
    Path(str(db) + suffix).write_bytes(data)
    with pytest.raises(ValueError):
        audit.verify_snapshot(db, ref, inspect_process=quiet)


def test_rejects_header_nonzero_frames(snapshot):
    db, ref = snapshot
    valid_sidecars(db)
    shm = Path(str(db) + '-shm')
    data = bytearray(shm.read_bytes())
    data[16:20] = struct.pack('<I', 1)
    data[64:68] = struct.pack('<I', 1)
    shm.write_bytes(data)
    with pytest.raises(ValueError, match='SHM'):
        audit.verify_snapshot(db, ref, inspect_process=quiet)


def test_rejects_changed_database(snapshot):
    db, ref = snapshot
    db.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed frozen'):
        audit.verify_snapshot(db, ref, inspect_process=quiet)


def test_rejects_sidecar_change_during_hash(snapshot, monkeypatch):
    db, ref = snapshot
    valid_sidecars(db)
    original = audit.check_binding
    def mutate(ref):
        original(ref)
        Path(str(db) + '-wal').write_bytes(b'x')
    monkeypatch.setattr(audit, 'check_binding', mutate)
    with pytest.raises(ValueError, match='nonempty WAL'):
        audit.verify_snapshot(db, ref, inspect_process=quiet)


def test_rejects_activity_lock(snapshot):
    db, ref = snapshot
    (db.parent.parent / ('.' + db.parent.name + '.sknow.lock')).write_bytes(b'')
    with pytest.raises(ValueError, match='activity lock'):
        audit.verify_snapshot(db, ref, inspect_process=quiet)


def test_process_check_failure_blocks(snapshot):
    db, ref = snapshot
    def failure(_):
        raise ValueError('process inspection failed; BLOCKED')
    with pytest.raises(ValueError, match='BLOCKED'):
        audit.verify_snapshot(db, ref, inspect_process=failure)
