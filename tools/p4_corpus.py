"""Offline P4 trusted corpus preparation; no models and no source writes.

Export is deliberately exclusive. Inspect emits source text to stdout for local
human gold authoring, never to a public report. All commands hash the snapshot
before opening SQLite. Script labels are heuristics, not language identification.
"""
import argparse
import hashlib
import heapq
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from pathlib import Path

VERSION = "p4-corpus-v1"
SEED = "sakura-p4-pilot-2026-v1"
PILOT_SIZE = 50_000
FLOOR = 100
FAMILIES = ("bangumi", "moegirl", "danbooru", "local_tag")
SCRIPTS = ("kana_present", "han_without_kana", "latin_without_han_kana")
ROOT = Path(__file__).resolve().parents[1]
FIELDS = """d.id AS document_id,d.entry_id,e.kind,e.namespace,e.value,
 d.title,d.original,d.language,d.status,d.source_id,d.evidence_id"""
TRUST = """e.conflicted=0
 AND d.status IN ('source_backed','generated_from_evidence')
 AND e.kind!='episode'
 AND EXISTS (SELECT 1 FROM entry_evidence v
             WHERE v.entry_id=e.id AND v.status='source_backed')"""
SCAN = f"""SELECT {FIELDS} FROM search_fts f
 CROSS JOIN documents d ON d.id=f.document_id
 CROSS JOIN entries e ON e.id=d.entry_id
 WHERE f.entry_id=e.id AND {TRUST} ORDER BY f.rowid"""
IDENTITY_RESOLUTION = {
    "snapshot": "base_snapshot (SHA256 and byte size verified before opening)",
    "reference": "Each document's identity_proof_ref.entry_id binds entry_evidence.entry_id.",
    "sql": "SELECT source_id,evidence_id,status FROM entry_evidence "
           "WHERE entry_id=? AND status='source_backed' ORDER BY id",
    "requirement": "At least one row; source_id resolves in sources in the same snapshot. "
                   "These identity references are distinct from document source/evidence IDs.",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sidecars(path):
    result = {}
    for suffix in ("-wal", "-journal", "-shm"):
        p = Path(str(path) + suffix)
        result[suffix] = p.stat().st_size if p.exists() else None
        if suffix != "-shm" and result[suffix]:
            raise ValueError(f"nonempty SQLite sidecar: {p}")
    return result


@contextmanager
def verified_snapshot(path, expected_sha256, expected_size):
    path = Path(path).resolve(strict=True)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected SHA256 must be lowercase hex")
    before = path.stat()
    state = sidecars(path)
    if before.st_size != expected_size:
        raise ValueError("snapshot size mismatch")
    if sha256_file(path) != expected_sha256:
        raise ValueError("snapshot SHA256 mismatch")
    if ((path.stat().st_size, path.stat().st_mtime_ns) !=
            (before.st_size, before.st_mtime_ns) or sidecars(path) != state):
        raise ValueError("snapshot changed during verification")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    try:
        yield conn, {"sha256": expected_sha256, "size": expected_size,
                     "sidecars": state}
    finally:
        conn.close()
        if ((path.stat().st_size, path.stat().st_mtime_ns) !=
            (before.st_size, before.st_mtime_ns) or sidecars(path) != state):
            raise ValueError("snapshot or sidecars changed during read")


def script_label(text):
    if re.search(r"[\u3040-\u30ff]", text):
        return "kana_present"
    if re.search(r"[\u3400-\u9fff]", text):
        return "han_without_kana"
    if re.search(r"[A-Za-z]", text):
        return "latin_without_han_kana"
    return "other"


def source_metadata(conn):
    return {row[0]: json.loads(row[1]) for row in
            conn.execute("SELECT source_id,metadata FROM sources ORDER BY source_id")}


def family(metadata):
    provider = metadata.get("provider")
    return {"bangumi": "bangumi", "moegirl": "moegirl", "danbooru": "danbooru",
            "tag_wiki": "local_tag"}.get(provider, "other")


def project(row, sources):
    result = dict(row)
    result["entry_key"] = {k: result.pop(k) for k in ("kind", "namespace", "value")}
    sid = result["source_id"]
    if sid not in sources or not result["evidence_id"]:
        raise ValueError("document lacks source/evidence reference")
    result["identity_proof_ref"] = {"entry_id": result["entry_id"],
                                    "status": "source_backed"}
    result["source_metadata_ref"] = f"sources:{sid}"
    result["source_family"] = family(sources[sid])
    result["script_label"] = script_label((result["title"] or "") + "\n" +
                                           (result["original"] or ""))
    return result


def safe_output_path(path, directory):
    root = ROOT.resolve(strict=True)
    allowed = root / directory
    # Check lexical ancestors before resolving, including allowed roots themselves.
    path = Path(os.path.abspath(path))
    for candidate in (allowed, path):
        for ancestor in (candidate, *candidate.parents):
            if ancestor.is_symlink() or os.path.isjunction(ancestor):
                raise ValueError("output symlink/junction ancestors are forbidden")
    if not allowed.resolve().is_relative_to(root):
        raise ValueError("allowed output root escapes project")
    if not path.is_relative_to(allowed) or not path.resolve().is_relative_to(allowed.resolve()):
        raise ValueError(f"output must be under {directory}")
    return path


def eligible(conn, sources):
    # Disk B-tree dedup preserves first FTS rowid order without a FULL-sized set.
    # All scratch writes are local; bounded page cache, no mmap or temp-file spill.
    scratch = safe_output_path(ROOT / "build/p4", "build/p4")
    scratch.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="dedup-", dir=scratch) as work,
        closing(sqlite3.connect(Path(work) / "seen.sqlite")) as seen,
    ):
        seen.execute("PRAGMA journal_mode=OFF")
        seen.execute("PRAGMA temp_store=MEMORY")
        seen.execute("PRAGMA cache_size=-2048")
        seen.execute("PRAGMA mmap_size=0")
        seen.execute("CREATE TABLE seen (id INTEGER PRIMARY KEY)")
        for row in conn.execute(SCAN):
            inserted = seen.execute("INSERT OR IGNORE INTO seen VALUES (?)",
                                    (row["document_id"],)).rowcount
            if inserted:
                yield project(row, sources)


