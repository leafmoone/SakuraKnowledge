"""Synthetic only: no production snapshot, models, or benchmark executions."""
import json
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import p4_pilot_lexical as m
from tools.p4_retrieval_metrics import EntryKey, Hit, TrustedPin, ranking_metrics


def fixture(tmp_path, count=4):
    source = tmp_path / "source.sqlite"
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.executescript("""
            CREATE TABLE sources(source_id TEXT PRIMARY KEY);
            INSERT INTO sources VALUES('s');
            CREATE TABLE entries(id INTEGER PRIMARY KEY,kind,namespace,value,conflicted);
            CREATE TABLE documents(id INTEGER PRIMARY KEY,entry_id,title,original,status,source_id,evidence_id);
            CREATE TABLE entry_evidence(id INTEGER PRIMARY KEY,entry_id,source_id,evidence_id,status);
            CREATE TABLE aliases(id INTEGER PRIMARY KEY,entry_id,text,status,source_id,evidence_id);
        """)
        docs = []
        for i in range(1, count + 2):
            # Final identity is deliberately outside the pilot.
            namespace = "other" if i == 2 else "ns"
            value = "shared" if i <= 2 else f"value-{i}"
            conn.execute("INSERT INTO entries VALUES(?,?,?,?,0)", (i, "tag", namespace, value))
            conn.execute("INSERT INTO entry_evidence VALUES(?,?,?,?,?)", (i, i, "s", f"id-{i}", "source_backed"))
            conn.execute("INSERT INTO aliases VALUES(?,?,?,?,?,?)", (i, i, "alias", "source_backed", "s", f"alias-{i}"))
            conn.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (i, i, "Title", "common 青空 café", "source_backed", "s", f"doc-{i}"))
            if i <= count:
                docs.append({"document_id": i, "entry_id": i, "entry_key": {
                    "kind": "tag", "namespace": namespace, "value": value},
                    "title": "Title", "original": "common 青空 café", "status": "source_backed",
                    "source_id": "s", "evidence_id": f"doc-{i}"})
        conn.execute("INSERT INTO aliases VALUES(999,3,'generated','generated_from_evidence','s','bad')")
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_bytes(b"".join(m.canonical(d) + b"\n" for d in reversed(docs)))
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"cases": [
        {"case_id": "q2", "query": "alias", "subset": "lexical"},
        {"case_id": "q1", "query": "common", "subset": "semantic"},
        {"case_id": "q3", "query": "shared", "subset": "ambiguous/negative"},
        {"case_id": "q4", "query": "generated", "subset": "lexical"},
        {"case_id": "q5", "query": "青空 CAFÉ", "subset": "crosslingual"},
    ]}), encoding="utf-8")
    data = json.loads(gold.read_bytes())
    data.update(status='FROZEN_PRE_EMBEDDING',
                base_snapshot_sha256=m.sha256_file(source),
                base_snapshot_bytes=source.stat().st_size, candidate_hard_negatives=[])
    for case in data['cases']:
        case['accepted_targets'] = []
        case['candidate_hard_negative_document_ids'] = []
    gold.write_bytes(m.canonical(data))
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(m.canonical({"corpus_sha256": m.sha256_file(corpus),
        "selected_count": count, "base_snapshot": m.binding(source)}))
    return corpus, gold, manifest, source, tmp_path / "build/p4/index.sqlite"


def build(paths, count=4):
    return m.prepare(*paths, expected_count=count, root=paths[0].parent)


def test_prepare_query_pins_and_arithmetic(tmp_path):
    paths = fixture(tmp_path)
    before = m.binding(paths[3])
    receipt = build(paths)
    result = m.query(paths[4], paths[1], expected_index_sha256=receipt["index"]["sha256"])
    assert m.binding(paths[3]) == before
    assert not Path(str(paths[3]) + "-wal").exists()
    assert [r["case_id"] for r in result["cases"]] == ["q1", "q2", "q3", "q4", "q5"]
    lexical, alias, exact, generated, unicode = result["cases"]
    assert len(lexical["raw_hits"]) == len(unicode["raw_hits"]) == 4
    assert len(alias["trusted_pins"]) == 4
    assert len(exact["trusted_pins"]) == 2
    assert exact["ranking"][0]["namespace"] == "ns"
    assert exact["ranking"][1]["namespace"] == "other"
    assert not generated["trusted_pins"]
    for row in result["cases"]:
        assert row["identity_status"] == "not_asserted"
        assert row["promoted_identities"] == []
        for hit in row["raw_hits"]:
            Hit(**{**hit, "entry": EntryKey(**hit["entry"])})
        for pin in row["trusted_pins"]:
            TrustedPin(**{**pin, "entry": EntryKey(**pin["entry"])})
    ranking = [EntryKey(**key) for key in lexical["ranking"]]
    assert asdict(ranking_metrics(ranking, [ranking[0]]))["recall_at_10"] == 1
    assert "multiple_trusted_identities_preserved_not_resolved" in exact["warnings"]
    assert result == m.query(paths[4], paths[1], expected_index_sha256=receipt["index"]["sha256"])


