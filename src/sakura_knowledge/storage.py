"""Locked JSONL contract importer; a directory is published only after verification."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import tomllib

from . import CONTRACT_VERSION, SEARCH_TEXT_VERSION
from .model import EntryKey, GROUPS, STATUSES, TRUSTED, search_text

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE sources(source_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
CREATE TABLE entries(id INTEGER PRIMARY KEY, kind TEXT, namespace TEXT, value TEXT,
 type TEXT, locator TEXT, UNIQUE(kind,namespace,value));
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
CREATE INDEX link_src ON links(src,relation);
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
    seen = set()
    for source in data.get("sources", []):
        missing = REQUIRED_SOURCE - source.keys()
        if missing:
            raise ValueError(f"source metadata missing: {sorted(missing)}")
        if source["source_id"] in seen:
            raise ValueError("duplicate source_id")
        seen.add(source["source_id"])
        if "://" in source["repo"] and "@" in source["repo"].split("://", 1)[1]:
            raise ValueError("credential-bearing repo forbidden")
        source["path"] = str((path.parent / source["path"]).resolve())
    if not seen:
        raise ValueError("manifest has no sources")
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
        docs = conn.execute("SELECT count(*) FROM search_fts").fetchone()[0]
        return {"ok": integrity == "ok" and not foreign, "integrity": integrity,
                "foreign_key_errors": len(foreign), "fts_documents": docs,
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
            return "unresolved"
        verification = record.get("verification_status", "candidate")
        if verification not in {"native", "redirect", "candidate", "verified", "conflict"}:
            raise ValueError("unknown link verification status")
        if record["relation"] == "entity_tag" and verification == "verified":
            if record["dst"]["kind"] != "tag":
                raise ValueError("entity_tag destination must be tag")
        conn.execute("INSERT INTO links(src,dst,relation,source_id,evidence_id,method,"
                     "verification_status,payload) VALUES(?,?,?,?,?,?,?,?)",
                     (src, dst, record["relation"], sid, fallback, record["method"],
                      verification, json.dumps(record, ensure_ascii=False)))
        return "conflicted" if verification == "conflict" else "accepted"
    eid = entry_id(conn, record["key"], True, record)
    for alias in record.get("aliases", []):
        status, ref = evidence(alias, fallback)
        conn.execute("INSERT INTO aliases(entry_id,text,language,type,status,source_id,"
                     "evidence_id,payload) VALUES(?,?,?,?,?,?,?,?)",
                     (eid, alias["text"], alias.get("language"), alias.get("type"), status,
                      sid, ref, json.dumps(alias, ensure_ascii=False)))
    for doc in record.get("documents", []):
        status, ref = evidence(doc, fallback)
        original = doc.get("original", "")
        text = search_text(doc.get("title", "") + " " + original)
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
    return "accepted"


def build(manifest, output):
    started = time.perf_counter()
    data, manifest_sha = load_manifest(manifest)
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("publish destination must be new; old snapshot is never overwritten")
    for source in data["sources"]:
        if source["adapter"] != "contract-jsonl-v1":
            raise ValueError("unaudited adapter; use explicit contract-jsonl-v1 only")
        if digest(source["path"]) != source["local_sha256"]:
            raise ValueError("input digest mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".sknow-", dir=output.parent))
    counts = {}
    try:
        with closing(sqlite3.connect(temp / "knowledge.sqlite")) as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO build_meta VALUES('contract_version',?)", (CONTRACT_VERSION,))
            conn.execute("INSERT INTO build_meta VALUES('search_text_version',?)", (SEARCH_TEXT_VERSION,))
            conn.execute("INSERT INTO build_meta VALUES('snapshot',?)", (manifest_sha,))
            for source in data["sources"]:
                conn.execute("INSERT INTO sources VALUES(?,?)",
                             (source["source_id"], json.dumps(source, ensure_ascii=False)))
                count = dict.fromkeys(("input", "accepted", "rejected", "conflicted", "duplicate",
                                       "unresolved"), 0)
                counts[source["source_id"]] = count
                seen = set()
                with open(source["path"], encoding="utf-8") as stream:
                    for line, text in enumerate(stream, 1):
                        count["input"] += 1
                        fingerprint = hashlib.sha256(text.encode()).digest()
                        if fingerprint in seen:
                            count["duplicate"] += 1
                            continue
                        seen.add(fingerprint)
                        conn.execute("SAVEPOINT record")
                        try:
                            result = insert_record(conn, json.loads(text), source, line,
                                                   data.get("index_episodes", False))
                        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError):
                            conn.execute("ROLLBACK TO record")
                            result = "rejected"
                        conn.execute("RELEASE record")
                        count[result] += 1
                        if line % 1000 == 0:
                            conn.commit()
                conn.commit()
            conn.execute("INSERT INTO search_fts(search_fts) VALUES('integrity-check')")
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        checks = verify(temp / "knowledge.sqlite")
        if not checks["ok"] or any(c["rejected"] or c["unresolved"] for c in counts.values()):
            raise ValueError(f"verification rejected publication: {counts}")
        if digest(manifest) != manifest_sha:
            raise ValueError("manifest changed during build")
        for source in data["sources"]:
            if digest(source["path"]) != source["local_sha256"]:
                raise ValueError("source changed during build")
        report = {"snapshot": manifest_sha, "counts": counts, "verification": checks,
                  "elapsed_seconds": time.perf_counter() - started}
        (temp / "sources.lock.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
        (temp / "build_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.rename(temp, output)
        return report
    finally:
        if temp.exists():
            shutil.rmtree(temp)