def rank(document):
    payload = [VERSION, SEED, document["entry_key"], document["document_id"]]
    return int.from_bytes(hashlib.sha256(canonical(payload)).digest(), "big")


def retain(heap, capacity, score, doc_id):
    item = (-score, -doc_id)
    if len(heap) < capacity:
        heapq.heappush(heap, item)
    elif item > heap[0]:
        heapq.heapreplace(heap, item)


def ordered(heap):
    return sorted((-score, -doc_id) for score, doc_id in heap)


def load_mandatory(path):
    if path is None:
        return {}, None
    raw = Path(path).read_bytes()
    items = json.loads(raw)
    if not isinstance(items, list):
        raise TypeError("mandatory input must be an explicit JSON array")
    result = {}
    for item in items:
        if (not isinstance(item, dict) or set(item) !=
                {"document_id", "entry_key", "role", "reason"} or
                type(item["document_id"]) is not int or
                item["role"] not in {"gold_target", "hard_negative"} or
                not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise ValueError("invalid mandatory inclusion")
        if item["document_id"] in result:
            raise ValueError("duplicate mandatory document")
        result[item["document_id"]] = item
    return result, hashlib.sha256(raw).hexdigest()


def select(conn, sources, size=PILOT_SIZE, mandatory=None, required_kinds=()):
    if size <= 0:
        raise ValueError("size must be positive")
    mandatory = mandatory or {}
    global_heap, strata = [], defaultdict(list)
    counts = {k: Counter() for k in ("source_family", "script_label", "kind", "language")}
    full_hash, count, found = hashlib.sha256(), 0, {}
    with closing(eligible(conn, sources)) as documents:
        for doc in documents:
            count += 1
            full_hash.update(canonical(doc) + b"\n")
            score, did = rank(doc), doc["document_id"]
            retain(global_heap, size, score, did)
            for field in ("source_family", "script_label", "kind"):
                label = doc["entry_key"]["kind"] if field == "kind" else doc[field]
                if (field == "kind" or
                        label in (FAMILIES if field == "source_family" else SCRIPTS)):
                    retain(strata[(field, label)], FLOOR, score, did)
                counts[field][label] += 1
            counts["language"][doc["language"] or "unspecified"] += 1
            if did in mandatory:
                if mandatory[did]["entry_key"] != doc["entry_key"]:
                    raise ValueError("mandatory entry key mismatch")
                found[did] = score
    if set(found) != set(mandatory):
        raise ValueError("mandatory documents not eligible")
    for field, labels in (("source_family", FAMILIES), ("script_label", SCRIPTS),
                          ("kind", required_kinds)):
        for label in labels:
            if not counts[field][label]:
                raise ValueError(f"missing required stratum: {field}:{label}")
    if count < size:
        raise ValueError(f"insufficient eligible unique documents: {count} < {size}")
    selected, reasons = dict(found), defaultdict(list)
    for did in found:
        reasons[did].append("mandatory:" + mandatory[did]["role"])
    for (field, label), heap in sorted(strata.items()):
        for score, did in ordered(heap):
            selected[did] = score
            reasons[did].append(f"floor:{field}:{label}")
    if len(selected) > size:
        raise ValueError("mandatory inclusions and fixed floors exceed pilot size")
    for score, did in ordered(global_heap):
        if len(selected) == size:
            break
        if did not in selected:
            selected[did] = score
            reasons[did].append("global_bottom_k")
    ids = sorted(selected, key=lambda did: (selected[did], did))
    return ids, reasons, {"eligible_count": count, "eligible_sha256": full_hash.hexdigest(),
                          "eligible_hash_order": "first consistent FTS rowid per document",
                          "eligible_strata": counts}


def fetch(conn, did, sources):
    row = conn.execute(f"SELECT {FIELDS} FROM documents d JOIN entries e "
                       "ON e.id=d.entry_id WHERE d.id=?", (did,)).fetchone()
    return project(row, sources)


def contained_output(path, directory):
    path = safe_output_path(path, directory)
    if path.exists():
        raise FileExistsError(path)
    return path


def export(conn, binding, corpus, manifest, mandatory_path=None, required_kinds=()):
    corpus = contained_output(corpus, "build/p4")
    manifest = contained_output(manifest, "reports/P4")
    mandatory, mandatory_hash = load_mandatory(mandatory_path)
    sources = source_metadata(conn)
    ids, reasons, audit = select(conn, sources, size=PILOT_SIZE, mandatory=mandatory,
                                 required_kinds=required_kinds)
    selected_counts = {k: Counter() for k in
                       ("source_family", "script_label", "kind", "language")}
    corpus.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    # Reserve both names exclusively; failures intentionally leave partial files
    # as failure evidence, never replace an existing corpus or receipt.
    with corpus.open("xb") as out, manifest.open("xb") as receipt:
        h = hashlib.sha256()
        for did in ids:
            doc = fetch(conn, did, sources)
            for field, counts in selected_counts.items():
                label = (doc["entry_key"]["kind"] if field == "kind" else doc[field])
                counts[label or "unspecified"] += 1
            doc["selection_reasons"] = reasons[did]
            line = canonical(doc) + b"\n"
            out.write(line)
            h.update(line)
        report = {"version": VERSION, "seed": SEED, "base_snapshot": binding,
                  "index_episodes": False, "selected_count": len(ids),
                  "corpus_sha256": h.hexdigest(), "corpus_path": str(corpus.relative_to(ROOT)),
                  "rank_rule": "SHA256(canonical JSON [version,seed,typed entry key,document ID])",
                  "selected_order": "rank ascending, document ID ascending",
                  "source_family_floor": FLOOR, "script_floor": FLOOR, "kind_floor": FLOOR,
                  "required_families": FAMILIES, "required_scripts": SCRIPTS,
                  "required_kinds": sorted(set(required_kinds)),
                  "identity_proof_resolution": IDENTITY_RESOLUTION,
                  "family_provider_map": {"bangumi": "bangumi", "moegirl": "moegirl",
                                          "danbooru": "danbooru", "tag_wiki": "local_tag"},
                  "selected_strata": selected_counts, "sources": sources,
                  "mandatory_input_sha256": mandatory_hash,
                  "mandatory_inclusions": list(mandatory.values()),
                  "embedding_fields": ["title", "original"],
                  "limitations": ["Script labels are heuristic, not authoritative languages.",
                                  "Observed kinds receive floors; absent kinds are not inferred.",
                                  "Floors use min(100, available); infeasible unions fail.",
                                  "No model/vector-based sampling."], **audit}
        receipt.write(canonical(report) + b"\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--size", type=int, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    exp = commands.add_parser("export", help="exclusive 50,000-document local pilot export")
    exp.add_argument("--corpus", type=Path, required=True)
    exp.add_argument("--manifest", type=Path, required=True)
    exp.add_argument("--mandatory", type=Path)
    exp.add_argument("--required-kind", action="append", default=[],
                     help="require a nonempty eligible kind (repeatable; no inferred population)")
    inspect = commands.add_parser("inspect", help="local source excerpts for human gold authoring")
    inspect.add_argument("--document-id", type=int, action="append")
    inspect.add_argument("--family", choices=FAMILIES)
    inspect.add_argument("--kind")
    inspect.add_argument("--contains", help="literal case-insensitive title/original filter")
    inspect.add_argument("--limit", type=int, default=20)
    inspect.add_argument("--excerpt-chars", type=int, default=2000)
    args = parser.parse_args(argv)
    if args.command == "inspect" and (args.limit <= 0 or args.excerpt_chars <= 0):
        parser.error("limit and excerpt-chars must be positive")
    with verified_snapshot(args.snapshot, args.sha256, args.size) as (conn, binding):
        if args.command == "export":
            report = export(conn, binding, args.corpus, args.manifest, args.mandatory,
                            args.required_kind)
            print(json.dumps({"selected_count": report["selected_count"],
                              "corpus_sha256": report["corpus_sha256"]}))
        else:
            sources, emitted = source_metadata(conn), 0
            with closing(eligible(conn, sources)) as documents:
                for doc in documents:
                    if args.document_id and doc["document_id"] not in args.document_id:
                        continue
                    if args.family and doc["source_family"] != args.family:
                        continue
                    if args.kind and doc["entry_key"]["kind"] != args.kind:
                        continue
                    text = (doc["title"] or "") + "\n" + (doc["original"] or "")
                    if args.contains and args.contains.casefold() not in text.casefold():
                        continue
                    doc["original_sha256"] = hashlib.sha256(
                        (doc["original"] or "").encode()).hexdigest()
                    doc["original_characters"] = len(doc["original"] or "")
                    doc["original"] = (doc["original"] or "")[:args.excerpt_chars]
                    doc["excerpt_start"] = 0
                    doc["source_metadata"] = sources[doc["source_id"]]
                    doc["base_snapshot"] = binding
                    doc["identity_proof_resolution"] = IDENTITY_RESOLUTION
                    print(canonical(doc).decode())
                    emitted += 1
                    if emitted == args.limit:
                        break


if __name__ == "__main__":
    main()
