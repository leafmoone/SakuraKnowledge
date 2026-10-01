"""Offline P4 scoring adapter; no model, database, or benchmark execution.

CLI: python -m tools.p4_pilot_score --job LOCAL_JOB.json
Job paths: gold, corpus (JSONL), lexical, dense_a, dense_b, model_summary,
config, output; optional details and cpu. Output is a small create-new summary;
details retains all input hits and fused provenance. Paths must be under cwd.
Optional CPU input is retained in input bindings but is NOT_QUALIFIED:
self-declared receipts cannot establish measured hybrid retrieval costs.
A measured hybrid producer is required before CPU model selection.
The existing exact total_retrieve scope omits BM25/fusion and is NOT accepted.
"""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from statistics import mean

from tools import p4_retrieval_metrics as metrics

SUBSET_ALIASES = {"ambiguous/negative": "ambiguous_negative"}
FUSION = {"method": "rrf", "k": 60, "branch_depth": 100, "exact_alias_pinned": True}
SELECTION = {
    "min_semantic_recall10_gain": .10, "min_crosslingual_recall10_gain": .10,
    "min_semantic_crosslingual_mrr10_gain": 0.0,
    "min_semantic_crosslingual_ndcg10_gain": 0.0,
    "max_lexical_macro_recall10_loss": {"numerator": 1, "denominator": 30},
    "max_lexical_mrr10_loss": .03, "max_lexical_ndcg10_loss": .03,
    "max_comparable_subset_recall10_gap": .025, "max_comparable_overall_ndcg10_gap": .03,
    "quality_leader_order": ["mean_semantic_crosslingual_recall10_desc",
                             "mean_semantic_crosslingual_ndcg10_desc",
                             "overall_ndcg10_desc", "model_identifier_asc"],
    "tie_break_order": ["cpu_total_retrieve_p95", "peak_rss", "model_plus_index_bytes",
                        "model_identifier_asc"],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True, order=True)
class EntryKey:
    namespace: str
    kind: str
    entry_id: str

    def __post_init__(self):
        require(all(isinstance(v, str) and v.strip() for v in
                    (self.namespace, self.kind, self.entry_id)), "invalid typed identity")

    def arithmetic(self):
        # The arithmetic library's value slot is opaque. Only this explicit bridge
        # uses it for a snapshot-bound ID; source value is NEVER used as entry_id.
        return metrics.EntryKey(self.kind, self.namespace, self.entry_id)


def source_key(row):
    require(set(row) == {"kind", "namespace", "value"}, "invalid source entry schema")
    return metrics.EntryKey(**row)


def typed(row):
    key = source_key(row["entry_key"])
    value = row["entry_id"]
    require(type(value) is int and value > 0 or isinstance(value, str) and value.isdecimal(),
            "invalid anchor entry_id")
    return EntryKey(key.namespace, key.kind, str(value))


def case_map(rows, expected=None):
    result = {}
    for row in rows:
        cid = row["case_id"]
        require(isinstance(cid, str) and cid and cid not in result, "duplicate/invalid case ID")
        require(row.get("status", "PASS") == "PASS", "failed or NOT_RUN case")
        require(not row.get("promoted_identities"), "identity promotions are not supported by this adapter")
        result[cid] = row
    require(result and (expected is None or set(result) == set(expected)), "missing/extra cases")
    return result


class Mapping:
    def __init__(self, documents):
        self.documents = {}
        self.entries = {}
        reverse = {}
        for row in documents:
            did, key, identity = str(row["document_id"]), source_key(row["entry_key"]), typed(row)
            require(did not in self.documents, "duplicate corpus document")
            require(key not in self.entries or self.entries[key] == identity, "conflicting entry mapping")
            require(identity not in reverse or reverse[identity] == key, "conflicting source values")
            self.documents[did] = row
            self.entries[key] = identity
            reverse[identity] = key
        self.source_keys = {identity.arithmetic(): key for identity, key in reverse.items()}

    def identity(self, key):
        require(source_key(key) in self.entries, "unmapped source key")
        return self.entries[source_key(key)].arithmetic()

    def hit(self, row):
        doc = self.documents.get(row["document_id"])
        require(doc is not None and source_key(doc["entry_key"]) == source_key(row["entry"]),
                "hit document/entry mismatch")
        for field in ("source_id", "evidence_id"):
            require(row[field] == doc[field], "hit evidence mismatch")
        return metrics.Hit(**{**row, "entry": self.identity(row["entry"])})

    def hits(self, rows, dense=False):
        hits = [self.hit(row) for row in rows]
        require([h.rank for h in hits] == list(range(1, len(hits) + 1)), "nonconsecutive raw ranks")
        require(len(hits) <= 100, "branch exceeds frozen raw depth")
        if dense:
            require(len({h.entry for h in hits}) == len(hits), "dense must already be entry-max deduplicated")
        return hits


