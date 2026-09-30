"""Committed bytes are authoritative, even when checkout EOL bytes differ."""
import hashlib
import importlib.util
import subprocess
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "receipt_binding", Path(__file__).resolve().parents[1] / "tools/bind_committed_receipts.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_r9_committed_byte_binding_distinguishes_crlf(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)
    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / ".gitattributes").write_bytes(b"*.json text eol=lf\n")
    source = b'{"value":1}\n'
    path = tmp_path / "receipt.json"
    path.write_bytes(source)
    git("add", ".gitattributes", "receipt.json")
    git("commit", "-m", "fixture")
    path.write_bytes(source.replace(b"\n", b"\r\n"))
    record = MODULE.binding(tmp_path, "HEAD", ["receipt.json"])["entries"]["receipt.json"]
    assert record["committed_sha256"] == hashlib.sha256(source).hexdigest()
    assert record["committed_size_bytes"] == len(source)
    assert not record["worktree_equals_committed"]
    assert record["worktree_size_bytes"] == len(source) + 1
