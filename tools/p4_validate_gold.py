"""Validate and optionally freeze unchanged P4 engineering gold; no model or DB writes."""
import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime

from p4_snapshot_check import EXPECTED_BYTES, EXPECTED_SHA256, ROOT, binding, sidecars

COUNTS = {"lexical": 30, "semantic": 40, "crosslingual": 30, "ambiguous/negative": 20}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(conn, gold):
    """Validate every occurrence, including reverse-direction hard negatives."""
    require(gold["base_snapshot_sha256"] == EXPECTED_SHA256 and
            gold["base_snapshot_bytes"] == EXPECTED_BYTES, "gold snapshot binding mismatch")
    cases = gold["cases"]
    require(dict(Counter(c["subset"] for c in cases)) == COUNTS == gold["subset_counts"],
            "case counts mismatch")
    require(len({c["case_id"] for c in cases}) == 120, "duplicate case IDs")
    anchors, known = [], {}
    for case in cases:
        cid = case["case_id"]
        require(bool(case["query"].strip()), f"{cid}: empty query")
        targets = case["accepted_targets"]
        ids = [a["document_id"] for a in targets]
        negatives = case["candidate_hard_negative_document_ids"]
        require(len(ids) == len(set(ids)), f"{cid}: duplicate targets")
        require(not set(ids) & set(negatives), f"{cid}: negative is accepted target")
        if case.get("case_type") == "constructed_no_identity":
            require(case["subset"] == "ambiguous/negative" and not targets and
                    not negatives and case.get("ranking_metrics") == "N/A",
                    f"{cid}: constructed negative has fake positive or ranking label")
        else:
            require(bool(targets), f"{cid}: missing positive targets")
            if case["subset"] == "ambiguous/negative":
                require(case.get("case_type") == "source_supported_ambiguity" and len(ids) >= 2,
                        f"{cid}: malformed ambiguity")
        for anchor in targets:
            anchors.append((cid, "accepted_target", anchor))
            known.setdefault(anchor["document_id"], anchor)
    for item in gold["candidate_hard_negatives"]:
        anchor, did = item["anchor"], item["document_id"]
        require(did == anchor["document_id"], f"hard-negative {did}: anchor ID mismatch")
        require(item["related_target_document_id"] in known,
                f"hard-negative {did}: related target absent")
        known.setdefault(did, anchor)
        anchors.append((f"candidate_hard_negatives:{did}", "hard_negative", anchor))
    for case in cases:
        for did in case["candidate_hard_negative_document_ids"]:
            require(did in known, f"{case['case_id']}: unanchored hard-negative {did}")
            anchors.append((case["case_id"], "hard_negative", known[did]))
    docs, members = {}, defaultdict(list)
    for did in sorted(known):
        row = conn.execute("SELECT d.*,e.kind,e.namespace,e.value,e.conflicted "
                           "FROM documents d JOIN entries e ON e.id=d.entry_id WHERE d.id=?",
                           (did,)).fetchone()
        docs[did] = dict(row) if row else None
    # Membership-only scan; reject illegal duplicates too. No MATCH or ranking.
    for row in conn.execute("SELECT rowid,document_id,entry_id FROM search_fts"):
        if row[1] in docs:
            members[row[1]].append({"rowid": row[0], "entry_id": row[2]})
    checks = []
    for cid, role, anchor in anchors:
        did = anchor["document_id"]
        prefix = f"{cid}/{role}/document:{did}"
        d = docs[did]
        require(d is not None, f"{prefix}: document missing")
        require(d["conflicted"] == 0 and d["kind"] != "episode", f"{prefix}: illegal entry")
        require(d["status"] in {"source_backed", "generated_from_evidence"},
                f"{prefix}: untrusted document status")
        for key in ("entry_id", "source_id", "evidence_id", "title"):
            require(anchor[key] == d[key], f"{prefix}: {key} mismatch")
        require(anchor["stored_language"] == d["language"], f"{prefix}: language mismatch")
        require(anchor["entry_key"] == {k: d[k] for k in ("kind", "namespace", "value")},
                f"{prefix}: entry key mismatch")
        require(bool(d["source_id"] and d["evidence_id"]), f"{prefix}: missing source/evidence")
        require(conn.execute("SELECT 1 FROM sources WHERE source_id=?",
                             (d["source_id"],)).fetchone(), f"{prefix}: source absent")
        identity = anchor["identity_evidence"]
        require(identity["source_id"] and identity["evidence_id"],
                f"{prefix}: empty identity evidence")
        proof = conn.execute("SELECT v.id FROM entry_evidence v JOIN sources s "
                             "ON s.source_id=v.source_id WHERE v.entry_id=? "
                             "AND v.source_id=? AND v.evidence_id=? AND v.status='source_backed'",
                             (d["entry_id"], identity["source_id"],
                              identity["evidence_id"])).fetchone()
        require(proof, f"{prefix}: identity not source backed")
        require(anchor["original_sha256"] == digest(d["original"]),
                f"{prefix}: original hash mismatch")
        require(anchor["document_text_sha256"] == digest(d["title"] + "\n" + d["original"]),
                f"{prefix}: document text hash mismatch")
        start, excerpt = anchor["excerpt_start"], anchor["excerpt"]
        require(anchor["excerpt_field"] == "original" and type(start) is int and start >= 0
                and bool(excerpt) and d["original"][start:start + len(excerpt)] == excerpt,
                f"{prefix}: excerpt mismatch")
        require(members[did] and all(m["entry_id"] == d["entry_id"] for m in members[did]),
                f"{prefix}: missing or illegal FTS membership")
        checks.append({"case_id": cid, "role": role, "document_id": did, "status": "PASS"})
    proofs = []
    for did, d in sorted(docs.items()):
        proofs.append({"document_id": did, "entry_id": d["entry_id"],
                       "entry_key": {k: d[k] for k in ("kind", "namespace", "value")},
                       "status": d["status"], "conflicted": d["conflicted"],
                       "source_id": d["source_id"], "evidence_id": d["evidence_id"],
                       "identity_evidence": known[did]["identity_evidence"],
                       "document_text_sha256": digest(d["title"] + "\n" + d["original"]),
                       "original_sha256": digest(d["original"]), "fts_rows": members[did]})
    return {"subset_counts": COUNTS, "anchor_checks": checks, "document_proofs": proofs,
            "unique_documents": len(proofs), "anchor_occurrences": len(checks),
            "constructed_negative_cases": [c["case_id"] for c in cases
                                            if c.get("case_type") == "constructed_no_identity"]}


