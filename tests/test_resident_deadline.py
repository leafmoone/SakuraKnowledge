"""Hard native request deadline on fresh lexical fixtures, not model qualification.

SKNOW_PILOT_TEST_BIN must name an already-built pilot. These tests never build
binaries or access production packs. A timeout may leave an incomplete frame;
nonzero process exit is fatal, not a claim that a FAIL envelope was delivered.
"""

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
