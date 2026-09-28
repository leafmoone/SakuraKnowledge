"""Audit character-space candidates without asserting cross-site identity."""
from collections import Counter

from .model import EntryKey


def audit_candidates(forward, reverse, character_ids, page_titles):
    counts = Counter(input=0, empty=0, one_to_many=0, missing=0, inconsistent=0)
    links = []
    for raw_id, titles in forward.items():
        cid = str(raw_id)
        if titles is None:
            titles = []
        if not isinstance(titles, list) or any(not isinstance(t, str) for t in titles):
            raise ValueError("mapping values must be lists of original page titles")
        counts["input"] += 1
        counts["empty"] += not titles
        counts["one_to_many"] += len(titles) > 1
        for title in titles:
            back = reverse.get(title, []) or []
            if not isinstance(back, list):
                raise TypeError("reverse mapping values must be ID lists")
            missing = cid not in character_ids or title not in page_titles
            inconsistent = cid not in {str(i) for i in back}
            counts["missing"] += missing
            counts["inconsistent"] += inconsistent
            links.append({"src": EntryKey("character", "bangumi.character", cid).as_dict(),
                          "dst": EntryKey("page", "moegirl.page", title).as_dict(),
                          "verification_status": "candidate", "target_missing": missing,
                          "reverse_inconsistent": inconsistent,
                          "forward_locator": f"/{cid}", "reverse_locator": f"/{title}"})
    counts["many_to_one"] = sum(isinstance(v, list) and len(v) > 1 for v in reverse.values())
    return {"counts": dict(counts), "candidates": links}
