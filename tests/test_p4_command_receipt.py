import base64
import json
import sys

import pytest

from tools import p4_command_receipt as runner


def test_receipt_nonzero_utf8_and_exclusive(tmp_path, monkeypatch):
    output = tmp_path / 'receipt.json'
    monkeypatch.setattr(sys, 'argv', ['receipt', '--output', str(output), '--',
                                    sys.executable, '-c',
                                    "import sys;print('日本語');print('failure',file=sys.stderr);sys.exit(7)"])
    assert runner.main() == 7
    receipt = json.loads(output.read_text(encoding='utf-8'))
    assert receipt['exit_code'] == 7
    assert receipt['stdout_utf8_valid'] is True
    assert receipt['stderr_utf8_valid'] is True
    assert receipt['stdout'].strip() == '日本語'
    assert receipt['stderr'].strip() == 'failure'
    assert base64.b64decode(receipt['stdout_base64']).decode('utf-8') == receipt['stdout']
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        runner.main()
    assert output.read_bytes() == original
