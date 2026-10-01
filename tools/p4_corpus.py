"""Read-only trusted-text census, deterministic quota pilot, and local gold inspection.

Export is exclusive. Inspect emits text locally, never to a public report.
All snapshot reads verify SHA256 before SQL and again after closing SQLite.
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

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/p4-trusted-text-v1.json"
VERSION = "p4-trusted-text-v1"
RANK_RULE = "SHA256(seed + ':' + str(document_id))"
FAMILIES = ("bangumi", "moegirl", "danbooru", "local_tag")
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
 WHERE f.entry_id=e.id AND f.text=d.search_text AND {TRUST} ORDER BY f.rowid"""
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


def load_config(path=DEFAULT_CONFIG):
    raw = Path(path).read_bytes()
    config = json.loads(raw)
    if (config["version"] != VERSION or config["index_episodes"] is not False or
            config["rank_rule"] != RANK_RULE or not isinstance(config["seed"], str) or
            not config["seed"].strip() or not config["strata"]):
        raise ValueError("invalid trusted-text configuration")
    identities = set()
    for spec in config["strata"].values():
        key = tuple(spec[k] for k in ("source_family", "kind", "namespace"))
        if key in identities or spec["kind"] == "episode":
            raise ValueError("duplicate or episode stratum")
        identities.add(key)
        if any(type(spec[k]) is not int or spec[k] <= 0
               for k in ("eligible_count", "pilot_quota")):
            raise ValueError("stratum counts must be positive integers")
        if spec["pilot_quota"] > spec["eligible_count"]:
            raise ValueError("quota exceeds census")
    for total, field in (("eligible_total", "eligible_count"), ("pilot_size", "pilot_quota")):
        if config[total] != sum(s[field] for s in config["strata"].values()):
            raise ValueError("configuration total mismatch")
    return config, hashlib.sha256(raw).hexdigest()


def sidecars(path):
    result = {}
    for suffix in ("-wal", "-journal", "-shm"):
        p = Path(str(path) + suffix)
        if not p.exists():
            result[suffix] = None
            continue
        stat = p.stat()
        if suffix != "-shm" and stat.st_size:
            raise ValueError(f"nonempty SQLite sidecar: {p}")
        result[suffix] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                          "sha256": sha256_file(p)}
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
        yield conn, {"sha256": expected_sha256, "size": expected_size, "sidecars": state}
    finally:
        conn.close()
        if (sha256_file(path) != expected_sha256 or
                (path.stat().st_size, path.stat().st_mtime_ns) !=
                (before.st_size, before.st_mtime_ns) or sidecars(path) != state):
            raise ValueError("snapshot or sidecars changed during read")


def check_policy(conn):
    policy = conn.execute("SELECT value FROM build_meta WHERE key='index_episodes'").fetchone()
    if policy is None or policy[0] != "false":
        raise ValueError("index_episodes policy must be false")


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
    return {"bangumi": "bangumi", "moegirl": "moegirl", "danbooru": "danbooru",
            "tag_wiki": "local_tag"}.get(metadata.get("provider"), "other")


def project(row, sources):
    result = dict(row)
    result["entry_key"] = {k: result.pop(k) for k in ("kind", "namespace", "value")}
    sid = result["source_id"]
    if sid not in sources or not result["evidence_id"]:
        raise ValueError("document lacks source/evidence reference")
    result["identity_proof_ref"] = {"entry_id": result["entry_id"], "status": "source_backed"}
    result["source_metadata_ref"] = f"sources:{sid}"
    result["source_family"] = family(sources[sid])
    result["script_label"] = script_label((result["title"] or "") + "\n" +
                                           (result["original"] or ""))
    return result


def safe_output_path(path, directory):
    root = ROOT.resolve(strict=True)
    allowed = root / directory
    path = Path(os.path.abspath(path))
    for candidate in (allowed, path):
        for ancestor in (candidate, *candidate.parents):
            if ancestor.is_symlink() or getattr(os.path, "isjunction", lambda p: False)(ancestor):
                raise ValueError("output symlink/junction ancestors are forbidden")
    if not allowed.resolve().is_relative_to(root):
        raise ValueError("allowed output root escapes project")
    if not path.is_relative_to(allowed) or not path.resolve().is_relative_to(allowed.resolve()):
        raise ValueError(f"output must be under {directory}")
    return path


def eligible(conn, sources):
    check_policy(conn)
    # Disk B-tree dedup: bounded cache and no FULL-sized Python membership set.
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


def stratum(doc, config):
    key = (doc["source_family"], doc["entry_key"]["kind"], doc["entry_key"]["namespace"])
    for name, spec in config["strata"].items():
        if key == tuple(spec[k] for k in ("source_family", "kind", "namespace")):
            return name
    raise ValueError(f"unexpected eligible stratum: {key}")


def rank(document, seed):
    return int.from_bytes(hashlib.sha256(
        f"{seed}:{document['document_id']}".encode()).digest(), "big")


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


def verify_census(counts, config):
    expected = {name: spec["eligible_count"] for name, spec in config["strata"].items()}
    if dict(counts) != expected or sum(counts.values()) != config["eligible_total"]:
        raise ValueError(f"trusted-text census mismatch: observed={dict(counts)}, expected={expected}")


