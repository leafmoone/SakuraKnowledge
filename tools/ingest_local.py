"""Convert audited immutable input copies into explicit, lineaged normalized JSONL.

This is an ingestion-only command; never writes under --source. --sample is a
bounded smoke test, not evidence of full input acceptance.
"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import time
from collections import Counter
from pathlib import Path

from sakura_knowledge.adapters import (
    BANGUMI_FILES,
    MOEGIRL_FILES,
    bangumi_entity,
    iter_bangumi,
    iter_danbooru_links,
    iter_danbooru_pages,
    iter_moegirl,
    iter_moegirl_mappings,
    iter_tag_wiki,
    moegirl_character,
    tag_group_record,
)
from sakura_knowledge.model import GROUPS as SEVEN_GROUPS
from sakura_knowledge.safety import safe_extract
from sakura_knowledge.storage import digest

GROUPS = ("bangumi", "moegirl", "mapping", "danbooru", "tag_wiki")


def copy_locked(source, destination, expected):
    if destination.exists():
        if digest(destination) != expected:
            raise ValueError(f"existing frozen copy differs: {destination}")
        return
    checksum = hashlib.sha256()
    temp = destination.with_name(destination.name + ".new")
    with source.open("rb") as raw, temp.open("xb") as frozen:
        before = source.stat()
        for data in iter(lambda: raw.read(1024 * 1024), b""):
            checksum.update(data)
            frozen.write(data)
        after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        temp.unlink()
        raise ValueError(f"source changed during copy: {source}")
    if checksum.hexdigest() != expected:
        temp.unlink()
        raise ValueError(f"source hash changed: {source}")
    temp.rename(destination)


def materialize(root, cache, audit):
    archive = cache / "archive-frozen"
    if not archive.exists():
        safe_extract(root / "Archive_dump-2026-09-22.zip", archive,
                     audit["files"]["Archive_dump-2026-09-22.zip"]["sha256"],
                     max_bytes=6_000_000_000)
    for name in BANGUMI_FILES:
        file = f"{name}.jsonlines"
        if digest(archive / file) != audit["files"][f"Archive_dump/{file}"]["sha256"]:
            raise ValueError(f"frozen Archive member mismatch: {file}")
    for group, names, location in (("moegirl", MOEGIRL_FILES, "moegirl-dataset/moegirl"),
                                   ("mapping", ("bgm2moegirl", "moegirl2bgm",
                                                "bgm_info", "bgm_redirects_full"),
                                    "moegirl-dataset/bangumi")):
        target = cache / f"{group}-frozen"
        target.mkdir(exist_ok=True)
        for name in names:
            rel = f"{location}/{name}.json"
            copy_locked(root / rel, target / f"{name}.json", audit["files"][rel]["sha256"])
    target = cache / "parquet-frozen"
    target.mkdir(exist_ok=True)
    for name in ("danbooru_wiki", "danbooru_wiki_links"):
        rel = f"raw/danbooru_wiki/wiki/{name}.parquet"
        copy_locked(root / rel, target / f"{name}.parquet", audit["files"][rel]["sha256"])
    db = cache / "tag_wiki-frozen.sqlite"
    if digest(db) != audit["sqlite"]["backup_file"]["sha256"]:
        raise ValueError("frozen tag_wiki backup mismatch")
    return {"bangumi": archive, "moegirl": cache / "moegirl-frozen",
            "mapping": cache / "mapping-frozen", "danbooru": target, "tag_wiki": db}


def read_entries(group, paths, sample, danbooru_snapshot=None):
    if group == "bangumi":
        return (value for _, value in iter_bangumi(paths[group], sample=sample))
    if group == "moegirl":
        return iter_moegirl(paths[group], sample=sample)
    if group == "mapping":
        return iter_moegirl_mappings(paths[group], sample=sample)
    if group == "danbooru":
        pages = iter_danbooru_pages(paths[group] / "danbooru_wiki.parquet", sample=sample)
        links = iter_danbooru_links(paths[group] / "danbooru_wiki_links.parquet", sample=sample)
        from itertools import chain
        return chain(pages, links)
    return iter_tag_wiki(paths[group], sample=sample, danbooru_snapshot=danbooru_snapshot)


def sample_dependencies(output, paths, links, keys, counts):
    """Include actual endpoints for one audited native/candidate edge per source."""
    first = {}
    for group, link in links:
        first.setdefault(group, link)
    needed = {group: set() for group in ("bangumi", "moegirl", "danbooru", "tag_wiki")}
    for link in first.values():
        for key in (link["src"], link["dst"]):
            identity = (key["kind"], key["namespace"], key["value"])
            if identity in keys:
                continue
            group = {"bangumi": "bangumi", "moegirl": "moegirl"}.get(
                key["namespace"].split(".")[0], "bangumi")
            # More explicit namespace dispatch for Danbooru vs other content.
            if key["namespace"] == "danbooru.wiki":
                group = "danbooru"
            elif key["namespace"] == "local.tag_aggregate":
                group = "tag_wiki"
            needed[group].add(identity)

    def add(group, record):
        key = record["key"]
        identity = (key["kind"], key["namespace"], key["value"])
        if identity not in needed[group] or identity in keys:
            return
        with (output / f"{group}.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        keys.add(identity)
        counts[group]["entity"] = counts[group].get("entity", 0) + 1
        counts[group]["added_edge_endpoint"] = counts[group].get("added_edge_endpoint", 0) + 1

    for kind in BANGUMI_FILES[:4]:
        target = needed["bangumi"]
        if not any(key[0] == kind for key in target):
            continue
        with (paths["bangumi"] / f"{kind}.jsonlines").open("rb") as stream:
            for line in stream:
                row = json.loads(line)
                if (kind, f"bangumi.{kind}", str(row["id"])) in target:
                    add("bangumi", bangumi_entity(kind, row))
                if target.issubset(keys):
                    break
    if needed["moegirl"]:
        root = paths["moegirl"]
        def load(name):
            with (root / f"{name}.json").open(encoding="utf-8") as stream:
                return json.load(stream)
        indexed = set(load("char_index"))
        extra, attrs, subjects, cvs, genders = (load(n) for n in
            ("extra_processed", "char2attr", "char2subject", "char2cv", "char2gender"))
        for kind, namespace, name in needed["moegirl"]:
            if kind == "character" and namespace == "moegirl.character" and name in indexed:
                add("moegirl", moegirl_character(name, extra.get(name, {}), attrs.get(name, []),
                    subjects.get(name, []), cvs.get(name, []), genders.get(name)))
    if needed["danbooru"]:
        for page in iter_danbooru_pages(paths["danbooru"] / "danbooru_wiki.parquet"):
            add("danbooru", page)
            if needed["danbooru"].issubset(keys):
                break
    if needed["tag_wiki"]:
        db = sqlite3.connect(paths["tag_wiki"].resolve().as_uri() + "?mode=ro&immutable=1",
                             uri=True)
        db.row_factory = sqlite3.Row
        try:
            for _, _, tag in needed["tag_wiki"]:
                for group in SEVEN_GROUPS:
                    row = db.execute(f'SELECT * FROM "{group}" WHERE tag_key=?',
                                     (tag,)).fetchone()
                    if row is not None:
                        add("tag_wiki", tag_group_record(group, row))
                        break
        finally:
            db.close()
    return {group: len(values - keys) for group, values in needed.items()}


def source_meta(group, source_files, normalized_path, audit, root, *, sample,
                commit, converter_command, source_rows):
    mapping_commit = "1ff222f8af5e399e230b9f88eb50995869ed22bf"
    bangumi_digest = audit["files"]["Archive_dump-2026-09-22.zip"]["sha256"]
    sources = {"bangumi": "https://github.com/bangumi/Archive/releases/tag/archive",
               "moegirl": "https://github.com/Zzzzzzyt/moegirl-dataset",
               "mapping": "https://github.com/Zzzzzzyt/moegirl-dataset",
               "danbooru": "https://huggingface.co/datasets/leafmoone/danbooru_wiki",
               "tag_wiki": "local://derived/tag_wiki.sqlite"}
    cutoff = "2025-12-28" if group == "moegirl" else (
        "2025-12-23" if group == "mapping" else None)
    # Null means unknown, not the time a local file was observed or hashed.
    inventory = {rel: audit["files"][rel] for rel in source_files}
    if group == "tag_wiki":
        inventory["sqlite_mode_ro_consistent_backup"] = {
            "path": audit["sqlite"]["frozen"], **audit["sqlite"]["backup_file"],
            "source_original_file": "tag_wiki.sqlite",
            "backup_started_at_utc": audit["sqlite"]["backup_started_at_utc"],
            "backup_finished_at_utc": audit["sqlite"]["backup_finished_at_utc"]}
    ref = {"bangumi": "official Archive README + aux/latest.json; ZIP member hashes match",
           "moegirl": "local README cutoff; tracked Git HEAD; separately hashed JSON",
           "mapping": "local README derived-Bangumi cutoff; candidate mappings only",
           "danbooru": "Parquet file hashes and actual row-group/footer schema",
           "tag_wiki": "mode=ro backup; integrity and hash apply only to backup"}
    unknown = {key: "not supplied by authoritative source; not inferred from local mtime"
               for key in ("exported_at", "fetched_at_utc", "data_license")}
    if group in {"moegirl", "mapping", "danbooru", "tag_wiki"}:
        unknown["upstream_digest"] = "no authenticated upstream digest for this local dataset"
    if group in {"danbooru", "tag_wiki"}:
        unknown["upstream_revision"] = "no authenticated source revision for these bytes"
    if cutoff is None:
        unknown["source_declared_cutoff"] = "no declared content cutoff tied to these bytes"
    return {"source_id": f"{group}-{'sample' if sample else 'complete'}-{digest(normalized_path)[:12]}",
            "provider": group, "dataset_role": "normalized_engine_input",
            "repo": sources[group], "upstream_revision": mapping_commit if group in {
                "moegirl", "mapping"} else (bangumi_digest if group == "bangumi" else None),
            "asset_name": group, "upstream_digest": bangumi_digest if group == "bangumi" else None,
            "local_sha256": digest(normalized_path), "source_declared_cutoff": cutoff,
            "exported_at": None, "fetched_at_utc": None,
            "inspected_at_utc": audit["observed_at_utc"],
            "schema_version": "audited-native-2026-09-28", "importer_version": "P1-Rev2",
            "converter_source_commit": commit,
            "converter_command": converter_command,
            "conversion_spec_version": "local-ingest-v2-full-original-local-tags",
            "mapping_generator_revision": mapping_commit if group == "mapping" else None,
            "input_file_inventory": inventory, "counts": {"source_rows": source_rows},
            "source_references": [ref[group]], "refresh_status": "local_frozen_sample" if sample
            else "local_frozen_full", "code_license": None, "data_license": None,
            "unknown_reasons": unknown, "path": str(normalized_path.resolve()),
            "adapter": "contract-jsonl-v1", "original_root_observed": str(root),
            "frozen_backup_sha256": audit["sqlite"]["backup_file"]["sha256"] if
                group == "tag_wiki" else None,
            "official_asset_created_at": "2026-09-22T21:03:41Z" if group == "bangumi" else None,
            "cutoff_scope": "upstream README declaration; not verified content date" if cutoff else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample", type=int)
    parser.add_argument('--tag-text-danbooru-snapshot', type=Path, help='Explicit readonly source-backed Danbooru snapshot for reconstructed tag text proofs')
    args = parser.parse_args()
    root = args.source.resolve()
    cache = args.cache.resolve()
    output = args.output.resolve()
    if any(root == p or root in p.parents for p in (cache, output)):
        raise ValueError("outputs cannot be written inside the source tree")
    if output.exists():
        raise FileExistsError(output)
    if args.sample is not None and not 1 <= args.sample <= 100:
        raise ValueError("sample must be 1..100")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--", "src", "tools"],
                               text=True).strip():
        raise ValueError("converter sources modified; commit before converting")
    command = ["PYTHONPATH=src", "build/ingest-venv/Scripts/python", "tools/ingest_local.py",
               "--source", str(root), "--audit", str(args.audit.resolve()),
               "--cache", str(cache), "--output", str(output)]
    if args.sample:
        command.extend(["--sample", str(args.sample)])
    if Path(audit["root"]).resolve() != root or not audit["official_zip_digest_match"] or not (
            audit["all_zip_members_match"] and audit["sqlite"]["integrity"] == "ok"):
        raise ValueError("audit does not verify these frozen source bytes")
    begun = time.monotonic()
    paths = materialize(root, cache, audit)
    output.mkdir(parents=True)
    source_files = {
        "bangumi": [f"Archive_dump/{n}.jsonlines" for n in BANGUMI_FILES],
        "moegirl": [f"moegirl-dataset/moegirl/{n}.json" for n in MOEGIRL_FILES],
        "mapping": [f"moegirl-dataset/bangumi/{n}.json" for n in
                    ("bgm2moegirl", "moegirl2bgm", "bgm_info", "bgm_redirects_full")],
        "danbooru": [f"raw/danbooru_wiki/wiki/{n}.parquet" for n in
                     ("danbooru_wiki", "danbooru_wiki_links")],
        "tag_wiki": [],
    }
    # Full runs keep all link records, preserving unresolved references and
    # allowing the build to account for them rather than silently dropping data.
    # Sample runs restrict edges to present endpoints, clearly labelled coverage.
    all_keys = set()
    sample_links = []
    sample_unresolved = Counter()
    counts = {}
    for group in GROUPS:
        file = output / f"{group}.jsonl"
        stats = Counter()
        with file.open("x", encoding="utf-8", newline="\n") as stream:
            for record in read_entries(group, paths, args.sample, args.tag_text_danbooru_snapshot):
                if args.sample is not None and record.get("record_type") in {"link", "unresolved"}:
                    if record["record_type"] == "link":
                        sample_links.append((group, record))
                    else:
                        sample_unresolved[group] += 1
                    continue
                if args.sample is not None:
                    k = record["key"]
                    all_keys.add((k["kind"], k["namespace"], k["value"]))
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                stats[record.get("record_type", "entity")] += 1
        counts[group] = dict(stats)
        print(f"converted {group}: {stats}", flush=True)
    missing_sample_dependencies = {}
    if args.sample is not None:
        missing_sample_dependencies = sample_dependencies(
            output, paths, sample_links, all_keys, counts)
        for group, row in sample_links:
            src, dst = row["src"], row["dst"]
            if all((k["kind"], k["namespace"], k["value"]) in all_keys for k in (src, dst)):
                with (output / f"{group}.jsonl").open("a", encoding="utf-8", newline="\n") as file:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts[group]["sample_link"] = counts[group].get("sample_link", 0) + 1
        print("sample_only_edges_dropped", len(sample_links) - sum(c.get("sample_link", 0)
                                                       for c in counts.values()), flush=True)
        print("sample_only_unresolved_excluded", dict(sample_unresolved), flush=True)
    archive_counts = {name: info["rows"] for name, info in audit["archive"].items()}
    source_counts = {
        "bangumi": {"archive_files": archive_counts,
                    "record_rows": sum(archive_counts.values())},
        "moegirl": {"generated_entities": counts["moegirl"].get("entity", 0),
                    "scope": "normalized, not source row count"},
        "mapping": {"generated_candidate_links": counts["mapping"].get("link", 0),
                    "scope": "normalized, not source row count"},
        "danbooru": {"wiki_pages": counts["danbooru"].get("entity", 0),
                     "wiki_links": (counts["danbooru"].get("link", 0) +
                                    counts["danbooru"].get("unresolved", 0)),
                     "scope": "normalized all Parquet rows; footer checked separately"},
        "tag_wiki": {"tables": {name: info["rows"] for name, info in
                                  audit["sqlite"]["tables"].items()},
                     "scope": "frozen-backup rows, not unique EntryKeys"}}
    if args.sample is None and (source_counts["bangumi"]["record_rows"] != sum(
            counts["bangumi"].values()) or
            source_counts["danbooru"]["wiki_pages"] !=
            audit["sqlite"]["tables"]["wiki_pages"]["rows"]):
        raise ValueError("source inventory and adapter counts disagree")
    sources = [source_meta(group, source_files[group], output / f"{group}.jsonl", audit,
                           root, sample=args.sample, commit=commit,
                           converter_command=command,
                           source_rows=source_counts[group]) for group in GROUPS]
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps({"sources": sources, "index_episodes": False,
                      "audit_receipt_sha256": digest(args.audit), "sample_limit": args.sample,
                      "tag_wiki_frozen_source": str(paths["tag_wiki"]),
                      "tag_wiki_frozen_sha256": audit["sqlite"]["backup_file"]["sha256"],
                      "converter_source_commit": commit,
                      "converter_command": command,
                      "conversion_spec_version": "local-ingest-v2-full-original-local-tags",
                      "adapter_counts": counts,
                      "sample_excluded_unresolved": dict(sample_unresolved),
                      "sample_unavailable_edge_dependencies": missing_sample_dependencies,
                      "sample_excluded_links_without_both_endpoints": (
                          len(sample_links) - sum(c.get("sample_link", 0)
                                                  for c in counts.values())) if args.sample else 0,
                      "allow_unresolved_reasons": [] if args.sample else [
                          "unresolved_wiki_link", "missing_endpoint"]},
                      ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"manifest {manifest}; elapsed {time.monotonic()-begun:.2f}s", flush=True)


if __name__ == "__main__":
    main()
