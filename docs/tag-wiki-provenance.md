# Frozen tag-wiki text proof contract

`tag-wiki-text-proof-v1` supports text only. It never verifies tag/page identity,
creates native danbooru.tag, promotes candidate links or changes resolve rules.
Inputs are an explicitly supplied frozen tag-wiki SQLite file and a
source-backed Danbooru pack. Current upstream scripts are not authenticated
historical revisions; all proofs explicitly say reconstructed_from_frozen_bytes.

## Acceptance

All candidate rows for a tag are counted before filtering. Exactly one distinct
Wiki ID must exist. Duplicate candidate rows for the same ID are not ambiguity.
The frozen Wiki page must exist, be non-deleted and have nonempty body. The
source-backed Danbooru runtime document must have exactly the same raw body bytes
and trusted identity proof. Confidence, producer source_backed/verified/AI status,
model labels, URL titles and spelling alone are insufficient.

For cache JSON only short_summary/detailed_description are individually tested;
annotations use semantic_summary. Select the longest individually provable field,
not concatenated unproved JSON/safety/category/relationships. Collapse Python
Unicode `re` whitespace runs to ASCII space and strip endpoints; do not normalize
case, punctuation, NFKC, spelling or fuzzy distance. Text must be a prefix or
contiguous excerpt of the independently loaded normalized body. Conservative
minimum 24 characters/four Unicode word runs was selected before retrieval, not
learned from runtime outputs. This is an information floor, not a claim that every
excerpt is uniquely identifying.

SHA256 is over UTF-8 raw Wiki body and final trusted text separately. Envelope
contains proof version/method/field, raw table/cache-key locator/status, local
aggregate typed key, original tag source/evidence, Wiki typed key/source/evidence/
document ID, candidate IDs and hashes. No full body or producer JSON is embedded.
Same tag and text hash deduplicate; distinct independently supported projections
remain distinct. Current full audit found no duplicate accepted projection.

## Projection behavior

Reject rows without tag evidence, deleted/empty Wiki text, ambiguous Wiki IDs,
insufficient text or text not independently derivable from the frozen body.
The raw no_reference label does not mean absence of all knowledge on the Internet.
AI/status neither automatically grants nor denies a provable independent field.

New documents are generated_from_evidence under pre-existing trusted local tag
entries, original source/evidence closure; no new identity evidence. Old documents
retain their exact draft/no_reference statuses and payloads. Entries, evidence,
aliases, links, resolutions, sources compare exactly against the old pack. FTS
uses existing search_text NFKC/CJK tokenizer and only trusted text status. New
membership binds actual FTS row/document/entry tuples and new snapshot hash.

`python -m tools.tag_wiki_provenance audit --tag-wiki FROZEN --danbooru-pack DAN --output NEW_AUDIT`
`python -m tools.tag_wiki_provenance build --base-pack OLD_TAG --tag-wiki FROZEN --danbooru-pack DAN --output NEW_TAG`
Create-new outputs, input connections readonly; manifest published after checks.
Adapter uses the same Auditor with explicit iter_tag_wiki(danbooru_snapshot=...);
full ingest opt-in is `--tag-text-danbooru-snapshot`. Default legacy import remains
unchanged. No online/LLM/embedding calls. Portable payload retains text_provenance
and search_text_truncated. Working audit outputs remain outside the runtime pack and source Git.

Tag-only retrieval needs neither model nor Danbooru installed: export established
proofs, compact lineage remains in documents. Export/independent validation uses
frozen Wiki and audited Danbooru. Public lexical hits carry document/source/
evidence rank; ordinary FTS is not an exact/alias pin. The fixed global fusion
algorithm/weights are unchanged; additional lexical evidence may alter ranking.
