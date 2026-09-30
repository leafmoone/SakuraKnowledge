"""Separate reused-connection API and independent CLI latency, no retries.

>=30 observations per workload/runtime/mode. Concurrent communicate prevents
pipe deadlock; host RSS samples are whole-process peaks, not per-call allocations.
Raw responses, stderr/exit and warmups retained separately. No disk-cold claim.
"""
import argparse
import base64
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

WORKLOADS = [
    {"id": "exact", "op": "lookup", "query": "SCP-3812"},
    {"id": "alias", "op": "lookup", "query": "加特"},
    {"id": "ambiguous", "op": "lookup", "query": "975"},
    {"id": "missing", "op": "lookup", "query": "不存在的实体九二七幺"},
    {"id": "fts_cjk", "op": "search", "query": "孤独摇滚"},
    {"id": "S18", "op": "search", "query": "a's_wonderland"},
    {"id": "introduce", "op": "ask", "query": "介绍一下 加特"},
    {"id": "tag_unmapped", "op": "ask", "query": "加特 的标签是什么"},
]


def run(command, data=None, timeout=15):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    start = time.perf_counter()
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    peaks = []
    stopped = threading.Event()

    def monitor():
        process = psutil.Process(proc.pid)
        while not stopped.is_set():
            try:
                peaks.append(process.memory_info().rss)
            except psutil.Error:
                break
            stopped.wait(0.005)

    watcher = threading.Thread(target=monitor)
    watcher.start()
    timed_out = False
    try:
        out, err = proc.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        out, err = proc.communicate()
    finally:
        stopped.set()
        watcher.join()
    record = {"argv": command, "exit": proc.returncode, "outer_timeout": timed_out,
              "wall_s": time.perf_counter()-start, "rss_peak_bytes": max(peaks, default=None),
              "rss_samples": len(peaks)}
    for stream, value in (("stdout", out), ("stderr", err)):
        record[stream + "_base64"] = base64.b64encode(value).decode("ascii")
        record[stream + "_sha256"] = hashlib.sha256(value).hexdigest()
    return record, out, err


def percentile(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*p)-1)] if values else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--bin", type=Path, required=True)
    ap.add_argument("--reused-bin", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=30)
    args = ap.parse_args()
    if args.samples < 30 or args.out.exists():
        raise ValueError("need >=30 samples and new receipt path")
    db = str(args.db.resolve())
    records, process_receipts = [], []
    requests = [{**work, "round": n, "warmup": n == -1}
                for n in range(-1, args.samples) for work in WORKLOADS]
    data = "".join(json.dumps(r, ensure_ascii=True)+'\n' for r in requests).encode()
    for runtime, cmd in (
        ("python", [sys.executable, str(Path(__file__).with_name("bench_reused.py")), db]),
        ("rust", [str(args.reused_bin.resolve()), db]),
    ):
        receipt, out, _err = run(cmd, data, timeout=600)
        receipt.update(mode="reused_connection", runtime=runtime)
        process_receipts.append(receipt)
        responses = out.decode("utf-8", errors="strict").splitlines()
        for i, request in enumerate(requests):
            result = json.loads(responses[i]) if i < len(responses) else {"exit": None, "error": "missing"}
            records.append({"mode": "reused_connection", "runtime": runtime, **request,
                            **result, "process_exit": receipt["exit"],
                            "process_rss_peak_bytes": receipt["rss_peak_bytes"]})
    for request in requests:
        for runtime in ("python", "rust"):
            prefix = ([sys.executable, "-c", "from sakura_knowledge.cli import main;raise SystemExit(main())"]
                      if runtime == "python" else [str(args.bin.resolve())])
            cmd = prefix + [request["op"], db, request["query"]]
            if request["op"] == "search":
                cmd += ["--topk", "10"]
            rec, out, _err = run(cmd)
            rec.update(mode="independent_cli", runtime=runtime, **request)
            rec["output"] = out.decode("utf-8", errors="strict")
            records.append(rec)
    summary = []
    for mode in ("reused_connection", "independent_cli"):
        for runtime in ("python", "rust"):
            for work in WORKLOADS:
                rows = [r for r in records if r["mode"] == mode and r["runtime"] == runtime
                        and r["id"] == work["id"] and not r["warmup"]]
                good = []
                failures = []
                for row in rows:
                    try:
                        body = json.loads(row.get("output", ""))
                        assert row["exit"] == 0 and not row.get("outer_timeout")
                        assert not any(w in body.get("warnings", []) for w in
                                       ("search_document_scan_limit", "response_budget_truncated"))
                        good.append(row["api_s"] if mode == "reused_connection" else row["wall_s"])
                    except (ValueError, AssertionError):
                        failures.append(row["round"])
                summary.append({"mode": mode, "runtime": runtime, "workload": work["id"],
                                "attempted": len(rows), "success": len(good), "failed_rounds": failures,
                                "p50_s": percentile(good, .5), "p95_s": percentile(good, .95)})
    result = {"mode": "formal_no_retries", "disk_cold": "NOT_CLAIMED",
              "warmup": "one fixed excluded pass per mode/runtime", "samples": args.samples,
              "summary": summary, "records": records, "reused_process_receipts": process_receipts}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=True, separators=(",", ":"))
    print(json.dumps(summary, ensure_ascii=True))
    return int(any(s["success"] != args.samples for s in summary))


if __name__ == "__main__":
    raise SystemExit(main())
