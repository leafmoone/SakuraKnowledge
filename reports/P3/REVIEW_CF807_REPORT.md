# cf807 P3 targeted review repair — PENDING_REVIEW / BLOCKED / NOT_READY

Review baseline:`cf807c1a5179ce4b451b9a85870b6684d2dccaf3` (**CHANGES_REQUIRED**).
Root authorized exactly four directional repairs, no real GET/human review/full
candidate/main/P4/Python production resolver. Source/artifact commit:
`7393d601a6d95432f41da243395ed5d3e0a2fda1`.
This report supersedes the current code claims of P3_REPORT.md, but preserves all
old reports/old50gold/failed49 output/raw unchanged. It does not claim acceptance.

## 1. Known endpoint is not a multilingual spelling query (HIGH)

Explicit native TagKey and verified entity_tag.dst use only native_exact/official
alias canonicalization, then filter actual terminal category. Direct spelling also
selects native/official priority before category, so an exclusion does not enable
Wiki substitution. With source_backed A(cat4), B(cat3), Wiki spellingA→B and verified
hero→A, category3 cannot resolveB. Unfiltered endpointA/hero resolvesA withoutfalse
A/Bambiguity. No name/score/confidence establishes a verified mapping. The synthetic
verifiedlink is an independent contract counterexample, **not a real positive**.

Normal builder/atomic publish7record fixture covers A/hero each None/3/4category;
complete JSON asserted from manually specified independent expected responses and
oracle. Independent oracle filters known endpoints too, not samebug mirroring.

## 2. Proof completeness, description association and unresolved reasons

A→B→C compilation retains directed officialstepIDs/rawrefs/endpoints/status and all
A/B/C outgoing uniqueness scopes. The independent compiler fixture reconstructs
rawAPI/frozenoldWiki without runtime projections; intermediateBscope is asserted.
Compatible Wiki link/projection bind actual officialtag+WikiIDs/keypair and bothcuts:
oldnormalized sourceID/hash/path/line/evidenceID, liveofficial rawSHA/locator/eid,
matching dates and body/name hashes. Runtime traverses the existing indexed actual
wiki_tag edge (no scan/globalname re-resolution), validates cutfields and returns
associationrefs+actualedgeID+descriptiondocIDs. Absent compatibility means no docs.
Native and officialalias description chain independently asserted using original
fixturebody and actualassociation. Changed realWiki versions retain quarantineproof
with old/new unequal timestamps and no docs. No source descriptions regenerated.
Canonical_unknown returns structured name/matched_by/missing_native_terminal etc.,
not only genericwarning. Requiredproof remains outside disposable relations.

## 3. Frozen actual source gold, not copied from resolver

New `review-cf807-real-gold.json` declared55cases using retained officialraw and
normalizedinput evidence before runtime acceptance. Original50file/hash unchanged.
Adds actualcandidate queue Bangumisubject265→neon_genesis_evangelion (stillunmapped),
初音未来 --kindcharacter (4Moegirlidentities entity_ambiguous), haruhi_suzumiya and
soryu_asuka_langley (inactivealias/missingnative terminals canonical_unknown), plus
explicit ijichi_nijika query. Both ijichi/konpaku cases assert descriptions=[] and
real unequal-cut quarantineproof. Compatible description cases independently bind
actualrawIDs/keys/dates/bodyhash/actualedge/documentroles, not just rolepresence.
The checker now honors descriptions_empty/unresolved_reasons/evidence_assertions.
Verified realentity_tag positives remain **0**, not mislabeled WikiChinese success.

New realpilot:fdbb5d85c954e5a3b04227d07f82567e3af3cb8cdaca6b4768247909e1bd457c,
`build/p3-review-cf807-final-pilot/knowledge.sqlite`,451entries/222FTS/874input=accepted,
30native/28Wiki/2quarantines/352assessments,100candidate decisions/0verified/0human.
Originalpilot is unchanged. Offlinefirstrepairpilot remained published separately;
newfinalpaths add explicitquarantineproof, not overlay/rebuild/retry of fullcandidate.

## 4. Bound each HTTP hop; no new official requests

Collector uses a NoRedirect HTTPRedirectHandler: any3xx raises/stops that source,
not implicit urllibfollow. One counted attemptedGET is oneHTTP hop. Mock-only tests
cover301/302/303/307/308 (no secondrequest),302/401/403/429 source stop andRetry-After,
request200budget preventsHTTP, >=1.05s spacing for eachattempt. No genuine GETs.
Historical52request/42target/186307B+4MiBreserve accounting stays untouched; no claim
that a redirect actually occurred or previous requests exceeded budget.

## Validation and artifacts

- Before expectedendpoint/proofs:7FAIL/2PASS (retained review-cf807-before.json).
- Collector initialfixture expected wrong exit3/status:10FAIL/1PASS retained; fixed
  fixture uses existing exit2/sourceblocked beforecode,5redirectFAIL/6PASS retained.
- Afterfixture v1:46PASS/1FAIL due mockResponse sharedclassheaders contamination;
  corrected instanceheaders. Newfinalreceipt47PASS (20new+27existing), no network.
- Source7393fullpytest **234PASS**, Rust **6PASS**; sevenchecks each exit0.
- Debug and newrelease real55fullJSON+independentoracle+raw/inputexpected **55PASS**:
 39/39positive,16/16nonresolved,0wrongtag; retries0. Sourceexternal8oldpairs+55new
 expected/fullJSON and10ABC pairs PASS. Newbinary unchangedold151135fullJSON+
 16expectederrors PASS, retries0.13predeclaredworkloads×30×2=780measurements+26fixed
 warmups PASS,0timeout/failure/retry, separately measured reusedconnection/CLI p95.
 Performance is PILOT_ONLY, not fullcandidatecapacity/RSS. All exactrecords/streams
 are in review-cf807-delivery.json and separatelyhashed referencedraw receipts.
- New `git archive` source7393releasebinary/examples/wheel/newvenv, not relabeled
 b393artifacts. External-I-Xutf8/noPYTHONPATH/site-packages/Pythonnoresolver verified
 in artifactexternal receipt.12wheelmodules match exactarchiveexports; LFvsCRLF
 committedblob/export digests separate, not a false exactGitblobclaim.
- Finalartifactmanifest/gate/committedbinding bind exact7artifact/data bytes and
 allreceipt Gitblobs; raw stored once byhash. Countboundaries explicit: collection
 inventories precede their own command/output; finalcommit audit includes closedset.

## Real blocker and boundaries (unchanged)

**BLOCKED / NOT_READY. Full candidate NOT_RUN / zero attempts.** No necessary real
verifiedentity_tag positive or actualhumanreview. No expandedGET, synthetic/human
pretence, fullbuild, oldsnapshotwrite/index/VACUUM, mainmerge/P4/Pool integration.
Fullcandidate performance/RSS NOT_RUN; all resolverperformance is newpilot-only.
Linux/Pi/Pool/dbstat/fullhumanfacts NOT_RUN. Official data licenseunknown/local-only.
Need genuine sourceID/link evidence or real scopedhuman decisions, replay/newpilot/
allgates; do not automatically retry/launch fullbuild. Ordinary finaldevpush+lsremote
must bind fixedSHA before root requests unifiedreview. Code review may approve this
repair without magically accepting the overall P3 knowledge coverage gap.
