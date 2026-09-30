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

## P3 scoped official metadata (separate from immutable P1 cut)

The original zero-native observation above remains true for that frozen P1 cut.
P3 acquired only 30 preselected native tags with embedded Wiki associations and
42 scoped outgoing-alias name queries, using 52 total requests including earlier
documentation. Receipts: `reports/P3/native-acquisition.json` and
`alias-acquisition.json`. This is a bounded nontransactional official API window,
not a full upstream refresh or historical rewrite. Source raw/data license remains
unknown; raw stays local-only with hashes and locators, not an unrestricted dataset.

`tools/p3_compile_inputs.py` validates native IDs/category/lifecycle and directed
active alias graphs, preserving retired/deleted records without redirecting them.
28 official Wiki associations match the old page's exact body, updated_at and
other_names. Two changed Wiki versions are quarantined, not relabeled as compatible.
Existing source dates remain separate. Native/Wiki/local aggregate/entities remain
distinct namespaces; generated text creates none of these identities.

Real P3 pilot: 30 native identities, 28 native `wiki_tag` links, 352 indexed name
assessments. Conflict-preserving selection includes every old source record with
matching selected typed values or source-backed names (not only favorable matches).
100 cross-source candidates have replayable execution-agent decisions; **zero
verified entity_tag** and **zero human_verified**. Same-name matches do not become
verified. Missing real entity_tag positive evidence blocks the full candidate;
`reports/P3/full-candidate-gate.json` records zero full-build attempts. This is P3
NOT_READY / BLOCKED, not P3 acceptance or source-fact approval.

### cf807 fixed-review repair (no new acquisition)

Review found known endpoint substitution, incomplete intermediate alias scopes and
Wiki-description association chains, missing real negative gold cases, and a latent
urllib redirect accounting bypass. Source7393d60 repairs only these authorized items.
Every directed alias step retains its actual endpoints/status and raw scope, including
intermediate nodes. Actual native wiki_tag links now bind the old normalized source
hash/line/evidence and official raw ID/reference with exact body/date/name digests;
resolver returns the edge and document IDs. Version conflicts retain unequal-date
quarantine evidence and explicitly no descriptions. Unknown terminal reasons survive.

Collector now forbids redirects and stops that source. Mock redirect/401/403/429,
request200-budget and >=1.05s-spacing tests issue no network GETs. Historical52request
and byte receipts remain unchanged; no evidence says redirects actually occurred or
historical budget was exceeded. New55gold is frozen from retained raw/input bytes,
not resolver outputs, and keeps actual candidate-only/ambiguous/missing-terminal and
changedWiki empty-description expectations distinct from verified positives. Both
new realpilot and full-build gate keep verified_entity_tag=0 and fullbuildattempts=0.