def fuse(mapping, backends, pins):
    # Identity stays snapshot-bound; ordering follows kind/namespace/source value.
    candidates = metrics.reciprocal_rank_fusion(backends, pins)
    ordered = sorted(candidates, key=lambda candidate: (
        0 if candidate.trusted_pins else 1,
        0.0 if candidate.trusted_pins else -candidate.rrf_score,
        mapping.source_keys[candidate.entry],
    ))
    return tuple(replace(candidate, hybrid_rank=rank)
                 for rank, candidate in enumerate(ordered, 1))


def quality_gates(baseline, report):
    failures = []
    for subset in ("lexical", "semantic", "crosslingual"):
        for metric in ("recall_at_10", "mrr_at_10", "ndcg_at_10"):
            base, value = (r[subset].metrics[metric].value for r in (baseline, report))
            require(base is not None and value is not None, "missing quality subset")
            threshold = (base - (1 / 30 if metric == "recall_at_10" else .03)
                         if subset == "lexical" else base + (.10 if metric == "recall_at_10" else 0))
            if value < threshold:
                failures.append(f"{subset}.{metric}")
    return failures


def diagnostic_reports(modes, anchors):
    paired, document_report = {}, {}
    for mode, rows in modes.items():
        if mode == "BM25_ONLY":
            continue
        paired[mode] = {}
        for subset in ("overall", *metrics.SUBSETS):
            paired[mode][subset] = {}
            for metric in metrics.METRICS:
                deltas = [getattr(r.metrics, metric) - getattr(b.metrics, metric)
                          for r, b in zip(rows, modes["BM25_ONLY"])
                          if (subset == "overall" or r.subset == subset) and r.target_count]
                paired[mode][subset][metric] = {"mean_delta": mean(deltas) if deltas else None,
                                                "denominator": len(deltas)}
    for mode, rows in anchors.items():
        document_report[mode] = {}
        for subset in ("overall", *metrics.SUBSETS):
            document_report[mode][subset] = {}
            for metric in ("recall_at_5", "recall_at_10", "recall_at_20"):
                values = [r[metric] for r in rows if r[metric] is not None and
                          (subset == "overall" or r["subset"] == subset)]
                document_report[mode][subset][metric] = {"value": mean(values) if values else None,
                                                        "denominator": len(values)}
    return paired, document_report


