"""Explicit response-v3 expectation deltas; preserve all original case inputs.

Locked before the formal repaired run. Grounded in independent introduction
fixtures, not harvested from matching runtimes. All other locked fields remain.
"""
from parity_cases import CASES as ORIGINAL_CASES


def repaired_cases():
    result = []
    for cid, op, args, original, mode in ORIGINAL_CASES:
        expected = dict(original)
        if original.get("query_template") == "introduce":
            expected["mapping_status"] = "not_requested"
            expected["target_namespace"] = None
            if expected["status"] == "entity_found_tag_unmapped":
                expected["status"] = "found"
        if cid == "E18":
            # Lightweight inspect must not walk the 21GB dbstat page table.
            expected["dbstat_status"] = "not_run"
        if cid == "U08":
            # Punctuation is a literal identity character, no longer stripped.
            expected = {"status": "unknown", "warnings": [], "n_candidates": 0,
                        "query_template": "introduce", "mapping_status": "not_requested",
                        "n_relations": 0, "parsed_subject": "975。", "target_namespace": None}
        result.append((cid, op, args, expected, mode))
    assert len(result) == 151
    return result


CASES = repaired_cases()
