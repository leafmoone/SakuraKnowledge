"""Single-shot S18 full JSON diagnosis/receipt after independent fixtures.

Not a replacement for the required full formal parity or 30-sample performance.
"""
import argparse
import json
import time
from pathlib import Path

from check_parity import capture, diff

from sakura_knowledge.api import Knowledge
from sakura_knowledge.model import match_query
from sakura_knowledge.search import SQL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--probe", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    start = time.perf_counter()
    with Knowledge(args.db) as api:
        opened = time.perf_counter() - start
        start = time.perf_counter()
        value = api.search("a's_wonderland", topk=10)
        elapsed = time.perf_counter() - start
        start = time.perf_counter()
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        serialized = time.perf_counter() - start
        py = {"value": value, "open_s": opened, "search_s": elapsed,
              "serialization_s": serialized, "response_bytes": len(raw),
              "profile": api.last_search_profile}
        explain = [list(r) for r in api.conn.execute("EXPLAIN QUERY PLAN " + SQL,
                    (match_query("a's_wonderland"), None, None))]
    rs = capture([str(args.probe.resolve()), str(args.db.resolve())])
    problems = diff(value, rs["value"]["value"]) if "value" in rs else [{"rust_failure": rs}]
    receipt = {"mode": "single_shot_diagnostic", "retries": 0, "query": "a's_wonderland",
               "topk": 10, "match": match_query("a's_wonderland"), "sql": SQL,
               "python_explain": explain, "python": py, "rust": rs,
               "full_json_problems": problems,
               "status": "EQUAL" if not problems else "FAIL"}
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=True, indent=2)
    print(json.dumps({"status": receipt["status"], "python_search_s": elapsed,
                      "rust_search_s": rs.get("value", {}).get("search_s"),
                      "problems": problems}, ensure_ascii=True))
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
