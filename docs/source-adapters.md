# Source adapters and actual audit

## Bangumi Archive
Latest metadata was actually requested successfully; see metadata/bangumi-latest.json, including check timestamp and upstream digest. Recorded asset size 441318128 bytes; dump not downloaded in this bounded implementation run. No local *.jsonlines found in workspace. Latest metadata is not an entity-schema audit. Nine-file streaming adapter remains NOT_RUN/unimplemented: subject, character, person, episode, subject-persons, subject-relations, subject-characters, person-characters, person-relations (.jsonlines). Unknown person_type must never be guessed. Raw infobox/tags, dates raw/parsed/anomaly, future values, roles/order/spoiler and FK checks require real schema inspection first. Episode indexing defaults false.

## Zzzzzzyt/moegirl-dataset
Public recursive tree fetched; revision 1ff222f8af5e399e230b9f88eb50995869ed22bf. Initial guessed source paths returned 404; corrected paths discovered in that recorded tree fetched at fixed revision. Evidence in reports/P1/public-audit. dump_converter lines 13–15 read character.jsonlines: derived bgm_info IDs are character-space, not subject. Its regex infobox/date/gender inference is upstream behavior, not adopted as a reliable parser. moegirl_mapper contains special_map overrides and null entries; none establish verified identity.

Required char_index/extra_processed/char2attr/attr2char/char2subject/subject_index/char2cv/cv2char/char2gender data were not locally found or imported. attrs/subjects four top categories are not four entity tables. char2subject categories may be maintenance/region, not universally character_of. CV names do not auto-join Bangumi person. Gender stays raw; attributes are not translated into tags. No claims of original Wikitext without actual body evidence. Images are references only. Mapping adapter is only a pure candidate auditor; no actual mapping cardinality statistics or new-vs-old dump reconciliation have run.

## Danbooru wiki / tag_wiki
No local real files discovered. Namespace and schemas unknown. Both integrations BLOCKED. Do not infer namespace danbooru or claim real compatibility from the normalized fixture contract. Exact seven image groups remain in model.GROUPS. No six-library large SQLite/TAR files opened.

Refresh events remain separate: code HEAD, official Archive dump, Moegirl bodies and mappings. Unknown licensing/cutoff facts stay null. Downloaded upstream source is retained as audit data, not executed.
