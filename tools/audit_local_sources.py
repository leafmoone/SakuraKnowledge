"""Read-only local source inventory; cache/receipt are outside the source directory.

Run explicitly; never execute any code or instructions from the data tree.
"""
import argparse
import hashlib
import json
import sqlite3
import time
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ARCHIVE = ("subject", "character", "person", "episode", "subject-persons",
           "subject-relations", "subject-characters", "person-characters", "person-relations")
MOEGIRL = ("char_index", "extra_processed", "char2attr", "attr2char", "char2subject",
           "subject_index", "char2cv", "cv2char", "char2gender")
MAPPINGS = ("bgm2moegirl", "moegirl2bgm", "bgm_info", "bgm_redirects_full")
OFFICIAL_ZIP_SHA256 = "73470620537cd77b22fd247fd9b10f8cd3f57b14c74ec4949f8ff1a7c205abb0"


def hash_stream(stream):
    h = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(block)
        size += len(block)
    return h.hexdigest(), size


def hash_path(path):
    with path.open("rb") as stream:
        result, size = hash_stream(stream)
    if size != path.stat().st_size:
        raise ValueError(f"source changed during hash: {path}")
    return {"sha256": result, "bytes": size}


def inspect_jsonlines(path):
    count = 0
    fields = Counter()
    values = Counter()
    with path.open("rb") as stream:
        for line in stream:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"unexpected JSONL row in {path}")
            count += 1
            for key, value in row.items():
                fields[(key, type(value).__name__)] += 1
            if path.name == "person-relations.jsonlines":
                values[row.get("person_type")] += 1
    return {"rows": count, "field_types": {f"{key}:{kind}": n for (key, kind), n in
                                         sorted(fields.items())},
            "person_type_counts": dict(values)}


def inspect_sqlite(source, frozen):
    """Consistent SQLite backup from a ro connection, not an immutable live-file read."""
    if frozen.exists():
        raise FileExistsError(frozen)
    started = datetime.now(UTC).isoformat()
    uri = source.resolve().as_uri() + "?mode=ro"
    src = sqlite3.connect(uri, uri=True, timeout=30)
    dest = sqlite3.connect(frozen)
    try:
        src.backup(dest, pages=2048, sleep=0.05)
    except BaseException:
        dest.close()
        frozen.unlink(missing_ok=True)
        raise
    finally:
        src.close()
    try:
        dest.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        integrity = dest.execute("PRAGMA integrity_check").fetchone()[0]
        names = [name for (name,) in dest.execute("SELECT name FROM sqlite_master "
                                                 "WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        tables = {name: {"columns": [(col[1], col[2]) for col in
                                    dest.execute(f'PRAGMA table_info("{name}")')],
                         "rows": dest.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]}
                  for name in names if not name.startswith("fts")}
        if integrity != "ok":
            raise ValueError(f"source backup failed integrity_check: {integrity}")
    finally:
        dest.close()
    return {"backup_started_at_utc": started, "backup_finished_at_utc":
            datetime.now(UTC).isoformat(), "source_uri_mode": "ro",
            "integrity_scope": "backup_not_live", "integrity": integrity,
            "tables": tables, "frozen": str(frozen), "backup_file": hash_path(frozen)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = args.receipt.resolve()
    cache = args.cache.resolve()
    if root == cache or root in cache.parents or root == receipt or root in receipt.parents:
        raise ValueError("output must not be in the input directory")
    cache.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"observed_at_utc": datetime.now(UTC).isoformat(),
              "root": str(root), "files": {}, "archive": {}, "sqlite": None}
    all_files = [root / "Archive_dump" / f"{n}.jsonlines" for n in ARCHIVE]
    all_files += [root / "moegirl-dataset" / "moegirl" / f"{n}.json" for n in MOEGIRL]
    all_files += [root / "moegirl-dataset" / "bangumi" / f"{n}.json" for n in MAPPINGS]
    all_files += [root / "raw" / "danbooru_wiki" / "wiki" / f"{n}.parquet"
                  for n in ("danbooru_wiki", "danbooru_wiki_links")]
    all_files.append(root / "Archive_dump-2026-09-22.zip")
    for path in all_files:
        rel = path.relative_to(root).as_posix()
        print(f"hash {rel}", flush=True)
        report["files"][rel] = hash_path(path)
        if path.parent == root / "Archive_dump":
            report["archive"][path.stem] = inspect_jsonlines(path)
    zip_path = root / "Archive_dump-2026-09-22.zip"
    zip_key = zip_path.relative_to(root).as_posix()
    report["official_zip_digest_match"] = (
        report["files"][zip_key]["sha256"] == OFFICIAL_ZIP_SHA256)
    with zipfile.ZipFile(zip_path) as archive:
        names = {p.filename for p in archive.infolist()}
        if names != {f"{n}.jsonlines" for n in ARCHIVE}:
            raise ValueError("ZIP member inventory differs from nine-file contract")
        report["archive_zip_member_match"] = {}
        for name in sorted(names):
            with archive.open(name) as stream:
                sha, size = hash_stream(stream)
            local = f"Archive_dump/{name}"
            entry = report["files"][local]
            report["archive_zip_member_match"][name] = {
                "local_path": local, "zip_stream_sha256": sha,
                "zip_uncompressed_bytes": size, "local_sha256": entry["sha256"],
                "local_bytes": entry["bytes"],
                "match": sha == entry["sha256"] and size == entry["bytes"]}
    source = root / "tag_wiki.sqlite"
    report["live_sqlite_observed"] = {
        "observed_at_utc": datetime.now(UTC).isoformat(), "bytes": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "wal_exists": source.with_name(source.name + "-wal").exists(),
        "shm_exists": source.with_name(source.name + "-shm").exists()}
    report["sqlite"] = inspect_sqlite(source, cache / "tag_wiki-frozen.sqlite")
    report["elapsed_seconds"] = time.monotonic() - started
    report["all_zip_members_match"] = all(
        item["match"] for item in report["archive_zip_member_match"].values())
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"receipt: {receipt}; ZIP official digest: {report['official_zip_digest_match']}", flush=True)


if __name__ == "__main__":
    main()
