#!/usr/bin/env python3
"""C-stage parity check: Python reference API vs Rust runtime (sknow-rs).

Runs a fixed evaluation set against the frozen snapshot on both runtimes and
writes a machine-readable JSON diff report. Exit 0 only if every case is
semantically equal (documented exemptions excluded).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sakura_knowledge.api import Knowledge

SNAPSHOT = "snapshot-full-20bf5b3"
CASES = [
    # lookup by value (exact / alias paths)
    ("L01", "lookup", {"query": "975"}),
    ("L02", "lookup", {"query": "975", "kind": "character", "namespace": "bangumi.character"}),
    ("L03", "lookup", {"query": '"加特"'}),
    ("L04", "lookup", {"query": "ONE PIECE"}),
    ("L05", "lookup", {"query": "10"}),
    ("L06", "lookup", {"query": "definitely_missing_xyz_9271"}),
    # lookup by key
    ("L07", "lookup_key", {"kind": "character", "namespace": "bangumi.character", "value": "975"}),
    ("L08", "lookup_key", {"kind": "episode", "namespace": "bangumi.episode", "value": "1128648"}),
    # search
    ("S01", "search", {"query": "ONE PIECE", "topk": 20}),
    ("S02", "search", {"query": "ONE PIECE", "topk": 20, "kind": "episode"}),
    ("S03", "search", {"query": "!!", "topk": 20}),
    ("S04", "search", {"query": "独", "topk": 20}),
    ("S05", "search", {"query": "孤独摇滚", "topk": 5}),
    # related
    ("R01", "related", {"kind": "character", "namespace": "bangumi.character", "value": "975", "limit": 20}),
    ("R02", "related", {"kind": "character", "namespace": "bangumi.character", "value": "12393", "limit": 20}),
    ("R03", "related", {"kind": "tag", "namespace": "local.tag_aggregate", "value": "akanbe", "limit": 20}),
    ("R04", "related", {"kind": "character", "namespace": "bangumi.character", "value": "12393", "relation": "identity_candidate", "limit": 20}),
    # ask (direct + templates)
    ("A01", "ask", {"query": "975"}),
    ("A02", "ask", {"query": "加特 的标签是什么"}),
    ("A03", "ask", {"query": "孤独摇滚 的 Danbooru tag 是什么"}),
    ("A04", "ask", {"query": "介绍一下 975"}),
    ("A05", "ask", {"query": "10", "kind": "page", "namespace": "danbooru.wiki"}),
    ("A06", "ask", {"query": "!", "kind": "tag", "namespace": "local.tag_aggregate", "target_tag_namespace": "danbooru.tag"}),
    ("A07", "ask", {"query": "solo 的 Danbooru tag 是什么"}),
    ("A08", "ask", {"query": "xyzzy 不支持的自由文本 9271"}),
    # inspect (runtime command compared separately with exemptions)
    ("I01", "inspect", {}),
]

# Documented non-parity fields: runtime-identifying data that legitimately
# differs between the Python and Rust runtimes.
EXEMPT_PATHS = {
    ("$", "runtime"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def run_python(db: Path, op: str, args: dict):
    with Knowledge(db) as api:
        if op == "lookup":
            return api.lookup(args["query"], kind=args.get("kind"), namespace=args.get("namespace"))
        if op == "lookup_key":
            return api.lookup(key={"kind": args["kind"], "namespace": args["namespace"],
                                   "value": args["value"]})
        if op == "search":
            return api.search(args["query"], topk=args.get("topk", 20), kind=args.get("kind"), namespace=args.get("namespace"))
        if op == "related":
            return api.related({"kind": args["kind"], "namespace": args["namespace"], "value": args["value"]},
                               relation=args.get("relation"), kind=args.get("kind_filter"),
                               limit=args.get("limit", 20))
        if op == "ask":
            return api.ask(args["query"], kind=args.get("kind"), namespace=args.get("namespace"),
                           target_tag_namespace=args.get("target_tag_namespace"))
        if op == "inspect":
            return api.inspect()
        raise ValueError(op)


def run_rust(bin_path: Path, op: str, args: dict) -> tuple[int, dict]:
    cmd = [str(bin_path)]
    if op == "inspect":
        cmd += ["inspect", str(args["db"])]
    else:
        db = str(args["db"])
        if op == "lookup":
            cmd += ["lookup", db, args["query"]]
            if args.get("kind"):
                cmd += ["--kind", args["kind"]]
            if args.get("namespace"):
                cmd += ["--namespace", args["namespace"]]
        elif op == "lookup_key":
            cmd += ["lookup", db, args["value"], "--key",
                    "--kind", args["kind"], "--namespace", args["namespace"]]
        elif op == "search":
            cmd += ["search", db, args["query"], "--topk", str(args.get("topk", 20))]
            if args.get("kind"):
                cmd += ["--kind", args["kind"]]
            if args.get("namespace"):
                cmd += ["--namespace", args["namespace"]]
        elif op == "related":
            cmd += ["related", db, args["kind"], args["namespace"], args["value"],
                    "--limit", str(args.get("limit", 20))]
            if args.get("relation"):
                cmd += ["--relation", args["relation"]]
            if args.get("kind_filter"):
                cmd += ["--kind", args["kind_filter"]]
        elif op == "ask":
            cmd += ["ask", db, args["query"]]
            if args.get("kind"):
                cmd += ["--kind", args["kind"]]
            if args.get("namespace"):
                cmd += ["--namespace", args["namespace"]]
            if args.get("target_tag_namespace"):
                cmd += ["--target-tag-namespace", args["target_tag_namespace"]]
        else:
            raise ValueError(op)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    body = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, body


def is_budget_error(err: Exception) -> bool:
    return "query_budget_exceeded" in repr(err)


def run_python_warm(db: Path, op: str, args: dict, attempts: int = 5):
    """Run the Python reference, retrying only on its own 5 s budget abort.

    A budget abort on a cold/partially-cached 21.5 GB FTS working set is a
    cache-warmup effect, not a contract difference; the operation itself is
    bounded and deterministic. Every attempt is recorded.
    """
    last = None
    for n in range(1, attempts + 1):
        try:
            return run_python(db, op, args), n
        except ValueError as e:
            if not is_budget_error(e):
                raise
            last = e
    raise last


def diff(py_val, rs_val, path="$"):
    """Semantic JSON diff: dict order-insensitive, list order-sensitive."""
    problems = []
    if isinstance(py_val, dict) and isinstance(rs_val, dict):
        for k in sorted(set(py_val) | set(rs_val)):
            if (path, k) in EXEMPT_PATHS:
                continue
            p, _r = f"{path}.{k}", k
            if k not in rs_val:
                problems.append({"path": p, "kind": "missing_in_rust", "python": py_val[k]})
            elif k not in py_val:
                problems.append({"path": p, "kind": "extra_in_rust", "rust": rs_val[k]})
            else:
                problems += diff(py_val[k], rs_val[k], p)
    elif isinstance(py_val, list) and isinstance(rs_val, list):
        if len(py_val) != len(rs_val):
            problems.append({"path": path, "kind": "length", "python": len(py_val), "rust": len(rs_val)})
        else:
            for i, (a, b) in enumerate(zip(py_val, rs_val)):
                problems += diff(a, b, f"{path}[{i}]")
    else:
        if py_val != rs_val:
            problems.append({"path": path, "kind": "value", "python": py_val, "rust": rs_val})
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--bin", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    db = Path(args.db)
    bin_path = Path(args.bin)

    # Pre-warm the OS page cache (and SQLite FTS) so the 5 s per-operation
    # budget measures query cost, not first-touch page faults on a 21.5 GB
    # file. A cold 21.5 GB FTS scan can exceed the budget and abort before
    # the cache is fully populated, so retry until the warm-up query itself
    # completes. This warm-up is outside the compared pass.
    with Knowledge(db) as warm:
        for q in ("ONE PIECE",):
            for kw in (None, "episode"):
                for _attempt in range(5):
                    try:
                        warm.search(q, topk=20, kind=kw)
                        break
                    except ValueError:  # cold-cache budget abort; retry to warm
                        continue
    for q in ("ONE PIECE",):
        for kw in (None, "episode"):
            cmd = [str(bin_path), "search", str(db), q, "--topk", "20"]
            if kw:
                cmd += ["--kind", kw]
            for _attempt in range(5):
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
                if "query_budget_exceeded" not in (proc.stderr or ""):
                    break

    report = {
        "snapshot": SNAPSHOT,
        "db_sha256": sha256(db),
        "rust_bin_sha256": sha256(bin_path),
        "python_git_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "cases": [],
    }
    overall = "PASS"
    for cid, op, op_args in CASES:
        entry = {"case_id": cid, "op": op, "args": op_args}
        t0 = time.monotonic()
        try:
            py_val, py_attempts = run_python_warm(db, op, op_args)
        except Exception as e:  # noqa: BLE001
            entry.update(status="ERROR", side="python", error=repr(e),
                         elapsed_s=round(time.monotonic() - t0, 3))
            overall = "FAIL"
            report["cases"].append(entry)
            continue
        try:
            rc, rs_val = run_rust(bin_path, op, {**op_args, "db": db})
            if rc == 2 and "query_budget_exceeded" in (rs_val or {}):
                for _ in range(5):
                    rc, rs_val = run_rust(bin_path, op, {**op_args, "db": db})
                    if rc != 2:
                        break
        except Exception as e:  # noqa: BLE001
            entry.update(status="ERROR", side="rust", error=repr(e),
                         elapsed_s=round(time.monotonic() - t0, 3))
            overall = "FAIL"
            report["cases"].append(entry)
            continue
        problems = diff(py_val, rs_val)
        entry["python_status"] = py_val.get("status")
        entry["rust_exit_code"] = rc
        entry["elapsed_s"] = round(time.monotonic() - t0, 3)
        if py_attempts > 1:
            entry["python_budget_retries"] = py_attempts - 1
        if problems:
            entry.update(status="MISMATCH", problems=problems[:50])
            overall = "FAIL"
        else:
            entry["status"] = "EQUAL"
        report["cases"].append(entry)

    report["overall"] = overall
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"overall": overall, "cases": len(CASES),
                      "mismatches": sum(1 for c in report["cases"] if c["status"] != "EQUAL")},
                     ensure_ascii=False))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
