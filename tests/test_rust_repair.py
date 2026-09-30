"""Explicit cross-runtime synthetic fixtures; enable with SKNOW_RS_TEST_BIN.

Not real-source validation. Python independent tests establish expected behavior
first; these tests additionally require full recursive JSON equality.
"""
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_core import manifest, record
from test_repair_semantics import intro_db as shared_intro_db

from sakura_knowledge.api import Knowledge
from sakura_knowledge.storage import build

intro_db = shared_intro_db


@pytest.fixture
def binary():
    configured = os.environ.get("SKNOW_RS_TEST_BIN")
    if not configured:
        pytest.skip("Rust fixture integration NOT_RUN: set SKNOW_RS_TEST_BIN explicitly")
    path = Path(configured).resolve()
    assert path.is_file()
    return path


def invoke(binary, *args):
    proc = subprocess.run([str(binary), *map(str, args)], capture_output=True, timeout=15, check=False)
    out = proc.stdout.decode("utf-8", errors="strict")
    err = proc.stderr.decode("utf-8", errors="strict")
    assert proc.returncode == 0, (proc.returncode, err)
    assert err == ""
    return json.loads(out)


@pytest.mark.parametrize("query,status", [
    ("介绍一下 name.", "found"), ("介绍一下 name_(x)", "found"),
    ("介绍一下 hero", "entity_ambiguous"),
    ("介绍一下 literal", "entity_found_tag_unmapped"),
    ("name. 的标签是什么", "entity_found_tag_unmapped"),
    ("介绍一下 absent", "unknown"),
])
def test_introduction_independent_then_full_json(binary, intro_db, query, status):
    with Knowledge(intro_db) as api:
        want = api.ask(query)
    got = invoke(binary, "ask", intro_db, query)
    assert got["status"] == status
    if query in ("介绍一下 name.", "介绍一下 name_(x)", "介绍一下 absent"):
        assert got["mapping_status"] == "not_requested"
        assert got["relations"] == []
    assert got == want


def test_unicode_nonempty_fts_full_json(binary, tmp_path):
    entity = record("page", "fixture.page", "unicode-proof", "Straße ẞ Σ İ ＡＢＣ ｶﾀｶﾅ 中文 é 𐐀")
    build(manifest(tmp_path, [entity]), tmp_path / "db")
    db = tmp_path / "db" / "knowledge.sqlite"
    with Knowledge(db) as api:
        for query in ("STRASSE", "SS", "ς", "i", "abc", "カタカナ", "中文", "é", "𐐨"):
            got = invoke(binary, "search", db, query)
            assert got["candidates"][0]["entry_key"] == entity["key"]
            assert got["candidates"][0]["matched_by"] == "fts"
            assert got == api.search(query)


@pytest.mark.parametrize("version_key", ["contract_version", "search_text_version"])
def test_rust_rejects_unknown_versions(binary, intro_db, version_key):
    with sqlite3.connect(intro_db) as conn:
        conn.execute("UPDATE build_meta SET value='999' WHERE key=?", (version_key,))
    conn.close()
    proc = subprocess.run([str(binary), "lookup", str(intro_db), "hero"],
                          capture_output=True, timeout=15, check=False)
    assert proc.returncode == 2 and proc.stdout == b""
    body = json.loads(proc.stderr)
    assert body["message"] == f"unsupported {version_key}: 999"


@pytest.mark.parametrize("sql,message", [
    ("ALTER TABLE documents RENAME COLUMN original TO wrong", "documents missing original"),
    ("DROP TABLE aliases", "aliases missing"),
    ("DROP TABLE search_fts;CREATE TABLE search_fts(text,document_id,entry_id)", "not FTS5"),
])
def test_rust_rejects_broken_schema(binary, intro_db, sql, message):
    with sqlite3.connect(intro_db) as conn:
        conn.executescript(sql)
    conn.close()
    proc = subprocess.run([str(binary), "lookup", str(intro_db), "hero"],
                          capture_output=True, timeout=15, check=False)
    assert proc.returncode == 2 and proc.stdout == b""
    assert message in json.loads(proc.stderr)["message"]


def test_direct_unicode_tokens_and_match(binary):
    from test_repair_semantics import UNICODE_EXPECTED

    from sakura_knowledge.model import match_query, tokens
    probe = binary.parent / "examples" / "text_probe.exe"
    assert probe.is_file(), "build text_probe example before Rust fixture acceptance"
    cases = [q for q, _ in UNICODE_EXPECTED] + ["a" * 256, "a" * 257, " " * 4096,
                                             " " * 4097, "a " * 257]
    data = "".join(json.dumps(q, ensure_ascii=True) + "\n" for q in cases).encode("utf-8")
    proc = subprocess.run([str(probe)], input=data, capture_output=True, timeout=15, check=False)
    assert proc.returncode == 0 and proc.stderr == b""
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(rows) == len(cases)
    for q, row in zip(cases, rows):
        assert row["runtime"]["unicode_version"] == "16.0.0"
        try:
            expected = {"tokens": tokens(q), "match": match_query(q)}
        except ValueError as exc:
            expected = {"error": str(exc)}
        assert row["result"] == expected


def test_rust_observations_conflicts_null_empty_and_bounds(binary, intro_db):
    with sqlite3.connect(intro_db) as conn:
        eid = conn.execute("SELECT id FROM entries WHERE value='hero'").fetchone()[0]
        conn.execute("INSERT INTO aliases(entry_id,text,status,source_id,evidence_id) "
                     "VALUES(?,'field-alias','source_backed','fixture-v1','alias-only')", (eid,))
        for i in range(6):
            sid = str(i)
            conn.execute("INSERT INTO sources VALUES(?, '{}')", (sid,))
            payload = {"raw": {"raw_cv_names": [sid], "raw_gender": None,
                               "raw_subject_categories": [], "raw_attributes": "x" * 20000}}
            conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                         "VALUES(?,?,?,'source_backed',?)", (eid, sid, sid+'-field', json.dumps(payload)))
    conn.close()
    with Knowledge(intro_db) as api:
        expected = api.lookup("field-alias")
    result = invoke(binary, "lookup", intro_db, "field-alias")
    assert result == expected
    assert [o["value"] for o in result["source_fields"]["raw_cv_names"]] == [[str(i)] for i in range(4)]
    assert result["source_fields"]["raw_gender"][0]["value_state"] == "null"
    assert result["source_fields"]["raw_subject_categories"][0]["value_state"] == "empty"
    assert result["source_fields"]["raw_attributes"][0]["truncated"]
    assert len(result["source_fields_truncated"]) == 4
    assert result["citations"][0]["evidence_id"] == "alias-only"
    assert {e["evidence_id"] for e in result["source_fields_evidence"]} == {str(i)+'-field' for i in range(4)}
