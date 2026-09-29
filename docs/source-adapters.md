# Source Adapters and Local Audit

This document records the local source boundary used for the frozen P1 build. It does not claim a live refresh, complete upstream truth, or full human fact review.

## Status matrix

| Source | Local status | Evidence boundary |
|---|---|---|
| Bangumi Archive | `LOCAL_AUDITED_AND_BUILT` | Nine archive members were audited, normalized, and included in the fixed snapshot; unresolved archive-internal endpoints remain reported. |
| Zzzzzzyt/moegirl-dataset | `LOCAL_AUDITED_AND_BUILT` | Character records and mappings were audited and normalized from the frozen local cut; raw structured fields remain source text and are not translated into tags. |
| Danbooru Wiki | `LOCAL_AUDITED_AND_BUILT` | Wiki pages and resolved/unresolved wiki links were imported from the frozen local dataset; this does not create native `danbooru.tag` identities. |
| tag-wiki | `LOCAL_AUDITED_AND_BUILT` | The frozen local tag database backup was normalized; candidate wiki matches remain candidates and duplicate source rows are accounted for. |

## Boundaries and gaps

Moegirl `char2subject` categories are preserved as raw categories; they do not automatically become a `character_of` relation. CV names remain raw names and do not automatically join to Bangumi person identities. Attributes and gender remain raw fields and are not translated into Danbooru tags. Candidate mappings (`identity_candidate`, `wiki_match_candidate`) are never promoted to verified links.

The audited local cut contains **zero native `danbooru.tag` identities** and **zero verified `entity_tag` links**. A local aggregate tag, page title, exact spelling, confidence value, or candidate link cannot establish a Danbooru tag identity. The API reports `target_unmapped` or `entity_ambiguous` instead.

The Pi runtime was not exercised (`PI_SKILL_INTEGRATION=NOT_RUN`). Full human source-fact review was not performed (`HUMAN_FACT_REVIEW=NOT_RUN`). The fixed inputs and the generated snapshot are evidence for this recorded local build only.
