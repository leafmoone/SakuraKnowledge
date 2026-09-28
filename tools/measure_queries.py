"""Measure real-snapshot query latency, budget failures and peak RSS.

Read-only: opens the snapshot immutable, never rewrites it. Each workload
runs a warm-up call, then repeated calls; per-operation timings (ms) are
reported with p50/p95/max. Budget failures are counted, not hidden.
"""
import argparse
import json
import statistics
import time
from pathlib import Path

import psutil

from sakura_knowledge.api import Knowledge
from sakura_knowledge.model import EntryKey


def percentiles(values):
    if not values:
        return {}
    values = sorted(values)
    return {"p50_ms": statistics.median(values),
            "p95_ms": values[max(0, int(len(values) * 0.95) - 1)],
            "max_ms": values[-1], "n": len(values)}


def timed(fn, repetitions=5):
    try:
        fn()  # warm-up
    except ValueError:
        pass
    samples, failures = [], 0
    for _ in range(repetitions):
        begin = time.perf_counter()
        try:
            fn()
            samples.append((time.perf_counter() - begin) * 1000)
        except ValueError as exc:
            if "query_budget_exceeded" in str(exc):
                failures += 1
    return samples, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    process = psutil.Process()
    peak = process.memory_info().rss
    result = {"database": str(args.database.resolve()),
              "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime()),
              "operations": {}, "budget_failures": {}}
    with Knowledge(args.database) as api:
        # Deterministic real CJK two-character query terms from the snapshot's
        # own trusted aliases (console-safe: no hard-coded guesses).
        cjk_terms = [row["text"] for row in api.conn.execute(
            "SELECT text FROM aliases WHERE length(text)=2 AND "
            "text GLOB '*[一-龥]*' ORDER BY text LIMIT 2")]
        if len(cjk_terms) < 2:
            raise SystemExit("expected real CJK alias terms in snapshot")
        def workload(name, fn, reps=5):
            samples, failures = timed(fn, reps)
            result["operations"][name] = percentiles(samples)
            result["budget_failures"][name] = failures
            peak_now = process.memory_info().rss
            nonlocal peak
            peak = max(peak, peak_now)
        workload("ask_local_tag_no_target",
                 lambda: api.ask("!", kind="tag", namespace="local.tag_aggregate"))
        workload("ask_local_tag_target_danbooru",
                 lambda: api.ask("!", kind="tag", namespace="local.tag_aggregate",
                                 target_tag_namespace="danbooru.tag"))
        workload("lookup_exact_key_person",
                 lambda: api.lookup(key=EntryKey("person", "bangumi.person", "1")))
        workload("lookup_by_value_subject",
                 lambda: api.lookup("975", kind="subject", namespace="bangumi.subject"))
        workload("lookup_alias_value_page",
                 lambda: api.lookup("10", kind="page", namespace="danbooru.wiki"))
        result["query_terms"] = {"cjk_first": cjk_terms[0], "cjk_second": cjk_terms[1]}
        workload("search_cjk_two_chars",
                 lambda: api.search(cjk_terms[0]))
        workload("search_cjk_second_two_chars",
                 lambda: api.search(cjk_terms[1]))
        workload("search_english",
                 lambda: api.search("hello"))
        workload("related_high_degree_limit100",
                 lambda: api.related(EntryKey("subject", "bangumi.subject", "975"), limit=100))
        workload("related_high_degree_limit10",
                 lambda: api.related(EntryKey("subject", "bangumi.subject", "975"), limit=10))
        workload("ask_page_no_verified_tag",
                 lambda: api.ask("10", kind="page", namespace="danbooru.wiki"))
    result["peak_rss_bytes"] = peak
    result["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime())
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
