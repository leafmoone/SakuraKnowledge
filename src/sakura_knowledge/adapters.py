"""Audited source-specific transformation to the versioned normalized engine contract.

No source data is executed. Parquet uses an optional ingestion-only pyarrow install.
Candidates/AI drafts are never promoted into verified links or trusted citations.
"""
import json
import sqlite3
from pathlib import Path

from .model import GROUPS, EntryKey

BANGUMI_FILES = ("subject", "character", "person", "episode", "subject-persons",
                 "subject-relations", "subject-characters", "person-characters",
                 "person-relations")
MOEGIRL_FILES = ("char_index", "extra_processed", "char2attr", "attr2char",
                 "char2subject", "subject_index", "char2cv", "cv2char", "char2gender")
BANGUMI_RELATIONS = ("subject-persons", "subject-relations", "subject-characters",
                     "person-characters", "person-relations")


def _key(kind, namespace, value):
    return EntryKey(kind, namespace, str(value)).as_dict()


def _alias(value, raw_field, status="source_backed"):
    return {"text": value, "type": raw_field, "status": status}


def _document(title, text, *, status="source_backed", **extra):
    return {"title": title, "original": text, "status": status, **extra}


def _entity(key, *, aliases=(), documents=(), occurrences=(),
            status="source_backed", **raw):
    return {"key": key, "aliases": list(aliases), "documents": list(documents),
            "occurrences": list(occurrences), "status": status, "raw": raw}


def bangumi_entity(name, row):
    if name not in BANGUMI_FILES[:4]:
        raise ValueError("unknown Bangumi entity")
    ident = row["id"]
    if type(ident) is not int or ident < 1:
        raise ValueError("invalid Bangumi ID")
    names = [(field, row.get(field)) for field in ("name", "name_cn")]
    title = row.get("name") or row.get("name_cn") or str(ident)
    aliases = [_alias(value, field) for field, value in names if isinstance(value, str) and value]
    text = row.get("summary", row.get("description", "")) or ""
    if not isinstance(text, str):
        raise TypeError("unexpected Bangumi body")
    # Preserve the full original source body, even beyond indexing/response
    # limits. Infobox remains in raw with its original type and bytes.
    original = text
    docs = [_document(title, original)] if title or original else []
    raw = {k: v for k, v in row.items() if k not in {"name", "name_cn"}}
    return _entity(_key(name, f"bangumi.{name}", ident), aliases=aliases,
                   documents=docs, **raw)


def bangumi_relation(name, row):
    if name not in BANGUMI_RELATIONS:
        raise ValueError("unknown Bangumi relation")
    role = "native"
    if name == "subject-persons":
        src, dst = _key("subject", "bangumi.subject", row["subject_id"]), _key(
            "person", "bangumi.person", row["person_id"])
        relation = "credit_person"
    elif name == "subject-relations":
        src, dst = _key("subject", "bangumi.subject", row["subject_id"]), _key(
            "subject", "bangumi.subject", row["related_subject_id"])
        relation = "subject_relation"
    elif name == "subject-characters":
        src, dst = _key("subject", "bangumi.subject", row["subject_id"]), _key(
            "character", "bangumi.character", row["character_id"])
        relation = "features_character"
    elif name == "person-characters":
        src, dst = _key("person", "bangumi.person", row["person_id"]), _key(
            "character", "bangumi.character", row["character_id"])
        relation = "portrays_character"
    else:
        code = row.get("person_type")
        if code not in {"prsn", "crt"}:
            return {"record_type": "unresolved", "reason": "unknown_person_type",
                    "raw": row, "relation_file": name}
        kind = "person" if code == "prsn" else "character"
        src, dst = _key(kind, f"bangumi.{kind}", row["person_id"]), _key(
            kind, f"bangumi.{kind}", row["related_person_id"])
        relation = "person_relation" if kind == "person" else "character_relation"
    # Raw row preserves position, appear_eps, person-characters subject_id,
    # relation_type, order, spoiler, ended, type and summary in context.
    return {"record_type": "link", "src": src, "dst": dst, "relation": relation,
            "method": f"bangumi.Archive:{name}", "verification_status": role,
            "raw": row}


def iter_bangumi(directory, *, sample=None):
    root = Path(directory)
    for name in BANGUMI_FILES:
        with (root / f"{name}.jsonlines").open("rb") as stream:
            for position, line in enumerate(stream, 1):
                if sample is not None and position > sample:
                    break
                row = json.loads(line)
                yield name, bangumi_entity(name, row) if name not in BANGUMI_RELATIONS else (
                    bangumi_relation(name, row))


