"""Source-external installed-wheel/binary A-C fixtures; retain all child bytes."""
import argparse
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from sakura_knowledge.storage import SCHEMA


def main():
    parser = argparse.ArgumentParser()
    for name in ("python", "rust", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    cases = []
    for sign in ("", "-"):
        num = sign+"1"+"0"*5000
        for ignored in (False, True):
            raw = '"ignored":'+num+',"raw_gender":"simple"' if ignored else '"raw_gender":'+num
            cases.append(("A"+sign+str(ignored), '{"raw":{'+raw+'}}', "fixture", "lookup",
                          "simple" if ignored else None, not ignored, False))
    for name, number, expected, cut in [
        ("decimal", "1."+"0"*2050, 1.0, False),
        ("exponent", "1e+"+"0"*2050, 1.0, False),
        ("overflow", "1e9999", None, True),
        ("underflow", "1e-9999", 0.0, False),
    ]:
        cases.append(("B"+name, '{"raw":{"raw_gender":'+number+'}}', "fixture", "lookup", expected, cut, False))
    cases.extend([("Cnormal", "{}", "fixture", "inspect", None, False, False),
                  ("Chuge", "{}", "s"*600000, "inspect", None, False, True)])
    python_code = ("import sys,json;from sakura_knowledge.api import Knowledge\n"
                   "try:\n with Knowledge(sys.argv[1]) as k:\n"
                   "  v=k.inspect() if sys.argv[2]=='inspect' else k.lookup('hero')\n"
                   " print(json.dumps(v,ensure_ascii=False,separators=(',',':')))\n"
                   "except ValueError as e:\n"
                   " print(json.dumps({'error':'ValueError','message':str(e)}),file=sys.stderr);sys.exit(2)")
    records, results = [], []
    with tempfile.TemporaryDirectory(prefix="sknow-abc-artifacts-") as folder:
        for name, payload, snapshot, op, expected, cut, error in cases:
            db = Path(folder)/(name+".sqlite")
            conn = sqlite3.connect(db)
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO sources VALUES('fixture','{}')")
            conn.executemany("INSERT INTO build_meta VALUES(?,?)", [("contract_version", "2"),
                             ("search_text_version", "2"), ("snapshot", snapshot)])
            conn.execute("INSERT INTO entries(id,kind,namespace,value) VALUES(1,'page','fixture','hero')")
            conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                         "VALUES(1,'fixture','proof','source_backed',?)", (payload,))
            conn.commit()
            conn.close()
            commands = [[str(args.python.resolve()), "-c", python_code, str(db), op],
                        [str(args.rust.resolve()), op, str(db)] + (["hero"] if op == "lookup" else [])]
            values = []
            for command in commands:
                proc = subprocess.run(command, cwd=folder, env=env, capture_output=True, timeout=15, check=False)
                record = {"case": name, "argv": command, "cwd": folder, "exit": proc.returncode}
                for stream, data in (("stdout", proc.stdout), ("stderr", proc.stderr)):
                    record[stream] = data.decode("utf-8", errors="strict")
                    record[stream+"_base64"] = base64.b64encode(data).decode("ascii")
                    record[stream+"_sha256"] = hashlib.sha256(data).hexdigest()
                records.append(record)
                valid = proc.returncode == (2 if error else 0)
                value = json.loads(proc.stderr if error else proc.stdout) if valid else None
                if valid and error:
                    valid = value == {"error": "ValueError", "message": "response_budget_exceeded"} and not proc.stdout
                elif valid and op == "lookup":
                    field = value["source_fields"]["raw_gender"][0]
                    valid = field["value"] == expected and field["truncated"] == cut and field["value_state"] == "present"
                elif valid:
                    valid = value["snapshot"] == snapshot and len(proc.stdout) <= 524289
                record["passed"] = valid
                values.append(value)
            results.append({"case": name, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                            "passed": all(r["passed"] for r in records[-2:]) and values[0] == values[1]})
    output = {"status": "PASS" if all(r["passed"] for r in results) else "FAIL", "pairs": results,
              "records": records, "scope": "synthetic source-external A-C fixtures; installed wheel and standalone binary"}
    with args.out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(output, handle, indent=2)
    print(json.dumps({"status": output["status"], "pairs": len(results)}))
    return 0 if output["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
