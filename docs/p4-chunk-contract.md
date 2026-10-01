# Semantic chunk projection: paragraph-model-tokenizer-v1

Pre-embedding specification; no runtime or measured quality claim.

1. Input is exactly document.title and document.original from the frozen trusted
   projection. Null becomes empty. Normalize CRLF and lone CR to LF; no Unicode,
   case, punctuation or whitespace normalization otherwise. Canonical document
   text is title + '\n\n' + original (including separator for empty fields).
   text_sha256 uses UTF-8. Raw evidence and search_text are never embedding input.
2. Tokenize that complete string with the pack's exact frozen fast tokenizer,
   add_special_tokens=false, truncation=false, padding=false, retaining character
   offsets. Empty token streams emit no chunks and are reported, not fabricated.
3. Paragraph boundaries are ends of maximal runs of at least two LF characters.
   Convert each boundary to the first token whose start offset is >= boundary.
   Exclude boundary zero and duplicate positions. Title participates as the first
   paragraph and is NOT repeated on later chunks.
4. From start token s choose hard_end=min(s+384,total). If not the final window,
   choose the greatest paragraph boundary b with s+64 < b <= hard_end; if none,
   use hard_end. Thus oversized paragraphs split at the token window limit.
   Final windows end at total. After any nonfinal chunk set s=end-64: exactly 64
   canonical token positions overlap, also across paragraph boundaries. The strict
   boundary condition guarantees progress. Never drop suffix tokens.
5. Text is the original character slice from the first included token's offset
   start to the last included token's offset end. Validate offsets monotonic,
   nonnegative, within input; reject degenerate spans. Retokenizing sliced text
   may differ at word boundaries: if it exceeds 384 tokens, shorten the candidate
   end one canonical token at a time until the slice fits, then compute the next
   start with the same 64-position overlap rule. If this cannot progress, FAIL
   explicitly instead of truncating. Record canonical token start/end and actual
   retokenized token count. Chunk text contains no injected evidence/identity data.
6. Apply the separately frozen passage prefix at inference, then special tokens.
   Retokenize final inference text without truncation; reject length exceeding
   the model's pinned max sequence length. Query uses its separate prefix and an
   explicit length error, not silent truncation. Maximum chunk count is not capped
   to favor short documents. Model-tokenizer identity is part of projection identity.
7. chunk_index is zero-based in document order. chunk_id is SHA256 of canonical
   UTF-8 JSON (sorted keys, compact separators, no ASCII escaping) containing
   version, base_snapshot_sha256, tokenizer_inventory_sha256, document_id,
   chunk_index, canonical token start/end and text_sha256. All indices are JSON
   integers; hashes lowercase hex. Carry entry_id, typed entry_key, document_id,
   source_id/evidence_id, kind/namespace and document text hash separately.
8. Record the tokenizer library/version and tokenization configuration, including
   all added tokens/normalizers in its SHA-bound tokenizer JSON. Reject unsupported
   offset behavior. Freeze actual model tokenizers before materializing chunks.
   Unit tests must include mixed CJK/Latin, emoji, combining marks, empty title,
   CRLF, oversized paragraphs, short paragraphs and deterministic repeated runs.

Overlap counts canonical token positions, not bytes or characters. All slice
hashes and source offsets allow exact reconstruction from the immutable document.
Sidecar integrity independently joins chunk -> document -> entry and source.
