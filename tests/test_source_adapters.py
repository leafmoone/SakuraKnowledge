"""Small, audited native-shape fixtures. They are not full-source acceptance."""
import json
import sqlite3

import pytest
from test_hardening import fixture_manifest

from sakura_knowledge.adapters import (
    bangumi_entity,
    bangumi_relation,
    iter_moegirl_mappings,
    iter_tag_wiki,
    moegirl_character,
    tag_group_record,
)
from sakura_knowledge.api import Knowledge
from sakura_knowledge.model import GROUPS
from sakura_knowledge.storage import build, digest, verify


def test_bangumi_four_id_spaces_person_types_and_context():
    for kind in ("subject", "character", "person", "episode"):
        row = {"id": 1, "name": "同名", "summary": "original body", "type": 2}
        record = bangumi_entity(kind, row)
        assert record["key"] == {"kind": kind, "namespace": f"bangumi.{kind}", "value": "1"}
        assert record["raw"]["type"] == 2
        assert record["documents"][0]["original"] == "original body"
    for code, kind in (("prsn", "person"), ("crt", "character")):
        link = bangumi_relation("person-relations", {"person_type": code,
            "person_id": 7, "related_person_id": 8, "relation_type": 1002,
            "spoiler": False, "ended": True})
        assert link["src"] == {"kind": kind, "namespace": f"bangumi.{kind}", "value": "7"}
        assert link["dst"]["kind"] == kind
        assert link["raw"]["ended"] is True
    unknown = bangumi_relation("person-relations", {"person_type": "future", "person_id": 1,
                                                    "related_person_id": 2})
    assert unknown["record_type"] == "unresolved"
    assert unknown["raw"]["person_type"] == "future"
    staff = bangumi_relation("subject-persons", {"subject_id": 1, "person_id": 2,
                "position": 2004, "appear_eps": "4,5"})
    assert staff["raw"]["position"] == 2004 and staff["raw"]["appear_eps"] == "4,5"
    cv = bangumi_relation("person-characters", {"person_id": 3, "subject_id": 292,
                      "character_id": 4, "type": 1, "summary": "voice"})
    assert cv["raw"]["subject_id"] == 292
    assert cv["relation"] == "portrays_character"


def test_source_long_body_is_preserved_and_response_bounded(tmp_path):
    from sakura_knowledge.adapters import iter_danbooru_pages

    long = "introduction " + "x " * 52_000 + " final_tail_provenance"
    record = bangumi_entity("subject", {"id": 91, "name": "long", "summary": long,
                                       "infobox": "infobox marker"})
    assert record["documents"][0]["original"].endswith("final_tail_provenance")
    assert record["raw"]["summary"].endswith("final_tail_provenance")
    assert record["raw"]["infobox"] == "infobox marker"
    manifest = fixture_manifest(tmp_path, [record], name="longbody")
    out = tmp_path / "longbody-snapshot"
    build(manifest, out)
    with sqlite3.connect(out / "knowledge.sqlite") as conn:
        original, text, payload = conn.execute(
            "SELECT original,search_text,payload FROM documents").fetchone()
        assert original.endswith("final_tail_provenance")
        assert "final_tail_provenance" not in text
        assert json.loads(payload)["search_text_truncated"] is True
    with Knowledge(out / "knowledge.sqlite") as api:
        desc = api.lookup("long")["descriptions"][0]
        assert desc["response_truncated"] == 1
        assert desc["search_text_truncated"] == 1
        assert len(desc["original"]) == 4000
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        pytest.skip("optional ingestion-only pyarrow not installed")
    file = tmp_path / "pages.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": 99, "title": "test-page",
        "other_names": [], "body": long, "is_deleted": False,
        "is_locked": False, "created_at": "", "updated_at": ""}]), file)
    page, = list(iter_danbooru_pages(file, sample=1))
    assert page["documents"][0]["original"].endswith("final_tail_provenance")
    assert page["documents"][0]["original"] == long


