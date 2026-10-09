"""Offline token-aware chunk projection used by source-pack preparation."""
from __future__ import annotations

import hashlib
import itertools
import json
import re
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from typing import Protocol

VERSION = "paragraph-model-tokenizer-v1"
MAX_TOKENS = 384
OVERLAP = 64
STATISTICS_DEFINITIONS = {
    "document_count": "Input documents, including empty token streams.",
    "chunk_count": "Emitted chunks.",
    "empty_token_document_count": "Documents whose complete canonical text has no tokens.",
    "canonical_token_count": "Complete document tokens counted once, without overlap or specials.",
    "chunk_canonical_token_count": "Sum of chunk canonical spans, including 64-position overlaps.",
    "chunk_token_count": "Sum of retokenized chunk tokens, including overlap, without prefixes/specials.",
    "inference_token_count": "Sum of chunk inference tokens, including passage prefix and specials.",
    "chunk_text_bytes": "Sum of UTF-8 chunk text bytes, including overlap; excludes JSON framing.",
    "oversized_paragraph_count": "Canonical paragraph token intervals longer than 384, counted once.",
    "oversized_paragraph_split_count": (
        "Nonfinal emitted ends strictly inside a canonical paragraph longer than 384; "
        "one event per end, never recounting a split because its tokens overlap."
    ),
    "nonparagraph_split_count": "All nonfinal emitted ends that are not paragraph boundaries.",
}


class Encoding(Protocol):
    ids: Sequence[int]
    offsets: Sequence[tuple[int, int]]


class Tokenizer(Protocol):
    """Character offsets; encode must never truncate or pad, including specials."""

    def encode(self, text: str, *, add_special_tokens: bool = False) -> Encoding: ...


class ChunkError(ValueError):
    """Invalid projection input or unsupported tokenizer behavior."""


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()




def require(condition, message):
    if not condition:
        raise ChunkError(message)


def valid_hash(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            "SHA256 must be lowercase hex")
    return value


def document_text(document):
    fields = []
    for name in ("title", "original"):
        value = document[name]
        require(value is None or isinstance(value, str), "invalid document text")
        fields.append((value or "").replace("\r\n", "\n").replace("\r", "\n"))
    return "\n\n".join(fields)


def offsets_for(tokenizer, text):
    encoded = tokenizer.encode(text, add_special_tokens=False)
    offsets = list(encoded.offsets)
    require(len(offsets) == len(encoded.ids), "token/offset count mismatch")
    previous_start = previous_end = 0
    for span in offsets:
        require(isinstance(span, (tuple, list)) and len(span) == 2,
                "unsupported offset span")
        start, end = span
        require(type(start) is int and type(end) is int
                and 0 <= start < end <= len(text)
                and start >= previous_start and end >= previous_end,
                "unsupported offsets: require monotonic nondegenerate character spans")
        # Equal spans are valid for byte-level tokens sharing a Unicode character.
        previous_start, previous_end = start, end
    return offsets


def inference_token_count(tokenizer, text, *, prefix, max_sequence_tokens):
    """Length validation only, also usable for the separate query prefix."""
    require(isinstance(text, str) and isinstance(prefix, str), "invalid inference text")
    require(type(max_sequence_tokens) is int and max_sequence_tokens > 0,
            "invalid max_sequence_tokens")
    count = len(tokenizer.encode(prefix + text, add_special_tokens=True).ids)
    require(count <= max_sequence_tokens, "inference token budget exceeded")
    return count


