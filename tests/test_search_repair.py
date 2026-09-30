"""R1 rank/duplicate/tie/deadline expected fixtures, not real source facts."""
import time

import pytest
from test_core import manifest, record

from sakura_knowledge.api import Knowledge
from sakura_knowledge.search import select_rows
from sakura_knowledge.storage import build


def hit(name, score, rowid):
    return {"kind": "page", "namespace": "fixture", "value": name,
            "fts_rowid": rowid, "score": score}


def test_tie_order_is_identity_then_document_and_duplicates_collapse():
    rows = [hit("z", -2, 1), hit("a", -2, 4), hit("a", -2, 2),
            hit("b", -2, 8), hit("next", -1, 9)]
    selected, scanned, truncated = select_rows(rows, set(), 2, lambda: None)
    assert [(r["value"], r["fts_rowid"]) for r in selected] == [("a", 2), ("b", 8)]
    assert scanned == 5 and not truncated


def test_scan_cap_marks_incomplete_tie():
    rows = (hit(str(i), -2, i) for i in range(10001))
    selected, scanned, truncated = select_rows(rows, set(), 2, lambda: None)
    assert truncated and scanned == 10001 and len(selected) == 2


def test_exact_sufficient_skips_fts_and_nested_lookup_does_not_renew(tmp_path, monkeypatch):
    build(manifest(tmp_path, [record("page", "fixture", "hero", "hero words")]), tmp_path / "db")
    with Knowledge(tmp_path / "db" / "knowledge.sqlite") as api:
        queries = []
        api.conn.set_trace_callback(queries.append)
        result = api.search("hero", topk=1)
        assert result["candidates"][0]["matched_by"] == "exact"
        assert api.last_search_profile["fts_skipped_exact_sufficient"]
        assert not any("search_fts MATCH" in sql for sql in queries)
        lookup = api.lookup

        def exhausted(*args, **kwargs):
            api._deadline = time.monotonic() - 1
            return lookup(*args, **kwargs)

        monkeypatch.setattr(api, "lookup", exhausted)
        with pytest.raises(ValueError, match="query_budget_exceeded"):
            api.search("hero", topk=10)
        assert api._operation_depth == 0
        monkeypatch.setattr(api, "lookup", lookup)
        assert api.lookup("hero")["status"] == "found"  # next operation resets
