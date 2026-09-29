"""Snapshot read-only compatibility + schema/space/occurrence evidence.

Independent raw receipt for the frozen snapshot (item 5 + item 7 evidence):
  - path exists, size, sha256 (before AND after the run: identical => no
    writes by this tool or the read-only runtimes),
  - SQLite open with explicit read-only flags (python uri mode=ro; Rust
    SQLITE_OPEN_READ_ONLY), plus a python write ATTEMPT that must fail,
  - schema / build_meta versions, tables and required columns,
  - real use cases executed read-only (lookup/search/related/ask/inspect),
  - inspect error path against a non-snapshot database (both runtimes),
  - occurrence semantics: dataset partition, source_count, nullable
    sample_count, per-entry occurrence distribution,
  - source_fields bounded projection: populated / missing / empty cases,
  - space analysis: PRAGMA page_size/page_count/freelist_count + dbstat
    availability and per-table page totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sakura_knowledge.api import Knowledge

GROUPS = ("common_tags", "anime_pictures_1_noncommon", "bangumi_1_noncommon",
          "gamecg_5m_noncommon", "konachan_1_noncommon", "yande_1_noncommon",
          "zerochan_1_noncommon")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--bin", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    db = Path(args.db).resolve()
    bin_path = Path(args.bin).resolve()

    rep: dict = {"db_path": str(db), "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    rep["path_exists"] = db.exists()
    rep["size_bytes"] = db.stat().st_size if rep["path_exists"] else None
    sha_before = sha256(db) if rep["path_exists"] else None
    rep["sha256_before"] = sha_before

    # --- python read-only open + write attempt --------------------------
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    rep["python_readonly_open"] = "ok"
    try:
        conn.execute("UPDATE entries SET value=value WHERE rowid=1")
        rep["python_write_attempt"] = "UNEXPECTED_SUCCESS"
    except sqlite3.OperationalError as e:
        rep["python_write_attempt"] = f"blocked: {e}"
    rep["sqlite_version"] = sqlite3.sqlite_version

    # --- build_meta versions --------------------------------------------
    rep["build_meta"] = {r[0]: r[1] for r in conn.execute(
        "SELECT key,value FROM build_meta ORDER BY key")}

    # --- schema: tables + required columns -------------------------------
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    rep["tables"] = tables
    required = {
        "entries": ["id", "kind", "namespace", "value", "locator", "conflicted"],
        "occurrences": ["id", "entry_id", "source_id", "evidence_id", "dataset",
                        "group_name", "frequency", "payload"],
        "source_counts": ["source_id", "input", "accepted", "rejected",
                          "conflicted", "duplicate", "unresolved", "by_kind"],
        "documents": ["id", "entry_id", "source_id", "evidence_id", "status"],
        "aliases": ["id", "entry_id", "text", "source_id", "evidence_id", "status"],
        "links": ["src", "dst", "relation", "method", "verification_status"],
        "entry_evidence": ["id", "entry_id", "source_id", "status", "type",
                           "locator", "payload"],
        "build_meta": ["key", "value"],
    }
    cols: dict[str, list[str]] = {}
    for t in required:
        if t in tables:
            cols[t] = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
    rep["columns"] = cols
    rep["required_columns_ok"] = all(
        all(c in cols.get(t, []) for c in need) for t, need in required.items())

    # --- occurrence semantics --------------------------------------------
    occ = {}
    dist = conn.execute(
        "SELECT n, count(*) FROM (SELECT o.entry_id, count(*) n FROM occurrences o "
        "JOIN entries e ON e.id=o.entry_id WHERE e.kind='tag' "
        "GROUP BY o.entry_id) GROUP BY n ORDER BY n").fetchall()
    occ["tag_occurrence_count_distribution"] = dist
    samples = conn.execute(
        "SELECT e.value, o.dataset, o.group_name, o.frequency, o.payload "
        "FROM occurrences o JOIN entries e ON e.id=o.entry_id "
        "WHERE e.kind='tag' AND e.namespace='local.tag_aggregate' AND o.id IN "
        "(SELECT id FROM occurrences ORDER BY id LIMIT 3) "
        "ORDER BY o.id").fetchall()
    occ["samples"] = [{
        "value": s[0], "dataset": s[1], "group_name": s[2], "frequency": s[3],
        "raw_keys": sorted(json.loads(s[4])["raw"].keys()) if s[4] else None,
        "raw": json.loads(s[4])["raw"] if s[4] else None,
    } for s in samples]
    occ["sample_count_null_rows"] = conn.execute(
        "SELECT count(*) FROM occurrences o JOIN entries e ON e.id=o.entry_id "
        "WHERE e.kind='tag' AND json_extract(o.payload,'$.raw.sample_count') IS NULL").fetchone()[0]
    occ["sample_count_nonnull_rows"] = conn.execute(
        "SELECT count(*) FROM occurrences o JOIN entries e ON e.id=o.entry_id "
        "WHERE e.kind='tag' AND json_extract(o.payload,'$.raw.sample_count') IS NOT NULL").fetchone()[0]
    occ["datasets_seen"] = [r[0] for r in conn.execute(
        "SELECT DISTINCT dataset FROM occurrences ORDER BY dataset")]
    occ["dataset_is_partition_of_groups"] = set(occ["datasets_seen"]) <= set(GROUPS)
    rep["occurrences"] = occ

    # --- source_fields bounded projection --------------------------------
    sf = {}
    populated = conn.execute(
        "SELECT e.value FROM entry_evidence v JOIN entries e ON e.id=v.entry_id "
        "WHERE e.kind='character' AND e.namespace='moegirl.character' "
        "AND json_extract(v.payload,'$.raw.raw_attributes') IS NOT NULL LIMIT 1").fetchone()
    if populated:
        with Knowledge(str(db)) as api:
            d = api.lookup(key={"kind": "character", "namespace": "moegirl.character",
                                     "value": populated[0]})
            sf["populated_example"] = {
                "entry": populated[0],
                "source_fields": d.get("source_fields"),
                "evidence_citations": d.get("source_fields_evidence"),
            }
    missing = conn.execute(
        "SELECT e.value FROM entries e WHERE e.kind='character' "
        "AND e.namespace='bangumi.character' "
        "AND NOT EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id "
        "AND json_extract(v.payload,'$.raw.raw_attributes') IS NOT NULL) "
        "LIMIT 1").fetchone()
    if missing:
        with Knowledge(str(db)) as api:
            d = api.lookup(key={"kind": "character", "namespace": "bangumi.character",
                                     "value": missing[0]})
            sf["missing_raw_attributes_example"] = {
                "entry": missing[0], "source_fields": d.get("source_fields"),
            }
    allowed = {"raw_attributes", "raw_subject_categories", "raw_cv_names", "raw_gender"}
    sf["bounded_projection_keys_allowed"] = sorted(allowed)
    sf["projection_respected"] = all(
        set(x["source_fields"]) <= allowed
        for x in sf.values() if isinstance(x, dict) and "source_fields" in x)
    rep["source_fields"] = sf

    # --- real use cases, read-only ----------------------------------------
    with Knowledge(str(db)) as api:
        cases = [
            ("lookup_975", api.lookup("975")["status"]),
            ("lookup_key", api.lookup(key={"kind": "subject",
                                           "namespace": "bangumi.subject",
                                           "value": "1"})["status"]),
            ("search_heavy", api.search("heavy", topk=10)["status"]),
            ("related_subject_1", len(api.related(
                {"kind": "subject", "namespace": "bangumi.subject", "value": "1"},
                limit=20)["relations"])),
            ("ask_tag_template", api.ask("975 的标签是什么")["status"]),
            ("inspect", api.inspect()["snapshot"]),
        ]
    rep["real_use_cases"] = [{"name": n, "result": str(r)} for n, r in cases]

    # --- inspect error path: non-snapshot sqlite (both runtimes) ----------
    junk = ROOT / "build" / "_compat_junk.sqlite"
    jc = sqlite3.connect(junk)
    jc.execute("CREATE TABLE t(x)")
    jc.commit()
    jc.close()
    err_path = {}
    try:
        with Knowledge(str(junk)) as api:
            api.inspect()
        err_path["python"] = "UNEXPECTED_SUCCESS"
    except Exception as e:  # noqa: BLE001 - record the actual failure type
        err_path["python"] = f"{type(e).__name__}: {e}"
    p = subprocess.run([str(bin_path), "inspect", str(junk)],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    err_path["rust"] = {"exit": p.returncode, "stderr": p.stderr.strip()}
    rep["inspect_error_path"] = err_path
    for _ in range(5):
        try:
            junk.unlink(missing_ok=True)
            break
        except PermissionError:
            time.sleep(0.5)

    # --- rust read-only runtime check -------------------------------------
    p = subprocess.run([str(bin_path), "inspect", str(db)],
                       capture_output=True, text=True, encoding="utf-8", check=False)
    rep["rust_inspect"] = {"exit": p.returncode,
                           "output": json.loads(p.stdout) if p.stdout.strip() else None}

    # --- space analysis ----------------------------------------------------
    space = {
        "page_size": conn.execute("PRAGMA page_size").fetchone()[0],
        "page_count": conn.execute("PRAGMA page_count").fetchone()[0],
        "freelist_count": conn.execute("PRAGMA freelist_count").fetchone()[0],
    }
    try:
        space["dbstat_available"] = True
        space["dbstat_pages_total"] = conn.execute(
            "SELECT COALESCE(sum(page_count),0) FROM dbstat").fetchone()[0]
        space["dbstat_top_tables"] = [
            {"name": r[0], "pages": r[1], "page_count": r[2]}
            for r in conn.execute(
                "SELECT COALESCE(name,'(freelist/root)') name, "
                "COALESCE(sum(page_count),0) pages, count(*) "
                "FROM dbstat GROUP BY name ORDER BY pages DESC LIMIT 12")]
    except sqlite3.DatabaseError as e:
        space["dbstat_available"] = False
        space["dbstat_error"] = str(e)
    rep["space"] = space
    conn.close()

    # --- proof of no writes -------------------------------------------------
    rep["sha256_after"] = sha256(db)
    rep["no_write_verified"] = rep["sha256_after"] == sha_before
    rep["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    ok = (rep["path_exists"] and rep["no_write_verified"]
          and rep["required_columns_ok"]
          and rep["rust_inspect"]["exit"] == 0
          and "blocked" in rep["python_write_attempt"])
    print(json.dumps({"no_write_verified": rep["no_write_verified"],
                      "required_columns_ok": rep["required_columns_ok"],
                      "overall": "PASS" if ok else "FAIL"}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
