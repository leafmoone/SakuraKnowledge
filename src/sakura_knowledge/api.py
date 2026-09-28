"""Shared read-only API for the CLI and Skill."""
import sqlite3
import time

from . import CONTRACT_VERSION
from .model import EntryKey, match_query
from .storage import readonly


class Knowledge:
    def __init__(self, path):
        self.conn = readonly(path)
        self._deadline = time.monotonic() + 5
        self.conn.set_progress_handler(lambda: int(time.monotonic() > self._deadline), 1000)
        self.conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2_000_000)
        self.snapshot = self._execute(
            "SELECT value FROM build_meta WHERE key='snapshot'").fetchone()[0]

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def result(self, query, status, candidates=(), warnings=()):
        return {"contract_version": CONTRACT_VERSION, "snapshot": self.snapshot,
                "query": query, "status": status, "entry_key": None, "tag_key": None,
                "canonical": None, "candidates": list(candidates), "descriptions": [],
                "relations": [], "citations": [], "warnings": list(warnings)}

    def _budget(self):
        self._deadline = time.monotonic() + 5

    def _execute(self, sql, parameters=()):
        try:
            return self.conn.execute(sql, parameters)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise ValueError("query_budget_exceeded") from exc
            raise

    def describe(self, row, alias_text=None):
        key = EntryKey(row["kind"], row["namespace"], row["value"]).as_dict()
        docs = self._execute(
            "SELECT title,substr(original,1,4000) AS original, "
            "length(original)>4000 AS response_truncated, "
            "json_extract(payload,'$.search_text_truncated') AS search_text_truncated, "
            "source_id,evidence_id,status FROM documents WHERE entry_id=? "
            "AND status IN ('source_backed','generated_from_evidence') ORDER BY id LIMIT 10",
            (row["id"],)).fetchall()
        aliases = (self._execute(
            "SELECT text,source_id,evidence_id,status FROM aliases WHERE entry_id=? AND text=? "
            "AND status IN ('source_backed','generated_from_evidence') "
            "ORDER BY source_id,evidence_id LIMIT 100", (row["id"], alias_text)).fetchall()
            if alias_text is not None else [])
        identities = self._execute(
            "SELECT source_id,evidence_id,status,type,locator FROM entry_evidence "
            "WHERE entry_id=? AND status IN ('source_backed','generated_from_evidence') "
            "ORDER BY source_id,evidence_id LIMIT 100", (row["id"],)).fetchall()
        identity_proofs = aliases if alias_text is not None and alias_text != row["value"] else identities
        return {"entry_key": key, "locator": row["locator"],
                "descriptions": [dict(d) for d in docs],
                "aliases": [dict(a) for a in aliases],
                "identity_evidence": [dict(d) for d in identities],
                "citations": [{"source_id": d["source_id"], "evidence_id": d["evidence_id"]}
                              for d in identity_proofs]}

    def lookup(self, query=None, *, key=None, kind=None, namespace=None):
        self._budget()
        trusted = ("e.conflicted=0 AND EXISTS (SELECT 1 FROM entry_evidence v "
                   "WHERE v.entry_id=e.id AND v.status IN "
                   "('source_backed','generated_from_evidence'))")
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
                "SELECT DISTINCT e.* FROM entries e WHERE (e.value=? OR e.id IN "
                "(SELECT entry_id FROM aliases WHERE text=? AND status IN "
                "('source_backed','generated_from_evidence'))) "
                "AND (? IS NULL OR e.kind=?) AND (? IS NULL OR e.namespace=?) "
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
                             "found" if len(rows) == 1 else "ambiguous", candidates)
        if len(rows) == 1:
            result["entry_key"] = candidates[0]["entry_key"]
            result["canonical"] = candidates[0]
            result["descriptions"] = candidates[0]["descriptions"]
            result["citations"] = candidates[0]["citations"]
            if rows[0]["kind"] == "tag":
                result["tag_key"] = {k: rows[0][k] for k in ("namespace", "value")}
        if len(rows) > 100:
            result["warnings"].append("candidate_limit_reached")
        return result

    def search(self, query, *, topk=20, kind=None, namespace=None):
        self._budget()
        if type(topk) is not int or not 1 <= topk <= 100:
            raise ValueError("topk must be 1..100")
        exact = self.lookup(query, kind=kind, namespace=namespace)
        compiled = match_query(query)
        if not compiled:
            if exact["status"] == "not_found":
                exact["warnings"].append("too_short")
            return exact
        # FTS scores rank documents; the first document of an entry in this ordering
        # represents its best score. Bound row scans, including duplicates from an
        # entry with many documents; never load unbounded query results into memory.
        rows = self._execute(
            "SELECT e.*,bm25(search_fts) AS score FROM search_fts "
            "JOIN entries e ON e.id=search_fts.entry_id WHERE search_fts MATCH ? "
            "AND e.conflicted=0 AND EXISTS (SELECT 1 FROM entry_evidence v "
            "WHERE v.entry_id=e.id AND v.status IN "
            "('source_backed','generated_from_evidence')) "
            "AND (? IS NULL OR e.kind=?) AND (? IS NULL OR e.namespace=?) "
            "ORDER BY score,e.kind,e.namespace,e.value,search_fts.rowid LIMIT 10001",
            (compiled, kind, kind, namespace, namespace))
        candidates = exact["candidates"][:topk]
        seen = {(c["entry_key"]["kind"], c["entry_key"]["namespace"],
                 c["entry_key"]["value"]) for c in candidates}
        scanned = 0
        for row in rows:
            if len(candidates) >= topk:
                break
            scanned += 1
            if scanned > 10000:
                break
            identity = (row["kind"], row["namespace"], row["value"])
            if identity not in seen:
                candidates.append(self.describe(row))
                seen.add(identity)
            if len(candidates) >= topk:
                break
        exact["candidates"] = candidates
        if exact["status"] == "not_found":
            exact["status"] = "found" if candidates else "not_found"
        if scanned > 10000 and len(candidates) < topk:
            exact["warnings"].append("search_document_scan_limit")
        return exact

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
            "SELECT l.*,d.kind,d.namespace,d.value FROM links l JOIN entries s ON s.id=l.src "
            "JOIN entries d ON d.id=l.dst WHERE s.kind=? AND s.namespace=? AND s.value=? "
            "AND l.verification_status IN ('native','redirect','verified') AND d.conflicted=0 "
            "AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=d.id "
            "AND v.status IN ('source_backed','generated_from_evidence')) "
            "AND (? IS NULL OR l.relation=?) AND (? IS NULL OR d.kind=?) "
            "ORDER BY l.relation,d.kind,d.namespace,d.value,l.id LIMIT ?",
            (*key.parts(), relation, relation, kind, kind, limit)).fetchall()
        base["relations"] = [{"dst": EntryKey(r["kind"], r["namespace"], r["value"]).as_dict(),
                              "relation": r["relation"], "method": r["method"],
                              "verification_status": r["verification_status"],
                              "source_id": r["source_id"], "evidence_id": r["evidence_id"],
                              "payload": r["payload"]} for r in rows]
        return base

    def ask(self, query, *, kind=None, namespace=None, target_tag_namespace=None):
        """Resolve an exact *source* entity, then independently assess a target tag.

        namespace filters source entities only. Spelling, wiki titles and candidate
        links do not confer membership in a requested target namespace.
        """
        self._budget()
        if target_tag_namespace is not None and (not isinstance(target_tag_namespace, str)
                                                 or not 1 <= len(target_tag_namespace) <= 256):
            raise ValueError("target_tag_namespace must contain 1..256 characters")
        result = self.lookup(query, kind=kind, namespace=namespace)
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
            "SELECT d.namespace,d.value,MIN(l.id) AS proof_id FROM links l "
            "JOIN entries d ON d.id=l.dst WHERE l.src=? AND l.relation='entity_tag' "
            "AND l.verification_status='verified' AND d.kind='tag' AND d.conflicted=0 "
            "AND (? IS NULL OR d.namespace=?) AND EXISTS "
            "(SELECT 1 FROM entry_evidence v WHERE v.entry_id=d.id "
            "AND v.status IN ('source_backed','generated_from_evidence')) "
            "GROUP BY d.namespace,d.value ORDER BY d.namespace,d.value LIMIT 2",
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
            result["answer"] = "Multiple verified tag mappings; no target selected."
        else:
            result["status"] = "entity_found_tag_unmapped"
            result["mapping_status"] = "target_unmapped" if target_tag_namespace else "unmapped"
            result["answer"] = (f"Source entity found; no verified tag mapping to "
                                f"{target_tag_namespace}." if target_tag_namespace else
                                "Source entity found; no verified tag mapping in any namespace.")
        return result
