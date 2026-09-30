"""Shared read-only API for the CLI and Skill."""
import re
import sqlite3
import time
from functools import wraps

from . import CONTRACT_VERSION
from .model import IDENTITY_TRUSTED, TEXT_TRUSTED, EntryKey, match_query
from .response import RESPONSE_VERSION, bound_response, source_observations
from .search import FILTERED_SQL, select_rows
from .search import SQL as SEARCH_SQL
from .storage import readonly

_ID = ", ".join(f"'{s}'" for s in sorted(IDENTITY_TRUSTED))
_TEXT = ", ".join(f"'{s}'" for s in sorted(TEXT_TRUSTED))

# Bounded, deterministic natural-language templates. The subject X is taken
# verbatim (inner punctuation, brackets and underscores are never normalized);
# only surrounding whitespace is stripped. Parsing is separate from lookup.
_ASK_DANBOORU = re.compile(
    r"^(?P<x>.+?)\s*的\s*danbooru\s*tag\s*是什么\s*[？?。.\s]*$", re.IGNORECASE)
_ASK_TAG = re.compile(r"^(?P<x>.+?)\s*的\s*标签\s*是什么\s*[？?。.\s]*$")
_ASK_INTRODUCE = re.compile(r"^介绍(?:一下)?\s*(?P<x>.+?)\s*$")


def parse_ask_template(query):
    """Return (subject, mode) for a supported template, else None."""
    if not isinstance(query, str) or not 1 <= len(query) <= 4096:
        raise ValueError("query must contain 1..4096 characters")
    for pattern, mode in ((_ASK_DANBOORU, "danbooru.tag"),
                          (_ASK_TAG, "tag"), (_ASK_INTRODUCE, "introduce")):
        match = pattern.fullmatch(query)
        if match and match.group("x").strip():
            return match.group("x").strip(), mode
    return None


