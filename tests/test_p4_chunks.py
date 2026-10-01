"""Deterministic offline tests: no model, database or downloaded tokenizer."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import p4_chunks as chunks


class Characters:
    """One token per non-whitespace character, in Python character coordinates."""

    def encode(self, text, *, add_special_tokens=False):
        offsets = [(i, i + 1) for i, char in enumerate(text) if not char.isspace()]
        ids = list(range(len(offsets)))
        if add_special_tokens:
            ids = [-1, *ids, -2]
        return SimpleNamespace(ids=ids, offsets=offsets)


def document(title="Title", original="body"):
    return {"document_id": 17, "entry_id": 3,
            "entry_key": {"kind": "tag", "namespace": "test", "value": "中文"},
            "source_id": "source", "evidence_id": "evidence", "title": title,
            "original": original, "search_text": "MUST NOT EMBED", "raw": "NOR THIS"}


def project(doc, tokenizer=None, **overrides):
    options = {"base_snapshot_sha256": "a" * 64,
               "tokenizer_inventory_sha256": "b" * 64,
               "passage_prefix": "passage: ", "max_sequence_tokens": 512}
    options.update(overrides)
    return chunks.project_document(doc, tokenizer or Characters(), **options)


def assert_slices(doc, result):
    text = chunks.document_text(doc)
    offsets = chunks.offsets_for(Characters(), text)
    for i, chunk in enumerate(result):
        assert chunk["chunk_index"] == i
        assert chunk["text"] == text[chunk["char_start"]:chunk["char_end"]]
        assert chunk["text_sha256"] == hashlib.sha256(chunk["text"].encode()).hexdigest()
        assert chunk["document_text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert chunk["token_count"] <= 384
        assert chunk["entry_key"] == doc["entry_key"]
        assert chunk["source_id"] == doc["source_id"]
        assert chunk["evidence_id"] == doc["evidence_id"]
        if i:
            assert chunk["canonical_token_start"] == result[i - 1]["canonical_token_end"] - 64
            assert chunk["canonical_token_start"] > result[i - 1]["canonical_token_start"]
    assert result[-1]["canonical_token_end"] == len(offsets)


def test_normalization_unicode_null_and_determinism():
    doc = document(None, "漢字 Latin😀e\u0301\r\nA\rB\x00\t  C")
    assert chunks.document_text(doc) == "\n\n漢字 Latin😀e\u0301\nA\nB\x00\t  C"
    result = project(doc)
    assert result == project(doc)
    assert result[0]["text"] == "漢字 Latin😀e\u0301\nA\nB\x00\t  C"
    assert "MUST" not in result[0]["text"]
    assert_slices(doc, result)
    assert chunks.document_text(document(None, None)) == "\n\n"
    assert project(document(None, None)) == []
    assert project(document("", "  \r\n\t")) == []


def test_oversized_paragraph_no_suffix_loss_or_cap():
    doc = document("", "a" * 10000)
    result = project(doc)
    assert len(result) > 25
    assert result[0]["canonical_token_end"] == 384
    assert_slices(doc, result)


def test_paragraph_boundary_greatest_and_exact_overlap():
    doc = document("T" * 100, "a" * 100 + "\n\n\n" + "b" * 100 + "\n\n" + "c" * 300)
    result = project(doc)
    assert result[0]["canonical_token_end"] == 300
    assert result[1]["canonical_token_start"] == 236
    assert "T" not in result[1]["text"]
    assert_slices(doc, result)


@pytest.mark.parametrize("title_size,expected", [(64, 384), (65, 65)])
def test_boundary_strict_progress(title_size, expected):
    doc = document("T" * title_size, "a" * 500)
    result = project(doc)
    assert result[0]["canonical_token_end"] == expected
    assert_slices(doc, result)


def test_final_window_ignores_paragraph_boundaries():
    doc = document("T" * 100, "a" * 100 + "\n\n" + "b" * 100)
    result = project(doc)
    assert len(result) == 1
    assert result[0]["canonical_token_end"] == 300


class ExpandedSlices(Characters):
    def __init__(self, complete, factor=2):
        self.complete = complete
        self.factor = factor

    def encode(self, text, *, add_special_tokens=False):
        encoded = super().encode(text, add_special_tokens=add_special_tokens)
        if text != self.complete and not add_special_tokens:
            encoded.offsets = [span for span in encoded.offsets for _ in range(self.factor)]
            encoded.ids = list(range(len(encoded.offsets)))
        return encoded


def test_retokenization_shrinks_one_position_and_preserves_overlap():
    doc = document("", "a" * 800)
    tokenizer = ExpandedSlices(chunks.document_text(doc))
    result = project(doc, tokenizer)
    assert result[0]["canonical_token_end"] == 192
    assert result[0]["token_count"] == 384
    assert_slices(doc, result)


def test_retokenization_cannot_progress_fails_explicitly():
    doc = document("", "a" * 500)
    with pytest.raises(chunks.ChunkError, match="cannot progress"):
        project(doc, ExpandedSlices(chunks.document_text(doc), factor=6))


@pytest.mark.parametrize("offsets", [[(-1, 1)], [(0, 0)], [(0, 999)], [(2, 3), (1, 2)],
                                    [(0, 3), (1, 2)], [(False, 1)], [(0.0, 1)]])
def test_reject_unsupported_offsets(offsets):
    class Broken:
        def encode(self, text, *, add_special_tokens=False):
            return SimpleNamespace(ids=[1] * len(offsets), offsets=offsets)

    with pytest.raises(chunks.ChunkError, match="offset"):
        project(document(), Broken())


def test_reject_offset_count_mismatch():
    class Broken:
        def encode(self, text, *, add_special_tokens=False):
            return SimpleNamespace(ids=[1], offsets=[])

    with pytest.raises(chunks.ChunkError, match="count mismatch"):
        project(document(), Broken())


def test_empty_retokenization_rejected():
    class EmptySlices(Characters):
        def encode(self, text, *, add_special_tokens=False):
            return super().encode(text if text.startswith("\n\n") else "",
                                  add_special_tokens=add_special_tokens)

    with pytest.raises(chunks.ChunkError, match="empty stream"):
        project(document("", "abc"), EmptySlices())


def test_id_exact_canonical_json_and_bindings():
    doc = document()
    chunk = project(doc)[0]
    fields = ("version", "base_snapshot_sha256", "tokenizer_inventory_sha256", "document_id",
              "chunk_index", "canonical_token_start", "canonical_token_end", "text_sha256")
    identity = {key: chunk[key] for key in fields}
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert chunk["chunk_id"] == hashlib.sha256(raw).hexdigest()
    assert chunks.canonical(doc["entry_key"]).decode().find("中文") >= 0
    assert project(doc, base_snapshot_sha256="c" * 64)[0]["chunk_id"] != chunk["chunk_id"]
    assert project(doc, tokenizer_inventory_sha256="d" * 64)[0]["chunk_id"] != chunk["chunk_id"]


def test_prefix_special_token_budget_and_query_separation():
    doc = document("", "a" * 384)
    assert project(doc, passage_prefix="", max_sequence_tokens=386)
    with pytest.raises(chunks.ChunkError, match="inference token budget"):
        project(doc, passage_prefix="p", max_sequence_tokens=386)
    assert chunks.inference_token_count(Characters(), "abc", prefix="q:",
                                        max_sequence_tokens=7) == 7
    with pytest.raises(chunks.ChunkError, match="inference token budget"):
        chunks.inference_token_count(Characters(), "abc", prefix="query:", max_sequence_tokens=7)


@pytest.mark.parametrize("budget", [True, 0, -1, 384.0, "512"])
def test_strict_budget_even_on_empty_document(budget):
    with pytest.raises(chunks.ChunkError, match="max_sequence_tokens"):
        project(document(None, None), max_sequence_tokens=budget)


@pytest.mark.parametrize("updates", [{"title": 0}, {"original": []}, {"document_id": True},
                                     {"entry_id": "3"}, {"source_id": None},
                                     {"evidence_id": ""}, {"entry_key": "tag"}])
def test_invalid_input(updates):
    with pytest.raises(chunks.ChunkError):
        project({**document(), **updates})


def fixture_export(tmp_path, docs=None):
    docs = docs if docs is not None else [document(), {**document(None, None), "document_id": 18}]
    corpus = tmp_path / "pilot.jsonl"
    corpus.write_bytes(b"".join(chunks.canonical(doc) + b"\n" for doc in docs))
    manifest = {"corpus_sha256": chunks.file_digest(corpus), "selected_count": len(docs),
                "base_snapshot": {"sha256": "a" * 64}}
    output = tmp_path / "build" / "p4" / "chunks-test"
    inventory = {"tokenizer_json_sha256": "b" * 64, "library": "fake", "library_version": "1"}
    contract = {"passage_prefix": "p:", "query_prefix": "q:", "max_sequence_tokens": 512}
    inventory['contract'] = dict(contract)
    return corpus, manifest, output, Characters(), inventory, contract


def test_export_exclusive_deterministic_empty_reporting(tmp_path):
    args = fixture_export(tmp_path)
    report = chunks.export(*args, root=tmp_path)
    assert report["empty_token_document_ids"] == [18]
    assert report["empty_token_document_count"] == 1
    assert report["document_count"] == 2
    assert report["chunk_count"] == 1
    assert report["chunks_sha256"] == chunks.file_digest(args[2] / "chunks.jsonl")
    original = (args[2] / "chunks.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        chunks.export(*args, root=tmp_path)
    assert (args[2] / "chunks.jsonl").read_bytes() == original
    second = list(args)
    second[2] = args[2].with_name("second")
    assert chunks.export(*second, root=tmp_path) == report
    assert (second[2] / "chunks.jsonl").read_bytes() == original


def test_export_rejects_contract_mismatch(tmp_path):
    args = list(fixture_export(tmp_path))
    args[5] = {**args[5], 'passage_prefix': 'different:'}
    with pytest.raises(chunks.ChunkError, match='inventory contract mismatch'):
        chunks.export(*args, root=tmp_path)
    assert not args[2].exists()


def test_export_rejects_redirected_ancestor(tmp_path, monkeypatch):
    args = fixture_export(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink',
                        lambda path: path == tmp_path / 'build' or original(path))
    with pytest.raises(chunks.ChunkError, match='symlink forbidden'):
        chunks.export(*args, root=tmp_path)
    assert not args[2].exists()


def test_export_hash_and_path_guards(tmp_path):
    args = list(fixture_export(tmp_path))
    args[1]["corpus_sha256"] = "f" * 64
    with pytest.raises(chunks.ChunkError, match="SHA256 mismatch"):
        chunks.export(*args, root=tmp_path)
    assert not args[2].exists()
    args[2] = tmp_path / "outside"
    with pytest.raises(chunks.ChunkError, match="under build/p4"):
        chunks.export(*args, root=tmp_path)


def test_export_duplicate_and_count_failure_leave_no_success_receipt(tmp_path):
    args = fixture_export(tmp_path, [document(), document()])
    with pytest.raises(chunks.ChunkError, match="duplicate"):
        chunks.export(*args, root=tmp_path)
    assert not (args[2] / "manifest.json").exists()
    other = tmp_path / "other"
    other.mkdir()
    args = fixture_export(other)
    args[1]["selected_count"] += 1
    with pytest.raises(chunks.ChunkError, match="count mismatch"):
        chunks.export(*args, root=other)
    assert not (args[2] / "manifest.json").exists()
