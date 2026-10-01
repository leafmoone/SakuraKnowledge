"""Static checks of unchanged engineering labels, now source-validated and frozen."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA256 = "61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9"
COUNTS = {"lexical": 30, "semantic": 40, "crosslingual": 30, "ambiguous/negative": 20}


@pytest.fixture(scope="module")
def draft():
    # Read only the checked-in artifact; never import/run the authoring tool.
    text = (ROOT / "reports/P4/retrieval-gold.json").read_text(encoding="utf-8")
    assert "\ufffd" not in text
    report = json.loads(text)
    assert "\ufffd" not in json.dumps(report, ensure_ascii=False)
    return report


def test_draft_metadata_and_base_receipt(draft):
    assert draft["schema_version"] == "p4-source-gold-v1"
    assert draft["status"] == "FROZEN_PRE_EMBEDDING"
    raw = (ROOT / 'reports/P4/retrieval-gold.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        'ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba')
    assert draft["base_snapshot_sha256"] == BASE_SHA256
    assert draft["base_snapshot_bytes"] == 21718736896
    assert draft["baseline_receipt"] == "reports/P4/initial-snapshot-check.json"
    receipt = json.loads((ROOT / draft["baseline_receipt"]).read_text(encoding="utf-8"))
    baseline = json.loads(receipt["stdout"])
    assert receipt["status"] == baseline["status"] == "PASS"
    assert baseline["sha256"] == draft["base_snapshot_sha256"]
    assert baseline["bytes"] == draft["base_snapshot_bytes"]


def test_draft_counts_queries_and_target_roles(draft):
    cases = draft["cases"]
    assert len(cases) == 120
    assert draft["subset_counts"] == COUNTS
    assert Counter(case["subset"] for case in cases) == COUNTS
    assert [case["case_id"] for case in cases] == [f"P4-{i:03d}" for i in range(1, 121)]
    ambiguous = [case for case in cases if case["subset"] == "ambiguous/negative"]
    assert Counter(case["case_type"] for case in ambiguous) == {
        "source_supported_ambiguity": 10, "constructed_no_identity": 10,
    }
    for case in cases:
        assert isinstance(case["query"], str) and case["query"].strip()
        assert case["query_language"] in {"zh", "ja", "en"}
        targets = [anchor["document_id"] for anchor in case["accepted_targets"]]
        negatives = case["candidate_hard_negative_document_ids"]
        assert len(targets) == len(set(targets))
        assert all(type(did) is int and did > 0 for did in negatives)
        assert not set(targets) & set(negatives)
        if case["subset"] != "ambiguous/negative":
            assert len(targets) == 1
        elif case["case_type"] == "source_supported_ambiguity":
            assert len(targets) == 2
            assert case["accepted_set_scope"].strip()
            assert case["label_reason"].strip()
        else:
            assert targets == []
            assert case["ranking_metrics"] == "N/A"
            assert case["expected_behavior"].strip()
            assert case["label_reason"].strip()


def test_draft_anchor_and_source_key_schema(draft):
    anchors = [anchor for case in draft["cases"] for anchor in case["accepted_targets"]]
    assert len(anchors) == 120
    hard_negatives = draft["candidate_hard_negatives"]
    assert len(hard_negatives) == 10
    target_ids = {anchor["document_id"] for anchor in anchors}
    for negative in hard_negatives:
        assert negative["document_id"] == negative["anchor"]["document_id"]
        assert negative["related_target_document_id"] in target_ids
        assert negative["inspection_reason"].strip()
        anchors.append(negative["anchor"])
    seen = {}
    for anchor in anchors:
        for key in ("document_id", "entry_id"):
            assert type(anchor[key]) is int and anchor[key] > 0
        entry_key = anchor["entry_key"]
        assert set(entry_key) == {"kind", "namespace", "value"}
        assert all(isinstance(value, str) and value.strip() for value in entry_key.values())
        assert entry_key["kind"] != "episode"
        identity = anchor["identity_evidence"]
        assert set(identity) == {"source_id", "evidence_id"}
        for evidence in (anchor, identity):
            for key in ("source_id", "evidence_id"):
                assert isinstance(evidence[key], str) and evidence[key].strip()
        assert anchor["title"].strip()
        assert 0 < len(anchor["excerpt"]) <= 650
        assert anchor["excerpt_field"] == "original"
        assert anchor["excerpt_start"] == 0
        assert anchor["source_language"] in {"zh", "ja", "en"}
        assert anchor["stored_language"] is None
        assert anchor["language_uncertainty"].strip()
        for key in ("document_text_sha256", "original_sha256"):
            assert re.fullmatch(r"[0-9a-f]{64}", anchor[key])
        # Prefix anchors cannot independently authenticate full original-text hashes.
        assert seen.setdefault(anchor["document_id"], anchor) == anchor
