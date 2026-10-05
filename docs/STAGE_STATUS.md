# Current delivery status

## Frozen Wiki-backed tag text candidate

Baseline `b1799c84b341e8f42ee92a44005fa83cecf34d8a`, ordinary dev delivery.
New Core/tag candidate: `build/modular-components-next/`; old components preserved.
Actual combined root `build/tag-provenance-runtime-next/` uses readonly same-volume
hardlinks to unchanged Danbooru/Bangumi/Moegirl/model assets, relative config, no
symlink/development-path dependency. Only new tag DB/FTS/membership and Core change.
No ANN/embedding/model rebuild, identity/resolve promotion or fusion weight changes.

### Full source facts and proof

674889 raw records audited (not sampled): full cache no_reference601512,
source_backed69825, ai_annotated3342; annotations draft173/verified37.
66979 records prove a field, producing **66979 new generated_from_evidence
 documents/FTS rows**, duplicate projections0. All proved methods whitespace_prefix.
Failures: no_tag_evidence578105/deleted4946/empty20093/short1452/
not_derivable3314. No missing/multiple/parse cases observed; those remain fixtures.
Original source statuses/documents are not upgraded. Six identity/source tables
exactly compare both ways; all old documents retained byte-for-value unchanged.
Candidate links remain candidate and local tags remain local.tag_aggregate.

Proof requires actual candidate → one distinct non-deleted nonempty frozen Wiki
page → same raw body in existing trusted Danbooru document → independently
provable text field, minimum24chars4word runs, not status/AI/confidence. Hashes and
locators persist in compact text_provenance. Historical producer revision unknown;
proofs are reconstructed frozen bytes. Detailed contract/CLI:
`docs/tag-wiki-provenance.md`. Audit receipts `build/tag-provenance-audit-v1.json`
and proofs JSONL outside runtime pack. Independently checked all66979 actual
body/text hashes, prefix/candidate/tag binding in3.58246s, without calling prover.

### Validation

Source gold50 frozen before any retrieval:25 successful projections +5 each
actual no-evidence/deleted/empty/short/nonderivable record. Negative unit is raw
record locator, not whole tag (another record may prove text). All50 stored
projection/hash checks PASS. All25 positive FTS queries find intended local tag
using actual tag-only selection with model directory removed, encoding0.
Actual tag-only smoke exit0, lexical_hits100,898.1038ms,356294bytes. Model/ANN
not required; ordinary FTS never supplies exact/alias pins.

Final full Python suite **1251 PASS/18 Win1314 symlink skips/55 subtests**,65.85s,
explicit final binary/DLL PATH/D temporary directories. New proof tests24 plus
additional hash/method tamper tests; Rust library52PASS/releasebuild passed.
Lookup/ask blue_hair and lookup brown_eyes retain identity result fields; resolve
blue_hair full JSON identical. Structural merge/resolve algorithms unchanged.
New snapshot integrity/FK and exact identity/old-doc comparisons PASS. Actual
membership66979 bound to new DB hash, no old0-row membership reused.

`build/tag-provenance-all120-final-retry1.json`: fresh120 engineering PASS,
one shared model session and encoding each, <=5s complete response including
serialization, <=1MiB UTF-8 including newline, independent source/document/
evidence/typed closure and tag provenance text hashes. EOFexit0 readerjoined,
no active kill. First startup attempt failed before any queries because the test
root model directory was nested incorrectly; stderr retained, not PASS. Fixed
relative layout, no source/model bytes changed. Earlier build verify URI/C-temp
failures retained; completed new DB reused and D-temp exact comparisons passed.

| Group | b179 R10/MRR10/nDCG10 | New tag text |
|---|---|---|
| lexical | 1/.97778/.98333 | unchanged |
| semantic | .975/.89375/.91463 | unchanged |
| crosslingual | .53333/.25889/.32641 | .53333/.25810/.32564 |
| ambiguous-positive | .6/.37/.38776 | unchanged |

No group gains/loses R10. Changed metric cases P4-077/P4-083/P4-101/P4-102
reflect added tag lexical competition, not new semantic tuning. Crosslingual
ranking slightly decreases; no overall quality PASS claim. Saved per-case receipt
`build/tag-provenance-quality-comparison.json`; prior monolithic quality gaps remain.

Startup13596.6008ms vs b17911752.561; E2Ep50/p95/max829.1093/1960.0565/
4275.4629ms vs667.07855/2296.0959/2555.9523. Added lexical/provenance work raises
worst-case latency; all remain below5s. Bytesp95/max591273/863741 (before383583/
635848). Validator time separately recorded, not retrieval performance. RSS not
measured; finite gold not generalization evidence.

### Sizes and limits

Old tag pack1718178889bytes → new1952638242bytes; DB1951559680,
membership1077248,manifest1314. New Core64885516bytes; other components unchanged.
No mapping/vectors/ANN in tag pack. Old mother/FP32/valid packs preserved.
Public rights NOT_CLEARED; no large upload/Pi/Pool/live refresh/full human review.
This task adds narrow source-backed text support, not native identities, verified
mappings or safety labels. No next-stage generic pipeline/source expansion started.
