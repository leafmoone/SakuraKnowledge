"""STOP binder checks using temp files/mocked Git only."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('stop_bind', TOOLS / 'p3_retry1_stop_bind.py')
bind = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bind)


def test_strict_utf8():
    assert bind.decode_json('{"名称":1}'.encode()) == {'名称': 1}
    with pytest.raises(UnicodeError):
        bind.decode_json('{"a":1}'.encode('utf-16'))


def test_git_paths_nul_unicode(monkeypatch):
    monkeypatch.setattr(bind, 'git', lambda *args: 'reports/P3/名字.json\0reports/P3/line\nname.md\0'.encode())
    assert bind.git_paths('sha', 'reports/P3') == ['reports/P3/名字.json', 'reports/P3/line\nname.md']


def test_inventory_rejects_external_actual_raw(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    name = 'reports/P3/evidence.json'
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    data = json.dumps({'raw_path': str(tmp_path / 'outside.raw'), 'bytes': 0,
                       'sha256': bind.sha(b'')}).encode()
    path.write_bytes(data)
    def git(*args):
        if args[0] == 'ls-tree':
            return name.encode() + b'\0'
        if args[0] == 'show':
            return data
        return b'oid'
    monkeypatch.setattr(bind, 'git', git)
    with pytest.raises(ValueError, match='outside allowed'):
        bind.inventory('sha')


def test_frozen_checkout_byte_change_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'tools' / 'oracle.py'
    path.parent.mkdir()
    path.write_bytes(b'changed')
    frozen = {'bindings': [{'path': str(path), 'bytes': 8, 'sha256': bind.sha(b'original')}],
              'source_proof': []}
    monkeypatch.setattr(bind, 'git', lambda *args: json.dumps(frozen).encode())
    with pytest.raises(ValueError, match='checkout binding changed'):
        bind.frozen_bindings('sha')


def test_frozen_commit_change_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'tools' / 'oracle.py'
    path.parent.mkdir()
    path.write_bytes(b'original')
    frozen = {'bindings': [{'path': str(path), 'bytes': 8, 'sha256': bind.sha(b'original')}],
              'source_proof': []}
    def git(*args):
        return b'changed' if args[1].endswith(':tools/oracle.py') else json.dumps(frozen).encode()
    monkeypatch.setattr(bind, 'git', git)
    with pytest.raises(ValueError, match='committed blob'):
        bind.frozen_bindings('sha')


def test_excluded_untracked_reported_not_clean(monkeypatch):
    monkeypatch.setattr(bind, 'git', lambda *args: b'?? tools/p3_retry1_bind.py\0')
    observed = bind.worktree_observation()
    assert observed['status'] == 'DIRTY_EXCLUDED_UNTRACKED'
    assert observed['excluded_untracked'] == ['tools/p3_retry1_bind.py']


@pytest.mark.parametrize('status', [b' M src/changed.py\0', b'?? unexpected.py\0'])
def test_unapproved_worktree_change_rejected(monkeypatch, status):
    monkeypatch.setattr(bind, 'git', lambda *args: status)
    with pytest.raises(ValueError):
        bind.worktree_observation()