def score(gold, documents, lexical, dense, summary, config, bindings, cpu=None):
    """Score already-loaded artifacts. bindings contains hashes of exact input bytes."""
    require(config["fusion"] == FUSION and config["selection"] == SELECTION,
            "frozen numeric selection/fusion configuration changed")
    require(gold["schema_version"] == "p4-source-gold-v1" and
            gold["status"] == "FROZEN_PRE_EMBEDDING", "gold not frozen")
    cases = case_map(gold["cases"])
    subsets = {cid: SUBSET_ALIASES.get(c["subset"], c["subset"]) for cid, c in cases.items()}
    require(dict(Counter(subsets.values())) == config["case_counts"], "gold case counts mismatch")
    require(set(subsets.values()) <= set(metrics.SUBSETS), "unknown subset")
    require(lexical["schema"] == "p4-pilot-lexical-v1" and lexical.get("status", "PASS") == "PASS",
            "lexical schema/status mismatch")
    metadata = lexical["metadata"]
    require(metadata["binding_sha256"] == digest(canonical(
        {k: v for k, v in metadata.items() if k != "binding_sha256"})), "lexical binding mismatch")
    require(metadata["config_sha256"] == digest(canonical(metadata["config"])), "lexical config hash mismatch")
    require(metadata["config"]["document_depth"] == 100 and
            metadata["config"]["depth_before_entry_dedup"] is True, "lexical depth mismatch")
    for name in ("gold", "corpus"):
        require(metadata[name]["sha256"] == bindings[name], f"lexical {name} hash mismatch")
    require(metadata["snapshot"]["sha256"] == gold["base_snapshot_sha256"] == config["snapshot_sha256"],
            "snapshot hash mismatch")
    require(summary["status"] == "PASS", "model freeze failed")
    mapping = Mapping(documents)
    require(len(mapping.documents) == config["pilot_documents"] == metadata["document_count"],
            "corpus population mismatch")
    lex = case_map(lexical["cases"], cases)
    dense_cases = {}
    require(set(dense) == {"a", "b"}, "both models required")
    for model, artifact in dense.items():
        require(artifact["schema"] == "p4-exact-results-v2" and artifact["exact_reference"] is True
                and artifact["setup"]["status"] == "PASS" and artifact["depth"] == 100
                and artifact.get("status", "PASS") == "PASS"
                and artifact["aggregation"] == "maximum chunk dot score per typed entry", "invalid exact result")
        p, frozen = artifact["provenance"], summary["models"][model]
        for name in ("gold", "corpus", "summary"):
            require(p[name + "_sha256"] == bindings[name], f"dense {name} hash mismatch")
        require(p["model"] == model and p["repository"] == frozen["repository"] and
                p["revision"] == frozen["revision"] and
                p["model_inventory_sha256"] == frozen["obtained_receipt"]["inventory_sha256"] and
                p["contract_sha256"] == frozen["contract"]["file_sha256"], "model hash mismatch")
        dense_cases[model] = case_map(artifact["cases"], cases)
        require(all(c.get("status") == "PASS" for c in dense_cases[model].values()), "missing dense status")
    modes = {"BM25_ONLY": []}
    for model in ("A", "B"):
        modes.update({f"EXACT_DENSE_MODEL_{model}": [], f"RRF_HYBRID_MODEL_{model}": []})
    details = []
    anchors = {mode: [] for mode in modes}
    for cid, case in cases.items():
        targets, target_docs = [], set()
        for anchor in case["accepted_targets"]:
            require(mapping.identity(anchor["entry_key"]) == typed(anchor).arithmetic(), "anchor entry ID mismatch")
            doc = mapping.documents.get(str(anchor["document_id"]))
            require(doc is not None and typed(doc) == typed(anchor), "anchor document mismatch")
            for field in ("source_id", "evidence_id"):
                require(anchor[field] == doc[field], "anchor evidence mismatch")
            targets.append(typed(anchor).arithmetic())
            target_docs.add(str(anchor["document_id"]))
        row = lex[cid]
        require(row["query"] == case["query"] and row["subset"] == case["subset"] and
                row["mode"] == "BM25_ONLY" and row["identity_status"] == "not_asserted" and
                row["promoted_identities"] == [], "lexical case mismatch or identity promotion")
        hits = mapping.hits(row["raw_hits"])
        pins = [metrics.TrustedPin(**{**p, "entry": mapping.identity(p["entry"])})
                for p in row["trusted_pins"]]
        # BM25 pins and hybrid ties/pins share source-key, not snapshot-ID, order.
        source_pins = sorted({source_key(p["entry"]) for p in row["trusted_pins"]})
        ranking = list(dict.fromkeys([*(mapping.entries[p].arithmetic() for p in source_pins),
                                      *(h.entry for h in hits)]))[:100]
        require(ranking == [mapping.identity(k) for k in row["ranking"]], "lexical ranking mismatch")
        rankings = {"BM25_ONLY": ranking}
        document_lists = {"BM25_ONLY": [h.document_id for h in hits]}
        fused_details = {}
        for model in ("a", "b"):
            dh = mapping.hits(dense_cases[model][cid]["hits"], dense=True)
            dn, hn = f"EXACT_DENSE_MODEL_{model.upper()}", f"RRF_HYBRID_MODEL_{model.upper()}"
            fused = fuse(mapping, {"bm25": hits, "dense": dh}, pins)
            rankings[dn], rankings[hn] = [h.entry for h in dh], [c.entry for c in fused]
            document_lists[dn] = [h.document_id for h in dh]
            # Diagnostic document recall uses provenance of the first K fused
            # entries, not a fabricated document ranking or a pin's unseen document.
            document_lists[hn] = [[p.hit.document_id for p in c.provenance] for c in fused]
            fused_details[hn] = [asdict(c) for c in fused]
        for mode, ranking in rankings.items():
            modes[mode].append(metrics.evaluate_case(cid, subsets[cid], ranking, targets))
            recalls = {}
            for k in (5, 10, 20):
                docs = document_lists[mode][:k]
                found = {d for group in docs for d in group} if mode.startswith("RRF") else set(docs)
                recalls[f"recall_at_{k}"] = len(target_docs & found) / len(target_docs) if target_docs else None
            anchors[mode].append({"case_id": cid, "subset": subsets[cid], **recalls})
        details.append({"case_id": cid, "lexical": row,
                        "dense": {m: dense_cases[m][cid] for m in dense}, "fused": fused_details,
                        "scores": {m: asdict(rows[-1]) for m, rows in modes.items()}})
    reports = {m: metrics.aggregate_cases(rows) for m, rows in modes.items()}
    gates = {m: quality_gates(reports["BM25_ONLY"], reports[f"RRF_HYBRID_MODEL_{m.upper()}"])
             for m in ("a", "b")}
    qualifies = any(not failures for failures in gates.values())
    selection = {
        "status": "PENDING_CPU_HYBRID_EVIDENCE" if qualifies else "STOP",
        "selected": None if qualifies else "NONE",
        "quality_gate_failures": gates,
        "reason": ("measured CPU hybrid retrieval evidence required"
                   if qualifies else "neither hybrid passes the quality gates"),
        "cpu_evidence": {
            "status": "NOT_QUALIFIED" if cpu is not None else "NOT_RUN",
            "reason": "no measured hybrid producer exists; self-declared CPU receipts are not accepted; exact total_retrieve omits lexical retrieval and fusion",
        },
    }
    paired, document_report = diagnostic_reports(modes, anchors)
    return {"schema": "p4-pilot-score-v1", "bindings": bindings, "subset_aliases": SUBSET_ALIASES,
            "identity": "EntryKey(namespace,kind,entry_id string); corpus/anchor bound; never source value",
            "arithmetic_bridge": "fused detail entry.value is entry_id; original source keys retained in raw inputs",
            "warning": metrics.RELEVANCE_WARNING, "full": "NOT_RUN", "selection": selection,
            "metrics": {m: {s: asdict(a) for s, a in r.items()} for m, r in reports.items()},
            "candidate_counts": {m: {r.query_id: r.returned_count for r in rows} for m, rows in modes.items()},
            "paired_vs_bm25": paired, "document_anchor_recall": document_report,
            "document_policy": "BM25 raw documents; dense winning chunks; hybrid provenance of first K entries; pins alone supply no documents",
            "negative_policy": "empty targets are N/A (null); excluded from relevance means; no promotions created"}, details


