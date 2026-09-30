"""Independent synthetic expected behavior for the bd99b7a repair.

These are semantic assertions, not claims about real source facts.
"""
import json
import sqlite3

import pytest
from test_core import manifest, record

from sakura_knowledge.api import Knowledge
from sakura_knowledge.storage import build


@pytest.fixture
def intro_db(tmp_path):
    rows = [record("character", "fixture.character", name, "trusted description")
            for name in ("hero", "name.", "name_(x)", "介绍一下 literal")]
    for n in ("ambiguous-a", "ambiguous-b"):
        row = record("character", "fixture.character", n)
        row["aliases"] = [{"text": "介绍一下 hero", "status": "source_backed"}]
        rows.append(row)
    # The raw full question ambiguity must take precedence over parsing hero.
    build(manifest(tmp_path, rows), tmp_path / "db")
    return tmp_path / "db" / "knowledge.sqlite"


@pytest.mark.parametrize("name", ["name.", "name_(x)"])
def test_intro_preserves_legal_name_and_never_queries_tags(intro_db, name):
    with Knowledge(intro_db) as api:
        sql = []
        api.conn.set_trace_callback(sql.append)
        result = api.ask("介绍一下 " + name)
        assert result["status"] == "found"
        assert result["entry_key"]["value"] == name
        assert result["mapping_status"] == "not_requested"
        assert result["descriptions"][0]["original"] == "trusted description"
        assert not any("entity_tag" in q for q in sql)
        assert result["relations"] == []


def test_original_question_ambiguity_precedes_template(intro_db):
    with Knowledge(intro_db) as api:
        calls = []
        lookup = api.lookup

        def counted(*args, **kwargs):
            calls.append(args)
            return lookup(*args, **kwargs)

        api.lookup = counted
        result = api.ask("介绍一下 hero")
        assert result["status"] == "entity_ambiguous"
        assert result["query_template"] == "unsupported"
        assert result["parsed_subject"] is None
        assert len(result["candidates"]) == 2
        assert len(calls) == 1


def test_original_unique_name_precedes_template(intro_db):
    with Knowledge(intro_db) as api:
        result = api.ask("介绍一下 literal")
        assert result["entry_key"]["value"] == "介绍一下 literal"
        assert result["query_template"] == "unsupported"


def test_intro_target_conflict_and_tag_unmapped(intro_db):
    with Knowledge(intro_db) as api:
        with pytest.raises(ValueError, match="introduce template cannot combine"):
            api.ask("介绍一下 name.", target_tag_namespace="danbooru.tag")
        result = api.ask("name. 的标签是什么")
        assert result["status"] == "entity_found_tag_unmapped"
        assert result["mapping_status"] == "unmapped"


@pytest.mark.parametrize("key", ["contract_version", "search_text_version"])
def test_open_rejects_unknown_version_and_closes(intro_db, monkeypatch, key):
    with sqlite3.connect(intro_db) as conn:
        conn.execute("UPDATE build_meta SET value='999' WHERE key=?", (key,))
    conn.close()  # checkpoint fixture WAL before immutable read-only open
    import sakura_knowledge.api as module
    from sakura_knowledge.storage import readonly
    opened = []

    def tracked(path):
        conn = readonly(path)
        opened.append(conn)
        return conn

    monkeypatch.setattr(module, "readonly", tracked)
    with pytest.raises(ValueError, match=f"unsupported {key}: 999"):
        Knowledge(intro_db)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


@pytest.mark.parametrize("sql,match", [
    ("ALTER TABLE documents RENAME COLUMN original TO wrong", "documents missing original"),
    ("DROP TABLE aliases", "aliases missing"),
    ("DROP TABLE search_fts;CREATE TABLE search_fts(text,document_id,entry_id)", "not FTS5"),
])
def test_open_rejects_broken_schema(intro_db, sql, match):
    with sqlite3.connect(intro_db) as conn:
        conn.executescript(sql)
    conn.close()
    with pytest.raises(ValueError, match=match):
        Knowledge(intro_db)


@pytest.mark.parametrize("sources", [[], ["bangumi_1", "yande_1"]])
def test_common_partition_is_not_a_dataset(sources):
    from sakura_knowledge.adapters import tag_group_record
    row = {"tag_key": "common", "source_count": len(sources),
           "sources_json": json.dumps(sources), "category": "general"}
    item = tag_group_record("common_tags", row)
    occurrences = item["occurrences"]
    assert [o["dataset_id"] for o in occurrences] == (sources or [None])
    for obs in occurrences:
        assert obs["partition"] == "common_tags"
        assert obs["sample_count"] is None
        assert obs["raw"] == row
        assert "frequency" not in obs


