"""Pure capture-helper tests; never execute a formal baseline case."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('p4_approved_baseline', TOOLS / 'p4_approved_baseline.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.remove(str(TOOLS))


def receipt(code=0):
    return {'exit': code, 'timeout': False}


def test_independent_full_value_not_summary():
    row = {'original_case': {'mode': 'value'}}
    _, problems = MODULE.compare('P2', row, receipt(), b'{"nested": [2]}', b'',
                                 {'nested': [1]})
    assert problems == ['independent_full_value_mismatch']


def test_error_contract():
    row = {'original_case': {'mode': 'error', 'historical_expect': {'error': 'bad'}}}
    assert MODULE.compare('P2', row, receipt(2), b'',
                          b'{"error":"ValueError","message":"bad"}', None)[1] == []
    assert MODULE.compare('P2', row, receipt(0), b'x',
                          b'{"error":"ValueError","message":"bad"}', None)[1]


def test_source_assertions_and_wrong_status():
    row = {'original_case': {'expected': {'status': 'resolved', 'description': True}}}
    assert MODULE.compare('gold', row, receipt(), b'{"status":"unresolved"}', b'', None)[1]


@pytest.mark.parametrize('raw', [b'\xff', b'NaN', b'[]'])
def test_invalid_json(raw):
    assert MODULE.compare('P2', {'original_case': {'mode': 'value'}},
                          receipt(), raw, b'', {})[1]


def test_inner_timeout_counted():
    rec = receipt(2)
    row = {'original_case': {'mode': 'runtime_error', 'historical_expect': {'exit_rs': 2}}}
    assert MODULE.compare('P2', row, rec, b'',
                          b'{"error":"OperationalError","message":"query_budget_exceeded"}',
                          None)[1]
    assert rec['timeout']


def test_outer_deadline_retains_partial_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, 'LOCAL', tmp_path)
    monkeypatch.setattr(MODULE, 'ROOT', tmp_path)

    def timeout(*args, **kwargs):
        assert kwargs['timeout'] == 15
        raise subprocess.TimeoutExpired(args[0], 15, output=b'partial', stderr=b'\xff')

    monkeypatch.setattr(MODULE.subprocess, 'run', timeout)
    rec, out, err = MODULE.capture(['fake'], {}, 15)
    assert rec['timeout'] and rec['exit'] is None and rec['retries'] == 0
    assert rec['decode_error'] and out == b'partial' and err == b'\xff'


def test_target_overrides_inherited_pool(monkeypatch):
    monkeypatch.setenv('CARGO_TARGET_DIR', 'D:/Pool/target')
    assert MODULE.environment()['CARGO_TARGET_DIR'] == str(MODULE.TARGET.resolve())


def test_uri_readonly_immutable_and_only_binary_substitution():
    row = {'accepted_argv': ['old.exe', 'lookup', 'D:/old/knowledge.sqlite', 'hello']}
    argv = MODULE.case_argv(row, Path('new.exe'))
    assert argv[0] == 'new.exe'
    assert argv[2].endswith('?mode=ro&immutable=1')
    assert argv[1::2] == ['lookup', 'hello']
