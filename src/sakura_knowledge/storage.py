"""Locked JSONL contract importer; a directory is published only after verification."""
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import tomllib
from contextlib import closing
from pathlib import Path

from . import CONTRACT_VERSION, SEARCH_TEXT_VERSION
from .model import GROUPS, STATUSES, TRUSTED, EntryKey, search_text

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE sources(source_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
CREATE TABLE entries(id INTEGER PRIMARY KEY, kind TEXT, namespace TEXT, value TEXT,
 type TEXT, locator TEXT, conflicted INTEGER NOT NULL DEFAULT 0, UNIQUE(kind,namespace,value));
CREATE TABLE entry_evidence(id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries,
 source_id TEXT NOT NULL REFERENCES sources, evidence_id TEXT NOT NULL, status TEXT NOT NULL,
 type TEXT, locator TEXT, payload TEXT NOT NULL);
CREATE TABLE aliases(id INTEGER PRIMARY KEY, entry_id INTEGER REFERENCES entries,
 text TEXT, language TEXT, type TEXT, status TEXT, source_id TEXT REFERENCES sources,
 evidence_id TEXT, payload TEXT);
CREATE TABLE documents(id INTEGER PRIMARY KEY, entry_id INTEGER REFERENCES entries,
 title TEXT, original TEXT, search_text TEXT, language TEXT, status TEXT,
 source_id TEXT REFERENCES sources, evidence_id TEXT, payload TEXT);
CREATE TABLE occurrences(id INTEGER PRIMARY KEY, entry_id INTEGER REFERENCES entries,
 source_id TEXT REFERENCES sources, evidence_id TEXT, dataset TEXT, group_name TEXT,
 frequency INTEGER, payload TEXT);
CREATE TABLE links(id INTEGER PRIMARY KEY, src INTEGER REFERENCES entries,
 dst INTEGER REFERENCES entries, relation TEXT, source_id TEXT REFERENCES sources,
 evidence_id TEXT, method TEXT, verification_status TEXT, payload TEXT);
CREATE TABLE build_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE VIRTUAL TABLE search_fts USING fts5(text, document_id UNINDEXED, entry_id UNINDEXED);
CREATE INDEX alias_exact ON aliases(text,status);
CREATE INDEX entry_evidence_entry ON entry_evidence(entry_id,status);
CREATE INDEX link_src ON links(src,relation);
CREATE TABLE source_counts(source_id TEXT PRIMARY KEY REFERENCES sources, input INTEGER NOT NULL,
 accepted INTEGER NOT NULL, rejected INTEGER NOT NULL, conflicted INTEGER NOT NULL,
 duplicate INTEGER NOT NULL, unresolved INTEGER NOT NULL, by_kind TEXT NOT NULL);
CREATE TABLE seen_fingerprints(source_id TEXT NOT NULL, fingerprint BLOB NOT NULL,
 PRIMARY KEY(source_id,fingerprint)) WITHOUT ROWID;
CREATE TABLE pending_links(source_id TEXT NOT NULL, line INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE unresolved_records(source_id TEXT NOT NULL REFERENCES sources,
 line INTEGER NOT NULL, payload TEXT NOT NULL);
"""
REQUIRED_SOURCE = {"source_id", "provider", "dataset_role", "repo", "upstream_revision",
                   "asset_name", "upstream_digest", "local_sha256", "source_declared_cutoff",
                   "exported_at", "fetched_at_utc", "inspected_at_utc", "schema_version",
                   "importer_version", "mapping_generator_revision", "input_file_inventory",
                   "counts", "source_references", "refresh_status", "code_license", "data_license",
                   "path", "adapter"}


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode()) if path.suffix == ".toml" else json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise TypeError("manifest sources must be an array")
    if type(data.get("index_episodes", False)) is not bool:
        raise ValueError("index_episodes must be boolean")
    seen = set()
    for source in data["sources"]:
        if not isinstance(source, dict):
            raise TypeError("source must be an object")
        missing = REQUIRED_SOURCE - source.keys()
        if missing:
            raise ValueError(f"source metadata missing: {sorted(missing)}")
        if not isinstance(source["source_id"], str) or not source["source_id"]:
            raise ValueError("invalid source_id")
        if source["source_id"] in seen:
            raise ValueError("duplicate source_id")
        if not isinstance(source["repo"], str) or not isinstance(source["path"], str):
            raise TypeError("repo and path must be strings")
        if not isinstance(source["local_sha256"], str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", source["local_sha256"]):
            raise ValueError("local_sha256 must be a SHA256 hex digest")
        seen.add(source["source_id"])
        if "://" in source["repo"] and "@" in source["repo"].split("://", 1)[1]:
            raise ValueError("credential-bearing repo forbidden")
        source["path"] = str((path.parent / source["path"]).resolve())
    if not seen:
        raise ValueError("manifest has no sources")
    allowed = data.get("allow_unresolved_reasons", [])
    if (not isinstance(allowed, list) or any(reason not in
            {"missing_endpoint", "unresolved_wiki_link"} for reason in allowed)):
        raise ValueError("unsupported unresolved-record policy")
    return data, hashlib.sha256(raw).hexdigest()


def readonly(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def verify(path):
    with closing(readonly(path)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign = list(conn.execute("PRAGMA foreign_key_check"))
        index_episodes = conn.execute(
            "SELECT value FROM build_meta WHERE key='index_episodes'").fetchone()[0] == "true"
        expected = conn.execute(
            "SELECT count(*) FROM documents d JOIN entries e ON e.id=d.entry_id "
            "WHERE d.status IN ('source_backed','generated_from_evidence') "
            "AND (? OR e.kind != 'episode')", (index_episodes,)).fetchone()[0]
        fts = conn.execute("SELECT count(*) FROM search_fts").fetchone()[0]
        invalid = conn.execute(
            "SELECT count(*) FROM search_fts f LEFT JOIN documents d ON d.id=f.document_id "
            "LEFT JOIN entries e ON e.id=d.entry_id WHERE d.id IS NULL OR e.id!=f.entry_id "
            "OR f.text!=d.search_text OR d.status NOT IN "
            "('source_backed','generated_from_evidence') OR (NOT ? AND e.kind='episode')",
            (index_episodes,)).fetchone()[0]
        missing = conn.execute(
            "SELECT count(*) FROM documents d JOIN entries e ON e.id=d.entry_id "
            "WHERE d.status IN ('source_backed','generated_from_evidence') "
            "AND (? OR e.kind!='episode') AND (SELECT count(*) FROM search_fts f "
            "WHERE f.document_id=d.id)!=1", (index_episodes,)).fetchone()[0]
        accounts = []
        for row in conn.execute("SELECT s.source_id,c.* FROM sources s LEFT JOIN source_counts c "
                                "ON c.source_id=s.source_id"):
            if (row["input"] is None or row["input"] != sum(row[k] for k in
                ("accepted", "rejected", "conflicted", "duplicate", "unresolved"))):
                accounts.append(row["source_id"])
                continue
            stored = conn.execute(
                "SELECT (SELECT count(*) FROM entry_evidence WHERE source_id=?) + "
                "(SELECT count(*) FROM links WHERE source_id=?) + "
                "(SELECT count(*) FROM unresolved_records WHERE source_id=?)",
                (row["source_id"], row["source_id"], row["source_id"])).fetchone()[0]
            kinds = {kind: count for kind, count in conn.execute(
                "SELECT e.kind,count(*) FROM entry_evidence v JOIN entries e ON e.id=v.entry_id "
                "WHERE v.source_id=? GROUP BY e.kind", (row["source_id"],))}
            if (stored != row["accepted"] + row["conflicted"] + row["unresolved"]
                    or kinds != json.loads(row["by_kind"])):
                accounts.append(row["source_id"])
        unresolved_reasons = {reason: amount for reason, amount in conn.execute(
            "SELECT json_extract(payload,'$.reason'),count(*) FROM unresolved_records "
            "GROUP BY json_extract(payload,'$.reason')")}
        return {"ok": integrity == "ok" and not foreign and not invalid and not missing
                and fts == expected and not accounts, "integrity": integrity,
                "foreign_key_errors": len(foreign), "fts_documents": fts,
                "fts_expected": expected, "fts_invalid": invalid, "fts_missing": missing,
                "source_account_errors": accounts,
                "unresolved_reasons": unresolved_reasons,
                "entries": conn.execute("SELECT count(*) FROM entries").fetchone()[0]}


def entry_id(conn, key, create=False, record=None):
    key = EntryKey(**key)
    if create:
        record = record or {}
        conn.execute("INSERT OR IGNORE INTO entries(kind,namespace,value,type,locator) "
                     "VALUES(?,?,?,?,?)", (*key.parts(), record.get("type", key.kind),
                                          record.get("locator")))
    row = conn.execute("SELECT id FROM entries WHERE kind=? AND namespace=? AND value=?",
                       key.parts()).fetchone()
    return row[0] if row else None


def evidence(item, fallback):
    status = item.get("status", "no_reference")
    if status not in STATUSES:
        raise ValueError("unknown evidence status")
    ref = item.get("evidence_id", fallback)
    if not isinstance(ref, str) or not ref:
        raise ValueError("empty evidence locator")
    return status, ref


def insert_record(conn, record, source, line, index_episodes):
    sid = source["source_id"]
    fallback = f"{sid}:{source['local_sha256']}:line:{line}"
    if record.get("record_type") == "link":
        src = entry_id(conn, record["src"])
        dst = entry_id(conn, record["dst"])
        if src is None or dst is None:
            conn.execute("INSERT INTO unresolved_records VALUES(?,?,?)",
                         (sid, line, json.dumps({**record, "reason": "missing_endpoint"},
                                                ensure_ascii=False)))
            return "unresolved"
        verification = record.get("verification_status", "candidate")
        if verification not in {"native", "redirect", "candidate", "verified", "conflict"}:
            raise ValueError("unknown link verification status")
        if (record["relation"] == "entity_tag" and verification == "verified"
                and record["dst"]["kind"] != "tag"):
            raise ValueError("entity_tag destination must be tag")
        conn.execute("INSERT INTO links(src,dst,relation,source_id,evidence_id,method,"
                     "verification_status,payload) VALUES(?,?,?,?,?,?,?,?)",
                     (src, dst, record["relation"], sid, fallback, record["method"],
                      verification, json.dumps(record, ensure_ascii=False)))
        return "conflicted" if verification == "conflict" else "accepted"
    if record.get("record_type") == "unresolved":
        conn.execute("INSERT INTO unresolved_records VALUES(?,?,?)",
                     (sid, line, json.dumps(record, ensure_ascii=False)))
        return "unresolved"
    eid = entry_id(conn, record["key"], True, record)
    previous = conn.execute("SELECT type,locator,conflicted FROM entries WHERE id=?", (eid,)).fetchone()
    conflict = any(previous[field] is not None and record.get(field) is not None
                   and previous[field] != record[field] for field in ("type", "locator"))
    if conflict:
        conn.execute("UPDATE entries SET conflicted=1 WHERE id=?", (eid,))
    supporting = any(item.get("status", "no_reference") in TRUSTED
                     for group in ("aliases", "documents") for item in record.get(group, []))
    status = record.get("status", "source_backed" if supporting or not any(
        record.get(group) for group in ("aliases", "documents")) else "unverified_draft")
    if status not in STATUSES:
        raise ValueError("unknown entry status")
    metadata = {k: v for k, v in record.items()
                if k not in {"aliases", "documents", "occurrences"}}
    conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,type,locator,"
                 "payload) VALUES(?,?,?,?,?,?,?)",
                 (eid, sid, record.get("evidence_id", fallback),
                  "conflict" if conflict else status, record.get("type", record["key"]["kind"]),
                  record.get("locator"), json.dumps(metadata, ensure_ascii=False)))
    for alias in record.get("aliases", []):
        status, ref = evidence(alias, fallback)
        conn.execute("INSERT INTO aliases(entry_id,text,language,type,status,source_id,"
                     "evidence_id,payload) VALUES(?,?,?,?,?,?,?,?)",
                     (eid, alias["text"], alias.get("language"), alias.get("type"), status,
                      sid, ref, json.dumps(alias, ensure_ascii=False)))
    for doc in record.get("documents", []):
        status, ref = evidence(doc, fallback)
        original = doc.get("original", "")
        text = (search_text(doc.get("title", "") + " " + original)
                if status in TRUSTED else "")
        cur = conn.execute("INSERT INTO documents(entry_id,title,original,search_text,language,"
                           "status,source_id,evidence_id,payload) VALUES(?,?,?,?,?,?,?,?,?)",
                           (eid, doc.get("title", ""), original, text, doc.get("language"),
                            status, sid, ref, json.dumps(doc, ensure_ascii=False)))
        if status in TRUSTED and (record["key"]["kind"] != "episode" or index_episodes):
            conn.execute("INSERT INTO search_fts VALUES(?,?,?)", (text, cur.lastrowid, eid))
    for occurrence in record.get("occurrences", []):
        if occurrence["group"] not in GROUPS:
            raise ValueError("unknown seven-table group")
        frequency = occurrence["frequency"]
        if type(frequency) is not int or frequency < 0:
            raise ValueError("invalid frequency")
        conn.execute("INSERT INTO occurrences(entry_id,source_id,evidence_id,dataset,group_name,"
                     "frequency,payload) VALUES(?,?,?,?,?,?,?)",
                     (eid, sid, fallback, occurrence["dataset"], occurrence["group"], frequency,
                      json.dumps(occurrence, ensure_ascii=False)))
    return "conflicted" if conflict else "accepted"


def _freeze_input(source, destination):
    """Hash and import the same private byte stream, never a second open of a mutable input."""
    checksum = hashlib.sha256()
    with open(source["path"], "rb") as original, open(destination, "xb") as frozen:
        before = os.fstat(original.fileno())
        for chunk in iter(lambda: original.read(1024 * 1024), b""):
            checksum.update(chunk)
            frozen.write(chunk)
        after = os.fstat(original.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("source changed while copying")
    if checksum.hexdigest().lower() != source["local_sha256"].lower():
        raise ValueError("input digest mismatch")


def _publish_new_directory(temp, output):
    """Never replace a directory, including an externally created empty directory."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename unavailable")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(temp), -100, os.fsencode(output), 1):
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise FileExistsError(code, "destination already exists", str(output))
            raise OSError(code, os.strerror(code), str(output))
    elif os.name == "nt":
        os.rename(temp, output)  # Windows refuses an occupied directory target.
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace rename unavailable")