def run(db, gold_path, receipt_path, freeze=False):
    require(not receipt_path.exists(), "receipt already exists; refusing overwrite")
    raw = gold_path.read_bytes()
    gold = json.loads(raw)
    receipt = {"schema_version": "p4-continuation-gold-validation-v1", "status": "STOP",
               "started_at_utc": datetime.now(UTC).isoformat(),
               "gold_input_sha256": hashlib.sha256(raw).hexdigest(),
               "scope": "Engineering benchmark, not full human source-fact review. "
                        "Moegirl/local_tag coverage not required for this authorized freeze. "
                        "Hard negatives are candidates, not proven universally irrelevant.",
               "models_or_embeddings_executed": False, "sqlite_mode": "ro&immutable=1"}
    try:
        before = sidecars(db)
        actual = binding(db)
        receipt["snapshot"] = {"path": str(db), **actual, "sidecars_before": before}
        require(actual["sha256"] == EXPECTED_SHA256 and actual["bytes"] == EXPECTED_BYTES,
                "snapshot SHA256/size mismatch")
        require(not before["-journal"]["exists"] and not before["-wal"].get("bytes", 0),
                "rollback journal or nonempty WAL")
        require(sidecars(db) == before, "sidecars changed while hashing")
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro&immutable=1",
                                     uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            receipt["validation"] = validate(conn, gold)
        after = sidecars(db)
        receipt["snapshot"]["sidecars_after"] = after
        require(after == before and db.stat().st_size == actual["bytes"] and
                db.stat().st_mtime_ns == actual["mtime_ns"], "snapshot changed during validation")
        require(gold_path.read_bytes() == raw, "gold changed during validation")
        if freeze:
            require(gold["status"] == "DRAFT_PRE_EMBEDDING", "gold is not draft")
            old = b'"status": "DRAFT_PRE_EMBEDDING"'
            require(raw.count(old) == 1, "ambiguous draft status token")
            frozen = raw.replace(old, b'"status": "FROZEN_PRE_EMBEDDING"', 1)
            require(json.loads(frozen) == dict(gold, status="FROZEN_PRE_EMBEDDING"),
                    "freeze would change content")
            gold_path.write_bytes(frozen)
            receipt["frozen_gold_sha256"] = hashlib.sha256(frozen).hexdigest()
            receipt["freeze_change"] = "Only top-level status; all other bytes unchanged."
        receipt["status"] = "PASS"
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
        receipt["error"] = str(exc)
    with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    result = run(ROOT / "build/p3-full-authorized-retry1/knowledge.sqlite",
                 ROOT / "reports/P4/retrieval-gold.json",
                 ROOT / "reports/P4/continuation-gold-validation.json", args.freeze)
    print(json.dumps({k: v for k, v in result.items() if k not in {"validation", "snapshot"}},
                     ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