def project_document(document, tokenizer, *, base_snapshot_sha256,
                     tokenizer_inventory_sha256, passage_prefix, max_sequence_tokens,
                     statistics=None):
    """Return chunks; optionally replace statistics with defined document counters.

    Canonical tokens are unique original positions, not unique vocabulary IDs.
    Slice token counts can differ from canonical span sizes at Unicode/word edges.
    Statistics observe the projection and never change its boundaries.
    """
    valid_hash(base_snapshot_sha256)
    valid_hash(tokenizer_inventory_sha256)
    require(isinstance(passage_prefix, str), "invalid passage prefix")
    require(type(max_sequence_tokens) is int and max_sequence_tokens > 0,
            "invalid max_sequence_tokens")
    for field in ("document_id", "entry_id"):
        require(type(document[field]) is int, "document/entry IDs must be integers")
    key = document["entry_key"]
    require(isinstance(key, dict) and set(key) == {"kind", "namespace", "value"}
            and all(isinstance(v, str) for v in key.values()), "invalid typed entry key")
    for field in ("source_id", "evidence_id"):
        require(isinstance(document[field], (str, int))
                and not isinstance(document[field], bool) and bool(document[field]),
                "missing source/evidence reference")
    text = document_text(document)
    document_hash = digest(text.encode("utf-8"))
    offsets = offsets_for(tokenizer, text)
    starts = [span[0] for span in offsets]
    total = len(offsets)
    boundaries = sorted({bisect_left(starts, match.end())
                         for match in re.finditer(r"\n{2,}", text)} - {0})
    paragraph_edges = sorted({0, total, *boundaries})
    stats = dict.fromkeys(STATISTICS_DEFINITIONS, 0)
    stats.update(document_count=1, canonical_token_count=total,
                 empty_token_document_count=int(total == 0),
                 oversized_paragraph_count=sum(
                     right - left > MAX_TOKENS
                     for left, right in itertools.pairwise(paragraph_edges)))
    chunks, start = [], 0
    while start < total:
        end = min(start + MAX_TOKENS, total)
        if end != total:
            index = bisect_right(boundaries, end) - 1
            if index >= 0 and boundaries[index] > start + OVERLAP:
                end = boundaries[index]
        while True:
            require(end > start, "slice cannot fit token budget")
            char_start, char_end = offsets[start][0], offsets[end - 1][1]
            sliced = text[char_start:char_end]
            count = len(offsets_for(tokenizer, sliced))
            require(count > 0, "nonempty slice retokenized to empty stream")
            if count <= MAX_TOKENS:
                break
            end -= 1
            require(end > start + OVERLAP, "retokenization cannot progress with 64-token overlap")
        require(end == total or end > start + OVERLAP,
                "chunk cannot progress with 64-token overlap")
        inference_count = inference_token_count(
            tokenizer, sliced, prefix=passage_prefix, max_sequence_tokens=max_sequence_tokens)
        identity = {"version": VERSION, "base_snapshot_sha256": base_snapshot_sha256,
                    "tokenizer_inventory_sha256": tokenizer_inventory_sha256,
                    "document_id": document["document_id"], "chunk_index": len(chunks),
                    "canonical_token_start": start, "canonical_token_end": end,
                    "text_sha256": digest(sliced.encode("utf-8"))}
        chunks.append({**identity, "chunk_id": digest(canonical(identity)),
                       "entry_id": document["entry_id"], "entry_key": dict(key),
                       "kind": key["kind"], "namespace": key["namespace"],
                       "source_id": document["source_id"], "evidence_id": document["evidence_id"],
                       "document_text_sha256": document_hash, "text": sliced,
                       "char_start": char_start, "char_end": char_end,
                       "token_count": count, "inference_token_count": inference_count})
        stats["chunk_count"] += 1
        stats["chunk_canonical_token_count"] += end - start
        stats["chunk_token_count"] += count
        stats["inference_token_count"] += inference_count
        stats["chunk_text_bytes"] += len(sliced.encode("utf-8"))
        if end == total:
            break
        paragraph = bisect_right(paragraph_edges, end) - 1
        if paragraph_edges[paragraph] != end:
            stats["nonparagraph_split_count"] += 1
            if paragraph_edges[paragraph + 1] - paragraph_edges[paragraph] > MAX_TOKENS:
                stats["oversized_paragraph_split_count"] += 1
        start = end - OVERLAP
    if statistics is not None:
        statistics.clear()
        statistics.update(stats)
    return chunks
