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

    def ask(self, query, *, kind=None, namespace=None):
        self._budget()
        result = self.lookup(query, kind=kind, namespace=namespace)
        if result["status"] == "not_found":
            result["status"] = "unknown"
        elif result["status"] == "ambiguous":
            result["status"] = "entity_ambiguous"
        elif result["tag_key"] is None:
            linked = self.related(result["entry_key"], relation="entity_tag", kind="tag", limit=100)
            verified = [r for r in linked["relations"] if r["verification_status"] == "verified"]
            keys = {(r["dst"]["namespace"], r["dst"]["value"]) for r in verified}
            result["relations"] = verified
            result["status"] = ("entity_found_tag_unmapped" if not keys else
                                "tag_ambiguous" if len(keys) > 1 else "found")
            if len(keys) == 1:
                ns, value = next(iter(keys))
                result["tag_key"] = {"namespace": ns, "value": value}
            result["citations"].extend({"source_id": r["source_id"], "evidence_id": r["evidence_id"]}
                                       for r in verified)
        result["answer"] = {"unknown": "No reliable exact entity match.",
                            "entity_ambiguous": "Multiple entity matches; specify a key.",
                            "tag_ambiguous": "Multiple explicit tag mappings; no tag selected.",
                            "entity_found_tag_unmapped": "Entity found; no verified tag mapping.",
                            "found": "Reliable exact match found."}[result["status"]]
        return result
