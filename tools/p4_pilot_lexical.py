"""Offline pilot-only lexical harness. No benchmark is run by importing this module.

prepare copies only frozen pilot documents into a new local FTS5 database and
attests exact/alias pins against a hash-verified, immutable source snapshot.
query returns JSON arithmetic inputs, not identity-resolution assertions.
Raw document depth is 100 BEFORE dedup, matching p4_retrieval_metrics.Hit.
This depth convention is explicit: it need not yield 100 distinct entries.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import unicodedata
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sakura_knowledge.model import match_query, search_text
from tools.p4_corpus import canonical, sha256_file, verified_snapshot
from tools.p4_lexical_guards import gold_anchors, new_index, safe_output_path, validate_anchor
from tools.p4_retrieval_metrics import RELEVANCE_WARNING, EntryKey, Hit, TrustedPin

VERSION = "p4-pilot-lexical-v1"
DEPTH = 100
FTS_SCHEMA = "CREATE VIRTUAL TABLE search_fts USING fts5(text, document_id UNINDEXED, entry_id UNINDEXED)"
CONFIG = {
    "version": VERSION, "fts_schema": FTS_SCHEMA,
    "tokenizer": "FTS5 default unicode61 remove_diacritics=1",
    "text": "search_text((title + SPACE + original)[:100000])",
    "query": "model.match_query: NFKC/casefold, CJK bigrams, quoted OR",
    "document_depth": DEPTH, "depth_before_entry_dedup": True,
    "ties": "score ASC, kind ASC, namespace ASC, value ASC, document_id ASC",
    "pins": "verbatim value or source_backed alias; trusted nonconflicted pilot entries only; typed-key order",
    "pin_depth": "all pins retained separately; final ranking capped at 100",
    "identity_assertions": "none; ambiguity is never collapsed",
    "sqlite_version": sqlite3.sqlite_version, "unicode_version": unicodedata.unidata_version,
    "model_sha256": sha256_file(ROOT / "src/sakura_knowledge/model.py"),
}


def binding(path):
    return {"sha256": sha256_file(path), "size": Path(path).stat().st_size}


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def key_tuple(key):
    return tuple(asdict(EntryKey(**key)).values())


def load_gold(path):
    raw = Path(path).read_bytes()
    gold = json.loads(raw)
    cases = gold["cases"]
    ids = [c["case_id"] for c in cases]
    if (not cases or any(not isinstance(cid, str) or not cid for cid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("gold requires unique nonempty case_id values")
    for case in cases:
        if not isinstance(case["query"], str) or not 1 <= len(case["query"]) <= 4096:
            raise ValueError("query must contain 1..4096 characters")
        match_query(case["query"])
    return gold, {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def prepare(corpus, gold, manifest, snapshot, output, *, expected_count=50_000, root=ROOT):
    """Create-new index. Small expected_count is for explicit synthetic tests only.

    The export manifest is the frozen corpus/snapshot binding. Gold labels do not
    influence indexing, pin eligibility, query interpretation, or ranking.
    """
    corpus, gold, manifest, snapshot, output = map(Path, (corpus, gold, manifest, snapshot, output))
    output = safe_output_path(output, root)
    report_raw = manifest.read_bytes()
    report = json.loads(report_raw)
    corpus_binding = binding(corpus)
    gold_data, gold_binding = load_gold(gold)
    if corpus_binding["sha256"] != report["corpus_sha256"]:
        raise ValueError("corpus SHA256 mismatch")
    if report["selected_count"] != expected_count or expected_count <= 0:
        raise ValueError("unexpected pilot size")
    source = report["base_snapshot"]
    anchors = gold_anchors(gold_data, source)
    metadata = {
        "version": VERSION, "corpus": corpus_binding, "gold": gold_binding,
        "manifest": {"sha256": hashlib.sha256(report_raw).hexdigest(), "size": len(report_raw)},
        "snapshot": {k: source[k] for k in ("sha256", "size")},
        "config": CONFIG, "config_sha256": digest(CONFIG), "document_count": expected_count,
    }
    metadata["binding_sha256"] = digest(metadata)
    with (
        verified_snapshot(snapshot, source["sha256"], source["size"]) as (src, _),
        new_index(output, root) as dst,
    ):
        dst.executescript(FTS_SCHEMA + ";" + """
            CREATE TABLE documents(document_id INTEGER PRIMARY KEY, entry_id INTEGER,
                kind TEXT, namespace TEXT, value TEXT, source_id TEXT, evidence_id TEXT);
            CREATE TABLE pins(text TEXT, entry_id INTEGER, kind TEXT, namespace TEXT,
                value TEXT, match TEXT, source_id TEXT, evidence_id TEXT);
            CREATE INDEX pins_text ON pins(text);
            CREATE TABLE metadata(value TEXT NOT NULL);
        """)
        entries = {}
        count = 0
        checksum = hashlib.sha256()
        with corpus.open("rb") as stream:
            for raw in stream:
                checksum.update(raw)
                doc = json.loads(raw)
                did, eid = doc["document_id"], doc["entry_id"]
                key = key_tuple(doc["entry_key"])
                if type(did) is not int or type(eid) is not int:
                    raise ValueError("integer document/entry IDs required")
                if (key[0] == "episode" or doc["status"] not in
                        ("source_backed", "generated_from_evidence")):
                    raise ValueError("untrusted corpus document")
                # Verify source-backed identity and the exact exported text mapping;
                # a tampered JSONL cannot fabricate trusted pins or document evidence.
                row = src.execute("""SELECT d.*,e.kind,e.namespace,e.value,e.conflicted
                    FROM documents d JOIN entries e ON e.id=d.entry_id WHERE d.id=?""", (did,)).fetchone()
                if (row is None or row["conflicted"] or row["entry_id"] != eid
                        or tuple(row[k] for k in ("kind", "namespace", "value")) != key
                        or any(row[k] != doc[k] for k in
                               ("title", "original", "status", "source_id", "evidence_id"))):
                    raise ValueError("corpus/source document mismatch")
                if eid not in entries:
                    proofs = src.execute("""SELECT v.source_id,v.evidence_id FROM entry_evidence v
                        JOIN sources s ON s.source_id=v.source_id
                        WHERE v.entry_id=? AND v.status='source_backed' ORDER BY v.id""", (eid,)).fetchall()
                    if not proofs:
                        raise ValueError("missing trusted identity evidence")
                    entries[eid] = key
                    for proof in proofs:
                        pin = TrustedPin(EntryKey(*key), "exact", *proof)
                        dst.execute("INSERT INTO pins VALUES(?,?,?,?,?,?,?,?)",
                                    (key[2], eid, *key, pin.match, pin.source_id, pin.evidence_id))
                    for alias in src.execute("""SELECT a.text,a.source_id,a.evidence_id FROM aliases a
                        JOIN sources s ON s.source_id=a.source_id
                        WHERE a.entry_id=? AND a.status='source_backed' ORDER BY a.id""", (eid,)):
                        pin = TrustedPin(EntryKey(*key), "alias", alias["source_id"], alias["evidence_id"])
                        if not isinstance(alias["text"], str) or not alias["text"]:
                            raise ValueError("invalid trusted alias")
                        dst.execute("INSERT INTO pins VALUES(?,?,?,?,?,?,?,?)",
                                    (alias["text"], eid, *key, pin.match, pin.source_id, pin.evidence_id))
                elif entries[eid] != key:
                    raise ValueError("inconsistent entry mapping")
                for field in ("title", "original", "source_id", "evidence_id"):
                    if not isinstance(doc[field], str):
                        raise TypeError("invalid document field: " + field)
                for anchor in anchors.pop(did, ()):
                    validate_anchor(anchor, doc)
                text = search_text((doc["title"] + " " + doc["original"])[:100_000])
                dst.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)",
                            (did, eid, *key, doc["source_id"], doc["evidence_id"]))
                dst.execute("INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES(?,?,?,?)",
                            (did, text, did, eid))
                count += 1
        if count != expected_count or checksum.hexdigest() != corpus_binding["sha256"]:
            raise ValueError("corpus changed or incorrect document count")
        if anchors:
            raise ValueError('gold anchor documents missing from pilot')
        dst.execute("INSERT INTO search_fts(search_fts) VALUES('integrity-check')")
        dst.execute("INSERT INTO metadata VALUES(?)", (canonical(metadata).decode("utf-8"),))
        dst.commit()
    return {"metadata": metadata, "index": binding(output)}


def query_case(conn, case):
    query = case["query"]
    if not isinstance(query, str) or not 1 <= len(query) <= 4096:
        raise ValueError("query must contain 1..4096 characters")
    compiled = match_query(query)
    pins = []
    for row in conn.execute("""SELECT DISTINCT kind,namespace,value,match,source_id,evidence_id
            FROM pins WHERE text=? ORDER BY kind,namespace,value,match,source_id,evidence_id""", (query,)):
        pins.append(TrustedPin(EntryKey(*row[:3]), *row[3:]))
    hits = []
    if compiled:
        rows = conn.execute("""SELECT d.kind,d.namespace,d.value,bm25(search_fts) AS score,
                d.document_id,d.source_id,d.evidence_id FROM search_fts
                JOIN documents d ON d.document_id=search_fts.document_id
                WHERE search_fts MATCH ?
                ORDER BY score,d.kind,d.namespace,d.value,d.document_id LIMIT ?""", (compiled, DEPTH))
        for rank, row in enumerate(rows, 1):
            hits.append(Hit(EntryKey(*row[:3]), rank, row[3], str(row[4]),
                            source_id=row[5], evidence_id=row[6]))
    lexical = list(dict.fromkeys(hit.entry for hit in hits))
    trusted = sorted({pin.entry for pin in pins})
    ranking = list(dict.fromkeys([*trusted, *lexical]))[:DEPTH]
    warnings = [RELEVANCE_WARNING]
    if len(trusted) > 1:
        warnings.append("multiple_trusted_identities_preserved_not_resolved")
    if len(trusted) > DEPTH:
        warnings.append("ranking_truncated_all_trusted_pins_retained_separately")
    if not compiled:
        warnings.append("no_fts_tokens")
    return {
        "case_id": case["case_id"], "query_id": case["case_id"], "query": query,
        "subset": case.get("subset"), "mode": "BM25_ONLY",
        "metric_subset": ('ambiguous_negative' if case.get('subset') == 'ambiguous/negative'
                          else case.get('subset')),
        "raw_hits": [asdict(hit) for hit in hits],
        "lexical_ranking": [asdict(key) for key in lexical],
        "trusted_pins": [asdict(pin) for pin in pins],
        "ranking": [asdict(key) for key in ranking],
        "document_hits": [hit.document_id for hit in hits],
        "identity_status": "not_asserted", "promoted_identities": [],
        "trusted_identity_keys": [asdict(key) for key in trusted], "warnings": warnings,
    }


def query(index, gold, *, expected_index_sha256, case_ids=None):
    gold_data, gold_binding = load_gold(gold)
    index = Path(index)
    with verified_snapshot(index, expected_index_sha256, index.stat().st_size) as (conn, _):
        # Tuple rows simplify construction of the metric-library dataclasses.
        conn.row_factory = None
        metadata = json.loads(conn.execute("SELECT value FROM metadata").fetchone()[0])
        unbound = {k: v for k, v in metadata.items() if k != "binding_sha256"}
        if metadata["binding_sha256"] != digest(unbound):
            raise ValueError("metadata binding mismatch")
        if metadata["config"] != CONFIG or metadata["config_sha256"] != digest(CONFIG):
            raise ValueError("index/runtime configuration mismatch")
        if metadata["gold"] != gold_binding:
            raise ValueError("gold binding mismatch")
        cases = {case["case_id"]: case for case in gold_data["cases"]}
        selected = sorted(cases if case_ids is None else case_ids)
        if len(set(selected)) != len(selected) or any(cid not in cases for cid in selected):
            raise ValueError("unknown or duplicate case ID")
        return {"schema": VERSION, "metadata": metadata,
                "index_sha256": expected_index_sha256,
                "measurement": "quality inputs only; NOT a formal latency benchmark",
                "cases": [query_case(conn, cases[cid]) for cid in selected]}


def main(argv=None, *, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    for name in ("corpus", "gold", "manifest", "snapshot", "output"):
        prep.add_argument("--" + name, type=Path, required=True)
    prep.add_argument("--synthetic-count", type=int)
    prep.add_argument("--authorized-frozen", action="store_true",
                      help="parent authorized this frozen gold/pilot; not granted by this tool")
    run = commands.add_parser("query")
    run.add_argument("--index", type=Path, required=True)
    run.add_argument("--gold", type=Path, required=True)
    run.add_argument("--index-sha256", required=True)
    run.add_argument("--case-id", action="append")
    run.add_argument("--authorized-frozen", action="store_true")
    run.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        if not args.authorized_frozen and args.synthetic_count is None:
            parser.error("real prepare requires parent authorization and frozen gold/pilot")
        result = prepare(args.corpus, args.gold, args.manifest, args.snapshot, args.output,
                         expected_count=50_000 if args.synthetic_count is None else args.synthetic_count,
                         root=root)
    else:
        if not args.authorized_frozen and not args.synthetic:
            parser.error("real queries require parent authorization and frozen gold/pilot")
        result = query(args.index, args.gold, expected_index_sha256=args.index_sha256,
                       case_ids=args.case_id)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
