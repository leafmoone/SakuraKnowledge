"""Prepare-time guards for the local lexical pilot; no retrieval or source writes."""

import hashlib
import os
import re
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path

from tools.p4_retrieval_metrics import EntryKey


def _plain_path(path):
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        # Reparse points include Windows junctions (also on Python before 3.12).
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & 0x400):
            raise ValueError("symlink/junction path is forbidden: " + str(part))


def safe_output_path(path, root):
    """Return an absolute path strictly below repository root/build/p4.

    Relative paths use the process working directory. No directories are created.
    Root itself and every existing ancestor are checked before resolving anything.
    This is an accidental-misuse guard, not a hostile-concurrent-mutation sandbox.
    """
    path, root = Path(path), Path(root)
    if ".." in path.parts or ".." in root.parts:
        raise ValueError("parent traversal is forbidden")
    path, root = path.absolute(), root.absolute()
    _plain_path(root)
    _plain_path(path)
    allowed = root / "build" / "p4"
    if path == allowed or not path.is_relative_to(allowed):
        raise ValueError("output must be below build/p4")
    return path


@contextmanager
def new_index(path, root):
    """Yield a create-new SQLite connection; caller explicitly commits.

    Keep the exclusive reservation open until SQLite closes; never reopen with
    create permissions. samestat checks detect accidental path replacement, but
    do not promise protection against hostile concurrent filesystem mutation.
    Failed builds are retained and cannot silently be reused or overwritten.
    """
    path = safe_output_path(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_output_path(path, root)
    for suffix in ("-journal", "-wal", "-shm"):
        if os.path.lexists(str(path) + suffix):
            raise ValueError("existing SQLite sidecar: " + str(path) + suffix)
    with path.open("xb") as reservation:
        def check():
            safe_output_path(path, root)
            if not os.path.samestat(os.fstat(reservation.fileno()), path.stat()):
                raise ValueError("index reservation changed")

        check()
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn:
            check()
            try:
                yield conn
            finally:
                check()
        check()


def _id(value):
    if type(value) is not int or value <= 0:
        raise ValueError("positive integer document/entry ID required")
    return value


def _key(value):
    if not isinstance(value, dict) or set(value) != {"kind", "namespace", "value"}:
        raise ValueError("typed entry key required")
    return EntryKey(**value)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("lowercase SHA256 required")
    return value


def _anchor_shape(anchor):
    if not isinstance(anchor, dict):
        raise ValueError("anchor object required")  # noqa: TRY004 -- invalid JSON input
    _id(anchor["document_id"])
    _id(anchor["entry_id"])
    _key(anchor["entry_key"])
    for field in ("source_id", "evidence_id", "title"):
        if not isinstance(anchor[field], str) or (field != "title" and not anchor[field].strip()):
            raise ValueError("invalid anchor " + field)
    if "status" in anchor and anchor["status"] not in ("source_backed", "generated_from_evidence"):
        raise ValueError("invalid anchor status")
    for field in ("original_sha256", "document_text_sha256"):
        _sha(anchor[field])


def gold_anchors(gold, source):
    """Return document ID -> all anchor occurrences, without discarding conflicts.

    Case hard negatives may refer to either accepted or top-level negative
    anchors, including reverse-direction references. The caller must validate
    every occurrence against the corpus and reject IDs missing from the pilot.
    Source is the export manifest's base_snapshot {sha256, size} mapping.
    """
    if gold["status"] != "FROZEN_PRE_EMBEDDING":
        raise ValueError("gold must be FROZEN_PRE_EMBEDDING")
    if (_sha(gold["base_snapshot_sha256"]) != _sha(source["sha256"]) or
            type(gold["base_snapshot_bytes"]) is not int or
            type(source["size"]) is not int or source["size"] <= 0 or
            gold["base_snapshot_bytes"] != source["size"]):
        raise ValueError("gold snapshot binding mismatch")
    anchors = {}
    accepted = set()

    def add(anchor):
        _anchor_shape(anchor)
        anchors.setdefault(anchor["document_id"], []).append(anchor)

    for case in gold["cases"]:
        ids = []
        for anchor in case["accepted_targets"]:
            add(anchor)
            ids.append(anchor["document_id"])
        negatives = [_id(did) for did in case["candidate_hard_negative_document_ids"]]
        if len(set(ids)) != len(ids) or set(ids) & set(negatives):
            raise ValueError("duplicate accepted target or accepted hard negative")
        accepted.update(ids)
    for item in gold["candidate_hard_negatives"]:
        anchor = item["anchor"]
        add(anchor)
        if (_id(item["document_id"]) != anchor["document_id"] or
                _id(item["related_target_document_id"]) not in accepted):
            raise ValueError("hard-negative anchor reference mismatch")
    for case in gold["cases"]:
        for did in case["candidate_hard_negative_document_ids"]:
            if did not in anchors:
                raise ValueError("unanchored hard-negative reference")
    return anchors


def validate_anchor(anchor, doc):
    """Compare one frozen anchor with an already source-verified corpus document."""
    _anchor_shape(anchor)
    if _id(doc["document_id"]) != anchor["document_id"]:
        raise ValueError("anchor document_id mismatch")
    if _id(doc["entry_id"]) != anchor["entry_id"]:
        raise ValueError("anchor entry_id mismatch")
    if _key(anchor["entry_key"]) != _key(doc["entry_key"]):
        raise ValueError("anchor typed entry key mismatch")
    for field in ("source_id", "evidence_id", "title", "status"):
        if field in anchor and anchor[field] != doc[field]:
            raise ValueError("anchor " + field + " mismatch")
    if not isinstance(doc["original"], str) or not isinstance(doc["title"], str):
        raise ValueError("document text must be strings")  # noqa: TRY004 -- invalid JSON input
    for field, text in (("original_sha256", doc["original"]),
                        ("document_text_sha256", doc["title"] + "\n" + doc["original"])):
        if anchor[field] != hashlib.sha256(text.encode("utf-8")).hexdigest():
            raise ValueError("anchor " + field + " mismatch")
