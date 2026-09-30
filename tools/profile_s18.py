"""Bounded diagnostic reproduction of legacy S18 SQL, not formal acceptance.

One attempt; no retries. Records actual SQL/EXPLAIN and separates execute,
materialization, identity assembly and serialization; unavailable phases after
budget failure remain NOT_RUN. Does not modify the frozen database.
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path

from sakura_knowledge.api import Knowledge
from sakura_knowledge.model import match_query

SQL = """SELECT e.id,e.kind,e.namespace,e.value,bm25(search_fts),
d.title,substr(d.original,1,4000),length(d.original)>4000,d.source_id,d.evidence_id
FROM search_fts JOIN documents d ON d.id=search_fts.document_id
JOIN entries e ON e.id=search_fts.entry_id WHERE search_fts MATCH ?1
AND e.conflicted=0 AND d.status IN ('generated_from_evidence','source_backed')
AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status IN ('source_backed'))
AND (?2 IS NULL OR e.kind=?2) AND (?3 IS NULL OR e.namespace=?3)
ORDER BY bm25(search_fts),e.kind,e.namespace,e.value,search_fts.rowid LIMIT 10001"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    query = "a's_wonderland"
    match = match_query(query)
    report = {"purpose": "legacy SQL diagnostic, not acceptance", "query": query,
              "topk": 10, "match": match, "sql": SQL, "sqlite": sqlite3.sqlite_version,
              "phases": {}, "attempts": 1, "rows_materialized": 0, "body_utf8_bytes": 0}
    with Knowledge(args.db) as api:
        start = time.perf_counter()
        exact = api.lookup(query)
        report["phases"]["exact_identity_assembly_s"] = time.perf_counter() - start
        report["exact_candidates"] = len(exact["candidates"])
        report["configuration"] = {name: api.conn.execute("PRAGMA " + name).fetchone()[0]
                                   for name in ("page_size", "cache_size", "mmap_size", "temp_store")}
        report["explain"] = [list(r) for r in api.conn.execute("EXPLAIN QUERY PLAN " + SQL,
                                                            (match, None, None))]
        api._budget()
        start = time.perf_counter()
        rows = []
        cursor = None
        try:
            cursor = api._execute(SQL, (match, None, None))
            report["phases"]["fts_execute_sort_first_row_s"] = time.perf_counter() - start
            start = time.perf_counter()
            for row in cursor:
                rows.append(tuple(row))
                report["rows_materialized"] += 1
                report["body_utf8_bytes"] += len(row[6].encode("utf-8"))
            report["fts_status"] = "success"
        except (ValueError, sqlite3.Error) as exc:
            report["fts_status"] = "failure"
            report["error"] = str(exc)
        finally:
            report["phases"]["last_fts_phase_s"] = time.perf_counter() - start
            if cursor:
                cursor.close()
        report["rows_returned_before_error"] = len(rows)
        report["post_fts_assembly"] = "NOT_RUN" if report["fts_status"] != "success" else "diagnostic"
        if report["fts_status"] == "success":
            start = time.perf_counter()
            seen = {tuple(c["entry_key"].values()) for c in exact["candidates"]}
            chosen = []
            for row in rows:
                key = (row[1], row[2], row[3])
                if key not in seen:
                    seen.add(key)
                    chosen.append(api.lookup(key=dict(zip(("kind", "namespace", "value"), key))))
                    if len(seen) >= 10:
                        break
            report["phases"]["selected_identity_assembly_s"] = time.perf_counter() - start
            start = time.perf_counter()
            data = json.dumps(chosen, ensure_ascii=False).encode("utf-8")
            report["phases"]["json_serialization_s"] = time.perf_counter() - start
            report["selected_identities"] = len(chosen)
            report["serialized_bytes"] = len(data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=True)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
