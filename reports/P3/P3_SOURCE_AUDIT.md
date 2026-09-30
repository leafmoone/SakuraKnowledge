# P3 source audit — scoped metadata, not full refresh

P3_BASE/main:894dc6a73bfd42f18cc7648e8ab7481aae211ab1.
Implementation/artifact source:b393581c54d5ac0db76802897220f4818c1eb3c0.

## Local first

`preflight-source-audit.json` audits10 known files, actual SQLite schemas and frozen
input SHA; `live-handoff-audit.json` adds actual root/tag_wiki.sqlite and handoff
locators. No native official ID/category/lifecycle/alias evidence found locally.
Table names (`tag_aliases`, etc.) alone were not treated as official identities.
Five original normalized inputs remain unchanged. There was no recursive disk scan,
input write, source reinterpretation or modification outside SakuraKnowledge.

## Official bounded missing-evidence acquisition

Frozen30targets in target_manifest.json before requests;12 additional exactspellings
frozen in alias_target_manifest.json solely from the returned original Wiki names.
Budget42targets/52requests including4 earlier documentation requests; retry0,
concurrency1/1.05s spacing. Nativecollector185405B +aliascollector902B =186307B;
4MiB conservative reserve separately accounts for earlier documentation tool bytes.
All requests succeeded without401/403/429. Those would stop the source, not proxy/
credential retries. Source raw retained once byhash under ignored reports/P3/raw/;
raw URLs/query scopes/UTC fetch times/status/bytes/digest are retained in receipts.
No model/image/post download, service, Pool import, credentials or runtime network.

Official native source:danbooru-native-scoped-4ccce02e466f.30native tag numeric IDs,
original spellings/categories/post_count/deprecation/timestamps retained. Native IDs
never equal Wiki IDs by inference.42 per-name outgoing scopes fetched fewer than
limit1000 under exact predicates; no global alias completeness claim. Four alias
records:oneactive/threeinactive. Only active official edge redirects; retired/deleted
remain original evidence, not normalized verified mapping. Graph cycles/missing
targets/lifecycle conflicts/scope deficits are tested and fail canonical proof.

## Wiki/source cuts

Official embedded tag→Wiki association is checked against original frozen page
metadata, exactbody/updated_at/other_names.28compatible associations yield28native
wiki_tag links and same-source name assessments. ijichi_nijika (Wiki151534) and
konpaku_youmu (Wiki7644) changed after the original cut; quarantine2associations and
no oldWiki identity upgrade. Native existence remains valid independently. Bodies
are not regenerated/duplicated; resolver description reads bounded original oldWiki
documents with original source/evidence IDs. Source dates stay separate. This is a
finite nontransactional API window, not a universal current view or full refresh.
Upstream revision/data license unknown values remain unknown; raw local-only.

## Cross-source identity gap

Pilot selection scans all original normalized source records and retains every
identity/name match, including other types/sources and colliding names. The scan
selected201Bangumi records (114characters/13subjects/5persons/69episodes),91Moegirl
records (88characters/3categories),90Wiki pages and82localaggregate records.
Native compiled input adds410records (30identities/28links/352assessments).
Pilot874records all accepted/accounted;451entries/222FTSdocuments. No rejection.

100candidate mappings and100replayable decisions retained in v2-candidates.jsonl/
v2-decisions.jsonl; statuscandidate/reviewer_kindexecution_agent. No actual human
review, no generated confidence upgrade. Direct URLs in fetched Wiki did not supply
Bangumi/Moegirl cross-source IDs. **Verifiedentity_tag=0/human_verified=0.** This is
an explicit evidence gap: supply actual source ID/link evidence or genuine scoped
human decisions, replay and rebuild a new pilot before the full-build gate.

## Failed/superseded work

First compilation accessed raw_page_metadata at the wrong nesting level and
quarantined all30Wiki despite commandexit0. v1input/source_manifest/candidates/
decisions are preserved, **INVALID_COVERAGE**, not evidence of an upstream change.
v2correctly reads raw.raw_page_metadata and produces the only published realpilot.
No source reacquisition or fullbuild retry occurred. All historical P1/P2 inputs,
reports,151table and21.5GBsnapshot are immutable.