@pytest.mark.parametrize("reverse", [False, True])
def test_field_observations_keep_conflicts_and_actual_provenance(intro_db, reverse):
    with sqlite3.connect(intro_db) as conn:
        eid = conn.execute("SELECT id FROM entries WHERE value='hero'").fetchone()[0]
        conn.execute("INSERT INTO aliases(entry_id,text,status,source_id,evidence_id) "
                     "VALUES(?, 'field-alias','source_backed','fixture-v1','alias-only')", (eid,))
        sources = [("A", ["from-A"]), ("Z", ["from-Z"])]
        for source, values in reversed(sources) if reverse else sources:
            conn.execute("INSERT INTO sources VALUES(?, '{}')", (source,))
            conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                         "VALUES(?,?,?,'source_backed',?)",
                         (eid, source, source + '-field', json.dumps({"raw": {
                             "raw_cv_names": values, "raw_gender": None,
                             "raw_subject_categories": []}})))
    conn.close()
    with Knowledge(intro_db) as api:
        result = api.lookup("field-alias")
    fields = result["source_fields"]
    assert [o["value"] for o in fields["raw_cv_names"]] == [["from-A"], ["from-Z"]]
    assert [o["source_id"] for o in fields["raw_cv_names"]] == ["A", "Z"]
    assert [o["evidence_id"] for o in fields["raw_cv_names"]] == ["A-field", "Z-field"]
    assert result["citations"] == [{"source_id": "fixture-v1", "evidence_id": "alias-only"}]
    assert {o["source_id"] for o in result["source_fields_evidence"]} == {"A", "Z"}
    assert fields["raw_gender"][0]["value_state"] == "null"
    assert fields["raw_subject_categories"][0]["value_state"] == "empty"
    assert "raw_attributes" not in fields  # missing != null != empty
    assert all("payload" not in p for p in result["canonical"]["identity_evidence"])


def test_field_value_and_observation_bounds(intro_db):
    from sakura_knowledge.response import RESPONSE_BYTES, encoded_size
    with sqlite3.connect(intro_db) as conn:
        eid = conn.execute("SELECT id FROM entries WHERE value='hero'").fetchone()[0]
        for i in range(7):
            conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                         "VALUES(?,'fixture-v1',?,'source_backed',?)",
                         (eid, str(i), json.dumps({"raw": {
                             "raw_cv_names": "x" * 20000,
                             "raw_attributes": list(range(100)),
                             "raw_subject_categories": [[[[[["deep"]]]]]],
                             "raw_gender": "value"}})))
    conn.close()
    with Knowledge(intro_db) as api:
        result = api.lookup(key={"kind": "character", "namespace": "fixture.character",
                                 "value": "hero"})
    assert result["response_version"] == "3"
    assert encoded_size(result) <= RESPONSE_BYTES
    assert len(result["source_fields"]["raw_cv_names"]) == 4
    obs = result["source_fields"]["raw_cv_names"][0]
    assert len(obs["value"]) == 256 and obs["truncated"]
    assert result["source_fields"]["raw_attributes"][0]["value"] == list(range(16))
    assert result["source_fields"]["raw_subject_categories"][0]["truncated"]
    assert len(result["source_fields_truncated"]) == 4


UNICODE_EXPECTED = [
    ("Straße STRASSE ẞ SS", ["strasse", "strasse", "ss", "ss"]),
    ("Σ σ ς", ["σ", "σ", "σ"]),
    ("İ i\u0307", ["i", "i"]),
    ("ＡＢＣ ｶﾀｶﾅ", ["abc", "カタ", "タカ", "カナ"]),
    ("中文日本", ["中文", "文日", "日本"]),
    ("a\u00a0b\u2003c", ["a", "b", "c"]),
    ("a中文 中文a", ["a中文", "中文", "a"]),
    ("e\u0301 𐐀", ["é", "𐐨"]),
]


@pytest.mark.parametrize("query,want", UNICODE_EXPECTED)
def test_unicode_tokens_and_match_independent(query, want):
    from sakura_knowledge.model import match_query, tokens
    assert tokens(query) == want
    assert match_query(query) == " OR ".join('"' + s + '"' for s in dict.fromkeys(want))


def test_unicode_fts_returns_known_nonempty_identity(tmp_path):
    entity = record("page", "fixture.page", "unicode-proof", "Straße ẞ Σ İ ＡＢＣ ｶﾀｶﾅ 中文 é 𐐀")
    build(manifest(tmp_path, [entity]), tmp_path / "unicode-db")
    with Knowledge(tmp_path / "unicode-db" / "knowledge.sqlite") as api:
        for query in ("STRASSE", "SS", "ς", "i", "abc", "カタカナ", "中文", "é", "𐐨"):
            result = api.search(query)
            assert result["candidates"][0]["entry_key"] == entity["key"]
            assert result["candidates"][0]["matched_by"] == "fts"


def test_unicode_character_boundaries():
    from sakura_knowledge.model import tokens
    assert tokens("a" * 256) == ["a" * 256]
    assert tokens("a" * 257) == []
    assert tokens(" " * 4096) == []
    with pytest.raises(ValueError, match="4096"):
        tokens(" " * 4097)
    with pytest.raises(ValueError, match="256 tokens"):
        tokens("a " * 257)