def test_fts_is_pilot_only_and_uses_storage_text(tmp_path):
    paths = fixture(tmp_path)
    build(paths)
    with closing(sqlite3.connect(paths[4])) as conn:
        assert conn.execute("SELECT count(*) FROM search_fts").fetchone()[0] == 4
        assert conn.execute("SELECT text FROM search_fts LIMIT 1").fetchone()[0] == m.search_text("Title common 青空 café")
        actual = conn.execute("SELECT bm25(search_fts) FROM search_fts WHERE search_fts MATCH 'common'").fetchone()[0]
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.execute(m.FTS_SCHEMA)
        for i in range(4):
            reference.execute("INSERT INTO search_fts VALUES(?,?,?)", (m.search_text("Title common 青空 café"), i, i))
        expected = reference.execute("SELECT bm25(search_fts) FROM search_fts WHERE search_fts MATCH 'common'").fetchone()[0]
    assert actual == expected


def test_depth_raw_documents_then_first_occurrence_dedup(tmp_path):
    paths = fixture(tmp_path, count=105)
    build(paths, count=105)
    with closing(sqlite3.connect(paths[4])) as conn:
        conn.execute("UPDATE documents SET kind='tag',namespace='a',value='one' WHERE document_id<=101")
        result = m.query_case(conn, {"case_id": "depth", "query": "common"})
    assert len(result["raw_hits"]) == 100
    assert len(result["lexical_ranking"]) == 1
    assert [h["document_id"] for h in result["raw_hits"]] == [str(i) for i in range(1, 101)]


def test_bindings_and_no_overwrite(tmp_path):
    paths = fixture(tmp_path)
    receipt = build(paths)
    with pytest.raises(FileExistsError):
        build(paths)
    with pytest.raises(ValueError, match="SHA256"):
        m.query(paths[4], paths[1], expected_index_sha256="0" * 64)
    paths[1].write_text(paths[1].read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gold binding"):
        m.query(paths[4], paths[1], expected_index_sha256=receipt["index"]["sha256"])


def test_corpus_hash_rejected_before_source_access(tmp_path):
    paths = fixture(tmp_path)
    paths[0].write_bytes(paths[0].read_bytes() + b"\n")
    paths[3].unlink()
    with pytest.raises(ValueError, match="corpus SHA256"):
        build(paths)
    assert not paths[4].exists()


@pytest.mark.parametrize("change", ["conflicted", "generated_identity", "forged_document"])
def test_trust_fail_closed(tmp_path, change):
    paths = fixture(tmp_path)
    with closing(sqlite3.connect(paths[3])) as conn, conn:
        if change == "conflicted":
            conn.execute("UPDATE entries SET conflicted=1 WHERE id=1")
        elif change == "generated_identity":
            conn.execute("UPDATE entry_evidence SET status='generated_from_evidence' WHERE entry_id=1")
        else:
            conn.execute("UPDATE documents SET original='different' WHERE id=1")
    report = json.loads(paths[2].read_bytes())
    report["base_snapshot"] = m.binding(paths[3])
    paths[2].write_bytes(m.canonical(report))
    gold = json.loads(paths[1].read_bytes())
    gold['base_snapshot_sha256'] = report['base_snapshot']['sha256']
    gold['base_snapshot_bytes'] = report['base_snapshot']['size']
    paths[1].write_bytes(m.canonical(gold))
    with pytest.raises(ValueError, match="mismatch|identity evidence"):
        build(paths)


def test_cli_authorization_and_synthetic_roundtrip(tmp_path, capsys):
    paths = fixture(tmp_path)
    args = ["prepare"]
    for name, path in zip(("corpus", "gold", "manifest", "snapshot", "output"), paths):
        args.extend(["--" + name, str(path)])
    with pytest.raises(SystemExit):
        m.main(args)
    assert m.main(args + ["--synthetic-count", "4"], root=tmp_path) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert m.main(["query", "--index", str(paths[4]), "--gold", str(paths[1]),
                   "--index-sha256", receipt["index"]["sha256"], "--synthetic", "--case-id", "q1"]) == 0
    assert json.loads(capsys.readouterr().out)["cases"][0]["case_id"] == "q1"
