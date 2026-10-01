"""Synthetic-only filesystem and frozen-anchor guard tests."""

import copy
import hashlib
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import p4_lexical_guards as g


def document(did=1):
    return {"document_id": did, "entry_id": did + 10,
            "entry_key": {"kind": "tag", "namespace": "synthetic", "value": str(did)},
            "source_id": "source", "evidence_id": "evidence", "title": "Title 青空",
            "original": "café\r\nNo normalization.", "status": "source_backed"}


def anchor(doc):
    result = {k: copy.deepcopy(v) for k, v in doc.items() if k != "original"}
    result["original_sha256"] = hashlib.sha256(doc["original"].encode()).hexdigest()
    result["document_text_sha256"] = hashlib.sha256(
        (doc["title"] + "\n" + doc["original"]).encode()).hexdigest()
    return result


def frozen():
    a, b = anchor(document()), anchor(document(2))
    return {"status": "FROZEN_PRE_EMBEDDING", "base_snapshot_sha256": "a" * 64,
            "base_snapshot_bytes": 123,
            "cases": [{"accepted_targets": [a], "candidate_hard_negative_document_ids": [2]},
                      {"accepted_targets": [b], "candidate_hard_negative_document_ids": [1]},
                      {"accepted_targets": [], "candidate_hard_negative_document_ids": []}],
            "candidate_hard_negatives": [{"document_id": 2, "anchor": copy.deepcopy(b),
                                          "related_target_document_id": 1}]}


SOURCE = {"sha256": "a" * 64, "size": 123}


def test_safe_path_no_creation_and_relative(tmp_path, monkeypatch):
    output = tmp_path / "build/p4/deep/index.sqlite"
    assert g.safe_output_path(output, tmp_path) == output
    assert not output.parent.exists()
    monkeypatch.chdir(tmp_path)
    assert g.safe_output_path("build/p4/deep/index.sqlite", ".") == output


@pytest.mark.parametrize("name", ["index.sqlite", "build/p3/index.sqlite", "build/p4",
                                      "build/p4-other/index.sqlite", "build/p4/../index.sqlite"])
def test_path_rejects_escape(tmp_path, name):
    with pytest.raises(ValueError):
        g.safe_output_path(tmp_path / name, tmp_path)
    assert not (tmp_path / "build").exists()


def symlink(link, target, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"symlink privilege unavailable: {exc}")


@pytest.mark.parametrize("position", ["root", "ancestor", "build", "p4", "nested", "leaf", "dangling"])
def test_rejects_symlink_components(tmp_path, position):
    real = tmp_path / "real"
    real.mkdir()
    if position in ("root", "ancestor"):
        link = tmp_path / "link"
        symlink(link, real, True)
        root = link if position == "root" else link / "repo"
        output = root / "build/p4/index.sqlite"
    else:
        root = real
        parts = {"build": "build", "p4": "build/p4", "nested": "build/p4/nested",
                 "leaf": "build/p4/index.sqlite", "dangling": "build/p4/index.sqlite"}
        link = root / parts[position]
        link.parent.mkdir(parents=True, exist_ok=True)
        target = tmp_path / "target"
        if position != "dangling":
            target.mkdir()
        symlink(link, target, position not in ("leaf", "dangling"))
        output = link if position in ("leaf", "dangling") else link / "index.sqlite"
        if position == "build":
            output = link / "p4/index.sqlite"
    with pytest.raises(ValueError, match="symlink/junction"):
        g.safe_output_path(output, root)


def test_reparse_attribute_rejected(tmp_path, monkeypatch):
    real_lstat = Path.lstat

    def lstat(path, *args, **kwargs):
        if path == tmp_path:
            return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError, match="symlink/junction"):
        g.safe_output_path(tmp_path / "build/p4/x", tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_windows_junction(tmp_path):
    target, link = tmp_path / "target", tmp_path / "junction"
    target.mkdir()
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True, check=False)
    if result.returncode:
        pytest.skip("junction creation unavailable")
    try:
        with pytest.raises(ValueError, match="symlink/junction"):
            g.safe_output_path(link / "build/p4/index.sqlite", link)
    finally:
        link.rmdir()


