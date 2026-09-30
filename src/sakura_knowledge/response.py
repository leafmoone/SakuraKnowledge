"""Small bounded response contract, independent of storage/search-text v2.

Fields are observations, never a merged fact. Absent fields are absent;
explicit null and empty arrays remain observations with their original type.
"""
import json

RESPONSE_VERSION = "3"
FIELD_NAMES = ("raw_attributes", "raw_subject_categories", "raw_cv_names", "raw_gender")
FIELD_OBSERVATIONS = 4
VALUE_BYTES = 2048
TEXT_CHARS = 256
ARRAY_ITEMS = 16
NESTING_DEPTH = 4
RESPONSE_BYTES = 524288


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def bounded_value(value, depth=0):
    truncated = False
    if isinstance(value, str):
        return value[:TEXT_CHARS], len(value) > TEXT_CHARS
    if isinstance(value, (dict, list)):
        if depth >= NESTING_DEPTH:
            return None, True
        if isinstance(value, list):
            out = []
            for item in value[:ARRAY_ITEMS]:
                bounded, changed = bounded_value(item, depth + 1)
                out.append(bounded)
                truncated |= changed
        else:
            out = {}
            for key in sorted(value)[:ARRAY_ITEMS]:
                bounded, changed = bounded_value(value[key], depth + 1)
                out[key[:TEXT_CHARS]] = bounded
                truncated |= changed or len(key) > TEXT_CHARS
        truncated |= len(value) > ARRAY_ITEMS
        if encoded_size(out) > VALUE_BYTES:
            return None, True
        return out, truncated
    return value, False


def source_observations(identities):
    fields, evidence = {}, []
    truncated_fields = set()
    for proof in identities:
        payload = json.loads(proof["payload"])
        raw = payload.get("raw", payload)
        if not isinstance(raw, dict):
            continue
        for name in FIELD_NAMES:
            if name not in raw:
                continue
            observations = fields.setdefault(name, [])
            if len(observations) >= FIELD_OBSERVATIONS:
                truncated_fields.add(name)
                continue
            value, truncated = bounded_value(raw[name])
            observations.append({"source_id": proof["source_id"],
                                 "evidence_id": proof["evidence_id"],
                                 "status": proof["status"], "value": value,
                                 "value_state": "null" if raw[name] is None else
                                                "empty" if raw[name] in ([], {}, "") else "present",
                                 "truncated": truncated})
            evidence.append({"field": name, "source_id": proof["source_id"],
                             "evidence_id": proof["evidence_id"], "status": proof["status"]})
    return fields, evidence, sorted(truncated_fields)


def bound_response(result):
    """Budget covers the full serialized object, including repeated canonical.

No identity key is truncated. Drop tail candidates/relations with a warning;
if a single irreducible identity exceeds the budget, return an explicit error.
"""
    while encoded_size(result) > RESPONSE_BYTES:
        if "response_budget_truncated" not in result["warnings"]:
            result["warnings"].append("response_budget_truncated")
        if len(result["candidates"]) > 1:
            result["candidates"].pop()
        elif result["relations"]:
            result["relations"].pop()
        else:
            raise ValueError("response_budget_exceeded")
    return result