def local(path):
    root = Path.cwd().resolve()
    result = (root / path).resolve()
    require(result.is_relative_to(root), "path escapes local root")
    return result


def load(path):
    raw = local(path).read_bytes()
    return json.loads(raw), digest(raw)


def save(path, value):
    with local(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    job, _ = load(args.job)
    inputs = {}
    hashes = {}
    for name in ("gold", "lexical", "dense_a", "dense_b", "model_summary", "config"):
        inputs[name], hashes[name] = load(job[name])
    corpus = local(job["corpus"])
    h = hashlib.sha256()
    documents = []
    with corpus.open("rb") as stream:
        for line in stream:
            h.update(line)
            documents.append(json.loads(line))
    hashes["corpus"] = h.hexdigest()
    hashes["summary"] = hashes.pop("model_summary")
    cpu = None
    if "cpu" in job:
        cpu, hashes["cpu"] = load(job["cpu"])
    outputs = [local(job[k]) for k in ("output", "details") if k in job]
    require(len(outputs) == len(set(outputs)) and not any(p.exists() for p in outputs), "output already exists")
    report, details = score(inputs["gold"], documents, inputs["lexical"],
                            {m: inputs[f"dense_{m}"] for m in ("a", "b")},
                            inputs["model_summary"], inputs["config"], hashes, cpu)
    if "details" in job:
        save(job["details"], details)
    save(job["output"], report)


if __name__ == "__main__":
    main()
