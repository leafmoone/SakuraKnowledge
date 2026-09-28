"""Shared read-only API for the CLI and Skill."""
from . import CONTRACT_VERSION
from .model import EntryKey, match_query
from .storage import readonly


class Knowledge:
    def __init__(self, path):
        self.conn = readonly(path)
        self.snapshot = self.conn.execute(
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

    def describe(self, row):
        key = EntryKey(row["kind"], row["namespace"], row["value"]).as_dict()
        docs = self.conn.execute(
            "SELECT title,original,source_id,evidence_id,status FROM documents WHERE entry_id=? "
            "AND status IN ('source_backed','generated_from_evidence') ORDER BY id LIMIT 10",
            (row["id"],)).fetchall()
        return {"entry_key": key, "locator": row["locator"],
                "descriptions": [{**dict(d), "original": d["original"][:4000]} for d in docs]}

    def lookup(self, query=None, *, key=None, kind=None, namespace=None):
        if key is not None:
            if isinstance(key, dict):
                key = EntryKey(**key)
            rows = self.conn.execute(
                "SELECT * FROM entries WHERE kind=? AND namespace=? AND value=?",
                key.parts()).fetchall()
            query = key.as_dict()
        else:
            if not isinstance(query, str) or not query or len(query) > 4096:
                raise ValueError("query must contain 1..4096 characters")
            rows = self.conn.execute(
                "SELECT DISTINCT e.* FROM entries e WHERE (e.value=? OR e.id IN "
                "(SELECT entry_id FROM aliases WHERE text=? AND status IN "
                "('source_backed','generated_from_evidence'))) "
                "AND (? IS NULL OR e.kind=?) AND (? IS NULL OR e.namespace=?) "
                "ORDER BY e.kind,e.namespace,e.value LIMIT 101",
                (query, query, kind, kind, namespace, namespace)).fetchall()
        candidates = [self.describe(r) for r in rows]
        result = self.result(query, "not_found" if not rows else
                             "found" if len(rows) == 1 else "ambiguous", candidates)
        if len(rows) == 1:
            result["entry_key"] = candidates[0]["entry_key"]
            result["canonical"] = candidates[0]
            result["descriptions"] = candidates[0]["descriptions"]
            result["citations"] = [{"source_id": d["source_id"], "evidence_id": d["evidence_id"]}
                                   for d in result["descriptions"]]
            if rows[0]["kind"] == "tag":
                result["tag_key"] = {k: rows[0][k] for k in ("namespace", "value")}
        if len(rows) > 100:
            result["warnings"].append("candidate_limit_reached")
        return result

    def search(self, query, *, topk=20, kind=None, namespace=None):
        if type(topk) is not int or not 1 <= topk <= 100:
            raise ValueError("topk must be 1..100")
        exact = self.lookup(query, kind=kind, namespace=namespace)
        compiled = match_query(query)
        if not compiled:
            if exact["status"] == "not_found":
                exact["warnings"].append("too_short")
            return exact
        rows = self.conn.execute(
            "SELECT e.*,bm25(search_fts) AS score FROM search_fts "
            "JOIN entries e ON e.id=search_fts.entry_id WHERE search_fts MATCH ? "
            "AND (? IS NULL OR e.kind=?) AND (? IS NULL OR e.namespace=?) "
            "ORDER BY score,e.kind,e.namespace,e.value,search_fts.rowid",
            (compiled, kind, kind, namespace, namespace))
        candidates = exact["candidates"][:topk]
        seen = {tuple(c["entry_key"].values()) for c in candidates}
        for row in rows:
            identity = (row["kind"], row["namespace"], row["value"])
            if identity not in seen and len(candidates) < topk:
                candidates.append(self.describe(row))
                seen.add(identity)
            if len(candidates) >= topk:
                break
        return self.result(query, "found" if candidates else "not_found", candidates)

    def related(self, key, *, relation=None, kind=None, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")
        if isinstance(key, dict):
            key = EntryKey(**key)
        base = self.lookup(key=key)
        if base["status"] != "found":
            return base
        rows = self.conn.execute(
            "SELECT l.*,d.kind,d.namespace,d.value FROM links l JOIN entries s ON s.id=l.src "
            "JOIN entries d ON d.id=l.dst WHERE s.kind=? AND s.namespace=? AND s.value=? "
            "AND l.verification_status IN ('native','redirect','verified') "
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
