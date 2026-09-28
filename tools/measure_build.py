"""Measure a single real build with isolated process peak RSS and elapsed time.

Result receipt is saved even when build fails, and contains exact exit status.
No source snapshots are modified; build output must not pre-exist.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from sakura_knowledge.storage import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if args.output.exists() or args.receipt.exists():
        raise FileExistsError("build output or receipt exists; will not overwrite")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "sakura_knowledge.cli", "build",
               str(args.manifest.resolve()), str(args.output.resolve())]
    log = args.receipt.with_suffix(".stdout.log")
    started = datetime.now(UTC).isoformat()
    beginning = time.perf_counter()
    with log.open("x", encoding="utf-8") as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        process = psutil.Process(child.pid)
        peak = 0
        while child.poll() is None:
            try:
                peak = max(peak, process.memory_info().rss)
            except psutil.NoSuchProcess:
                pass
            time.sleep(0.1)
        exit_code = child.wait()
    report = {"command": command, "source_commit": args.source_commit,
              "manifest_sha256": digest(args.manifest), "started_at_utc": started,
              "completed_at_utc": datetime.now(UTC).isoformat(),
              "elapsed_seconds": round(time.perf_counter() - beginning, 3),
              "peak_rss_bytes": peak, "exit_code": exit_code,
              "output_path": str(args.output.resolve()), "log_path": str(log.resolve())}
    args.receipt.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
