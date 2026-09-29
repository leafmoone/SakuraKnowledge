"""A-evidence tests: occurrence semantics and source_fields bounded projection.

Covers the review items for P2:
  - occurrences are per-dataset (seven-table group) partition rows;
    frequency carries the observed source_count and the raw payload keeps
    the source row, including a NULLABLE sample_count (JSON null must
    survive the round trip as SQL NULL, not 0),
  - source_fields is a bounded projection: only the four whitelisted
    raw_* keys are exposed from identity evidence, anything else is
    dropped, and entries without such raw fields project to {}.
"""
import json
import sqlite3

import pytest

from sakura_knowledge.api import Knowledge
from sakura_knowledge.model import EntryKey
from sakura_knowledge.storage import REQUIRED_SOURCE, build, digest

ALLOWED_SOURCE_FIELDS = {"raw_attributes", "raw_subject_categories",
                         "raw_cv_names", "raw_gender"}


def manifest(tmp_path, records):
    source = tmp_path / "input.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    metadata = dict.fromkeys(REQUIRED_SOURCE)
    metadata.update(source_id="evidence-v1", repo="fixture://local", provider="fixture",
                    dataset_role="test_only", path="input.jsonl",
                    adapter="contract-jsonl-v1", local_sha256=digest(source))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"sources": [metadata]}), encoding="utf-8")
    return path


def test_occurrence_dataset_partition_and_nullable_sample_count(tmp_path):
    record = {
        "key": EntryKey("tag", "local.tag_aggregate", "ev-tag").as_dict(),
        "aliases": [{"text": "ev-tag", "status": "source_backed", "type": "tag_key"}],
        "occurrences": [
            {"group": "anime_pictures_1_noncommon",
             "dataset": "anime_pictures_1_noncommon", "frequency": 3,
             "raw": {"tag_key": "ev-tag", "source_count": 3,
                     "sample_count": None, "category": "general"}},
            {"group": "bangumi_1_noncommon",
             "dataset": "bangumi_1_noncommon", "frequency": 2,
             "raw": {"tag_key": "ev-tag", "source_count": 2,
                     "sample_count": None, "category": "general"}},
        ],
    }
    path = manifest(tmp_path, [record])
    output = tmp_path / "snapshot"
    build(path, output)
    db = output / "knowledge.sqlite"

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT o.dataset, o.group_name, o.frequency, o.payload FROM occurrences o "
        "JOIN entries e ON e.id=o.entry_id WHERE e.value='ev-tag' ORDER BY o.dataset"
    ).fetchall()
    conn.close()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("anime_pictures_1_noncommon", "anime_pictures_1_noncommon", 3),
        ("bangumi_1_noncommon", "bangumi_1_noncommon", 2),
    ]
    for _, _, frequency, payload in rows:
        occ = json.loads(payload)
        # frequency == observed source_count per dataset partition
        assert frequency == occ["raw"]["source_count"]
        # sample_count is nullable: JSON null must round-trip as null
        assert "sample_count" in occ["raw"]
        assert occ["raw"]["sample_count"] is None
        assert json.loads(payload)["dataset"] == occ["dataset"]


def test_occurrence_frequency_validation(tmp_path):
    record = {
        "key": EntryKey("tag", "local.tag_aggregate", "bad-freq").as_dict(),
        "aliases": [{"text": "bad-freq", "status": "source_backed", "type": "tag_key"}],
        "occurrences": [{"group": "anime_pictures_1_noncommon",
                         "dataset": "anime_pictures_1_noncommon",
                         "frequency": "3", "raw": {}}],
    }
    path = manifest(tmp_path, [record])
    with pytest.raises(ValueError, match="verification rejected publication"):
        build(path, tmp_path / "snapshot")
    # an invalid occurrence record is rejected, never published
    assert not (tmp_path / "snapshot").exists()


def test_source_fields_bounded_projection(tmp_path):
    record = {
        "key": EntryKey("character", "moegirl.character", "投影测试").as_dict(),
        "documents": [{"title": "t", "original": "o", "status": "source_backed"}],
        "raw": {
            "raw_attributes": {"height": "165"},
            "raw_gender": "female",
            "raw_subject_categories": ["cat"],
            "raw_cv_names": ["cv-a"],
            "raw_not_whitelisted": "must be dropped",
        },
    }
    empty_record = {
        "key": EntryKey("character", "bangumi.character", "999999").as_dict(),
        "documents": [{"title": "t2", "original": "o2", "status": "source_backed"}],
    }
    path = manifest(tmp_path, [record, empty_record])
    output = tmp_path / "snapshot"
    build(path, output)

    with Knowledge(output / "knowledge.sqlite") as api:
        populated = api.lookup(key=EntryKey("character", "moegirl.character", "投影测试"))
        assert populated["status"] == "found"
        fields = populated["source_fields"]
        assert set(fields) <= ALLOWED_SOURCE_FIELDS
        assert "raw_not_whitelisted" not in fields
        assert fields.get("raw_attributes") == {"height": "165"}
        assert fields.get("raw_gender") == "female"
        # bounded projection drops non-whitelisted keys from source_fields,
        # while the raw payload stays preserved in the entry_evidence row
        # (evidence boundary: raw bytes are never stripped from proofs)
        import sqlite3 as _s
        _conn = _s.connect(output / "knowledge.sqlite")
        _payload = _conn.execute(
            "SELECT payload FROM entry_evidence e JOIN entries t ON t.id=e.entry_id "
            "WHERE t.value='投影测试'").fetchone()[0]
        _conn.close()
        assert "raw_not_whitelisted" in _payload
        assert "raw_not_whitelisted" not in json.dumps(
            populated["source_fields"], ensure_ascii=False)
        # every exposed field is backed by a citation
        assert populated["source_fields_evidence"]

        empty = api.lookup(key=EntryKey("character", "bangumi.character", "999999"))
        assert empty["status"] == "found"
        assert empty["source_fields"] == {}


def test_readonly_open_blocks_writes(tmp_path):
    record = {
        "key": EntryKey("character", "bangumi.character", "只读").as_dict(),
        "documents": [{"title": "t", "original": "o", "status": "source_backed"}],
    }
    path = manifest(tmp_path, [record])
    output = tmp_path / "snapshot"
    build(path, output)
    db = output / "knowledge.sqlite"
    before = digest(db)
    with Knowledge(db) as api:
        assert api.lookup("只读")["status"] == "found"
        with pytest.raises(sqlite3.OperationalError):
            api.conn.execute("DELETE FROM entries")
        with pytest.raises(sqlite3.OperationalError):
            api.conn.execute("INSERT INTO build_meta VALUES ('x','y')")
    assert digest(db) == before


@pytest.mark.parametrize("argv", [["frobnicate"], [], ["search", "db.sqlite"],
                                  ["search", "db.sqlite", "q", "--limit"],
                                  ["lookup", "db.sqlite", "q", "--bogus"]])
def test_cli_usage_error_is_json(argv, capsys):
    from sakura_knowledge.cli import main
    assert main(argv) == 2
    out, err = capsys.readouterr()
    assert out == ""
    body = json.loads(err)
    assert body["error"] == "UsageError"
    assert body["message"].startswith("sknow")


def test_cli_help_still_stdout_exit_0(capsys):
    from sakura_knowledge.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out, err = capsys.readouterr()
    assert out.startswith("usage: sknow") and err == ""
