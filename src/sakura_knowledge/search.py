"""Lightweight rank stream with deterministic tie groups, no document bodies."""
SQL = """SELECT e.id,e.kind,e.namespace,e.value,e.locator,
search_fts.rank AS score,d.id AS document_id,search_fts.rowid AS fts_rowid
FROM search_fts JOIN documents d ON d.id=search_fts.document_id
JOIN entries e ON e.id=search_fts.entry_id WHERE search_fts MATCH ?1
AND e.conflicted=0 AND d.status IN ('generated_from_evidence','source_backed')
AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed')
AND (?2 IS NULL OR e.kind=?2) AND (?3 IS NULL OR e.namespace=?3)
ORDER BY search_fts.rank LIMIT 10001"""


# Selective filters should reject rows before ranking instead of ordering all
# corpus postings only to discard them. Still no bodies in the sort payload.
FILTERED_SQL = SQL.replace("search_fts.rank AS score", "bm25(search_fts) AS score").replace(
    "ORDER BY search_fts.rank", "ORDER BY score,e.kind,e.namespace,e.value,search_fts.rowid").replace(
    "FROM search_fts JOIN documents d ON d.id=search_fts.document_id\n"
    "JOIN entries e ON e.id=search_fts.entry_id",
    "FROM search_fts CROSS JOIN entries e ON e.id=search_fts.entry_id\n"
    "CROSS JOIN documents d ON d.id=search_fts.document_id")


# FTS5 can stream rank order without sorting the whole filtered result. At the
# scan cap callers retry FILTERED_SQL to preserve its historical tie subset.
FILTERED_STREAM_SQL = FILTERED_SQL.replace("bm25(search_fts) AS score", "search_fts.rank AS score").replace(
    "WHERE search_fts MATCH ?1", "WHERE search_fts MATCH ?1 AND rank MATCH 'bm25()'").replace(
    "ORDER BY score,e.kind,e.namespace,e.value,search_fts.rowid", "ORDER BY search_fts.rank")


def identity(row):
    return row["kind"], row["namespace"], row["value"]


def tie_key(row):
    return (*identity(row), row["fts_rowid"])


def select_rows(rows, seen, limit, check_deadline):
    """Consume complete equal-score groups; retain at most limit lightweight
    rows. The lookahead row detects the next score. At the scan cap mark the
    result explicitly incomplete (never silently call an incomplete tie exact).
    """
    chosen, group = [], {}
    score = None
    scanned = 0
    truncated = False
    for row in rows:
        check_deadline()
        scanned += 1
        if scanned > 10000:
            truncated = True
            break
        if score is not None and row["score"] != score:
            chosen.extend(sorted(group.values(), key=tie_key))
            seen.update(group)
            group = {}
            if len(chosen) >= limit:
                break
        score = row["score"]
        key = identity(row)
        if key in seen:
            continue
        if key not in group or tie_key(row) < tie_key(group[key]):
            group[key] = row
        if len(group) > limit - len(chosen):
            worst = max(group, key=lambda k: tie_key(group[k]))
            del group[worst]
    if len(chosen) < limit:
        chosen.extend(sorted(group.values(), key=tie_key))
    return chosen[:limit], scanned, truncated