def test_moegirl_category_not_work_and_mapping_candidate(tmp_path):
    record = moegirl_character("阿诗玲", {"别名": ["昵称"], "生日": [None, 5, 11]},
                               subjects=["爱尔兰作品", "凯尔经的秘密"],
                               cvs=["声优"], gender="unknown")
    assert record["key"]["namespace"] == "moegirl.character"
    assert record["raw"]["raw_subject_categories"] == ["爱尔兰作品", "凯尔经的秘密"]
    assert record["documents"] == []
    assert record["aliases"][0]["text"] == "阿诗玲"
    (tmp_path / "bgm2moegirl.json").write_text(json.dumps({"12393": ["阿诗玲"]}),
                                                 encoding="utf-8")
    (tmp_path / "moegirl2bgm.json").write_text(json.dumps({"阿诗玲": ["12393"]}),
                                                 encoding="utf-8")
    candidate, = list(iter_moegirl_mappings(tmp_path))
    assert candidate["verification_status"] == "candidate"
    assert candidate["raw"]["reverse"] == ["12393"]
    assert candidate["src"]["namespace"] == "bangumi.character"
    assert candidate["dst"]["namespace"] == "moegirl.character"
    # Unique reciprocal match and the source's claimed identity do not
    # become a verified entity_tag or a native entity-to-entity relation.
    assert candidate["relation"] == "identity_candidate"


def test_tag_evidence_exact_match_and_ai_status_are_not_verified(tmp_path):
    database = tmp_path / "source.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute(f'CREATE TABLE "{GROUPS[0]}"(tag_key,source_count)')
        for group in GROUPS[1:]:
            conn.execute(f'CREATE TABLE "{group}"(tag_key,source_count)')
        conn.execute('INSERT INTO "anime_pictures_1_noncommon" VALUES(?,?)', ('akanbe', 3))
        conn.execute('CREATE TABLE tag_evidence(tag_key,wiki_id,match_type,confidence)')
        conn.execute('INSERT INTO tag_evidence VALUES(?,?,?,?)',
                     ('akanbe', 5438, 'exact_title', 1.0))
        conn.execute('CREATE TABLE annotations(tag_key,status,semantic_summary,model)')
        conn.execute('INSERT INTO annotations VALUES(?,?,?,?)',
                     ('akanbe', 'verified', 'model generated', 'unknown-model'))
        conn.execute('CREATE TABLE full_annotation_cache(tag_key,status,result_json,model)')
        conn.execute('INSERT INTO full_annotation_cache VALUES(?,?,?,?)',
                     ('akanbe', 'source_backed', '{"made":"by model"}', 'unknown-model'))
    items = list(iter_tag_wiki(database))
    assert len(items) == 4
    tag, match, annotation, cache = items
    assert tag["key"]["namespace"] == "local.tag_aggregate"
    assert tag["occurrences"][0]["group"] == "anime_pictures_1_noncommon"
    assert match["verification_status"] == "candidate"
    assert match["raw"]["confidence"] == 1.0
    assert match["src"]["kind"] == "tag" and match["dst"]["kind"] == "page"
    assert match["src"]["namespace"] == "local.tag_aggregate"
    for item in (annotation, cache):
        assert item["status"] == "unverified_draft"
        assert item["documents"][0]["status"] == "unverified_draft"
    assert tag_group_record("anime_pictures_1_noncommon", {
        "tag_key": "akanbe", "source_count": 3})["key"]["value"] == "akanbe"


def test_explicit_unresolved_policy_quarantines_links_not_unknown_codes(tmp_path):
    tag = tag_group_record("anime_pictures_1_noncommon",
                           {"tag_key": "akanbe", "source_count": 3})
    unresolved = {"record_type": "unresolved", "reason": "unresolved_wiki_link",
                  "raw": {"source_id": 1, "resolved_id": None}}
    unknown = {"record_type": "unresolved", "reason": "unknown_person_type",
               "raw": {"person_type": "future"}}
    manifest = fixture_manifest(tmp_path, [tag, unresolved], name="allow")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["allow_unresolved_reasons"] = ["unresolved_wiki_link"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "allowed"
    result = build(manifest, out)
    assert result["verification"]["unresolved_reasons"] == {"unresolved_wiki_link": 1}
    assert verify(out / "knowledge.sqlite")["ok"]
    with Knowledge(out / "knowledge.sqlite") as api:
        assert api.ask("akanbe")["status"] == "found"
        assert api.ask("akanbe")["citations"]
        assert api.ask("akanbe", kind="tag", namespace="danbooru.tag")["status"] == "unknown"
    blocked = fixture_manifest(tmp_path, [tag, unknown], name="blocked")
    data = json.loads(blocked.read_text(encoding="utf-8"))
    data["allow_unresolved_reasons"] = ["unresolved_wiki_link"]
    blocked.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="verification rejected publication"):
        build(blocked, tmp_path / "blocked-output")
    assert not (tmp_path / "blocked-output").exists()
    assert digest(out / "knowledge.sqlite")
