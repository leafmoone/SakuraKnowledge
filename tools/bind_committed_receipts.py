"""Bind exact Git blob bytes, explicitly distinct from platform checkout bytes.

Never rewrites receipts. The output is a new external binding to an existing
commit, so it has no self-referential commit/hash cycle.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git_bytes(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def binding(root, revision, paths):
    commit = git_bytes(root, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
    entries = {}
    for name in paths:
        blob = git_bytes(root, "show", f"{commit}:{name}")
        worktree = (root / name).read_bytes()
        entries[name] = {
            "git_blob_oid": git_bytes(root, "rev-parse", f"{commit}:{name}").decode().strip(),
            "committed_sha256": hashlib.sha256(blob).hexdigest(),
            "committed_size_bytes": len(blob),
            "worktree_sha256": hashlib.sha256(worktree).hexdigest(),
            "worktree_size_bytes": len(worktree),
            "worktree_equals_committed": worktree == blob,
        }
    return {"schema": "committed-receipt-binding-v1", "commit": commit,
            "hash_rule": "SHA256 of exact git show COMMIT:PATH bytes; no newline/JSON normalization",
            "worktree_rule": "observed checkout bytes only; never substituted for committed bytes",
            "artifact_rule": "metadata correction does not rebuild or change historical artifacts",
            "entries": entries}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    result = binding(ROOT, args.revision, args.paths)
    with args.out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"commit": result["commit"], "entries": len(result["entries"])}))


if __name__ == "__main__":
    main()
