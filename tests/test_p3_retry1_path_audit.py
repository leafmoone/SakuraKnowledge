"""Audit-only slash-spelling regression; no real snapshots or acceptance runs."""
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('retry1_path_audit', TOOLS / 'p3_retry1_path_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def ref(path):
    data = path.read_bytes()
    return {'path': path.as_posix(), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def test_slash_spelling_only(tmp_path, monkeypatch):
    file = tmp_path / 'evidence.raw'
    file.write_bytes(b'source bytes')
    frozen = ref(file)
    actual = {**frozen, 'path': str(file)}
    monkeypatch.setattr(audit.acceptance, 'binding', lambda _: actual)
    audit.check_binding(frozen)


@pytest.mark.parametrize('field,value', [('bytes', 999), ('sha256', '0' * 64)])
def test_rejects_changed_byte_metadata(tmp_path, monkeypatch, field, value):
    file = tmp_path / 'evidence.raw'
    file.write_bytes(b'source bytes')
    frozen = ref(file)
    monkeypatch.setattr(audit.acceptance, 'binding', lambda _: {**frozen, field: value})
    with pytest.raises(ValueError, match='changed frozen input'):
        audit.check_binding(frozen)


def test_rejects_different_file_even_same_bytes(tmp_path, monkeypatch):
    first, second = tmp_path / 'first.raw', tmp_path / 'second.raw'
    first.write_bytes(b'same')
    second.write_bytes(b'same')
    monkeypatch.setattr(audit.acceptance, 'binding', lambda _: ref(second))
    with pytest.raises(ValueError, match='changed frozen input'):
        audit.check_binding(ref(first))


def test_rejects_actual_content_change(tmp_path):
    file = tmp_path / 'evidence.raw'
    file.write_bytes(b'original')
    frozen = ref(file)
    file.write_bytes(b'modified')
    with pytest.raises(ValueError, match='changed frozen input'):
        audit.check_binding(frozen)


def test_rejects_missing_file(tmp_path):
    file = tmp_path / 'evidence.raw'
    file.write_bytes(b'original')
    frozen = ref(file)
    file.unlink()
    with pytest.raises(FileNotFoundError):
        audit.check_binding(frozen)


def test_resolved_same_file_spelling(tmp_path):
    file = tmp_path / 'evidence.raw'
    file.write_bytes(b'original')
    frozen = ref(file)
    frozen['path'] = str(tmp_path / '.' / 'evidence.raw')
    audit.check_binding(frozen)