def bounded_response(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        outer = self._operation_depth == 0
        if outer:
            self._deadline = time.monotonic() + 5
        self._operation_depth += 1
        try:
            result = bound_response(method(self, *args, **kwargs))
            self._check_deadline()
            return result
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise ValueError("query_budget_exceeded") from exc
            raise
        finally:
            self._operation_depth -= 1
    return wrapped


class Knowledge:
    def __init__(self, path):
        self.conn = readonly(path)
        self._deadline = time.monotonic() + 5
        self._operation_depth = 0
        self.last_search_profile = {}
        self.conn.set_progress_handler(lambda: int(time.monotonic() > self._deadline), 1000)
        self.conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2_000_000)
        try:
            self._validate_storage()
        except Exception:
            self.conn.close()
            raise

    def _validate_storage(self):
        """Read-only constant-size capability/schema gate, never integrity_scan."""
        try:
            meta = dict(self._execute("SELECT key,value FROM build_meta WHERE key IN "
                                      "('contract_version','search_text_version','snapshot')"))
            for key in ("contract_version", "search_text_version"):
                if meta.get(key) != "2":
                    raise ValueError(f"unsupported {key}: {meta.get(key)}")
            if not meta.get("snapshot"):
                raise ValueError("missing snapshot identity")
            required = {
                "entries": "id kind namespace value locator conflicted",
                "entry_evidence": "id entry_id source_id evidence_id status type locator payload",
                "aliases": "id entry_id text source_id evidence_id status",
                "documents": "id entry_id title original status source_id evidence_id payload",
                "links": "id src dst relation method verification_status source_id evidence_id payload",
                "search_fts": "text document_id entry_id",
            }
            for table, names in required.items():
                columns = {r[1] for r in self._execute(f"PRAGMA table_info({table})")}
                missing = sorted(set(names.split()) - columns)
                if missing:
                    raise ValueError(f"invalid snapshot schema: {table} missing {','.join(missing)}")
            definition = self._execute("SELECT sql FROM sqlite_master WHERE name='search_fts'")
            if "using fts5" not in definition.fetchone()[0].lower():
                raise ValueError("invalid snapshot schema: search_fts is not FTS5")
            self._execute("SELECT rowid FROM search_fts WHERE search_fts MATCH ? LIMIT 0",
                          ('"runtime_capability_probe"',)).fetchall()
            if self._execute("SELECT json_extract('{\"probe\":1}', '$.probe')").fetchone()[0] != 1:
                raise ValueError("SQLite JSON capability unavailable")
            self.snapshot = meta["snapshot"]
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"invalid snapshot schema or capability: {exc}") from exc

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def result(self, query, status, candidates=(), warnings=()):
        return {"contract_version": CONTRACT_VERSION, "response_version": RESPONSE_VERSION,
                "snapshot": self.snapshot,
                "query": query, "status": status, "entry_key": None, "tag_key": None,
                "canonical": None, "candidates": list(candidates), "descriptions": [],
                "relations": [], "citations": [], "warnings": list(warnings)}

    @staticmethod
    def runtime_info():
        return {"contract_version": CONTRACT_VERSION, "sqlite_version": sqlite3.sqlite_version,
                "runtime": "python"}

    def inspect(self):
        self._budget()
        page_size = self._execute("PRAGMA page_size").fetchone()[0]
        page_count = self._execute("PRAGMA page_count").fetchone()[0]
        freelist_count = self._execute("PRAGMA freelist_count").fetchone()[0]
        # Optional dbstat is a whole-file page walk, not a lightweight inspect.
        # Keep it explicitly NOT_RUN rather than silently timing out or scanning.
        dbstat = None
        dbstat_status = "not_run"
        meta = {r["key"]: r["value"] for r in self._execute(
            "SELECT key,value FROM build_meta WHERE key IN ('contract_version','snapshot')")}
        return {"snapshot": self.snapshot, "contract_version": meta.get("contract_version"),
                "page_size": page_size, "page_count": page_count,
                "freelist_count": freelist_count, "dbstat_pages": dbstat,
                "dbstat_status": dbstat_status, "read_only": True}

    def _budget(self):
        if self._operation_depth == 0:
            self._deadline = time.monotonic() + 5
        self._check_deadline()

    def _check_deadline(self):
        if time.monotonic() > self._deadline:
            raise ValueError("query_budget_exceeded")

    def _execute(self, sql, parameters=()):
        self._check_deadline()
        try:
            return self.conn.execute(sql, parameters)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise ValueError("query_budget_exceeded") from exc
            raise

    def describe(self, row, alias_text=None):
        key = EntryKey(row["kind"], row["namespace"], row["value"]).as_dict()
        # Descriptions are TEXT_TRUSTED; identity proofs are IDENTITY_TRUSTED.
        docs = self._execute(
            f"SELECT title,substr(original,1,4000) AS original, "
            f"length(original)>4000 AS response_truncated, "
            f"json_extract(payload,'$.search_text_truncated') AS search_text_truncated, "
            f"source_id,evidence_id,status FROM documents WHERE entry_id=? "
            f"AND status IN ({_TEXT}) ORDER BY id LIMIT 10",
            (row["id"],)).fetchall()
        docs = [{**dict(d), "response_truncated": bool(d["response_truncated"]),
                 "search_text_truncated": (None if d["search_text_truncated"] is None else
                                           bool(d["search_text_truncated"]))} for d in docs]
        aliases = (self._execute(
            f"SELECT text,source_id,evidence_id,status FROM aliases WHERE entry_id=? AND text=? "
            f"AND status IN ({_ID}) "
            f"ORDER BY source_id,evidence_id LIMIT 100", (row["id"], alias_text)).fetchall()
            if alias_text is not None else [])
        identities = self._execute(
            f"SELECT source_id,evidence_id,status,type,locator,payload FROM entry_evidence "
            f"WHERE entry_id=? AND status IN ({_ID}) "
            f"ORDER BY source_id,evidence_id LIMIT 101", (row["id"],)).fetchall()
        identities_truncated = len(identities) > 100
        identities = identities[:100]
        identity_proofs = aliases if alias_text is not None and alias_text != row["value"] else identities
        fields, field_evidence, field_truncated = source_observations(identities)
        citations = [{"source_id": d["source_id"], "evidence_id": d["evidence_id"]}
                     for d in identity_proofs]
        return {"entry_key": key, "locator": row["locator"],
                "descriptions": [dict(d) for d in docs],
                "matched_documents": [dict(d) for d in docs],
                "aliases": [dict(a) for a in aliases],
                "identity_evidence": [{k: d[k] for k in
                                       ("source_id", "evidence_id", "status", "type", "locator")}
                                      for d in identities],
                "source_fields": fields, "source_fields_evidence": field_evidence,
                "source_fields_truncated": field_truncated,
                "identity_evidence_truncated": identities_truncated,
                "matched_by": "exact" if alias_text is None or alias_text == row["value"] else "alias",
                "source_id": identity_proofs[0]["source_id"] if identity_proofs else None,
                "evidence_id": identity_proofs[0]["evidence_id"] if identity_proofs else None,
                "citations": citations}

    @bounded_response
    def lookup(self, query=None, *, key=None, kind=None, namespace=None):
        self._budget()
        # Identity resolution: source-anchored evidence only; a generated
        # alias alone can never resolve an identity.
        trusted = ("e.conflicted=0 AND EXISTS (SELECT 1 FROM entry_evidence v "
                   f"WHERE v.entry_id=e.id AND v.status IN ({_ID}))")
        if key is not None:
            if isinstance(key, dict):
                key = EntryKey(**key)
            rows = self._execute(
                f"SELECT e.* FROM entries e WHERE e.kind=? AND e.namespace=? AND e.value=? "
                f"AND {trusted}", key.parts()).fetchall()
            query = key.as_dict()
        else:
            if not isinstance(query, str) or not query or len(query) > 4096:
                raise ValueError("query must contain 1..4096 characters")
            rows = self._execute(
                f"SELECT DISTINCT e.* FROM entries e WHERE (e.value=? OR e.id IN "
                f"(SELECT entry_id FROM aliases WHERE text=? AND status IN ({_ID}))) "
                f"AND (? IS NULL OR e.kind=?) AND (? IS NULL OR e.namespace=?) "
                f"AND {trusted} ORDER BY e.kind,e.namespace,e.value LIMIT 101",
                (query, query, kind, kind, namespace, namespace)).fetchall()
        paired = [(r, self.describe(r, query if key is None and query != r["value"]
                                    else None)) for r in rows]
        # An alias-only match needs its matching trusted alias, not unrelated
        # entry evidence; a direct value or full key needs trusted entry evidence.
        paired = [(r, c) for r, c in paired if c["citations"]]
        rows = [r for r, _ in paired]
        candidates = [c for _, c in paired]
        result = self.result(query, "not_found" if not rows else
                             "found" if len(rows) == 1 else "ambiguous", candidates[:100])
        if len(rows) == 1:
            result["entry_key"] = candidates[0]["entry_key"]
            result["canonical"] = candidates[0]
            result["descriptions"] = candidates[0]["descriptions"]
            result["matched_documents"] = candidates[0]["matched_documents"]
            result["source_fields"] = candidates[0]["source_fields"]
            result["source_fields_evidence"] = candidates[0]["source_fields_evidence"]
            result["source_fields_truncated"] = candidates[0]["source_fields_truncated"]
            result["matched_by"] = candidates[0]["matched_by"]
            result["source_id"] = candidates[0]["source_id"]
            result["evidence_id"] = candidates[0]["evidence_id"]
            result["citations"] = candidates[0]["citations"]
            if rows[0]["kind"] == "tag":
                result["tag_key"] = {k: rows[0][k] for k in ("namespace", "value")}
        if len(rows) > 100:
            result["warnings"].append("candidate_limit_reached")
        return result

    @bounded_response
    def search(self, query, *, topk=20, kind=None, namespace=None):
        self._budget()
        if type(topk) is not int or not 1 <= topk <= 100:
            raise ValueError("topk must be 1..100")
        started = time.perf_counter()
        self.last_search_profile = {"scanned_rows": 0, "materialized_matched_documents": 0,
                                    "returned_matched_body_utf8_bytes": 0}
        exact = self.lookup(query, kind=kind, namespace=namespace)
        self.last_search_profile["exact_identity_assembly_s"] = time.perf_counter() - started
        compiled = match_query(query)
        if len(exact["candidates"]) >= topk:
            exact["candidates"] = exact["candidates"][:topk]
            self.last_search_profile["fts_skipped_exact_sufficient"] = True
            return exact
        if not compiled:
            exact["candidates"] = exact["candidates"][:topk]
            if exact["status"] == "not_found":
                exact["warnings"].append("too_short")
            return exact
        candidates = exact["candidates"][:topk]
        seen = {(c["entry_key"]["kind"], c["entry_key"]["namespace"],
                 c["entry_key"]["value"]) for c in candidates}
        started = time.perf_counter()
        rows = self._execute(FILTERED_SQL if kind or namespace else SEARCH_SQL,
                             (compiled, kind, namespace))
        self.last_search_profile["fts_execute_first_row_s"] = time.perf_counter() - started
        started = time.perf_counter()
        try:
            selected, scanned, truncated = select_rows(rows, seen, topk - len(candidates),
                                                        self._check_deadline)
        finally:
            rows.close()
        self.last_search_profile.update(scanned_rows=scanned, selected_identities=len(selected),
                                        fts_select_s=time.perf_counter() - started)
        self.last_search_profile["identity_field_assembly_s"] = 0.0
        self.last_search_profile["matched_document_read_s"] = 0.0
        for row in selected:
            started = time.perf_counter()
            candidate = self.describe(row)
            self.last_search_profile["identity_field_assembly_s"] += time.perf_counter() - started
            started = time.perf_counter()
            document = self._execute(
                "SELECT title,substr(original,1,4000) AS original,length(original)>4000 AS truncated,"
                "source_id,evidence_id FROM documents WHERE id=?", (row["document_id"],)).fetchone()
            self.last_search_profile["matched_document_read_s"] += time.perf_counter() - started
            self.last_search_profile["materialized_matched_documents"] += 1
            self.last_search_profile["returned_matched_body_utf8_bytes"] += len(document["original"].encode("utf-8"))
            candidate["matched_by"] = "fts"
            candidate["score"] = row["score"]
            candidate["matched_documents"] = [{"title": document["title"],
                "original": document["original"], "response_truncated": bool(document["truncated"]),
                "source_id": document["source_id"], "evidence_id": document["evidence_id"]}]
            candidate["source_id"] = document["source_id"]
            candidate["evidence_id"] = document["evidence_id"]
            candidates.append(candidate)
        exact["candidates"] = candidates
        if exact["status"] == "not_found":
            exact["status"] = "found" if candidates else "not_found"
        if truncated:
            exact["warnings"].append("search_document_scan_limit")
        return exact

    @bounded_response
    def related(self, key, *, relation=None, kind=None, limit=20):
        self._budget()
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")
        if isinstance(key, dict):
            key = EntryKey(**key)
        base = self.lookup(key=key)
        if base["status"] != "found":
            return base
        rows = self._execute(
            f"SELECT l.*,d.kind,d.namespace,d.value FROM links l JOIN entries s ON s.id=l.src "
            f"JOIN entries d ON d.id=l.dst WHERE s.kind=? AND s.namespace=? AND s.value=? "
            f"AND l.verification_status IN ('native','redirect','verified') AND d.conflicted=0 "
            f"AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=d.id "
            f"AND v.status IN ({_ID})) "
            f"AND (? IS NULL OR l.relation=?) AND (? IS NULL OR d.kind=?) "
            f"ORDER BY l.relation,d.kind,d.namespace,d.value,l.id LIMIT ?",
            (*key.parts(), relation, relation, kind, kind, limit)).fetchall()
        base["relations"] = [{"dst": EntryKey(r["kind"], r["namespace"], r["value"]).as_dict(),
                              "relation": r["relation"], "method": r["method"],
                              "verification_status": r["verification_status"],
                              "source_id": r["source_id"], "evidence_id": r["evidence_id"],
                              "payload": r["payload"]} for r in rows]
        return base

    @bounded_response
    def ask(self, query, *, kind=None, namespace=None, target_tag_namespace=None):
        """Resolve an exact *source* entity, then independently assess a target tag.

        namespace filters source entities only. Spelling, wiki titles and candidate
        links do not confer membership in a requested target namespace.
        A small set of deterministic Chinese templates ("X 的 Danbooru tag 是什么",
        "X 的标签是什么", "介绍一下 X") is parsed first; anything else is treated
        as a direct entity name (existing API behaviour) and marked
        unsupported when it resolves to nothing.
        """
        self._budget()
        if target_tag_namespace is not None and (not isinstance(target_tag_namespace, str)
                                                 or not 1 <= len(target_tag_namespace) <= 256):
            raise ValueError("target_tag_namespace must contain 1..256 characters")
        direct = self.lookup(query, kind=kind, namespace=namespace)
        if direct["status"] in ("found", "ambiguous"):
            result = self._ask_resolved(query, kind=kind, namespace=namespace,
                                        target_tag_namespace=target_tag_namespace, resolved=direct)
            result["input_query"] = query
            result["parsed_subject"] = None
            result["query_template"] = "unsupported"
            return result
        parsed = parse_ask_template(query)
        if parsed is None:
            result = self._ask_resolved(query, kind=kind, namespace=namespace,
                                        target_tag_namespace=target_tag_namespace, resolved=direct)
            result["query_template"] = "unsupported"
            if result["status"] == "unknown":
                result["warnings"].append("unsupported_query_template")
            return result
        subject, mode = parsed
        if mode == "introduce":
            if target_tag_namespace is not None:
                raise ValueError("introduce template cannot combine with target_tag_namespace")
            result = self.lookup(subject, kind=kind, namespace=namespace)
            result["mapping_status"] = "not_requested"
            result["target_namespace"] = None
            if result["status"] == "not_found":
                result["status"] = "unknown"
                result["answer"] = "No reliable exact source entity match."
            elif result["status"] == "ambiguous":
                result["status"] = "entity_ambiguous"
                result["answer"] = "Multiple source entity matches; specify a source key."
            result["input_query"] = query
            result["parsed_subject"] = subject
            result["query_template"] = "introduce"
            if result["status"] == "found":
                result["answer"] = (f"Source entity {result['entry_key']['namespace']}"
                                    f"/{result['entry_key']['value']}; see descriptions "
                                    "and citations for source-backed text.")
            return result
        if mode == "danbooru.tag":
            if target_tag_namespace not in (None, "danbooru.tag"):
                raise ValueError("template implies target danbooru.tag; explicit "
                                 "target_tag_namespace conflicts")
            result = self._ask_resolved(subject, kind=kind, namespace=namespace,
                                        target_tag_namespace="danbooru.tag")
            result["input_query"] = query
            result["parsed_subject"] = subject
            result["query_template"] = "danbooru_tag"
            return result
        result = self._ask_resolved(subject, kind=kind, namespace=namespace,
                                    target_tag_namespace=target_tag_namespace)
        result["input_query"] = query
        result["parsed_subject"] = subject
        result["query_template"] = "tag"
        return result

    def _ask_resolved(self, query, *, kind=None, namespace=None, target_tag_namespace=None,
                      resolved=None):
        result = (resolved if resolved is not None else
                  self.lookup(query, kind=kind, namespace=namespace))
        result["input_query"] = query
        result["parsed_subject"] = None
        result["target_namespace"] = target_tag_namespace
        result["mapping_status"] = "unknown"
        if result["status"] == "not_found":
            result["status"] = "unknown"
            result["answer"] = "No reliable exact source entity match."
            return result
        if result["status"] == "ambiguous":
            result["status"] = "entity_ambiguous"
            result["mapping_status"] = "entity_ambiguous"
            result["answer"] = "Multiple source entity matches; specify a source key."
            return result

        source_tag = result["tag_key"]
        if source_tag and (target_tag_namespace is None or
                           source_tag["namespace"] == target_tag_namespace):
            result["mapping_status"] = ("target_identity" if target_tag_namespace is not None
                                        else "local_identity_only" if
                                        source_tag["namespace"] == "local.tag_aggregate"
                                        else "source_identity_only")
            result["answer"] = (f"Exact tag identity in {source_tag['namespace']}; "
                                "no cross-namespace mapping inferred.")
            return result
        # Do not retain a source tag as the *target* when its namespace differs.
        result["tag_key"] = None
        key = result["entry_key"]
        src_id = self._execute(
            "SELECT id FROM entries WHERE kind=? AND namespace=? AND value=?",
            (key["kind"], key["namespace"], key["value"])).fetchone()[0]
        # A display limit on related() is NOT a cardinality proof: the 101st
        # verified link could point to a second target. Group all eligible
        # edges, then fetch at most two *distinct* trusted target identities.
        identities = self._execute(
            f"SELECT d.namespace,d.value,MIN(l.id) AS proof_id FROM links l "
            f"JOIN entries d ON d.id=l.dst WHERE l.src=? AND l.relation='entity_tag' "
            f"AND l.verification_status='verified' AND d.kind='tag' AND d.conflicted=0 "
            f"AND (? IS NULL OR d.namespace=?) AND EXISTS "
            f"(SELECT 1 FROM entry_evidence v WHERE v.entry_id=d.id "
            f"AND v.status IN ({_ID})) "
            f"GROUP BY d.namespace,d.value ORDER BY d.namespace,d.value LIMIT 2",
            (src_id, target_tag_namespace, target_tag_namespace)).fetchall()
        for identity in identities:
            proof = self._execute(
                "SELECT relation,method,verification_status,source_id,evidence_id,payload "
                "FROM links WHERE id=?", (identity["proof_id"],)).fetchone()
            result["relations"].append({"dst": {"kind": "tag", "namespace": identity["namespace"],
                                                 "value": identity["value"]},
                                        **dict(proof)})
            result["citations"].append({"source_id": proof["source_id"],
                                        "evidence_id": proof["evidence_id"]})
        if len(identities) == 1:
            ns, value = identities[0]["namespace"], identities[0]["value"]
            result["tag_key"] = {"namespace": ns, "value": value}
            result["mapping_status"] = "target_verified" if target_tag_namespace else "verified"
            result["answer"] = f"Verified entity_tag mapping to {ns}; source entity retained."
        elif len(identities) > 1:
            result["status"] = "tag_ambiguous"
            result["mapping_status"] = "target_ambiguous" if target_tag_namespace else "ambiguous"
            result["answer"] = "Multiple verified tag mappings; no tag selected."
        else:
            result["status"] = "entity_found_tag_unmapped"
            result["mapping_status"] = "target_unmapped" if target_tag_namespace else "unmapped"
            result["answer"] = (f"Source entity found; no verified tag mapping to "
                                f"{target_tag_namespace}." if target_tag_namespace else
                                "Source entity found; no verified tag mapping in any namespace.")
        return result