def select(conn, sources, config=None, mandatory=None):
    config = config if config is not None else load_config()[0]
    mandatory = mandatory or {}
    heaps = {name: [] for name in config["strata"]}
    census, found = Counter(), {}
    counts = {k: Counter() for k in ("source_family", "script_label", "kind", "language")}
    full_hash = hashlib.sha256()
    with closing(eligible(conn, sources)) as documents:
        for doc in documents:
            name = stratum(doc, config)
            census[name] += 1
            full_hash.update(canonical(doc) + b"\n")
            score, did = rank(doc, config["seed"]), doc["document_id"]
            retain(heaps[name], config["strata"][name]["pilot_quota"], score, did)
            for field, labels in counts.items():
                label = doc["entry_key"]["kind"] if field == "kind" else doc[field]
                labels[label or "unspecified"] += 1
            if did in mandatory:
                if mandatory[did]["entry_key"] != doc["entry_key"]:
                    raise ValueError("mandatory entry key mismatch")
                found[did] = (name, score)
    if set(found) != set(mandatory):
        raise ValueError("mandatory documents not eligible")
    verify_census(census, config)
    selected, reasons, replacements = {}, defaultdict(list), []
    for name, heap in sorted(heaps.items()):
        ordinary = {did: score for score, did in ordered(heap)}
        required = {did: score for did, (label, score) in found.items() if label == name}
        if len(required) > config["strata"][name]["pilot_quota"]:
            raise ValueError(f"mandatory inclusions exceed quota: {name}")
        # Remove only worst-ranked nonmandatory rows, never cross stratum boundaries.
        victims = sorted((score, did) for did, score in ordinary.items() if did not in required)
        for did in sorted(required, key=lambda d: (required[d], d)):
            if did not in ordinary:
                _, removed = victims.pop()
                del ordinary[removed]
                ordinary[did] = required[did]
                replacements.append({"stratum": name, "included_document_id": did,
                                     "removed_document_id": removed,
                                     "role": mandatory[did]["role"],
                                     "reason": mandatory[did]["reason"]})
        for did, score in ordinary.items():
            selected[did] = score
            reasons[did].append(f"quota:{name}")
            if did in required:
                reasons[did].extend(["mandatory:" + mandatory[did]["role"],
                                     mandatory[did]["reason"]])
            else:
                reasons[did].append("stratum_bottom_k")
    ids = sorted(selected, key=lambda did: (selected[did], did))
    return ids, reasons, {"eligible_count": sum(census.values()),
                          "eligible_sha256": full_hash.hexdigest(),
                          "eligible_hash_order": "first consistent FTS rowid per document",
                          "eligible_census": census, "eligible_strata": counts,
                          "mandatory_replacements": replacements}


def fetch(conn, did, sources):
    row = conn.execute(f"SELECT {FIELDS} FROM documents d JOIN entries e "
                       "ON e.id=d.entry_id WHERE d.id=?", (did,)).fetchone()
    return project(row, sources)


def contained_output(path, directory):
    path = safe_output_path(path, directory)
    if path.exists():
        raise FileExistsError(path)
    return path


def export(conn, binding, corpus, manifest, mandatory_path=None, config_path=DEFAULT_CONFIG):
    corpus = contained_output(corpus, "build/p4")
    manifest = contained_output(manifest, "reports/P4")
    config, config_hash = load_config(config_path)
    if any(binding[k] != config["snapshot"][k] for k in ("sha256", "size")):
        raise ValueError("configuration snapshot binding mismatch")
    mandatory, mandatory_hash = load_mandatory(mandatory_path)
    sources = source_metadata(conn)
    ids, reasons, audit = select(conn, sources, config, mandatory)
    selected_counts, selected_census = defaultdict(Counter), Counter()
    corpus.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    # Failed corpus data remains evidence; manifest published after post-read checks.
    with corpus.open("xb") as out:
        h = hashlib.sha256()
        for did in ids:
            doc = fetch(conn, did, sources)
            selected_census[stratum(doc, config)] += 1
            for field in ("source_family", "script_label", "kind", "language"):
                label = doc["entry_key"]["kind"] if field == "kind" else doc[field]
                selected_counts[field][label or "unspecified"] += 1
            doc["selection_reasons"] = reasons[did]
            line = canonical(doc) + b"\n"
            out.write(line)
            h.update(line)
        quotas = {name: spec["pilot_quota"] for name, spec in config["strata"].items()}
        if dict(selected_census) != quotas or len(ids) != config["pilot_size"]:
            raise ValueError("selected quota mismatch")
        report = {"version": VERSION, "seed": config["seed"], "base_snapshot": binding,
                  "config_sha256": config_hash, "configuration": config,
                  "index_episodes": False, "selected_count": len(ids),
                  "corpus_sha256": h.hexdigest(), "corpus_path": str(corpus.relative_to(ROOT)),
                  "rank_rule": RANK_RULE, "selected_order": "rank ascending, document ID ascending",
                  "selected_census": selected_census, "selected_strata": selected_counts,
                  "identity_proof_resolution": IDENTITY_RESOLUTION, "sources": sources,
                  "mandatory_input_sha256": mandatory_hash,
                  "mandatory_inclusions": list(mandatory.values()),
                  "semantic_ineligible": config["semantic_ineligible"],
                  "embedding_fields": ["title", "original"],
                  "limitations": ["Script labels are heuristic, not authoritative languages.",
                                  "No model/vector-based sampling."], **audit}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--size", type=int, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    exp = commands.add_parser("export", help="exclusive quota pilot export")
    exp.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    exp.add_argument("--corpus", type=Path, required=True)
    exp.add_argument("--manifest", type=Path, required=True)
    exp.add_argument("--mandatory", type=Path, required=True)
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
            report = export(conn, binding, args.corpus, args.manifest, args.mandatory, args.config)
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
    if args.command == "export":
        manifest = contained_output(args.manifest, "reports/P4")
        with manifest.open("xb") as receipt:
            receipt.write(canonical(report) + b"\n")
        print(json.dumps({"selected_count": report["selected_count"],
                          "corpus_sha256": report["corpus_sha256"]}))


if __name__ == "__main__":
    main()
