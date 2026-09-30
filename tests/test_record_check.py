import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'record_check', Path(__file__).resolve().parents[1] / 'tools/record_check.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


@pytest.mark.parametrize(('option', 'requested', 'effective'), [
    ([], 300, 300), (['--timeout', '0'], 0, None), (['--timeout', '17'], 17, 17)])
def test_timeout_policy_and_child_capture(tmp_path, monkeypatch, capsys, option, requested, effective):
    out = tmp_path / 'command.json'
    monkeypatch.setattr(sys, 'argv', ['record_check', '--out', str(out), *option, '--', 'child', 'arg'])
    git_calls = []
    def git(argv):
        git_calls.append(argv)
        return b'fixtureSHA\n' if argv[1] == 'rev-parse' else b''
    monkeypatch.setattr(M.subprocess, 'check_output', git)
    children = []
    def run(argv, **kwargs):
        children.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, 'captured 中文'.encode(), b'warning')
    monkeypatch.setattr(M.subprocess, 'run', run)
    assert M.main() == 0
    assert git_calls == [['git', 'rev-parse', 'HEAD'], ['git', 'status', '--porcelain']]
    assert len(children) == 1
    argv, kwargs = children[0]
    assert argv == ['child', 'arg']
    assert kwargs['timeout'] == effective
    assert kwargs['capture_output'] is True
    assert kwargs['check'] is False
    assert kwargs['env']['PYTHONIOENCODING'] == 'utf-8'
    assert kwargs['env']['PYTHONUTF8'] == '1'
    receipt = json.loads(out.read_text(encoding='utf-8'))
    assert receipt['timeout_policy'] == {
        'requested': requested, 'effective': effective, 'disabled': requested == 0}
    assert receipt['stdout'] == 'captured 中文'
    assert receipt['stderr'] == 'warning'
    assert json.loads(capsys.readouterr().out) == receipt


def test_negative_timeout_rejected_before_git_or_child(tmp_path, monkeypatch):
    out = tmp_path / 'command.json'
    monkeypatch.setattr(sys, 'argv', ['record_check', '--out', str(out), '--timeout', '-1', '--', 'child'])
    monkeypatch.setattr(M.subprocess, 'check_output', lambda *_: pytest.fail('must not call git'))
    monkeypatch.setattr(M.subprocess, 'run', lambda *_: pytest.fail('must not start child'))
    with pytest.raises(SystemExit) as exc:
        M.main()
    assert exc.value.code == 2
    assert not out.exists()


def test_default_deadline_still_records_timeout(tmp_path, monkeypatch):
    out = tmp_path / 'command.json'
    monkeypatch.setattr(sys, 'argv', ['record_check', '--out', str(out), '--', 'child'])
    monkeypatch.setattr(M.subprocess, 'check_output', lambda *_: b'fixture\n')
    def expire(argv, **kwargs):
        assert kwargs['timeout'] == 300
        raise subprocess.TimeoutExpired(argv, 300, output=b'partial', stderr=b'error')
    monkeypatch.setattr(M.subprocess, 'run', expire)
    assert M.main() == 124
    receipt = json.loads(out.read_text())
    assert receipt['exit'] is None
    assert receipt['status'] == 'FAIL'
    assert receipt['stdout'] == 'partial'
    assert receipt['timeout_policy'] == {'requested': 300, 'effective': 300, 'disabled': False}