def test_new_index_rw_reservation_lifetime_and_commit(tmp_path, monkeypatch):
    output = tmp_path / "build/p4/space # percent%.sqlite"
    real_connect, real_open = sqlite3.connect, Path.open
    reservations = []
    calls = []

    def open_file(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        if args == ("xb",):
            reservations.append(stream)
        return stream

    def connect(database, **kwargs):
        assert reservations and not reservations[0].closed
        assert os.path.samestat(os.fstat(reservations[0].fileno()), output.stat())
        assert database == output.as_uri() + "?mode=rw"
        assert kwargs == {"uri": True}
        calls.append(database)
        return real_connect(database, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(g.sqlite3, "connect", connect)
    with g.new_index(output, tmp_path) as conn:
        assert not reservations[0].closed
        conn.execute("CREATE TABLE synthetic(value)")
        conn.execute("INSERT INTO synthetic VALUES(7)")
        conn.commit()
    assert len(calls) == 1 and reservations[0].closed
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with closing(real_connect(output)) as saved:
        assert saved.execute("SELECT value FROM synthetic").fetchone() == (7,)
    before = output.read_bytes()
    with pytest.raises(FileExistsError), g.new_index(output, tmp_path):
        pass
    assert output.read_bytes() == before


def test_new_index_failure_keeps_reservation_and_closes(tmp_path):
    output = tmp_path / "build/p4/failed.sqlite"
    with pytest.raises(RuntimeError, match="synthetic failure"), g.new_index(output, tmp_path) as conn:
        raise RuntimeError("synthetic failure")
    assert output.exists()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with pytest.raises(FileExistsError), g.new_index(output, tmp_path):
        pass


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_sidecars_refused(tmp_path, suffix):
    output = tmp_path / "build/p4/index.sqlite"
    output.parent.mkdir(parents=True)
    sidecar = Path(str(output) + suffix)
    sidecar.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="sidecar"), g.new_index(output, tmp_path):
        pass
    assert not output.exists()
    assert sidecar.read_bytes() == b"synthetic"


def test_samestat_checked_before_sqlite(tmp_path, monkeypatch):
    output = tmp_path / "build/p4/index.sqlite"
    monkeypatch.setattr(g.os.path, "samestat", lambda a, b: False)
    with pytest.raises(ValueError, match="reservation changed"), g.new_index(output, tmp_path):
        pass
    assert output.read_bytes() == b""


def test_all_anchor_occurrences_and_reverse_negative_coverage():
    gold = frozen()
    anchors = g.gold_anchors(gold, SOURCE)
    assert set(anchors) == {1, 2}
    assert len(anchors[2]) == 2
    for did, occurrences in anchors.items():
        for item in occurrences:
            g.validate_anchor(item, document(did))
    # Do not discard an inconsistent repeated anchor via setdefault/dedup.
    gold["candidate_hard_negatives"][0]["anchor"]["title"] = "different"
    occurrences = g.gold_anchors(gold, SOURCE)[2]
    g.validate_anchor(occurrences[0], document(2))
    with pytest.raises(ValueError, match="title"):
        g.validate_anchor(occurrences[1], document(2))


@pytest.mark.parametrize("field,value", [("status", "DRAFT_PRE_EMBEDDING"),
    ("base_snapshot_sha256", "b" * 64), ("base_snapshot_sha256", "A" * 64),
    ("base_snapshot_bytes", 124), ("base_snapshot_bytes", True), ("base_snapshot_bytes", "123")])
def test_gold_binding_rejected(field, value):
    gold = frozen()
    gold[field] = value
    with pytest.raises(ValueError):
        g.gold_anchors(gold, SOURCE)


@pytest.mark.parametrize("source", [{"sha256": "bad", "size": 123},
    {"sha256": "a" * 64, "size": True}, {"sha256": "a" * 64, "size": 0}])
def test_invalid_source_binding(source):
    with pytest.raises(ValueError):
        g.gold_anchors(frozen(), source)


@pytest.mark.parametrize("change", ["missing", "id_mismatch", "related", "bool", "overlap", "duplicate"])
def test_bad_reference_coverage(change):
    gold = frozen()
    case = gold["cases"][0]
    if change == "missing":
        case["candidate_hard_negative_document_ids"] = [99]
    elif change == "id_mismatch":
        gold["candidate_hard_negatives"][0]["document_id"] = 99
    elif change == "related":
        gold["candidate_hard_negatives"][0]["related_target_document_id"] = 99
    elif change == "bool":
        case["candidate_hard_negative_document_ids"] = [True]
    elif change == "overlap":
        case["candidate_hard_negative_document_ids"] = [1]
    else:
        case["accepted_targets"] *= 2
    with pytest.raises(ValueError):
        g.gold_anchors(gold, SOURCE)


@pytest.mark.parametrize("field,value", [("document_id", True), ("entry_id", "11"),
    ("entry_id", 0), ("entry_key", {"kind": "tag", "namespace": "", "value": "1"}),
    ("entry_key", {"kind": "tag", "namespace": "synthetic", "value": 1}),
    ("entry_key", {"kind": "tag", "namespace": "synthetic", "value": "1", "extra": "x"}),
    ("source_id", ""), ("evidence_id", None), ("title", 1), ("status", "unverified_draft"),
    ("original_sha256", "bad"), ("document_text_sha256", "A" * 64)])
def test_anchor_types_rejected(field, value):
    gold = frozen()
    item = gold["cases"][0]["accepted_targets"][0]
    item[field] = value
    with pytest.raises(ValueError):
        g.gold_anchors(gold, SOURCE)
    with pytest.raises(ValueError):
        g.validate_anchor(item, document())


@pytest.mark.parametrize("field,value", [("document_id", 2), ("entry_id", 12),
    ("entry_key", {"kind": "tag", "namespace": "other", "value": "1"}),
    ("entry_key", {"kind": "character", "namespace": "synthetic", "value": "1"}),
    ("source_id", "other"), ("evidence_id", "other"), ("title", "other"),
    ("status", "generated_from_evidence"), ("original", "café\nNo normalization."),
    ("original", "cafe\u0301\r\nNo normalization."), ("original", None)])
def test_document_mismatches(field, value):
    doc = document()
    item = anchor(doc)
    doc[field] = value
    with pytest.raises(ValueError):
        g.validate_anchor(item, doc)


def test_optional_status_and_both_hashes():
    doc = document()
    item = anchor(doc)
    del item["status"]
    g.validate_anchor(item, doc)
    for field in ("original_sha256", "document_text_sha256"):
        bad = dict(item, **{field: "0" * 64})
        with pytest.raises(ValueError, match=field):
            g.validate_anchor(bad, doc)
    item["document_text_sha256"] = hashlib.sha256(
        (doc["title"] + " " + doc["original"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="document_text_sha256"):
        g.validate_anchor(item, doc)