def moegirl_character(name, extra, attributes=(), subjects=(), cvs=(), gender=None):
    if not isinstance(extra, dict):
        raise TypeError("Moegirl character metadata must be object")
    aliases = [_alias(name, "title")]
    aliases += [_alias(alias, "extra_processed.\u522b\u540d") for alias in extra.get("\u522b\u540d", [])
                if isinstance(alias, str) and alias and alias != name]
    # Processed fields and the character-to-category list are not authenticated
    # page Wikitext or typed works. Retain as raw metadata, never synthesize body.
    return _entity(_key("character", "moegirl.character", name), aliases=aliases,
                   status="source_backed", extra_processed=extra,
                   raw_attributes=attributes, raw_subject_categories=subjects,
                   raw_cv_names=cvs, raw_gender=gender)


def moegirl_subject(name):
    return _entity(_key("subject", "moegirl.category", name),
                   aliases=[_alias(name, "subject_index")], raw_category_title=name)


def iter_moegirl(directory, *, sample=None):
    root = Path(directory)
    def load(name):
        with (root / f"{name}.json").open(encoding="utf-8") as stream:
            return json.load(stream)
    names = load("char_index")
    subjects = load("subject_index")
    extra = load("extra_processed")
    attrs = load("char2attr")
    categories = load("char2subject")
    cvs = load("char2cv")
    genders = load("char2gender")
    for name in names[:sample]:
        yield moegirl_character(name, extra.get(name, {}), attrs.get(name, []),
                                categories.get(name, []), cvs.get(name, []), genders.get(name))
    for name in subjects[:sample]:
        yield moegirl_subject(name)
    # Native category association is intentionally not a `character_of` work
    # relation, regardless of suffix; categories can encode regions/maintenance.
    # Mapping tables are processed separately as candidates, never verified.


def iter_moegirl_mappings(directory, *, sample=None):
    root = Path(directory)
    with (root / "bgm2moegirl.json").open(encoding="utf-8") as stream:
        forward = json.load(stream)
    with (root / "moegirl2bgm.json").open(encoding="utf-8") as stream:
        reverse = json.load(stream)
    for index, (ident, names) in enumerate(forward.items()):
        if sample is not None and index >= sample:
            break
        if not isinstance(names, list):
            raise TypeError("mapping must be a list")
        for name in names:
            if not isinstance(name, str) or not name:
                continue
            # These are not returned by `related`, which requires native/verified.
            yield {"record_type": "link", "src": _key("character", "bangumi.character", ident),
                   "dst": _key("character", "moegirl.character", name),
                   "relation": "identity_candidate", "method": "moegirl.bgm2moegirl",
                   "verification_status": "candidate", "raw": {"forward": names,
                   "reverse": reverse.get(name), "mapping_character_id": ident}}


def iter_danbooru_pages(parquet, *, sample=None):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Parquet import needs ingestion-only pyarrow") from exc
    rows = 0
    reader = pq.ParquetFile(parquet)
    for batch in reader.iter_batches(batch_size=512):
        for row in batch.to_pylist():
            key = _key("page", "danbooru.wiki", row["id"])
            if row["is_deleted"]:
                yield _entity(key, status="no_reference", raw_page=row)
            else:
                aliases = [_alias(row["title"], "title")]
                aliases += [_alias(value, "other_names") for value in row["other_names"] or []
                            if isinstance(value, str) and value]
                yield _entity(key, aliases=aliases,
                              documents=[_document(row["title"], row["body"] or "")],
                              raw_page_metadata={k: v for k, v in row.items() if k != "body"})
            rows += 1
            if sample is not None and rows >= sample:
                return


def iter_danbooru_links(parquet, *, sample=None):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Parquet import needs ingestion-only pyarrow") from exc
    rows = 0
    for batch in pq.ParquetFile(parquet).iter_batches(batch_size=512):
        for row in batch.to_pylist():
            if row["resolved_id"] is not None:
                yield {"record_type": "link", "src": _key("page", "danbooru.wiki",
                        row["source_id"]), "dst": _key("page", "danbooru.wiki",
                        row["resolved_id"]), "relation": "wiki_link",
                        "method": "danbooru.parquet", "verification_status": "native", "raw": row}
            else:
                yield {"record_type": "unresolved", "reason": "unresolved_wiki_link", "raw": row}
            rows += 1
            if sample is not None and rows >= sample:
                return


