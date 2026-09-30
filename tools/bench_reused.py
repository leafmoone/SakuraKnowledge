"""One Python Knowledge object/connection for a JSON-lines request stream."""
import json
import sqlite3
import sys
import time

from sakura_knowledge.api import Knowledge

start = time.perf_counter()
with Knowledge(sys.argv[1]) as api:
    opened = time.perf_counter() - start
    for line in sys.stdin:
        request = json.loads(line)
        start = time.perf_counter()
        try:
            options = {"topk": 10} if request["op"] == "search" else {}
            result = getattr(api, request["op"])(request["query"], **options)
            elapsed = time.perf_counter() - start
            start = time.perf_counter()
            output = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            rec = {"api_s": elapsed, "serialization_s": time.perf_counter() - start,
                   "open_s": opened, "output": output, "exit": 0}
        except (ValueError, sqlite3.Error) as exc:
            rec = {"api_s": time.perf_counter() - start, "open_s": opened,
                   "error": str(exc), "exit": 2}
        print(json.dumps(rec, ensure_ascii=True), flush=True)
