"""Synthetic tests: never access the FULL snapshot."""
import copy
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from sakura_knowledge.storage import SCHEMA

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("p4_validate_gold", TOOLS / "p4_validate_gold.py")
p4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p4)
sys.path.pop(0)


@pytest.fixture
def sample(tmp_path):
    db = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO sources VALUES('source','{}')")
    anchors = []
    for did in (1, 2):
        conn.execute("INSERT INTO entries(id,kind,namespace,value) VALUES(?,'page','test',?)",
                     (did, str(did)))
        conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                     "VALUES(?,'source','identity','source_backed','{}')", (did,))
        conn.execute("INSERT INTO documents(id,entry_id,title,original,search_text,status,"
                     "source_id,evidence_id,payload) VALUES(?,?,'title','text','text',"
                     "'source_backed','source','document','{}')", (did, did))
        conn.execute("INSERT INTO search_fts VALUES('text',?,?)", (did, did))
        anchors.append({"document_id": did, "entry_id": did, "entry_key": {
            "kind": "page", "namespace": "test", "value": str(did)},
            "title": "title", "source_id": "source", "evidence_id": "document",
            "identity_evidence": {"source_id": "source", "evidence_id": "identity"},
            "stored_language": None, "original_sha256": p4.digest("text"),
            "document_text_sha256": p4.digest("title\ntext"), "excerpt_start": 0,
            "excerpt_field": "original", "excerpt": "text"})
    cases = []
    for subset, count in p4.COUNTS.items():
        for _ in range(count):
            case = {"case_id": f"case-{len(cases)}", "subset": subset, "query": "question",
                    "accepted_targets": [copy.deepcopy(anchors[0])],
                    "candidate_hard_negative_document_ids": [2]}
            if subset == "ambiguous/negative":
                case.update(case_type="constructed_no_identity", accepted_targets=[],
                            candidate_hard_negative_document_ids=[], ranking_metrics="N/A")
            cases.append(case)
    gold = {"status": "DRAFT_PRE_EMBEDDING", "base_snapshot_sha256": p4.EXPECTED_SHA256,
            "base_snapshot_bytes": p4.EXPECTED_BYTES, "subset_counts": p4.COUNTS,
            "cases": cases, "candidate_hard_negatives": [{"document_id": 2,
            "related_target_document_id": 1, "anchor": anchors[1]}]}
    conn.commit()
    yield db, conn, gold
    conn.close()


def test_all_anchor_roles(sample):
    _, conn, gold = sample
    result = p4.validate(conn, gold)
    assert result["unique_documents"] == 2
    assert result["anchor_occurrences"] == 201
    assert len(result["constructed_negative_cases"]) == 20


@pytest.mark.parametrize("sql,error", [
    ("UPDATE entries SET conflicted=1 WHERE id=2", "illegal entry"),
    ("UPDATE entries SET kind='episode' WHERE id=2", "illegal entry"),
    ("UPDATE documents SET status='no_reference' WHERE id=2", "untrusted"),
    ("UPDATE documents SET original='changed' WHERE id=2", "original hash"),
    ("DELETE FROM entry_evidence WHERE entry_id=2", "identity not source backed"),
    ("DELETE FROM sources", "source absent"),
    ("DELETE FROM search_fts WHERE document_id=2", "FTS membership"),
    ("INSERT INTO search_fts VALUES('bad',2,99)", "FTS membership"),
])
def test_bad_hard_negative_stops(sample, sql, error):
    _, conn, gold = sample
    conn.execute("PRAGMA foreign_keys=OFF")  # Deliberately corrupt a synthetic boundary.
    conn.execute(sql)
    with pytest.raises(ValueError, match=error):
        p4.validate(conn, gold)


@pytest.mark.parametrize("field,value,error", [
    ("excerpt", "invented", "excerpt mismatch"),
    ("document_text_sha256", "0" * 64, "document text hash"),
    ("evidence_id", "wrong", "evidence_id mismatch"),
    ("entry_key", {}, "entry key mismatch"),
])
def test_repeated_anchor_independently_checked(sample, field, value, error):
    _, conn, gold = sample
    gold["cases"][5]["accepted_targets"][0][field] = value
    with pytest.raises(ValueError, match=f"case-5.*{error}"):
        p4.validate(conn, gold)


def test_negative_cannot_have_fake_positive(sample):
    _, conn, gold = sample
    gold["cases"][-1]["accepted_targets"] = gold["cases"][0]["accepted_targets"]
    with pytest.raises(ValueError, match="fake positive"):
        p4.validate(conn, gold)


def test_counts(sample):
    _, conn, gold = sample
    gold["cases"].pop()
    with pytest.raises(ValueError, match="counts"):
        p4.validate(conn, gold)


def test_freeze_only_status_and_receipt(sample, tmp_path, monkeypatch):
    db, _, gold = sample
    actual = p4.binding(db)
    monkeypatch.setattr(p4, "EXPECTED_SHA256", actual["sha256"])
    monkeypatch.setattr(p4, "EXPECTED_BYTES", actual["bytes"])
    gold.update(base_snapshot_sha256=actual["sha256"], base_snapshot_bytes=actual["bytes"])
    path, receipt = tmp_path / "gold.json", tmp_path / "receipt.json"
    raw = json.dumps(gold, ensure_ascii=False, indent=2).encode()
    path.write_bytes(raw)
    result = p4.run(db, path, receipt, freeze=True)
    assert result["status"] == "PASS", result
    assert path.read_bytes() == raw.replace(b'DRAFT_PRE_EMBEDDING', b'FROZEN_PRE_EMBEDDING')
    assert result["frozen_gold_sha256"] == p4.binding(path)["sha256"]
    assert p4.binding(db) == actual
    with pytest.raises(ValueError, match="already exists"):
        p4.run(db, path, receipt, freeze=True)


def test_wrong_snapshot_never_freezes(sample, tmp_path):
    db, _, gold = sample
    path, receipt = tmp_path / "gold.json", tmp_path / "receipt.json"
    raw = json.dumps(gold).encode()
    path.write_bytes(raw)
    result = p4.run(db, path, receipt, freeze=True)
    assert result["status"] == "STOP"
    assert "snapshot SHA256/size" in result["error"]
    assert path.read_bytes() == raw
