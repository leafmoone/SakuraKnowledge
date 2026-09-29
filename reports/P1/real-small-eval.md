# P1 real small evaluation (frozen 20bf5b3 snapshot)

**Scope (binding):** 26 hand-selected cases against the **frozen**
`build/snapshot-full-20bf5b3/knowledge.sqlite`
(manifest `7e1592a61452d437ae46fab589317d2ac7b10c5a02c6c966097fa679a963a57c`).
`expected_behavior` states the **contract**, never a guessed source fact.
This is a small reconciliation of engine behaviour on real data — it is
**not** a full-database factual review and **not** human fact review of the
underlying sources. Machine-readable detail: `real-small-eval.json`.

Coverage: subject / character / person / moegirl CJK / 属性或CV (credit_person,
features_character) / source alias / candidate (identity_candidate,
wiki_match_candidate) / ambiguous / unknown / Danbooru unmapped /
孤独摇滚 question (template).

## Cases

| id | mode | query (label) | expected (contract) | actual | judgement |
|----|------|---------------|---------------------|--------|-----------|
| E01 | lookup | subject key 975 | found + citation | found | pass |
| E02 | lookup | alias 'ONE PIECE' | ambiguous (3 subjects share alias) | ambiguous | pass |
| E03 | lookup | bangumi character CJK alias | found + citation | found | pass |
| E04 | lookup | bangumi person CJK alias (CV) | found + citation | found | pass |
| E05 | lookup | moegirl character (CJK) | found, citation, desc only if source-backed | found, 0 desc | pass |
| E06 | lookup | danbooru page other_names alias | found | found | pass |
| E07 | ask | local tag 'solo', no target | local_identity_only | local_identity_only | pass |
| E08 | ask | local tag 'solo', target danbooru | entity_found_tag_unmapped, tag null | as expected | pass |
| E09 | ask_template | 'akanbe 的标签是什么' | no cross-namespace inference | entity_ambiguous (local tag vs danbooru page) | pass |
| E10 | related | subject 975, limit 20 | native credit_person (CV) with proof | 20 native edges | pass |
| E11 | related | subject 4 features_character | native features visible | 8 native | pass |
| E12 | related | character 12393 | identity_candidate NOT surfaced | only native | pass |
| E13 | related | local tag akanbe | wiki_match_candidate NOT surfaced | found, no candidate edges | pass |
| E14 | lookup | '10' unfiltered | ambiguous | ambiguous (52) | pass |
| E15 | lookup | 'definitely_missing_xyz_9271' | not_found | not_found | pass |
| E16 | ask_template | '孤独摇滚 的 Danbooru tag 是什么' | honest status, never invent tag | entity_ambiguous (episode + danbooru page) | pass |
| E17 | ask_template | '介绍一下 975' | no silent pick | entity_ambiguous (4 kinds) | pass |
| E18 | lookup | episode key 1128648 | found (episodes keyed, FTS off) | found | pass |
| E19 | search | 'ONE PIECE' | ranked candidates w/ citations | found | pass |
| E20 | search | 2-char alias term '!!' | honest candidates | found (see note) | pass |
| E21 | ask | page 10 danbooru.wiki | no verified tag => unmapped | entity_found_tag_unmapped | pass |
| E22 | related | character 12393 identity_candidate | candidates are not verified | 0 relations | pass |
| E23 | search | 'ONE PIECE' kind=episode | not_found (episodes excluded from FTS) | not_found | pass |
| E24 | ask | '975' direct name | ambiguous, direct-name compatibility | entity_ambiguous | pass |
| E25 | ask | local tag '!' target danbooru | knowledge gap, null tag_key | target_unmapped | pass |
| E26 | ask | '今天天气怎么样' | unknown + unsupported_query_template | as expected | pass |

## Notes on honesty of the data

- **E09/E16/E24/E25/E21** demonstrate the danbooru/local namespace
  separation on real shared spellings. Because the snapshot contains **zero**
  verified `entity_tag` edges (see B statistics below), `target_unmapped` /
  `unmapped` is the only truthful answer for every tag-target question in
  this cut — no mapping is invented to satisfy a query.
- **E20** deterministic term filter selected `!!`; disclosed in the JSON
  notes, not relabeled as CJK.
- **E05** moegirl value keeps its stored quoted form; 0 descriptions because
  no source-backed document is attached to that record slice.

## Verdict

26/26 pass against the contract on the frozen snapshot. This does **not**
constitute full-database fact review or source truth review.
