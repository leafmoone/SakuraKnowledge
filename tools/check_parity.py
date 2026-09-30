"""Formal full-JSON parity, no retries, fixed optional warmups.

Each invocation has a 15s host-process hard limit; this never replaces the
runtime's 5s operation budget. Missing values and all timeouts fail. Raw
bytes (base64 + hashes), argv, exit and time survive even malformed output.
Historical receipts and case tables are not rewritten by this runner.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from parity_policy import classify, summarize
from parity_repair_expected import CASES

from sakura_knowledge.api import Knowledge

DB = None
HARD_TIMEOUT_S = 15


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def run_python(op: str, args: dict):
    with Knowledge(DB) as api:
        if op == "lookup_key":
            return api.lookup(key={k: args[k] for k in ("kind", "namespace", "value")})
        if op == "related":
            return api.related({k: args[k] for k in ("kind", "namespace", "value")},
                               relation=args.get("relation"), kind=args.get("kind_filter"),
                               limit=args.get("limit", 20))
        return getattr(api, op)(**args)


def rust_argv(op: str, args: dict) -> list[str]:
    dbp = str(DB)
    if op == "inspect":
        return ["inspect", dbp]
    if op == "lookup_key":
        return ["lookup", dbp, args["value"], "--key", "--kind", args["kind"],
                "--namespace", args["namespace"]]
    if op == "related":
        cmd = ["related", dbp, args["kind"], args["namespace"], args["value"],
               "--limit", str(args.get("limit", 20))]
        for key, flag in (("relation", "--relation"), ("kind_filter", "--kind")):
            if args.get(key):
                cmd += [flag, args[key]]
        return cmd
    cmd = [op, dbp, args["query"]]
    if op == "search":
        cmd += ["--topk", str(args.get("topk", 20))]
    for key in ("kind", "namespace", "target_tag_namespace"):
        if args.get(key) is not None:
            cmd += ["--" + key.replace("_", "-"), args[key]]
    return cmd


def capture(cmd: list[str], timeout_s: float = HARD_TIMEOUT_S) -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               PYTHONPATH=str(ROOT / "src"))
    start = time.perf_counter()
    timed_out = False
    try:
        p = subprocess.run(cmd, capture_output=True, env=env, timeout=timeout_s,
                           check=False)
        out, err, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        out, err, code = exc.stdout or b"", exc.stderr or b"", None
        timed_out = True
    result = {"argv": cmd, "exit": code, "elapsed_s": time.perf_counter() - start,
              "outer_timeout": timed_out, "timeout": timed_out, "attempted": 1,
              "succeeded": 0, "other_error": 0}
    for stream, data in (("stdout", out), ("stderr", err)):
        result[stream + "_base64"] = base64.b64encode(data).decode("ascii")
        result[stream + "_sha256"] = hashlib.sha256(data).hexdigest()
        result[stream + "_bytes"] = len(data)
        try:
            result[stream] = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            result["decode_error"] = str(exc)
    if not timed_out:
        try:
            if "decode_error" in result:
                raise ValueError("not UTF-8")
            body = json.loads(result["stdout"] if code == 0 else result["stderr"])
            if code == 0:
                result["value"] = body
                result["succeeded"] = 1
            else:
                result["error"] = body
                result["timeout"] = (isinstance(body, dict)
                                     and body.get("message") == "query_budget_exceeded")
        except (ValueError, KeyError) as exc:
            result["error"] = {"message": "invalid JSON output", "detail": str(exc)}
    result["other_error"] = int(not result["succeeded"] and not result["timeout"])
    return result


def diff(a, b, path="$"):
    problems = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                problems.append({"path": f"{path}.{key}", "kind": "missing_key"})
            else:
                problems.extend(diff(a[key], b[key], f"{path}.{key}"))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            problems.append({"path": path, "kind": "length", "python": len(a), "rust": len(b)})
        for i, (x, y) in enumerate(zip(a, b)):
            problems.extend(diff(x, y, f"{path}[{i}]"))
    elif type(a) is not type(b) or a != b:
        problems.append({"path": path, "kind": "value", "python": a, "rust": b})
    return problems


def check_expect(value: dict, expect: dict) -> list[dict]:
    problems = []
    if not isinstance(value, dict):
        return [{"kind": "invalid_success_json_shape"}]
    for name in ("candidates", "relations", "warnings"):
        if name in value and (not isinstance(value[name], list) or
                              (name == "candidates" and any(not isinstance(c, dict) for c in value[name]))):
            return [{"kind": "invalid_response_field_shape", "field": name}]
    for key, want in expect.items():
        if key == "n_candidates":
            got = len(value.get("candidates") or [])
        elif key == "n_relations":
            got = len(value.get("relations") or [])
        elif key.startswith("first_candidate_"):
            first = (value.get("candidates") or [{}])[0]
            got = first.get("entry_key" if key == "first_candidate_key" else "matched_by")
        else:
            got = value.get(key)
        if got != want:
            problems.append({"path": key, "kind": "expect", "want": want, "got": got})
    return problems


def python_cmd(op: str, args: dict) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--python-child",
            str(DB), op, json.dumps(args, ensure_ascii=True)]


def run_case(case, bin_path: Path) -> dict:
    cid, op, args, expect, mode = case
    entry = {"case_id": cid, "op": op, "args": args, "expect": expect, "mode": mode}
    if mode not in ("cli", "runtime_error"):
        py = capture(python_cmd(op, args))
        rs = capture([str(bin_path)] + rust_argv(op, args))
        entry.update(classify(py, rs, mode, expect, diff, check_expect))
    else:
        def subst(argv):
            return [str(DB) if a == "DB" else
                    str(DB.parent / "missing-parity-input.sqlite") if a == "DB_MISSING"
                    else a for a in argv]
        py = capture([sys.executable, "-c", ("import sys; from sakura_knowledge.cli import main; "
                      "sys.exit(main(sys.argv[1:]))")] + subst(args["argv_py"]))
        rs = capture([str(bin_path)] + subst(args["argv_rs"]))
        problems = []
        for side, rec in (("py", py), ("rs", rs)):
            if rec["timeout"] or rec["exit"] != expect[f"exit_{side}"]:
                problems.append({"kind": "exit_or_timeout", "side": side})
            if rec.get("stdout", ""):
                problems.append({"kind": "stdout_not_empty", "side": side})
            error = rec.get("error", {})
            if not isinstance(error, dict):
                problems.append({"kind": "invalid_error_json_shape", "side": side})
                continue
            for field in ("error", "message"):
                key = f"stderr_{side}_{field}"
                if key in expect and error.get(field) != expect[key]:
                    problems.append({"kind": key, "want": expect[key], "got": error.get(field)})
            if rec.get("decode_error") or not isinstance(error, dict) or "error" not in error:
                problems.append({"kind": "invalid_error_json", "side": side})
        entry.update(status="EXPECTED_ERROR_FAIL" if problems else "EXPECTED_ERROR_PASS",
                     problems=problems, passed=not problems, semantic_compared=False,
                     error_contract_verified=not problems)
    entry.update(python=py, rust=rs)
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--bin", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--warmup-rounds", type=int, choices=range(3), default=0)
    args = ap.parse_args()
    global DB
    DB = Path(args.db).resolve()
    binary, output = Path(args.bin).resolve(), Path(args.out)
    if output.exists():
        raise FileExistsError(f"receipt must use new path: {output}")
    report = {"mode": "formal", "retries": 0, "outer_timeout_s": HARD_TIMEOUT_S,
              "inner_budget_s": 5, "warmup_rounds": args.warmup_rounds,
              "warmup": [], "cases": [], "db_sha256": sha256(DB),
              "rust_bin_sha256": sha256(binary)}
    for _ in range(args.warmup_rounds):
        for case in CASES:
            report["warmup"].append(run_case(case, binary))
    for case in CASES:
        report["cases"].append(run_case(case, binary))
    report["summary"] = summarize(report["cases"], len(CASES))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=True, indent=2)
    print(json.dumps(report["summary"]))
    return 0 if report["summary"]["overall"] == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--python-child":
        DB = Path(sys.argv[2])
        try:
            result = run_python(sys.argv[3], json.loads(sys.argv[4]))
            print(json.dumps(result, ensure_ascii=True))
        except Exception as exc:
            print(json.dumps({"error": type(exc).__name__, "message": str(exc)},
                             ensure_ascii=True), file=sys.stderr)
            raise SystemExit(2) from exc
    else:
        raise SystemExit(main())
