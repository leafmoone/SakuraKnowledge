"""Explicit contract JSONL fixtures, never evidence of compatibility with real sources."""
import json
import sqlite3
import threading
import zipfile

import pytest

from sakura_knowledge import storage
from sakura_knowledge.api import Knowledge
from sakura_knowledge.model import EntryKey, match_query, search_text, tokens
from sakura_knowledge.safety import safe_extract
from sakura_knowledge.storage import REQUIRED_SOURCE, build, digest, verify


def entity(kind, value, *, namespace="fixture", aliases=(), docs=(), **metadata):
    return {"key": EntryKey(kind, namespace, value).as_dict(),
            "aliases": list(aliases), "documents": list(docs), **metadata}


def doc(title, evidence="document-proof"):
    return {"title": title, "original": title, "status": "source_backed",
            "evidence_id": evidence}


def fixture_manifest(tmp_path, records, *, source_id="fixture-v1", name="input"):
    source = tmp_path / f"{name}.jsonl"
    source.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                      encoding="utf-8")
    metadata = dict.fromkeys(REQUIRED_SOURCE)
    metadata.update(source_id=source_id, provider="fixture", dataset_role="test_only",
                    repo="fixture://local", path=source.name, adapter="contract-jsonl-v1",
                    local_sha256=digest(source))
    manifest = tmp_path / f"{name}.json"
    manifest.write_text(json.dumps({"sources": [metadata]}), encoding="utf-8")
    return manifest


def test_draft_tag_and_alias_evidence_gate(tmp_path):
    draft = entity("tag", "draft_tag", namespace="danbooru.tag",
                   docs=[{"title": "draft", "status": "unverified_draft"}])
    left = entity("character", "1", aliases=[{"text": "双名", "status": "source_backed",
                                                "evidence_id": "alias-proof-1"}])
    right = entity("person", "2", aliases=[{"text": "双名", "status": "source_backed",
                                            "evidence_id": "alias-proof-2"}])
    out = tmp_path / "snapshot"
    build(fixture_manifest(tmp_path, [draft, left, right]), out)
    with Knowledge(out / "knowledge.sqlite") as api:
        key = draft["key"]
        assert api.lookup(key=key)["status"] == "not_found"
        assert api.lookup("draft_tag")["status"] == "not_found"
        assert api.ask("draft_tag")["status"] == "unknown"
        assert api.lookup("双名")["status"] == "ambiguous"
        found = api.lookup("双名", kind="character")
        assert found["citations"] == [{"source_id": "fixture-v1",
                                       "evidence_id": "alias-proof-1"}]
        assert found["descriptions"] == []
        assert api.ask("双名", kind="character")["status"] == "entity_found_tag_unmapped"
        assert api.ask("双名", kind="character")["tag_key"] is None


def test_fts_exact_first_dedup_stable_and_long_document(tmp_path):
    records = [entity("character", "exact", aliases=[{"text": "hello", "status":
                "source_backed", "evidence_id": "alias-exact"}], docs=[doc("hello")]),
               entity("character", "a", docs=[doc("hello"), doc("hello elsewhere", "d2")]),
               entity("character", "b", docs=[doc("hello")]),
               entity("page", "long", docs=[doc(" ".join(["word"] * 300) +
                                                    " finishword " + "甲" * 500 + "终点")])]
    out = tmp_path / "snapshot"
    build(fixture_manifest(tmp_path, records), out)
    with Knowledge(out / "knowledge.sqlite") as api:
        first = api.search("hello")
        assert first["candidates"][0]["entry_key"]["value"] == "exact"
        assert len(api.search("hello", topk=1)["candidates"]) == 1
        assert first["citations"] == [{"source_id": "fixture-v1",
                                       "evidence_id": "alias-exact"}]
        assert [c["entry_key"]["value"] for c in first["candidates"]].count("a") == 1
        assert api.search("hello")["candidates"] == first["candidates"]
        assert api.search("finishword")["candidates"][0]["entry_key"]["value"] == "long"
        assert api.search("终点")["candidates"][0]["entry_key"]["value"] == "long"
        assert api.search("终")["warnings"] == ["too_short"]
    assert "终点" in search_text("甲" * 500 + "终点").split()
    assert match_query("Hello 中文") == '"hello" OR "中文"'
    with pytest.raises(ValueError, match="256 tokens"):
        tokens(" ".join(str(i) for i in range(257)))


