"""Local release entry forwarding smoke; no model/search corpus scan."""
import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('query', ['\u4e2d\u6587 \u65e5\u672c\u8a9e "quoted words"', '', 'a\\"nested\\" b\\\\', 'tail\\\\'])
def test_windows_launcher_preserves_unicode_spaces_quotes_and_exit_code(query):
    if not shutil.which('powershell') or not (ROOT / 'build/p4-usearch-native-fix/rust-target/release/sknow-rs.exe').exists():
        pytest.skip('local Windows release prerequisite')
    script = f"& '{ROOT}/scripts/sknow.ps1' lookup '{query}'"
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    result = subprocess.run(['powershell', '-NoProfile', '-EncodedCommand', encoded], capture_output=True, check=False)
    if query:
        assert result.returncode == 0
        assert json.loads(result.stdout)['query'] == query
    else:
        assert result.returncode == 1 and result.stdout == b''
        assert b'query must contain' in result.stderr
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'scripts/sknow.ps1'), 'invalid-command'], capture_output=True, check=False)
    assert result.returncode == 2
    assert result.stdout == b''
