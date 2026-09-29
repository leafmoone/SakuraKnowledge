"""P2 delivery: wheel CLI run in an isolated venv + Rust binary run from
outside the source tree, with a hash manifest (review items 3 + 4).

Both runtimes execute the same CLI command matrix against the frozen
snapshot: help, lookup, search, related, ask, and a validation-error
command. argv, stdout, stderr and exit code are recorded verbatim.

Artifacts (wheel, distribution dir, venv) are untracked on purpose;
this receipt + the hash manifest (reports/P2) are the committed evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], env: dict | None = None) -> dict:
    t0 = time.monotonic()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       check=False, env=env)
    return {"argv": cmd, "exit": p.returncode,
            "elapsed_s": round(time.monotonic() - t0, 3),
            "stdout": p.stdout, "stderr": p.stderr}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--rs-bin", required=True,
                    help="rust binary to copy into the distribution dir")
    ap.add_argument("--dist", required=True)
    ap.add_argument("--venv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    db = Path(args.db).resolve()
    wheel = Path(args.wheel).resolve()
    rs_bin = Path(args.rs_bin).resolve()
    dist = Path(args.dist).resolve()
    venv = Path(args.venv).resolve()

    rep: dict = {
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "snapshot": {"path": str(db), "sha256": sha256(db)},
        "code_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                   capture_output=True, text=True,
                                   check=False).stdout.strip(),
    }

    # ---------------- wheel + isolated venv ------------------------------
    rep["wheel"] = {"path": str(wheel), "sha256": sha256(wheel)}
    if venv.exists():
        shutil.rmtree(venv)
    v = subprocess.run([sys.executable, "-m", "venv", "--without-pip",
                        str(venv)], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", check=False)
    rep["venv_created"] = {"cmd": [sys.executable, "-m", "venv",
                                   "--without-pip", str(venv)], "exit": v.returncode}
    if v.returncode != 0:
        rep["venv_created"]["stderr"] = v.stderr
    # bootstrap pip inside the isolated venv from the system ensurepip only
    vp = venv / "Scripts" / "python.exe"
    b = subprocess.run([str(vp), "-m", "ensurepip", "--default-pip"],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    i = subprocess.run([str(vp), "-m", "pip", "install", "--no-index",
                        "--find-links", str(wheel.parent), str(wheel)],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    rep["wheel_installed"] = {"ensurepip_exit": b.returncode,
                              "pip_install_exit": i.returncode,
                              "pip_stderr_tail": i.stderr.strip()[-400:]}
    ver = subprocess.run([str(vp), "-m", "pip", "show", "sakura-knowledge"],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    rep["wheel_installed"]["pip_show"] = ver.stdout.strip()
    rep["executor"] = {
        "python": vp.read_text(encoding="utf-8", errors="replace") and str(vp),
        "python_version": subprocess.run(
            [str(vp), "--version"], capture_output=True, text=True,
            encoding="utf-8", check=False).stdout.strip(),
        "system_python": sys.version.split()[0],
        "isolation": "fresh venv, --without-pip, installed only the wheel",
    }

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    sknow = [str(venv / "Scripts" / "sknow.exe")]
    commands = [
        ["help", sknow + ["--help"]],
        ["help_short", sknow + ["-h"]],
        ["lookup", sknow + ["lookup", str(db), "975"]],
        ["lookup_key", sknow + ["lookup", str(db), "1", "--key",
                                "--kind", "subject", "--namespace", "bangumi.subject"]],
        ["search", sknow + ["search", str(db), "heavy", "--limit", "10"]],
        ["related", sknow + ["related", str(db), "1", "--kind", "subject",
                             "--namespace", "bangumi.subject", "--limit", "10"]],
        ["ask", sknow + ["ask", str(db), "975 的标签是什么"]],
        ["ask_danbooru", sknow + ["ask", str(db), "碧蓝航线:响 的 Danbooru tag 是什么"]],
        ["error_topk", sknow + ["search", str(db), "one piece", "--limit", "0"]],
        ["error_missing_db", sknow + ["lookup", str(ROOT / "no_such.db"), "x"]],
        ["error_unknown_op", sknow + ["frobnicate"]],
    ]
    wheel_results = {}
    for name, cmd in commands:
        r = run(cmd, env)
        if len(r["stdout"]) > 4000:
            r["stdout"] = r["stdout"][:4000] + f"...[truncated {len(r['stdout'])} bytes]"
        if len(r["stderr"]) > 2000:
            r["stderr"] = r["stderr"][:2000] + f"...[truncated {len(r['stderr'])} bytes]"
        wheel_results[name] = r
    rep["wheel_cli"] = wheel_results

    # ---------------- rust distribution outside the source tree ----------
    dist.mkdir(parents=True, exist_ok=True)
    rs_dir = dist / "sknow-rs-0.2.0-win64"
    if rs_dir.exists():
        shutil.rmtree(rs_dir)
    rs_dir.mkdir(parents=True)
    target = rs_dir / "sknow-rs.exe"
    shutil.copy2(rs_bin, target)
    rep["rust_distribution"] = {
        "source_tree_binary": str(rs_bin),
        "distribution_dir": str(rs_dir),
        "outside_source_tree": str(rs_dir) not in str(ROOT / "rust"),
        "binary_sha256": sha256(target),
        "source_sha256_matches": sha256(target) == sha256(rs_bin),
    }
    rust_results = {}
    for name, cmd in commands:
        r = run([str(target) if c.endswith("sknow.exe") else c for c in cmd], env)
        if len(r["stdout"]) > 4000:
            r["stdout"] = r["stdout"][:4000] + f"...[truncated {len(r['stdout'])} bytes]"
        if len(r["stderr"]) > 2000:
            r["stderr"] = r["stderr"][:2000] + f"...[truncated {len(r['stderr'])} bytes]"
        rust_results[name] = r
    rep["rust_cli"] = rust_results

    # toolchain evidence
    for tool in ("rustc", "cargo"):
        p = subprocess.run([tool, "--version"], capture_output=True, text=True,
                           encoding="utf-8", check=False)
        rep.setdefault("toolchain", {})[tool] = (p.stdout.strip()
                                                 if p.returncode == 0 else "NOT_FOUND")
    g = subprocess.run(["gcc", "--version"], capture_output=True, text=True,
                       encoding="utf-8", check=False)
    rep["toolchain"]["gcc"] = g.stdout.strip().splitlines()[0] if g.returncode == 0 else "NOT_FOUND"

    # ---------------- hash manifest ---------------------------------------
    manifest = {
        "created_at_utc": rep["started_at_utc"],
        "snapshot_sha256": rep["snapshot"]["sha256"],
        "code_sha": rep["code_sha"],
        "artifacts": {
            "wheel": {"path": str(wheel), "sha256": rep["wheel"]["sha256"]},
            "rust_binary": {"path": str(target),
                            "sha256": rep["rust_distribution"]["binary_sha256"]},
        },
    }
    man_path = ROOT / "reports" / "P2" / "p2-artifact-manifest.json"
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    rep["manifest_path"] = str(man_path)

    # ---------------- expectations -----------------------------------------
    exp = {
        "help": 0, "help_short": 0, "lookup": 0, "lookup_key": 0, "search": 0,
        "related": 0, "ask": 0, "ask_danbooru": 0,
        "error_topk": 2, "error_missing_db": 2, "error_unknown_op": 2,
    }
    problems = []
    for side, results in (("wheel", wheel_results), ("rust", rust_results)):
        for name, want in exp.items():
            got = results.get(name, {}).get("exit")
            if got != want:
                problems.append({"side": side, "name": name,
                                 "want_exit": want, "got_exit": got})
        if results.get("error_topk", {}).get("stdout", "").strip():
            problems.append({"side": side, "name": "error_topk",
                             "kind": "stdout_must_be_empty"})
    rep["exit_code_problems"] = problems
    rep["overall"] = "PASS" if not problems else "FAIL"
    rep["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(json.dumps({"overall": rep["overall"], "problems": problems},
                     ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