def build(manifest, output):
    started = time.perf_counter()
    data, manifest_sha = load_manifest(manifest)
    output = Path(output).resolve()
    for source in data["sources"]:
        if source["adapter"] != "contract-jsonl-v1":
            raise ValueError("unaudited adapter; use explicit contract-jsonl-v1 only")
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.parent / f".{output.name}.sknow.lock"
    # O_EXCL coordinates local builders; do not rename onto an existing snapshot.
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temp = None
    counts = {}
    rejections = []
    try:
        os.close(fd)
        if output.exists():
            raise FileExistsError("publish destination must be new; old snapshot is never overwritten")
        temp = Path(tempfile.mkdtemp(prefix=".sknow-", dir=output.parent))
        inputs = temp / ".inputs"
        inputs.mkdir()
        for index, source in enumerate(data["sources"]):
            _freeze_input(source, inputs / str(index))
        with closing(sqlite3.connect(temp / "knowledge.sqlite")) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            for name, value in (("contract_version", CONTRACT_VERSION),
                                ("search_text_version", SEARCH_TEXT_VERSION),
                                ("index_episodes", json.dumps(data.get("index_episodes", False))),
                                ("snapshot", manifest_sha)):
                conn.execute("INSERT INTO build_meta VALUES(?,?)", (name, value))
            for index, source in enumerate(data["sources"]):
                sid = source["source_id"]
                conn.execute("INSERT INTO sources VALUES(?,?)",
                             (sid, json.dumps(source, ensure_ascii=False)))
                count = dict.fromkeys(("input", "accepted", "rejected", "conflicted", "duplicate",
                                       "unresolved"), 0)
                count["by_kind"] = {}
                counts[sid] = count
                with open(inputs / str(index), "rb") as stream:
                    for line, raw in enumerate(iter(lambda: stream.readline(2_000_001), b""), 1):
                        count["input"] += 1
                        fingerprint = hashlib.sha256(raw).digest()
                        cur = conn.execute("INSERT OR IGNORE INTO seen_fingerprints VALUES(?,?)",
                                           (sid, fingerprint))
                        if cur.rowcount == 0:
                            count["duplicate"] += 1
                            continue
                        conn.execute("SAVEPOINT record")
                        record = None
                        try:
                            if len(raw) > 2_000_000:
                                raise ValueError("JSONL record exceeds 2 MB")
                            text = raw.decode("utf-8")
                            record = json.loads(text)
                            if not isinstance(record, dict):
                                raise TypeError("JSONL record must be an object")
                            if record.get("record_type") == "link":
                                conn.execute("INSERT INTO pending_links VALUES(?,?,?)",
                                             (sid, line, text))
                                result = None
                            else:
                                result = insert_record(conn, record, source, line,
                                                       data.get("index_episodes", False))
                        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                            conn.execute("ROLLBACK TO record")
                            result = "rejected"
                            if len(rejections) < 100:
                                rejections.append({"source_id": sid, "line": line,
                                                   "reason": type(exc).__name__})
                        conn.execute("RELEASE record")
                        if result is not None:
                            count[result] += 1
                            if result in {"accepted", "conflicted"} and record is not None:
                                kind = record["key"]["kind"]
                                by_kind = count["by_kind"]
                                by_kind[kind] = by_kind.get(kind, 0) + 1
                        if line % 1000 == 0:
                            conn.commit()
                conn.commit()
            by_id = {s["source_id"]: s for s in data["sources"]}
            for sid, line, payload in conn.execute(
                    "SELECT source_id,line,payload FROM pending_links ORDER BY rowid"):
                conn.execute("SAVEPOINT record")
                try:
                    result = insert_record(conn, json.loads(payload), by_id[sid], line,
                                           data.get("index_episodes", False))
                except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                    conn.execute("ROLLBACK TO record")
                    result = "rejected"
                    if len(rejections) < 100:
                        rejections.append({"source_id": sid, "line": line,
                                           "reason": type(exc).__name__})
                conn.execute("RELEASE record")
                counts[sid][result] += 1
            for sid, count in counts.items():
                conn.execute("INSERT INTO source_counts VALUES(?,?,?,?,?,?,?,?)",
                             (sid, *(count[name] for name in ("input", "accepted", "rejected",
                                "conflicted", "duplicate", "unresolved")),
                              json.dumps(count["by_kind"], sort_keys=True)))
            conn.execute("DROP TABLE pending_links")
            conn.execute("DROP TABLE seen_fingerprints")
            conn.execute("INSERT INTO search_fts(search_fts) VALUES('integrity-check')")
            conn.commit()
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint[0] != 0:
                raise ValueError("WAL checkpoint busy")
        shutil.rmtree(inputs)
        checks = verify(temp / "knowledge.sqlite")
        allowed = set(data.get("allow_unresolved_reasons", []))
        if (not checks["ok"] or any(c["rejected"] for c in counts.values()) or
                set(checks["unresolved_reasons"]) - allowed):
            raise ValueError(f"verification rejected publication: {counts}; {checks}")
        if digest(manifest) != manifest_sha:
            raise ValueError("manifest changed during build")
        for source in data["sources"]:
            if digest(source["path"]).lower() != source["local_sha256"].lower():
                raise ValueError("source changed during build")
        report = {"snapshot": manifest_sha, "counts": counts, "verification": checks,
                  "wal_checkpoint": list(checkpoint),
                  "elapsed_seconds": time.perf_counter() - started}
        (temp / "sources.lock.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
        (temp / "build_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if output.exists():
            raise FileExistsError("destination created during build")
        _publish_new_directory(temp, output)
        return report
    except ValueError:
        if rejections:
            receipt = output.parent / f".{output.name}.rejections.json"
            try:
                with open(receipt, "x", encoding="utf-8") as stream:
                    json.dump({"counts": counts, "rejections_first_100": rejections}, stream)
            except FileExistsError:
                pass
        raise
    finally:
        if temp is not None and temp.exists():
            shutil.rmtree(temp)
        lock.unlink()
