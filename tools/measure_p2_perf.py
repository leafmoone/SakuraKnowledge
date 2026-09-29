"""P2 raw performance samples: Python wheel CLI vs sknow-rs, end-to-end.

Every sample is one process invocation (spawn + open + query + JSON out),
recorded raw to JSONL: case, runtime, round, exit, wall ms, peak RSS,
stderr. There are NO retries: a budget failure is a failure sample and is
counted as such. Round 0 is the cold/first pass and is reported separately
from the warm rounds. Percentiles use nearest-rank (p95 = ceil(0.95 n)).

Read-only against the frozen snapshot; sha256 is checked before and after.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_parity
from parity_cases import CASES


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def py_argv(op: str, args: dict, db: str) -> list[str]:
    """Python CLI surface for the same case (see sakura_knowledge.cli)."""
    if op == "lookup":
        cmd = ["lookup", db, args["query"]]
    elif op == "lookup_key":
        return ["lookup", db, args["value"], "--key", "--kind", args["kind"],
                "--namespace", args["namespace"]]
    elif op == "search":
        cmd = ["search", db, args["query"], "--limit", str(args.get("topk", 20))]
    elif op == "related":
        cmd = ["related", db, args["value"], "--kind", args["kind"],
               "--namespace", args["namespace"], "--limit", str(args.get("limit", 20))]
        if args.get("relation"):
            cmd += ["--relation", args["relation"]]
        return cmd
    elif op == "ask":
        cmd = ["ask", db, args["query"]]
        if args.get("target_tag_namespace"):
            cmd += ["--target-tag-namespace", args["target_tag_namespace"]]
    else:
        raise ValueError(op)
    if args.get("kind"):
        cmd += ["--kind", args["kind"]]
    if args.get("namespace"):
        cmd += ["--namespace", args["namespace"]]
    return cmd


SAMPLE_TIMEOUT_S = 120.0


def measure(cmd: list[str], env: dict, track_rss: bool) -> dict:
    """One bounded sample. Pipes are drained by reader threads while the
    main thread polls for exit (a blocked writer on a full pipe is the
    classic Windows deadlock). Peak RSS is tracked on round 0 only
    (Windows has no per-process peak_wset; sampling max RSS at 5 ms is
    the portable substitute and is what we commit to)."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env)
    chunks: dict[str, bytes] = {}

    def drain(pipe, key: str) -> None:
        buf = bytearray()
        while True:
            b = pipe.read(1 << 16)
            if not b:
                break
            buf += b
        chunks[key] = bytes(buf)

    threads = [threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True)]
    for t in threads:
        t.start()
    peak = 0
    timed_out = False
    while proc.poll() is None:
        if track_rss:
            try:
                peak = max(peak, psutil.Process(proc.pid).memory_info().rss)
            except psutil.NoSuchProcess:
                pass
        if time.perf_counter() - t0 > SAMPLE_TIMEOUT_S:
            proc.kill()
            timed_out = True
            break
        time.sleep(0.005)
    for t in threads:
        t.join(timeout=5)
    out = chunks.get("out", b"")
    err = chunks.get("err", b"")
    wall = (time.perf_counter() - t0) * 1000
    if timed_out:
        return {"exit": -1, "wall_ms": round(wall, 2), "peak_rss_bytes": peak or None,
                "stdout_bytes": len(out), "stdout_sha256": hashlib.sha256(out).hexdigest(),
                "stderr": "sample_timeout_killed", "timeout": True}
    return {"exit": proc.returncode, "wall_ms": round(wall, 2),
            "peak_rss_bytes": peak or None, "stdout_bytes": len(out),
            "stdout_sha256": hashlib.sha256(out).hexdigest(),
            "stderr": err.decode("utf-8", errors="strict").strip()}


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def summarize(samples: list[dict]) -> dict:
    ok = [s["wall_ms"] for s in samples if s["exit"] == 0]
    fails = [s for s in samples if s["exit"] != 0]
    res = {"n": len(samples), "ok": len(ok), "failures": len(fails),
           "failure_messages": sorted({s["stderr"] for s in fails})}
    if ok:
        res.update(p50_ms=pct(ok, 0.50), p95_ms=pct(ok, 0.95),
                   p99_ms=pct(ok, 0.99), max_ms=max(ok), min_ms=min(ok))
    rss = [s["peak_rss_bytes"] for s in samples if s["peak_rss_bytes"]]
    if rss:
        res["peak_rss_max_bytes"] = max(rss)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--py-sknow", required=True, help="wheel-installed sknow.exe")
    ap.add_argument("--rs-bin", required=True)
    ap.add_argument("--rounds", type=int, default=5, help="warm rounds after cold round 0")
    ap.add_argument("--samples-out", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    db = Path(args.db).resolve()
    check_parity.DB = db  # rust_argv reads the module-level DB
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    rep: dict = {"started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "snapshot_sha256_before": sha256(db),
                 "code_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                            capture_output=True, text=True,
                                            check=False).stdout.strip(),
                 "py_sknow": {"path": args.py_sknow},
                 "rs_bin": {"path": args.rs_bin, "sha256": sha256(Path(args.rs_bin))},
                 "method": {"rounds_warm": args.rounds, "cold_round": 0,
                            "retries": 0, "percentile": "nearest-rank",
                            "timing": "end-to-end process wall clock",
                            "sample_timeout_s": SAMPLE_TIMEOUT_S,
                            "rss_tracking": "round 0 only, 5ms poll, max RSS",
                            "budget_s_per_operation": 5},
                 "host": {"cpu_count": psutil.cpu_count(),
                          "ram_bytes": psutil.virtual_memory().total,
                          "platform": sys.platform}}
    cases, excluded = [], []
    for cid, op, a, _, mode in CASES:
        if mode not in ("value", "budget_limited") or op == "inspect":
            continue
        if op == "related" and a.get("kind_filter"):
            # Python CLI has no destination-kind filter; excluded for both
            # runtimes so the comparison stays like-for-like.
            excluded.append({"case_id": cid, "reason": "kind_filter_not_in_python_cli"})
            continue
        cases.append((cid, op, a))
    rep["cases_measured"] = [c[0] for c in cases]
    rep["cases_excluded"] = excluded
    samples = []
    samples_path = Path(args.samples_out)
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    # Warm the page cache once per runtime so rounds measure the query,
    # not the first physical read of the 21.5 GB file. Recorded, not
    # counted as a sample.
    warm = []
    for runtime, cmd in (
            ("python", [args.py_sknow] + py_argv("search", {"query": "heavy", "topk": 5}, str(db))),
            ("rust", [args.rs_bin] + check_parity.rust_argv("search", {"query": "heavy", "topk": 5}))):
        m = measure(cmd, env, track_rss=False)
        warm.append({"runtime": runtime, "cmd": cmd, **m})
    rep["warmup"] = warm

    with open(samples_path, "w", encoding="utf-8", newline="\n") as sf:
        done = 0
        total = (args.rounds + 1) * len(cases) * 2
        for rnd in range(args.rounds + 1):
            for cid, op, a in cases:
                for runtime, cmd in (
                        ("python", [args.py_sknow] + py_argv(op, a, str(db))),
                        ("rust", [args.rs_bin] + check_parity.rust_argv(op, a))):
                    m = measure(cmd, env, track_rss=(rnd == 0))
                    rec = {"round": rnd, "case_id": cid, "op": op, "runtime": runtime,
                           **m}
                    samples.append(rec)
                    sf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    sf.flush()
                    done += 1
                    if done % 50 == 0:
                        print(f"progress {done}/{total}", file=sys.stderr)
    rep["samples_file"] = str(samples_path)
    rep["samples_sha256"] = sha256(samples_path)
    rep["n_samples"] = len(samples)

    summary: dict = {}
    for runtime in ("python", "rust"):
        for phase, rounds in (("cold", {0}), ("warm", set(range(1, args.rounds + 1)))):
            sel = [s for s in samples if s["runtime"] == runtime and s["round"] in rounds]
            summary.setdefault(runtime, {})[phase] = {"all": summarize(sel)}
            for op in sorted({s["op"] for s in sel}):
                summary[runtime][phase][op] = summarize([s for s in sel if s["op"] == op])
    rep["summary"] = summary
    per_case_fail = {}
    for s in samples:
        if s["exit"] != 0:
            per_case_fail.setdefault(f'{s["runtime"]}:{s["case_id"]}', []).append(
                {"round": s["round"], "wall_ms": s["wall_ms"], "stderr": s["stderr"]})
    rep["failures_by_case"] = per_case_fail
    rep["snapshot_sha256_after"] = sha256(db)
    rep["snapshot_unchanged"] = rep["snapshot_sha256_before"] == rep["snapshot_sha256_after"]
    rep["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(json.dumps({"n_samples": len(samples), "failing_case_runtime_pairs":
                      sorted(per_case_fail), "snapshot_unchanged": rep["snapshot_unchanged"]},
                     ensure_ascii=False))
    return 0 if rep["snapshot_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