def test_bm25_ties_deduplicate_multiple_documents(tmp_path):
    records = [entity("page", "a", docs=[doc("same common", "a1"),
                                          doc("same common", "a2")]),
               entity("page", "b", docs=[doc("same common", "b1")])]
    records += [entity("page", str(i), docs=[doc("same common") for _ in range(15)])
                for i in range(30)]
    out = tmp_path / "snapshot"
    build(fixture_manifest(tmp_path, records), out)
    with Knowledge(out / "knowledge.sqlite") as api:
        keys = [c["entry_key"]["value"] for c in api.search("same", topk=20)["candidates"]]
        assert len(keys) == len(set(keys)) == 20
        assert keys == [c["entry_key"]["value"] for c in
                        api.search("same", topk=20)["candidates"]]
    assert verify(out / "knowledge.sqlite")["ok"]
    # Single-pass FTS grouping; no correlated per-document FTS scan.
    with sqlite3.connect(out / "knowledge.sqlite") as conn:
        plan = [detail for _, _, _, detail in conn.execute(
            "EXPLAIN QUERY PLAN SELECT document_id,count(*) FROM search_fts "
            "GROUP BY document_id")]
        assert sum("SCAN search_fts VIRTUAL TABLE" in p for p in plan) == 1
        assert not any("CORRELATED" in p for p in plan)


def test_target_cardinality_ignores_link_display_cap_and_untrusted_edges(tmp_path):
    hero = entity("character", "hero", status="source_backed")
    a = entity("tag", "a", namespace="danbooru.tag", status="source_backed")
    b = entity("tag", "b", namespace="danbooru.tag", status="source_backed")
    other = entity("tag", "elsewhere", namespace="local.tag_aggregate",
                   status="source_backed")
    draft = entity("tag", "draft", namespace="danbooru.tag", status="no_reference")

    def edge(dst, status="verified", relation="entity_tag", ordinal=None):
        return {"record_type": "link", "src": hero["key"], "dst": dst["key"],
                "relation": relation, "method": "fixture", "verification_status": status,
                "evidence_id": f"fixture-proof-{ordinal}" if ordinal is not None else "single-proof"}

    records = [hero, a, b, other, draft, *[edge(a, ordinal=i) for i in range(100)],
               *[edge(b, "candidate") for _ in range(80)],
               *[edge(b, "native") for _ in range(40)],
               edge(draft), edge(other), edge(a, relation="points_to"), edge(b)]
    out = tmp_path / "many-links"
    build(fixture_manifest(tmp_path, records), out)
    with Knowledge(out / "knowledge.sqlite") as api:
        result = api.ask("hero", target_tag_namespace="danbooru.tag")
        assert result["status"] == "tag_ambiguous"
        assert result["mapping_status"] == "target_ambiguous"
        assert result["tag_key"] is None
        assert {r["dst"]["value"] for r in result["relations"]} == {"a", "b"}
        local = api.ask("hero", target_tag_namespace="local.tag_aggregate")
        assert local["tag_key"] == {"namespace": "local.tag_aggregate", "value": "elsewhere"}
        assert len(api.related(hero["key"], limit=100)["relations"]) == 100
    with sqlite3.connect(out / "knowledge.sqlite") as conn:
        plans = {
            "value": "SELECT id FROM entries WHERE value='hero'",
            "document": "SELECT id FROM documents WHERE entry_id=1 AND status='source_backed'",
            "alias": "SELECT id FROM aliases WHERE entry_id=1 AND text='hero'",
            "links": ("SELECT dst FROM links WHERE src=1 AND relation='entity_tag' "
                      "AND verification_status='verified'"),
        }
        for label, sql in plans.items():
            detail = " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql))
            assert {"value": "entry_value", "document": "document_entry",
                    "alias": "alias_entry", "links": "link_src"}[label] in detail