# Explicit audited partition/source vocabulary. Partitions are not datasets.
TAG_DATASETS = {
    "anime_pictures_1_noncommon": "anime_pictures_1",
    "bangumi_1_noncommon": "bangumi_1",
    "gamecg_5m_noncommon": "gamecg_5m",
    "konachan_1_noncommon": "konachan_1",
    "yande_1_noncommon": "yande_1",
    "zerochan_1_noncommon": "zerochan_1",
}


def tag_group_record(group, row):
    item = dict(row)
    if group not in GROUPS:
        raise ValueError("unknown seven-table group")
    coverage = item.get("source_count")
    if type(coverage) is not int or coverage < 0:
        raise ValueError("invalid source_count")
    sources = json.loads(item["sources_json"]) if item.get("sources_json") else []
    if not isinstance(sources, list) or any(s not in TAG_DATASETS.values() for s in sources):
        raise ValueError("invalid dataset membership")
    if len(sources) != len(set(sources)):
        raise ValueError("duplicate dataset membership")
    # Preserve every actual member, not just the partition's naming source.
    # Common with absent membership remains unknown, never a 'common' dataset.
    members = sorted(sources) or ([TAG_DATASETS[group]] if group in TAG_DATASETS else [None])
    occurrences = [{
        "occurrence_contract": "2", "partition": group, "dataset_id": member,
        "source_count": coverage, "sample_count": None,
        "membership_basis": "sources_json" if sources else
                            "partition_mapping" if member else "unknown",
        "raw": item,
    } for member in members]
    key = _key("tag", "local.tag_aggregate", item["tag_key"])
    return _entity(key, status="source_backed", aliases=[_alias(
        item["tag_key"], "tag_key")], occurrences=occurrences, raw_group=group, raw_tag=item)


def iter_tag_wiki(path, *, sample=None, danbooru_snapshot=None):
    # `path` MUST be a byte-frozen backup, not the live source's active WAL.
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for group in GROUPS:
            sql = f'SELECT * FROM "{group}" ORDER BY tag_key'
            if sample is not None:
                sql += f" LIMIT {int(sample)}"
            for row in conn.execute(sql):
                # Tag occurrences are observed by the seven datasets, but
                # Local aggregate of seven native tag-occurrence tables: no
                # native Danbooru tag identity is implied by shared spelling.
                yield tag_group_record(group, row)
        sql = "SELECT * FROM tag_evidence"
        if sample is not None:
            sql += f" LIMIT {int(sample)}"
        for row in conn.execute(sql):
            item = dict(row)
            # Confidence/exact title is a matching *candidate*, never proof
            # that the tag denotes the page. These records are not verified
            # entity_tag links and thus cannot make ask() assert an identity.
            yield {"record_type": "link", "src": _key("tag", "local.tag_aggregate",
                   item["tag_key"]), "dst": _key("page", "danbooru.wiki",
                   item["wiki_id"]), "relation": "wiki_match_candidate",
                   "method": "tag_wiki.tag_evidence", "verification_status": "candidate",
                   "raw": item}
        # Producer-supplied status='verified' or 'source_backed' in a model
        # cache is NOT evidence of human review or independent wiki support.
        for table, text_field in (("annotations", "semantic_summary"),
                                  ("full_annotation_cache", "result_json")):
            sql = f'SELECT * FROM "{table}"'
            if sample is not None:
                sql += f" LIMIT {int(sample)}"
            for row in conn.execute(sql):
                item = dict(row)
                raw_status = item["status"]
                status = "no_reference" if raw_status == "no_reference" else "unverified_draft"
                yield _entity(_key("tag", "local.tag_aggregate", item["tag_key"]),
                              status=status,
                              documents=[_document(item["tag_key"], item[text_field] or "",
                                                   status=status, raw_model=item.get("model"),
                                                   raw_annotation_status=raw_status)],
                              raw_annotation_source=table,
                              raw_annotation={k: v for k, v in item.items()
                                              if k != text_field})
        if danbooru_snapshot is not None:
            from .tag_wiki_provenance import Auditor, records
            checker = Auditor(path, danbooru_snapshot)
            try:
                for record in records(checker.tag):
                    result = checker.prove(record)
                    if result:
                        text, proof = result
                        yield _entity(_key('tag', 'local.tag_aggregate', record['tag_key']),
                                      status='generated_from_evidence',
                                      documents=[_document(record['tag_key'], text,
                                                           status='generated_from_evidence',
                                                           text_provenance=proof)])
            finally:
                checker.close()
    finally:
        conn.close()
