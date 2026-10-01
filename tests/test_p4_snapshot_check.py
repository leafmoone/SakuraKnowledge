"""Small file checks only; never hash or open the real FULL in unit tests."""
import hashlib
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'p4_snapshot_check', Path(__file__).parents[1] / 'tools/p4_snapshot_check.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_binding_preserves_bytes(tmp_path):
    path = tmp_path / 'sample'
    path.write_bytes(b'unchanged\x00bytes')
    before = path.stat()
    result = MODULE.binding(path)
    assert result == {'bytes': 15, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'mtime_ns': before.st_mtime_ns}
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_absent_sidecars_not_created(tmp_path):
    db = tmp_path / 'knowledge.sqlite'
    assert MODULE.sidecars(db) == {s: {'exists': False}
                                   for s in ('-wal', '-shm', '-journal')}
    assert list(tmp_path.iterdir()) == []


def test_present_sidecars_are_hashed_not_removed(tmp_path):
    db = tmp_path / 'knowledge.sqlite'
    wal = Path(str(db) + '-wal')
    wal.write_bytes(b'not safe for immutable reads')
    result = MODULE.sidecars(db)
    assert result['-wal']['bytes'] == len(wal.read_bytes())
    assert result['-wal']['sha256'] == hashlib.sha256(wal.read_bytes()).hexdigest()
    assert wal.exists()
