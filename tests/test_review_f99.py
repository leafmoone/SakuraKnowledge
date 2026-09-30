"""Independent regression expectations for the nine f99a115 review findings.

Synthetic fixtures only; never write the production snapshot.
"""
import json
import sqlite3
import subprocess
import sys
import time

import pytest
from test_core import manifest, record
from test_rust_repair import binary as rust_binary_fixture
from test_rust_repair import invoke

from sakura_knowledge.api import Knowledge
from sakura_knowledge.storage import build

binary = rust_binary_fixture


def snapshot(tmp_path, rows):
    build(manifest(tmp_path, rows), tmp_path / "fixture")
    return tmp_path / "fixture" / "knowledge.sqlite"


@pytest.mark.parametrize("query", ["a・b", "a\u3099b", "a" * 256 + "・"])
def test_r2_separator_tokens_match_and_nonempty_fts(binary, tmp_path, query):
    from sakura_knowledge.model import match_query, tokens
    expected = ["a", "b"] if len(query) < 10 else ["a" * 256]
    assert tokens(query) == expected
    probe = binary.parent / "examples" / "text_probe.exe"
    proc = subprocess.run([str(probe)], input=(json.dumps(query)+'\n').encode(),
                          capture_output=True, timeout=15, check=False)
    actual = json.loads(proc.stdout)["result"]
    assert actual == {"tokens": expected, "match": match_query(query)}
    db = snapshot(tmp_path, [record("page", "fixture.page", "proof", expected[0])])
    with Knowledge(db) as api:
        wanted = api.search(query)
    got = invoke(binary, "search", db, query)
    assert got["candidates"][0]["entry_key"]["value"] == "proof"
    assert got == wanted


@pytest.mark.parametrize("control", [chr(c) for c in range(0x1c, 0x20)])
@pytest.mark.parametrize("template", ["介绍一下 hero{}", "hero{} 的标签是什么"])
def test_r3_control_whitespace_subject(binary, tmp_path, control, template):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero", "description")])
    q = template.format(control)
    with Knowledge(db) as api:
        expected = api.ask(q)
    actual = invoke(binary, "ask", db, q)
    assert actual["parsed_subject"] == "hero"
    assert actual == expected


@pytest.mark.parametrize("variant", ["deep_ignored", "huge_integer", "normal_numbers"])
def test_r5_legal_raw_scalar_projection(binary, tmp_path, variant):
    row = record("page", "fixture.page", "hero", "description")
    raw = {"raw_gender": 42}
    if variant == "deep_ignored":
        nested = "ignored"
        for _ in range(130):
            nested = [nested]
        raw["not_a_projected_field"] = nested
    elif variant == "huge_integer":
        raw["raw_gender"] = 10 ** 2100
    else:
        raw["raw_attributes"] = [0, -5, 1.25, True, None]
    row["raw"] = raw
    db = snapshot(tmp_path, [row])
    with Knowledge(db) as api:
        expected = api.lookup("hero")
    actual = invoke(binary, "lookup", db, "hero")
    assert actual == expected
    obs = actual["source_fields"]["raw_gender"][0]
    if variant == "huge_integer":
        assert obs["value"] is None and obs["truncated"]
    else:
        assert obs["value"] == 42 and not obs["truncated"]


@pytest.mark.parametrize("reverse", [False, True])
def test_r5_field_after_identity_display_cap(binary, tmp_path, reverse):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero", "description")])
    with sqlite3.connect(db) as conn:
        eid = conn.execute("SELECT id FROM entries WHERE value='hero'").fetchone()[0]
        conn.execute("DELETE FROM entry_evidence WHERE entry_id=?", (eid,))
        indexes = list(range(101))
        for n in reversed(indexes) if reverse else indexes:
            payload = {"raw": {"raw_gender": "field101"}} if n == 100 else {}
            conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                         "VALUES(?,'fixture-v1',?,'source_backed',?)", (eid, f"p{n:03d}", json.dumps(payload)))
    conn.close()
    with Knowledge(db) as api:
        expected = api.lookup("hero")
    actual = invoke(binary, "lookup", db, "hero")
    assert actual == expected
    # Either actually retrieve the field, or explicitly mark incompleteness.
    assert (actual["source_fields"].get("raw_gender") or
            "raw_gender" in actual["source_fields_truncated"])


