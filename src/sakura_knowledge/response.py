"""Small bounded response contract, independent of storage/search-text v2.

Fields are observations, never a merged fact. Absent fields are absent;
explicit null and empty arrays remain observations with their original type.
"""
import json
import math

RESPONSE_VERSION = "3"
FIELD_NAMES = ("raw_attributes", "raw_subject_categories", "raw_cv_names", "raw_gender")
FIELD_OBSERVATIONS = 4
VALUE_BYTES = 2048
TEXT_CHARS = 256
ARRAY_ITEMS = 16
NESTING_DEPTH = 4
RESPONSE_BYTES = 524288


def projected_integer(lexeme):
    """Never construct unbounded bigints; overflow marker stays a small integer.

    JSON's scanner validates syntax before this callback. The marker is outside
    the response integer domain, so bounded_value emits null/truncated/present.
    No process-global digits limit is changed, including for ignored raw fields.
    """
    if len(lexeme) > 20:
        return 2**64
    value = int(lexeme)
    return value if -(2**63) <= value <= 2**64-1 else 2**64


def invalid_constant(lexeme):
    raise ValueError(f"invalid evidence JSON constant: {lexeme}")


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def bounded_value(value, depth=0, check=lambda: None):
    check()
    truncated = False
    if isinstance(value, str):
        return value[:TEXT_CHARS], len(value) > TEXT_CHARS
    if isinstance(value, (dict, list)):
        if depth >= NESTING_DEPTH:
            return None, True
        if isinstance(value, list):
            out = []
            for item in value[:ARRAY_ITEMS]:
                bounded, changed = bounded_value(item, depth + 1, check)
                out.append(bounded)
                truncated |= changed
        else:
            out = {}
            for key in sorted(value)[:ARRAY_ITEMS]:
                bounded, changed = bounded_value(value[key], depth + 1, check)
                out[key[:TEXT_CHARS]] = bounded
                truncated |= changed or len(key) > TEXT_CHARS
        truncated |= len(value) > ARRAY_ITEMS
        if encoded_size(out) > VALUE_BYTES:
            return None, True
        return out, truncated
    if isinstance(value, float) and not math.isfinite(value):
        return None, True
    # Interoperable JSON integer domain; raw source bytes stay in storage.
    if isinstance(value, int) and not isinstance(value, bool) and not -(2**63) <= value <= 2**64 - 1:
        return None, True
    return (None, True) if encoded_size(value) > VALUE_BYTES else (value, False)


def source_observations(identities, check=lambda: None):
    fields, evidence = {}, []
    truncated_fields = set()
    for proof in identities:
        check()
        payload = json.loads(proof["payload"], parse_int=projected_integer,
                             parse_constant=invalid_constant)
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
            value, truncated = bounded_value(raw[name], check=check)
            observations.append({"source_id": proof["source_id"],
                                 "evidence_id": proof["evidence_id"],
                                 "status": proof["status"], "value": value,
                                 "value_state": "null" if raw[name] is None else
                                                "empty" if raw[name] in ([], {}, "") else "present",
                                 "truncated": truncated})
            evidence.append({"field": name, "source_id": proof["source_id"],
                             "evidence_id": proof["evidence_id"], "status": proof["status"]})
    return fields, evidence, sorted(truncated_fields)


def bound_response(result, check=lambda: None):
    """Budget covers the full serialized object, including repeated canonical.

No identity key is truncated. Drop tail candidates/relations with a warning;
if a single irreducible identity exceeds the budget, return an explicit error.
"""
    def size(value):
        # Stream chunks; never repeatedly serialize the whole candidate tree.
        total = 0
        for chunk in json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(value):
            check()
            total += len(chunk.encode("utf-8"))
        check()
        return total

    total = size(result)
    if total > RESPONSE_BYTES:
        if "response_budget_truncated" not in result.get("warnings", []):
            warnings = result.setdefault("warnings", [])
            before = size(warnings)
            warnings.append("response_budget_truncated")
            total += size(warnings) - before
        while total > RESPONSE_BYTES:
            check()
            if len(result.get("candidates", [])) > 1:
                total -= size(result["candidates"].pop()) + 1
            elif result.get("relations"):
                total -= size(result["relations"].pop()) + bool(result["relations"])
            else:
                check()
                raise ValueError("response_budget_exceeded")
    check()
    return result
