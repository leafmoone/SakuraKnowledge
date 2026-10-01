"""Offline P4 chunk projection; no model loading, inference, or network access.

CLI accepts a p4_corpus JSONL and its manifest, a frozen model plan (repository,
revision, contract), and an explicitly SHA-bound tokenizer.json. The plan's
contract supplies max_sequence_tokens, query_prefix and passage_prefix. Outputs
are a new directory under build/p4, containing chunks.jsonl and manifest.json.
Failures leave partial output as evidence; existing output is never replaced.
The optional tokenizers dependency is imported only by main().
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

VERSION = "paragraph-model-tokenizer-v1"
MAX_TOKENS = 384
OVERLAP = 64
ROOT = Path(__file__).resolve().parents[1]


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


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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
                     tokenizer_inventory_sha256, passage_prefix, max_sequence_tokens):
    """Return chunks in document order; [] explicitly represents an empty stream."""
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
        if end == total:
            break
        start = end - OVERLAP
    return chunks


def export(corpus, corpus_manifest, output, tokenizer, inventory, contract, *, root=ROOT):
    """Standalone JSON interface; verifies frozen corpus bytes before writing."""
    root = Path(root).resolve()
    corpus, output = Path(corpus), Path(output).absolute()
    allowed = root / "build" / "p4"
    require(output != allowed and output.is_relative_to(allowed), "output must be under build/p4")
    current = root
    for part in output.relative_to(root).parts:
        require(part not in ('.', '..'), "output path traversal")
        current = current / part
        require(not current.is_symlink(), "output symlink forbidden")
        if current.exists():
            require(not (getattr(current.lstat(), 'st_file_attributes', 0) & 0x400),
                    "output reparse point forbidden")
        require(current.resolve().is_relative_to(root), "output path escape")
    expected = valid_hash(corpus_manifest["corpus_sha256"])
    require(file_digest(corpus) == expected, "corpus SHA256 mismatch")
    snapshot = valid_hash(corpus_manifest["base_snapshot"]["sha256"])
    require(type(corpus_manifest["selected_count"]) is int
            and corpus_manifest["selected_count"] >= 0, "invalid selected_count")
    require(inventory.get('contract') == contract, 'tokenizer inventory contract mismatch')
    inventory_hash = digest(canonical(inventory))
    output.mkdir(parents=True, exist_ok=False)
    seen, empty = set(), []
    count, chunk_hash, input_hash = 0, hashlib.sha256(), hashlib.sha256()
    with corpus.open("rb") as source, (output / "chunks.jsonl").open("xb") as target:
        for line in source:
            input_hash.update(line)
            document = json.loads(line)
            did = document["document_id"]
            require(type(did) is int and did not in seen, "invalid or duplicate document ID")
            seen.add(did)
            chunks = project_document(
                document, tokenizer, base_snapshot_sha256=snapshot,
                tokenizer_inventory_sha256=inventory_hash,
                passage_prefix=contract["passage_prefix"],
                max_sequence_tokens=contract["max_sequence_tokens"])
            if not chunks:
                empty.append(did)
            for chunk in chunks:
                data = canonical(chunk) + b"\n"
                target.write(data)
                chunk_hash.update(data)
                count += 1
    require(input_hash.hexdigest() == expected, "corpus changed during projection")
    require(len(seen) == corpus_manifest["selected_count"], "corpus document count mismatch")
    report = {"version": VERSION, "base_snapshot_sha256": snapshot,
              "corpus_sha256": expected, "document_count": len(seen), "chunk_count": count,
              "empty_token_document_ids": empty, "empty_token_document_count": len(empty),
              "chunks_sha256": chunk_hash.hexdigest(), "tokenizer_inventory": inventory,
              "tokenizer_inventory_sha256": inventory_hash,
              "max_chunk_tokens": MAX_TOKENS, "overlap_tokens": OVERLAP,
              "offset_unit": "normalized_document_unicode_characters"}
    with (output / "manifest.json").open("xb") as receipt:
        receipt.write(canonical(report) + b"\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--tokenizer-json", type=Path, required=True)
    parser.add_argument("--tokenizer-sha256", required=True)
    parser.add_argument("--tokenizers-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw_config = args.model_config.read_bytes()
    config = json.loads(raw_config)
    require(isinstance(config["repository"], str) and bool(config["repository"]),
            "model repository required")
    require(isinstance(config["revision"], str)
            and re.fullmatch(r"[0-9a-f]{40}", config["revision"]), "model revision must be frozen")
    contract = config["contract"]
    require(all(isinstance(contract[k], str) for k in ("query_prefix", "passage_prefix")),
            "explicit separate prefixes required")
    require(type(contract["max_sequence_tokens"]) is int and contract["max_sequence_tokens"] > 0,
            "invalid max_sequence_tokens")
    raw_tokenizer = args.tokenizer_json.read_bytes()
    require(digest(raw_tokenizer) == valid_hash(args.tokenizer_sha256), "tokenizer SHA256 mismatch")
    import tokenizers  # Optional, local JSON only; never from_pretrained.

    require(tokenizers.__version__ == args.tokenizers_version, "tokenizers version mismatch")
    tokenizer = tokenizers.Tokenizer.from_str(raw_tokenizer.decode("utf-8"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    inventory = {"repository": config["repository"], "revision": config["revision"],
                 "model_config_sha256": digest(raw_config), "contract": contract,
                 "tokenizer_json_sha256": args.tokenizer_sha256,
                 "library": "tokenizers", "library_version": tokenizers.__version__,
                 "add_special_tokens": False, "truncation": False, "padding": False,
                 "offset_unit": "unicode_characters"}
    report = export(args.corpus, json.loads(args.corpus_manifest.read_bytes()), args.output,
                    tokenizer, inventory, contract)
    print(json.dumps({k: report[k] for k in ("chunk_count", "empty_token_document_count",
                                           "chunks_sha256")}))


if __name__ == "__main__":
    main()