def test_r6_fake_fts_table_rejected(binary, tmp_path):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero")])
    with sqlite3.connect(db) as conn:
        conn.executescript("DROP TABLE search_fts; CREATE TABLE search_fts("
                           "text,document_id,entry_id,search_fts TEXT DEFAULT 'using fts5');")
    conn.close()
    with pytest.raises(ValueError, match="FTS|fts"):
        Knowledge(db)
    proc = subprocess.run([str(binary), "inspect", str(db)], capture_output=True, timeout=15, check=False)
    assert proc.returncode == 2 and proc.stdout == b""


def test_r1_inspect_final_deadline(tmp_path, monkeypatch):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero")])
    with Knowledge(db) as api:
        execute = api._execute

        def expired_after_last_statement(sql, parameters=()):
            result = execute(sql, parameters)
            if "SELECT key,value FROM build_meta" in sql:
                api._deadline = time.monotonic() - 1
            return result

        monkeypatch.setattr(api, "_execute", expired_after_last_statement)
        with pytest.raises(ValueError, match="query_budget_exceeded"):
            api.inspect()


def test_r1_error_path_checks_same_deadline(tmp_path, monkeypatch):
    import sakura_knowledge.api as module
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero")])
    with Knowledge(db) as api:
        def expired_bounds(*_args, **_kwargs):
            api._deadline = time.monotonic() - 1
            raise ValueError("response_budget_exceeded")

        monkeypatch.setattr(module, "bound_response", expired_bounds)
        with pytest.raises(ValueError, match="query_budget_exceeded"):
            api.lookup("hero")


@pytest.mark.parametrize("runtime", ["python", "rust"])
def test_r1_huge_titles_many_candidates_bounded_before_serialization(binary, tmp_path, runtime):
    rows = []
    for i in range(100):
        row = record("page", "fixture.page", f"hero{i:03d}", "small body")
        row["aliases"] = [{"text": "shared", "status": "source_backed"}]
        row["documents"][0]["title"] = "x" * 300000
        rows.append(row)
    db = snapshot(tmp_path, rows)
    cmd = ([str(binary), "search", str(db), "shared", "--topk", "1"] if runtime == "rust" else
           [sys.executable, "-c", "from sakura_knowledge.cli import main;raise SystemExit(main())",
            "search", str(db), "shared", "--limit", "1"])
    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
    elapsed = time.monotonic()-start
    assert elapsed < 5.5
    assert proc.returncode == 0, proc.stderr
    value = json.loads(proc.stdout)
    assert len(value["candidates"]) == 1
    assert len(proc.stdout) <= 524289
    assert value["candidates"][0]["descriptions"][0]["title_truncated"]


@pytest.mark.parametrize("number,changed", [(-(2**63), False), (2**64-1, False),
                                             (-(2**63)-1, True), (2**64, True),
                                             (0, False), (1.25, False), (True, False),
                                             (None, False)])
def test_r5_scalar_domain_independent(binary, tmp_path, number, changed):
    row = record("page", "fixture.page", "hero")
    row["raw"] = {"raw_gender": number}
    db = snapshot(tmp_path, [row])
    with Knowledge(db) as api:
        python = api.lookup("hero")
    rust = invoke(binary, "lookup", db, "hero")
    for value in (python, rust):
        observed = value["source_fields"]["raw_gender"][0]
        assert observed["value"] == (None if changed else number)
        assert observed["truncated"] == changed
    assert python == rust


@pytest.mark.parametrize("query", ["介绍一下 hero\u200b", "hero\u200b 的标签是什么"])
def test_r3_non_whitespace_not_stripped(binary, tmp_path, query):
    db = snapshot(tmp_path, [record("page", "fixture.page", "hero")])
    with Knowledge(db) as api:
        expected = api.ask(query)
    actual = invoke(binary, "ask", db, query)
    assert actual["parsed_subject"] == "hero\u200b"
    assert actual["status"] == "unknown"
    assert actual == expected


def test_r1_field_and_serialization_deadline_checks():
    from sakura_knowledge.response import bound_response, bounded_value

    def expired():
        raise ValueError("query_budget_exceeded")

    for action in (lambda: bounded_value([1], check=expired),
                   lambda: bound_response({"candidates": []}, check=expired)):
        with pytest.raises(ValueError, match="query_budget_exceeded"):
            action()
