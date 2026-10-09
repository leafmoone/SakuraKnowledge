"""Hard native request deadline on fresh lexical fixtures, not model qualification.

SKNOW_PILOT_TEST_BIN must name an already-built pilot. These tests never build
binaries or access production packs. A timeout may leave an incomplete frame;
nonzero process exit is fatal, not a claim that a FAIL envelope was delivered.
"""

import contextlib
import json
import os
import subprocess
import time

import pytest
from test_tool_runtime_integration import (
    _binary,
    _build_pack,
    _config,
    _input,
    _opened,
    _request,
    _resident,
    _small_install,
    _start_pilot,
    _stop,
)

from tools.tool_integration_validate import MAX_BYTES


@pytest.fixture(scope='module')
def deadline_binary():
    return _binary('SKNOW_PILOT_TEST_BIN')


@pytest.fixture(scope='module')
def deadline_install(tmp_path_factory, deadline_binary):
    base = tmp_path_factory.mktemp('native-deadline')
    root = base / 'deadline runtime'
    # About 400 KiB: above ordinary Windows/Linux pipe capacity, below 2 MiB.
    # Preserve the complete source text, with an exact alias pin for cheap Top1.
    body = 'slowpipe ' + '日' * (400 * 1024 // 3)
    items = [
        {'type': 'subject', 'id': 'large', 'name': 'slowpipe', 'description': body},
        {'type': 'subject', 'id': 'small', 'name': 'tinysolo',
         'description': 'tinysolo intact synthetic source text'},
    ]
    _build_pack(base / 'builder', root, 'fixture-deadline', items)
    return _config(root), body, items[1]['description']


def test_native_deadline_fast_drained_pass_fail_pass_eof(deadline_binary, deadline_install):
    config, body, small_body = deadline_install
    responses, profiles = _resident(deadline_binary, config, [
        _request('q1', query='slowpipe', limit=1, source='fixture-deadline'),
        _request('q2', query='slowpipe', limit='bad', source='fixture-deadline'),
        _request('q3', query='tinysolo', limit=1, source='fixture-deadline'),
    ])
    assert [row['case_id'] for row in responses] == ['q1', 'q2', 'q3']
    assert [row['status'] for row in responses] == ['PASS', 'FAIL', 'PASS']
    assert responses[1]['error'] == 'invalid_limit'
    assert responses[1]['retries'] == 0
    for response, original in [(responses[0], body), (responses[2], small_body)]:
        assert len(response['documents']) == 1
        assert response['documents'][0]['original'] == original
        assert response['documents'][0]['source_packs'] == ['fixture-deadline']
        assert response['participating_packs'] == ['fixture-deadline']
        assert response['semantic_capable_packs'] == []
        assert response['timings_ms']['query_encodings'] == 0
    assert all(row['timings_ms']['process_query_encodings'] == 0 for row in responses)
    assert 400 * 1024 < profiles[0]['sent_bytes'] < MAX_BYTES
    assert all(not profile['response_too_large'] for profile in profiles)
    assert not (config.parent / 'model').exists()


def test_native_deadline_stops_blocked_stdout_without_false_delivery(
    deadline_binary, deadline_install,
):
    config, _, _ = deadline_install
    process = _start_pilot(deadline_binary, config)
    try:
        opened = _opened(process)  # Read only the small cold-open event.
        started = time.monotonic()
        process.stdin.write(_input([
            _request('blocked-q1', query='slowpipe', limit=1, source='fixture-deadline'),
            _request('must-not-run', query='tinysolo', limit=1, source='fixture-deadline'),
        ]))
        process.stdin.flush()
        process.stdin.close()
        # Deliberately do NOT drain stdout or stderr while the request is active.
        # wait(), unlike communicate(), cannot unblock the response's pipe write.
        exit_code = process.wait(timeout=9)
        elapsed = time.monotonic() - started
        assert exit_code == 124, exit_code
        assert 4.7 <= elapsed <= 7.0, elapsed
        remaining = process.stdout.read()
        stderr = process.stderr.read()
        assert len(remaining) < MAX_BYTES
        assert b'\n' not in remaining, remaining[-200:]
        if remaining:
            with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
                json.loads(remaining.decode('utf-8', errors='strict'))
        # A partial PASS prefix is not a delivered response. No concurrent FAIL
        # emitter, reopened event, next request, or retry is permitted.
        assert b'"status":"FAIL"' not in remaining + stderr
        assert b'"event":"opened"' not in remaining
        assert b'must-not-run' not in remaining + stderr
        assert json.loads(opened)['event'] == 'opened'
        assert not (config.parent / 'model').exists()
    except subprocess.TimeoutExpired:
        pytest.fail('native request remained blocked past its five-second deadline')
    finally:
        _stop(process)


def test_native_single_config_deadline_stops_blocked_stdout(deadline_install):
    binary = _binary('SKNOW_RS_TEST_BIN')
    config, _, _ = deadline_install
    started = time.monotonic()
    process = subprocess.Popen(
        [str(binary), '--config', str(config), 'retrieve', 'slowpipe',
         '--source', 'fixture-deadline', '--limit', '1'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
    )
    try:
        # This fixture has no model/index. Even cold lexical opening is tiny;
        # no pipe is drained until the watchdog has terminated the process.
        assert process.wait(timeout=9) == 124
        elapsed = time.monotonic() - started
        assert 4.7 <= elapsed <= 7.0, elapsed
        remaining = process.stdout.read()
        stderr = process.stderr.read()
        assert len(remaining) < MAX_BYTES
        assert b'\n' not in remaining
        assert b'"status":"FAIL"' not in remaining + stderr
        assert b'"event":"opened"' not in remaining
        if remaining:
            with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
                json.loads(remaining.decode('utf-8', errors='strict'))
    except subprocess.TimeoutExpired:
        pytest.fail('single config retrieval remained blocked beyond its deadline')
    finally:
        _stop(process)


@contextlib.contextmanager
def _filled_stderr_pipe():
    """Fill the actual OS-reported capacity, never assume a pipe buffer size."""
    reader, writer = os.pipe()
    try:
        if os.name == 'nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetNamedPipeInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
                                               ctypes.POINTER(wintypes.DWORD),
                                               ctypes.POINTER(wintypes.DWORD),
                                               ctypes.POINTER(wintypes.DWORD)]
            kernel.GetNamedPipeInfo.restype = wintypes.BOOL
            capacity = wintypes.DWORD()
            if not kernel.GetNamedPipeInfo(msvcrt.get_osfhandle(reader), None,
                                           ctypes.byref(capacity), None, None):
                raise ctypes.WinError(ctypes.get_last_error())
            size = capacity.value
        else:
            import fcntl
            size = fcntl.fcntl(writer, fcntl.F_GETPIPE_SZ)
        assert 0 < size <= 1024 * 1024, size
        filler = b'P' * size
        assert os.write(writer, filler) == size
        yield reader, writer, filler
    finally:
        os.close(reader)
        os.close(writer)


@pytest.mark.parametrize('failure', ['stdin_utf8', 'corrupt_db'])
def test_native_resident_fatal_with_already_full_stderr(
    deadline_binary, tmp_path, failure,
):
    config, pack = _small_install(tmp_path)
    with _filled_stderr_pipe() as (reader, writer, filler):
        process = subprocess.Popen(
            [str(deadline_binary), '--config', str(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=writer,
            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
        )
        try:
            _opened(process)
            started = time.monotonic()
            if failure == 'stdin_utf8':
                # BufRead::lines fails before a request guard. Result-returning
                # main must not print to the already full stderr after teardown.
                payload = b'\xff\n'
            else:
                (pack / 'knowledge.sqlite').write_bytes(b'corrupt new fixture only')
                payload = _input([_request('fatal-q1'), _request('must-not-run')])
            process.stdin.write(payload)
            process.stdin.flush()
            process.stdin.close()
            exit_code = process.wait(timeout=9)
            elapsed = time.monotonic() - started
            assert exit_code == (1 if failure == 'stdin_utf8' else 124), exit_code
            assert elapsed < (2.5 if failure == 'stdin_utf8' else 7), elapsed
            output = process.stdout.read()
            # Parent has not drained stderr until the child actually terminated.
            assert os.read(reader, len(filler)) == filler
            assert b'must-not-run' not in output
            if failure == 'stdin_utf8':
                assert output == b''
            else:
                rows = [json.loads(row.decode('utf-8')) for row in output.splitlines()]
                assert len(rows) == 1 and rows[0]['status'] == 'FAIL'
                assert rows[0]['error'] == 'runtime_error'
                # The full frame preceding blocked profiling is not completion.
                assert rows[0]['case_id'] == 'fatal-q1'
        except subprocess.TimeoutExpired:
            pytest.fail('fatal resident tried an unguarded diagnostic on full stderr')
        finally:
            _stop(process)


@pytest.mark.parametrize('failure', ['invalid_query', 'broken_stdout'])
def test_native_single_runtime_fatal_with_already_full_stderr(
    deadline_install, failure,
):
    binary = _binary('SKNOW_RS_TEST_BIN')
    config, _, _ = deadline_install
    with _filled_stderr_pipe() as (reader, writer, filler):
        output_reader, output_writer = os.pipe()
        if failure == 'broken_stdout':
            os.close(output_reader)
            output_reader = None
        query = 'x' * 4097 if failure == 'invalid_query' else 'tinysolo'
        started = time.monotonic()
        process = subprocess.Popen(
            [str(binary), '--config', str(config), 'retrieve', query,
             '--source', 'fixture-deadline', '--limit', '1'],
            stdout=output_writer, stderr=writer,
            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
        )
        os.close(output_writer)
        try:
            exit_code = process.wait(timeout=9)
            elapsed = time.monotonic() - started
            assert exit_code == (1 if failure == 'invalid_query' else 124), exit_code
            assert elapsed < (2.5 if failure == 'invalid_query' else 7), elapsed
            assert os.read(reader, len(filler)) == filler
            if output_reader is not None:
                assert os.read(output_reader, MAX_BYTES) == b''
        except subprocess.TimeoutExpired:
            pytest.fail('fatal single query tried an unguarded diagnostic on full stderr')
        finally:
            _stop(process)
            if output_reader is not None:
                os.close(output_reader)
