# 9d5 single residual repair — code PENDING_REVIEW, P3 BLOCKED / NOT_READY

Baseline: `9d5f26ddeb5335c8d449eb72335bb2df603d5e28`.
Only authorized residual: terminal Wiki quarantine evidence missing from active
alias projections. Endpoint/category, realgold, redirect closed items remain closed.
Source/artifacts: `229c2ddcc43c0d3919d44a4ea823f6a999a48a57`.

## Exact repair (15 compiler lines, no runtime expansion)

`tools/p3_compile_inputs.py` previously assessed aliases before comparing old/live
Wiki cuts. Native terminal C received actual quarantine reference later; A/B→C did
not. After all cut comparisons, collect actual native quarantine references by typed
canonical target, append them deduplicated to canonical projections for that same
target. Original native/official identity evidence, directed steps and complete
outgoing scopes stay unchanged. No placeholder role, compatible Wiki edge, body
regeneration or conflicted description is introduced. Canonical identity remains
resolved C; descriptions remain empty and reason/date evidence is now retained.
Rust resolver and independent tool oracle consume those unchanged bound projections;
no production Rust/Python source change was needed. The independent oracle's complete
JSON output is tested against raw-built expected values on every repaired route,
not treated as proof just because it agrees with runtime.

## Independent counterexample and acceptance

Raw inputs: native C ID3/category4; active alias1 A→B, alias2 B→C; scopes A/B/C complete;
old Wiki ID9/titleC/body unchanged/updated_at=old-cut, official embedded same Wiki/
title/body/updated_at=new-cut. Compiler runs in TEMP from these raw/input bytes, then
NORMAL builder verifies and atomically publishes a new fixture snapshot. No published
DB patch. Typed A/B fixture identities allow explicitnativekey; synthetic heroA→A
and heroC→C boundcrosssource links exercise verified endpoints, not real validation.

Eight independently declared fullJSON cases: ordinary A/B/C, explicit A/B/C,
explicit heroA/heroC. Expected chain manually binds actualsource IDs/rawSHA/oldinputSHA,
Wiki/native keypair, mixed_cut_version_conflict, old-cut != new-cut, scope A/B/C as
applicable, official alias IDs/direction/status; docs=[], no compatibility/docs refs.
Only expected snapshot/dynamic raw digest values are taken from frozen fixture bytes,
never runtime results. Compiler projection chains must equal those expected chains.

- Initial before:8FAIL, including mistaken fixture linkeID (builder uses fallback)
 and C tests additionally checked other failing projections. Receipt kept unchanged.
- Corrected before, still oldcompiler/binary: **5FAIL/3PASS**. A/B ordinary+explicit,
 heroA omit quarantine; C ordinary+explicit and heroC already pass. Actual defect,
 not a newly failing real55 query.
- After compiler repair: **8PASS**. New release acceptance stores exact commandstdout/
 stderr, complete expected/oracle bytes and raw/compiler/builder inputs once byhash.
 All eight completeJSON must match both independent expected and oracle. No retries.

Receipts: `review-9d5-quarantine-before*.json`, `quarantine-after.json`,
`quarantine-raw*.json`, `quarantine-release*.json` under reports/P3.

## New clean artifacts / unchanged real scope

New git archive229source→fresh releasebinary/examples/wheel/newvenv, no relabeling
previous outputs. Pythonpublic/P1P2/old151/Rustsrc unchanged from9d5.12wheelmodules
exactly match archiveexports, separatelyhash LFcommittedblob and CRLFexport bytes;
only EOL equivalence claimed, not exactGitblob equality.

Fullpytest **242PASS**, Rust6; seven checks each exit0 on fixed229source. Newbinary
quarantine8fullJSON/expected/oracle **PASS** separately from real55 **55PASS**
(39resolved/16nonresolved/wrongtag0), unchanged old151 **151PASS** (135completeJSON+
16expectederror contracts), sourceexternal8P2pairs+55Rustcases/10ABC **PASS**.
13fixedworkload dualmodepilotperformance:780measurements+26fixedwarmups **PASS**,
0retry/failure/timeout, maxreusedp95=0.0004716s, maxCLI p95=0.07266539987176657s.
These different boundaries are PILOT_ONLY, not fullcandidate capacity or RSS.
Actualsummary/raw/hash records live in `review-9d5-delivery.json`; no totals replace
the specific new alias/quarantine counterexample.

Only real activealias in frozen scope terminates at a compatible Wiki cut, so real55
gold remains unchanged. A separate offline recompilation to a new input directory
compares every compilednative/pilot JSONL byte against existing reviewed inputfiles;
no GETs. When identical, existing published realpilot is reused read-only, not
replaced or labeled as newly built. New manifests/receipts remain separate. Original
55/50gold, failed49 output, all historical116P3files and P1P2 receipts/raw preserved.
All frozen source/old21.5GBsnapshot/artifact bytes rehashed; finalcommittedbinding
records OID/SHA/size and finalremoteHEAD/main/clean independently after ordinarypush.

## Status and strict boundaries

Code: PENDING_REVIEW until root requests finalfixedSHA read-only review; no selfapproval.
Overall **P3 BLOCKED / NOT_READY**, necessary realverified entity_tag still **0**;
100candidate agentdecisions/0human, fullcandidate **NOT_RUN / zero attempts**.
No actualhumanreview, new upstream GET, fullcandidatebuild, original snapshot write/
index/VACUUM, Pythonpublicruntime capability, mainmerge, P4 or Pool work. Pilotonly
performance is not fullcandidate capacity/RSS. Linux/Pi/Pool/dbstat/fullhumanfacts/
fullrefresh remain NOT_RUN; rawdata licenseunknown/local-only. Need genuine source
cross-ID/link evidence or actual scopedhuman decisions; synthetic fixture cannot
unblock coverage. Do not automatically acquire/build while this blocker stands.
