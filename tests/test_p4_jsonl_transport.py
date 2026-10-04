"""Real pipe children, bounded reader and owned reaping; no model assets."""
import sys

import pytest

from tools.p4_rust_pilot import MAX_BYTES, Driver


@pytest.mark.parametrize(('code', 'reason'), [
    ("import sys;sys.stdout.buffer.write(b'x'*(524289));sys.stdout.flush();\nwhile True: sys.stdout.buffer.write(b'x'*65536);sys.stdout.flush()", 'oversize'),
    ("import sys;sys.stdout.write('partial');sys.stdout.flush()", 'unterminated'),
    ("pass", 'EOF'),
], ids=['oversize-continuing', 'partial-exit', 'early-eof'])
def test_terminal_failure_reaps_real_child(code, reason, tmp_path):
    with (tmp_path / 'stderr').open('wb') as stderr:
        driver = Driver([sys.executable, '-u', '-c', code], stderr)
        with pytest.raises(ValueError, match=f'kind={reason}'):
            driver.receive(5)
        assert driver.process.poll() is not None
        assert driver.shutdown['reader_joined']
        assert driver.process.stdout.closed and driver.process.stdin.closed
        assert len(driver.last_raw) <= MAX_BYTES + 1
        assert driver.transport_failure['read_bytes'] == len(driver.last_raw)
        driver.close()


def test_normal_error_and_utf8_exact_boundary_exit_naturally(tmp_path):
    # Exactly512KiB including UTF-8 and newline; unmodified complete JSON accepted.
    code = """import sys,json
v={'status':'PASS','text':'日'}
n=524288-len((json.dumps(v,ensure_ascii=False,separators=(',',':'))+'\\n').encode())
v['text'] += 'x'*n
sys.stdout.buffer.write((json.dumps(v,ensure_ascii=False,separators=(',',':'))+'\\n').encode());sys.stdout.flush()
sys.stdout.write('{"status":"FAIL","error":"normal","retries":0}\\n');sys.stdout.flush()
sys.stdin.buffer.read(1)
"""
    with (tmp_path / 'stderr').open('wb') as stderr:
        driver = Driver([sys.executable, '-u', '-c', code], stderr)
        value, size = driver.receive(5)
        assert value['text'].startswith('日') and size == MAX_BYTES
        value, _ = driver.receive(5)
        assert value['error'] == 'normal'
        shutdown = driver.close()
        assert shutdown['exit_code'] == 0 and not shutdown['actively_terminated']
        assert shutdown['reader_joined']
        assert driver.process.poll() == 0


def test_reader_exception_is_forwarded_and_owned_child_reaped(tmp_path):
    with (tmp_path / 'stderr').open('wb') as stderr:
        driver = Driver([sys.executable, '-u', '-c', 'import sys;sys.stdin.buffer.read(1)'], stderr)
        driver.lines.put(OSError('fixture pipe failure'))
        with pytest.raises(RuntimeError, match='fixture pipe failure'):
            driver.receive(1)
        assert driver.process.poll() is not None and driver.shutdown['reader_joined']
        assert driver.transport_failure['kind'] == 'reader_exception'


def test_blocked_child_can_be_reaped_on_timeout(tmp_path):
    with (tmp_path / 'stderr').open('wb') as stderr:
        driver = Driver([sys.executable, '-u', '-c', 'import sys;sys.stdin.buffer.read(1)'], stderr)
        with pytest.raises(TimeoutError):
            driver.receive(.02)
        driver.close(terminal=True)
        assert driver.process.poll() is not None
        assert driver.shutdown['actively_terminated']
        assert driver.shutdown['reader_joined']
