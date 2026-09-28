import json
import sqlite3
import zipfile

import pytest

from sakura_knowledge.api import Knowledge
from sakura_knowledge.model import EntryKey, GROUPS, match_query
from sakura_knowledge.safety import safe_extract
from sakura_knowledge.storage import REQUIRED_SOURCE, build, digest, verify


def record(kind, namespace, value, text="测试 日本語 Hello"):
    return {"key": EntryKey(kind, namespace, value).as_dict(),
            "aliases": [{"text": "同名", "status": "source_backed"}],
            "documents": [{"title": text, "original": text, "status": "source_backed"}]}


def manifest(tmp_path, records):
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                      encoding="utf-8")
    metadata = dict.fromkeys(REQUIRED_SOURCE)
    metadata.update(source_id="fixture-v1", repo="fixture://local", provider="fixture",
                    dataset_role="test_only", path="input.jsonl", adapter="contract-jsonl-v1",
                    local_sha256=digest(source))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"sources": [metadata]}), encoding="utf-8")
    return path


@pytest.fixture
def snapshot(tmp_path):
    records = [record(k, "bangumi." + k, 1) for k in ("subject", "character", "person", "episode")]
    records.append(record("page", "moegirl.page", "同名"))
    records.append(record("tag", "image.bangumi_1", "1", "image tag"))
    records.append({"key": EntryKey("page", "moegirl.page", "draft").as_dict(),
                    "aliases": [{"text": "秘密", "status": "unverified_draft"}],
                    "documents": [{"title": "草稿独有", "status": "unverified_draft"}]})
    path = manifest(tmp_path, records)
    output = tmp_path / "snapshot"
    build(path, output)
    return output / "knowledge.sqlite"


def test_identity_isolation(snapshot):
    with Knowledge(snapshot) as api:
        assert api.lookup("1")["status"] == "ambiguous"
        for kind in ("subject", "character", "person", "episode"):
            assert api.lookup(key=EntryKey(kind, "bangumi." + kind, 1))["status"] == "found"
        assert len(api.lookup("同名")["candidates"]) == 6
        assert api.lookup("1", namespace="image.bangumi_1")["tag_key"] is not None


def test_search_safety(snapshot):
    with Knowledge(snapshot) as api:
        for query in ("测试", "日本語", "hello", "Hello!", '" OR * --', "'; DROP TABLE entries;--"):
            result = api.search(query)
            assert isinstance(result["candidates"], list)
        assert api.search("测")["warnings"] == ["too_short"]
        assert api.search("草稿独有")["status"] == "not_found"
        assert api.lookup("秘密")["status"] == "not_found"
        assert api.search("测试", kind="episode")["status"] == "not_found"
        assert api.ask("1", kind="character")["status"] == "entity_found_tag_unmapped"
        assert api.ask("1")["status"] == "entity_ambiguous"
        assert api.ask("孤独摇滚")["tag_key"] is None
        with pytest.raises(ValueError):
            api.search("x", topk=101)
        with pytest.raises(sqlite3.OperationalError):
            api.conn.execute("DELETE FROM entries")
    assert verify(snapshot)["ok"]


def test_atomic_digest_and_existing(tmp_path):
    path = manifest(tmp_path, [record("character", "bangumi.character", 1)])
    out = tmp_path / "published"
    build(path, out)
    before = digest(out / "knowledge.sqlite")
    with pytest.raises(FileExistsError):
        build(path, out)
    assert digest(out / "knowledge.sqlite") == before
    (tmp_path / "input.jsonl").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        build(path, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_candidates_not_verified(tmp_path):
    a = record("character", "bangumi.character", 1)
    b = record("tag", "fixture.tags", "hello")
    link = {"record_type": "link", "src": a["key"], "dst": b["key"],
            "relation": "entity_tag", "method": "fixture", "verification_status": "candidate"}
    path = manifest(tmp_path, [a, b, link, a])
    out = tmp_path / "snapshot"
    report = build(path, out)
    assert report["counts"]["fixture-v1"]["duplicate"] == 1
    with Knowledge(out / "knowledge.sqlite") as api:
        assert api.ask("1")["status"] == "entity_found_tag_unmapped"
        assert api.related(a["key"])["relations"] == []


def test_unresolved_rejects_publication(tmp_path):
    a = record("character", "bangumi.character", 1)
    link = {"record_type": "link", "src": a["key"],
            "dst": EntryKey("character", "bangumi.character", 2).as_dict(),
            "relation": "same_as", "method": "fixture"}
    path = manifest(tmp_path, [a, link])
    with pytest.raises(ValueError, match="unresolved"):
        build(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("name", ["../outside", "/absolute", "C:/escape", "aux/file", "a/../../escape"])
def test_zip_escape(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name, "bad")
    with pytest.raises(ValueError):
        safe_extract(archive, tmp_path / "out", digest(archive))
    assert not (tmp_path / "out").exists()
    with pytest.raises(ValueError, match="digest"):
        safe_extract(archive, tmp_path / "out", "0" * 64)


def test_contract_constants():
    assert len(GROUPS) == 7
    assert GROUPS[0] == "common_tags"
    assert match_query("中文、English") == '"中文" OR "english"'
