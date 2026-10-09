# Source adapter boundaries

Source adapters consume explicitly declared read-only local input bytes and emit the normalized contract. This document defines product behavior, not a record of development tasks or source refresh claims.

| Source family | Supported input role | Trust boundary |
|---|---|---|
| Bangumi Archive | Subjects, characters, persons, episodes and native links | Preserve native endpoint IDs; unresolved archive endpoints remain unresolved. |
| Moegirl | Character records, aliases, structured attributes and source text | Categories/CV names remain raw observations, not inferred character/person/tag joins. |
| Danbooru Wiki | Wiki pages and page links | Wiki titles/text do not create native `danbooru.tag` identities. |
| Local tag-wiki | Source-local aggregate tags and independently proven Wiki-derived text | Local aggregate namespaces remain distinct; generated text is not native identity. |
| Native Danbooru metadata | Explicit native tag and directed alias records | Preserve IDs, category, lifecycle and actual alias endpoints; retired/deleted/conflicting records do not become active verified mappings. |
| Additional adapters | Explicit `module:class` implementing `SourceAdapter` | Declare input inventory and source owners; reuse the same typed record/evidence contract. |

## Identity and text

`(kind, namespace, value)` is the identity boundary. Only source-backed evidence establishes an identity. Titles, spellings, confidence, candidates or cross-namespace similarity cannot establish a verified cross-source relationship. A native Wiki association is not an entity-to-tag mapping.

Moegirl `char2subject` categories, raw attributes, gender and CV names remain payload. Do not infer `character_of`, Bangumi person joins or tag membership from raw names. Mapping versions and dates remain separate from later text revisions.

Generated text can be indexed only under an existing source-backed identity and with explicit evidence. `no_reference` and `unverified_draft` payloads do not become trustworthy merely because a producer labels them AI/verified. Proven tag-wiki text uses the independent [text proof contract](tag-wiki-provenance.md).

## Inventory and ownership

Adapters declare every regular input dependency under the input root. Transferable inventories and configs use relative paths, not local drive/user directories. Only declared files may be read by official adapters. Each normalized record belongs to a declared source owner; a package installation ID is not a source ID.

Preserve source/evidence IDs, native IDs, raw payloads, locators, source cut/revision and unresolved reasons. Build source accounts and snapshot constraints must match before publication. No candidate is promoted to hide unresolved input. Source-input integrity checks are part of producing a valid product; do not repeat full asset scans or hashes as a redundant development ritual.

## Scope limits

Frozen local data does not establish a live upstream refresh or complete upstream truth. A successful adapter build or a small synthetic fixture does not establish retrieval quality, identity truth, legal redistribution permission or full human fact review. Missing mappings return `unknown`, `ambiguous` or `target_unmapped`; they are never guessed.

See [normalized data](data-contract.md), [source-pack contract](source-pack-contract.md) and [adding a source](adding-a-source.md). Source raw bodies, working inventories, development reports, tests and logs are local-only, not tracked repository content.
