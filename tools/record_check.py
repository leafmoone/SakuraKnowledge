"""Record a check's exact streams/exit; never overwrite a receipt."""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def nonnegative_timeout(value):
    value = int(value)
    if value < 0:
        raise argparse.ArgumentTypeError("timeout must be nonnegative (0 disables the deadline)")
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeout", type=nonnegative_timeout, default=300)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.out.exists():
        raise FileExistsError(args.out)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    status = subprocess.check_output(["git", "status", "--porcelain"]).decode()
    start = time.perf_counter()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    effective_timeout = None if args.timeout == 0 else args.timeout
    timeout_policy = {"requested": args.timeout, "effective": effective_timeout,
                      "disabled": args.timeout == 0}
    try:
        p = subprocess.run(command, capture_output=True, timeout=effective_timeout,
                           check=False, env=env)
        code, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        code, out, err = None, exc.stdout or b"", exc.stderr or b""
    record = {"head": head, "working_tree": status, "argv": command, "exit": code,
              "elapsed_s": time.perf_counter() - start, "status": "PASS" if code == 0 else "FAIL",
              "timeout_policy": timeout_policy,
              "encoding_environment": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}}
    for name, data in (("stdout", out), ("stderr", err)):
        record[name + "_base64"] = base64.b64encode(data).decode("ascii")
        record[name + "_sha256"] = hashlib.sha256(data).hexdigest()
        record[name] = data.decode("utf-8", errors="backslashreplace")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=True)
    print(json.dumps(record, ensure_ascii=True))
    return code if code is not None else 124


if __name__ == "__main__":
    raise SystemExit(main())