def test_target_tag_namespace_is_not_source_namespace_or_candidate(tmp_path, capsys):
    from sakura_knowledge.cli import main

    local = entity("tag", "same_spelling", namespace="local.tag_aggregate",
                   status="source_backed")
    native = entity("tag", "same_spelling", namespace="danbooru.tag",
                    status="source_backed")
    source = entity("character", "hero", namespace="bangumi.character",
                    status="source_backed")
    verified_source = entity("character", "verified_hero", namespace="bangumi.character",
                             status="source_backed")
    links = [{"record_type": "link", "src": src["key"], "dst": dst["key"],
              "relation": "entity_tag", "method": "fixture",
              "verification_status": "candidate"} for src, dst in
             ((local, native), (native, local), (source, native))]
    links.append({"record_type": "link", "src": verified_source["key"], "dst": native["key"],
                  "relation": "entity_tag", "method": "fixture",
                  "verification_status": "verified"})
    out = tmp_path / "target-snapshot"
    build(fixture_manifest(tmp_path, [local, native, source, verified_source, *links]), out)
    database = out / "knowledge.sqlite"
    with Knowledge(database) as api:
        local_only = api.ask("same_spelling", kind="tag", namespace="local.tag_aggregate")
        assert local_only["status"] == "found"
        assert local_only["mapping_status"] == "local_identity_only"
        assert "local.tag_aggregate" in local_only["answer"]
        assert local_only["target_namespace"] is None
        target = api.ask("same_spelling", kind="tag", namespace="local.tag_aggregate",
                         target_tag_namespace="danbooru.tag")
        assert target["status"] == "entity_found_tag_unmapped"
        assert target["mapping_status"] == "target_unmapped"
        assert target["tag_key"] is None and target["relations"] == []
        assert target["entry_key"] == local["key"]
        assert target["canonical"]["entry_key"] == local["key"]
        assert api.ask("same_spelling", kind="tag", namespace="danbooru.tag",
                       target_tag_namespace="danbooru.tag")["mapping_status"] == "target_identity"
        assert api.ask("hero", kind="character", target_tag_namespace="danbooru.tag")[
            "mapping_status"] == "target_unmapped"
        mapped = api.ask("verified_hero", target_tag_namespace="danbooru.tag")
        assert mapped["mapping_status"] == "target_verified"
        assert mapped["tag_key"] == {"namespace": "danbooru.tag", "value": "same_spelling"}
        assert api.ask("same_spelling", kind="tag")["status"] == "entity_ambiguous"
        with pytest.raises(ValueError, match="target_tag_namespace"):
            api.ask("hero", target_tag_namespace="")
    assert main(["ask", str(database), "same_spelling", "--kind", "tag", "--namespace",
                 "local.tag_aggregate", "--target-tag-namespace", "danbooru.tag"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mapping_status"] == "target_unmapped" and payload["tag_key"] is None
    assert payload["target_namespace"] == "danbooru.tag"


def test_no_implicit_bare_tag_evidence_and_conflict_order(tmp_path):
    bare = entity("tag", "bare", namespace="danbooru.tag")
    manifest = fixture_manifest(tmp_path, [bare], name="bare")
    out = tmp_path / "bare-snapshot"
    build(manifest, out)
    with Knowledge(out / "knowledge.sqlite") as api:
        assert api.ask("bare", kind="tag", namespace="danbooru.tag")["status"] == "unknown"
    for n, values in enumerate(((None, "/one", "/two"),
                                ("/one", None, "/two"))):
        records = [entity("page", "same", locator=value, status="source_backed")
                   for value in values]
        manifest = fixture_manifest(tmp_path, records, name=f"perm{n}")
        out = tmp_path / f"perm{n}-snapshot"
        result = build(manifest, out)
        assert result["counts"]["fixture-v1"]["conflicted"] == 1
        with Knowledge(out / "knowledge.sqlite") as api:
            assert api.lookup("same")["status"] == "not_found"


def test_history_conflict_quarantine_and_date_not_refreshed(tmp_path):
    old = entity("page", "title", docs=[doc("old text")], type="article",
                 locator="/old", mapping_date="2025-12-23")
    refreshed = entity("page", "title", docs=[doc("new text")], type="article",
                       locator="/old", body_date="2026-09-01")
    conflict = entity("page", "title", type="maintenance", locator="/other")
    out = tmp_path / "snapshot"
    report = build(fixture_manifest(tmp_path, [old, refreshed, conflict]), out)
    assert report["counts"]["fixture-v1"]["conflicted"] == 1
    with Knowledge(out / "knowledge.sqlite") as api:
        assert api.lookup("title")["status"] == "not_found"
        rows = api.conn.execute("SELECT status,payload FROM entry_evidence ORDER BY id").fetchall()
        assert len(rows) == 3
        assert json.loads(rows[0]["payload"])["mapping_date"] == "2025-12-23"
        assert "mapping_date" not in json.loads(rows[1]["payload"])
        assert rows[2]["status"] == "conflict"
    assert verify(out / "knowledge.sqlite")["ok"]


def test_mapping_date_kept_across_separate_source_revisions(tmp_path):
    old = fixture_manifest(tmp_path, [entity("page", "p", mapping_date="2025-12-23")],
                           source_id="mapping-2025", name="mapping")
    new = fixture_manifest(tmp_path, [entity("page", "p", docs=[doc("new body")],
                                                  body_date="2026-09-01")],
                           source_id="body-2026", name="body")
    sources = json.loads(old.read_text(encoding="utf-8"))["sources"] + json.loads(
        new.read_text(encoding="utf-8"))["sources"]
    merged = tmp_path / "merged.json"
    merged.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    out = tmp_path / "snapshot"
    build(merged, out)
    with Knowledge(out / "knowledge.sqlite") as api:
        rows = api.conn.execute("SELECT source_id,payload FROM entry_evidence ORDER BY id").fetchall()
        assert [row["source_id"] for row in rows] == ["mapping-2025", "body-2026"]
        assert json.loads(rows[0]["payload"])["mapping_date"] == "2025-12-23"
        assert "mapping_date" not in json.loads(rows[1]["payload"])


def test_order_independent_links_related_bounds_and_accounts(tmp_path):
    src = entity("character", "hero", status="source_backed")
    dst = entity("tag", "safe", status="source_backed")
    link = {"record_type": "link", "src": src["key"], "dst": dst["key"],
            "relation": "entity_tag", "method": "fixture", "verification_status": "verified"}
    items = [link, src, dst]
    for number in range(101):
        other = entity("page", str(number), status="source_backed")
        items += [{"record_type": "link", "src": src["key"], "dst": other["key"],
                   "relation": "points_to", "method": "fixture", "verification_status": "native"},
                  other]
    out = tmp_path / "snapshot"
    report = build(fixture_manifest(tmp_path, items), out)
    assert report["counts"]["fixture-v1"]["input"] == len(items)
    assert report["counts"]["fixture-v1"]["by_kind"]["page"] == 101
    assert report["wal_checkpoint"][0] == 0
    assert not list(out.glob("*-wal"))
    with Knowledge(out / "knowledge.sqlite") as api:
        assert api.ask("hero")["tag_key"] == {"namespace": "fixture", "value": "safe"}
        assert len(api.related(src["key"])["relations"]) == 20
        assert len(api.related(src["key"], limit=100)["relations"]) == 100
        with pytest.raises(ValueError):
            api.related(src["key"], limit=101)
    assert verify(out / "knowledge.sqlite")["source_account_errors"] == []


def test_verify_detects_fts_and_source_ledger_corruption(tmp_path):
    out = tmp_path / "snapshot"
    build(fixture_manifest(tmp_path, [entity("page", "p", docs=[doc("中文")])]), out)
    database = out / "knowledge.sqlite"
    assert verify(database)["ok"]
    conn = sqlite3.connect(database)
    with conn:
        conn.execute("DELETE FROM search_fts")
    conn.close()  # immutable readers intentionally ignore an active WAL
    bad = verify(database)
    assert not bad["ok"] and bad["fts_missing"] == 1
    conn = sqlite3.connect(database)
    with conn:
        conn.execute("UPDATE source_counts SET input=input+1")
    conn.close()
    assert not verify(database)["ok"]
    assert verify(database)["source_account_errors"] == ["fixture-v1"]


def test_failed_input_and_publication_lock_keep_old_snapshot(tmp_path, monkeypatch):
    path = fixture_manifest(tmp_path, [entity("page", "old")])
    old = tmp_path / "old"
    build(path, old)
    before = digest(old / "knowledge.sqlite")
    target = tmp_path / "new"
    lock = tmp_path / ".new.sknow.lock"
    lock.write_text("someone building", encoding="utf-8")
    with pytest.raises(FileExistsError):
        build(path, target)
    assert lock.read_text(encoding="utf-8") == "someone building"
    lock.unlink()
    original = storage._freeze_input

    def change_after_copy(source, destination):
        original(source, destination)
        (tmp_path / "input.jsonl").write_text("changed", encoding="utf-8")

    monkeypatch.setattr(storage, "_freeze_input", change_after_copy)
    with pytest.raises(ValueError, match="source changed"):
        build(path, target)
    assert not target.exists() and digest(old / "knowledge.sqlite") == before


def test_concurrent_build_only_one_publishes(tmp_path):
    path = fixture_manifest(tmp_path, [entity("page", "single")])
    output = tmp_path / "snapshot"
    barrier = threading.Barrier(2)
    outcomes = []

    def run():
        barrier.wait()
        try:
            build(path, output)
            outcomes.append("published")
        except FileExistsError:
            outcomes.append("refused")

    jobs = [threading.Thread(target=run) for _ in range(2)]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(timeout=10)
    assert sorted(outcomes) == ["published", "refused"]
    assert verify(output / "knowledge.sqlite")["ok"]


def test_query_budget_and_oversized_jsonl(tmp_path):
    out = tmp_path / "snapshot"
    build(fixture_manifest(tmp_path, [entity("page", "p", docs=[doc("hello")])]), out)
    with Knowledge(out / "knowledge.sqlite") as api:
        api.conn.set_progress_handler(lambda: 1, 1)
        with pytest.raises(ValueError, match="query_budget_exceeded"):
            api.search("hello")
    over = fixture_manifest(tmp_path, [entity("page", "huge",
                        docs=[doc("z" * 2_000_000)])], name="oversize")
    with pytest.raises(ValueError, match="rejected"):
        build(over, tmp_path / "oversize-out")
    assert not (tmp_path / "oversize-out").exists()
    receipt = tmp_path / ".oversize-out.rejections.json"
    assert json.loads(receipt.read_text(encoding="utf-8"))["counts"]["fixture-v1"]["rejected"]


def test_external_destination_created_during_publish_is_never_replaced(tmp_path, monkeypatch):
    manifest = fixture_manifest(tmp_path, [entity("page", "p")])
    target = tmp_path / "snapshot"
    original = storage._publish_new_directory

    def concurrent_creator(temp, output):
        output.mkdir()
        (output / "outside.txt").write_text("keep", encoding="utf-8")
        original(temp, output)

    monkeypatch.setattr(storage, "_publish_new_directory", concurrent_creator)
    with pytest.raises(FileExistsError):
        build(manifest, target)
    assert (target / "outside.txt").read_text(encoding="utf-8") == "keep"


def test_zip_byte_cap_corruption_and_no_partial_output(tmp_path):
    archive = tmp_path / "zipfile.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("safe.txt", "text" * 100)
    with pytest.raises(ValueError, match="unsafe ZIP"):
        safe_extract(archive, tmp_path / "extracted", digest(archive), max_bytes=100)
    assert not (tmp_path / "extracted").exists()
    safe_extract(archive, tmp_path / "extracted", digest(archive))
    assert (tmp_path / "extracted" / "safe.txt").read_text() == "text" * 100
    with pytest.raises(FileExistsError):
        safe_extract(archive, tmp_path / "extracted", digest(archive))
