"""Check new artifacts from a source-tree-external directory and clean env."""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for b in iter(lambda: stream.read(4*1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    for name in ("python", "rust", "wheel", "db", "out"):
        ap.add_argument("--"+name, type=Path, required=True)
    ap.add_argument("--source-sha", required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    records = []
    with tempfile.TemporaryDirectory(prefix="sknow-repair-cli-") as external:
        def run(cmd, expected=0):
            p = subprocess.run(cmd, cwd=external, env=env, capture_output=True, timeout=30, check=False)
            rec = {"argv": cmd, "cwd": external, "exit": p.returncode, "expected_exit": expected}
            for stream, raw in (("stdout", p.stdout), ("stderr", p.stderr)):
                rec[stream] = raw.decode("utf-8", errors="strict")
                rec[stream+"_base64"] = base64.b64encode(raw).decode("ascii")
                rec[stream+"_sha256"] = hashlib.sha256(raw).hexdigest()
            rec["passed"] = p.returncode == expected
            records.append(rec)
            return rec
        probe = run([str(args.python.resolve()), "-c",
                     ("import sys,json,sakura_knowledge;print(json.dumps(dict("
                      "module=sakura_knowledge.__file__,encoding=sys.stdout.encoding,"
                      "utf8=sys.flags.utf8_mode)))")])
        measured = json.loads(probe["stdout"])
        cases = [("lookup", "975"), ("lookup", "加特"), ("search", "a's_wonderland"),
                 ("ask", "介绍一下 加特"), ("ask", "加特 的标签是什么"),
                 ("ask", "975 的 Danbooru tag 是什么"), ("lookup", "不存在的实体九二七幺")]
        pairs = []
        prefixes = [[str(args.python.resolve()), "-c",
                     "from sakura_knowledge.cli import main;raise SystemExit(main())"],
                    [str(args.rust.resolve())]]
        for op, query in cases:
            argv = [op, str(args.db.resolve())] + ([query] if query is not None else [])
            results = [run(prefix+argv+(["--limit" if i == 0 else "--topk", "10"]
                                       if op == "search" else []))
                       for i, prefix in enumerate(prefixes)]
            equal = all(r["passed"] for r in results) and json.loads(results[0]["stdout"]) == json.loads(results[1]["stdout"])
            pairs.append({"op": op, "query": query, "full_json_equal": equal})
        for i, prefix in enumerate(prefixes):
            run(prefix+["--help"])
            missing = run(prefix+["lookup"], 2)
            missing["passed"] &= json.loads(missing["stderr"])["error"] == "UsageError"
            invalid = run(prefix+["search", str(args.db.resolve()), "x",
                                  "--limit" if i == 0 else "--topk", "0"], 2)
            invalid["passed"] &= json.loads(invalid["stderr"])["message"] == "topk must be 1..100"
        related_py = prefixes[0]+["related", str(args.db.resolve()), "975", "--key",
                                   "--kind", "character", "--namespace", "bangumi.character"]
        related_rs = prefixes[1]+["related", str(args.db.resolve()), "character", "bangumi.character", "975"]
        related = [run(related_py), run(related_rs)]
        pairs.append({"op": "related", "query": "bangumi.character/975", "full_json_equal":
                      all(r["passed"] for r in related) and
                      json.loads(related[0]["stdout"]) == json.loads(related[1]["stdout"])})
        report = {"artifact_source_sha": args.source_sha,
                  "wheel": {"path": str(args.wheel), "sha256": digest(args.wheel)},
                  "rust": {"path": str(args.rust), "sha256": digest(args.rust)},
                  "environment": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONPATH": "removed"},
                  "measured": measured, "pairs": pairs, "records": records}
        passed = (all(r["passed"] for r in records) and all(p["full_json_equal"] for p in pairs)
                  and measured["utf8"] == 1 and measured["encoding"].lower() == "utf-8"
                  and "site-packages" in measured["module"])
        report["status"] = "PASS" if passed else "FAIL"
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
        print(json.dumps({"status": report["status"], "pairs": pairs}, ensure_ascii=True))
        return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
