# P3 delivery — BLOCKED / NOT_READY (not P3 acceptance)

Implementation/artifact source:`b393581c54d5ac0db76802897220f4818c1eb3c0`.
P3_BASE and immutable main:`894dc6a73bfd42f18cc7648e8ab7481aae211ab1`.
Evidence/final submitted commits are bound in committed-byte-binding.json and
normal dev push/independent remote verification; no mainmerge/P4 authorization.

## Real blocker / full-build decision

`full-candidate-gate.json` was executed from clean fixedb393source. All recorded
cleanSHA/main/inputSHA/old21.5GBSHA/disk/budget/realpilot/native/Wiki gates pass.
The **necessary real verified entity_tag positive** gate fails:100name-only mapping
candidates,0verifiedcross-source links,0actualhumanverification. Therefore:

- **FULL_CANDIDATE=BLOCKED / NOT_RUN / zero attempts.** No failed fullbuild, retry,
  overlay, oldsnapshot index rebuild, VACUUM, overwrite or opportunistic fallback.
- Real pilot and code may be inspected, but **P3 is not ready for acceptance**.
- Unblock with genuine bound cross-source ID/link evidence or scoped actual human
  decisions. Agent self-review/names/scores cannot produce a verified identity.
- Fullcandidate performance/RSS NOT_RUN. No claim of fullsource recall/fullrefresh.

## Implemented scope

Rust `Runtime::resolve_tag`/`sknow-rs resolve-tag` and explicit Rust `related_in`/
`related --direction in`. Typed originalTagKey, finalcategory constraint, no source
filter/key bypass, complete classification before displaylimit, active directed
canonical proof, source_scope/evidence_chain/descriptions. Shared5s operation and
524288B compactresponse cap; essential proof/identity cannot silently disappear.
Optional single-snapshot native projection and incoming index are produced offline
by existing builder before verified atomic publication. Oldsnapshot new capability
is explicitlyunsupported; oldcommands still pass. P2ask policy unchanged.

Python **public P2 Runtime/API/CLI remain frozen**. New Python modules are ETL/graph/
decision replay/builder validation; independentoracle lives in tools and is never
production runtime parity. Hardcoded fixtures preceded implementation; raw-source
50gold expectedbehavior is an additional independent layer beyond fullJSONoracle.
Contract/design:docs/P3_PLAN.md and docs/p3-resolver-contract.md.

## Input/evidence and real pilot

Audit: P3_SOURCE_AUDIT.md, preflight-source-audit.json, live-handoff-audit.json.
Official metadata52requests/42targets/186307collectorbytes+4MiBdocumentationreserve,
0retry/concurrency1/1.05s.30native identities,28compatible officialWiki associations,
2changedWiki versions quarantined,352assessments,100candidate-only decisions.

Frozenpilot:`build/p3-pilot-v2/knowledge.sqlite`.
Snapshot ID:`092133a1deede082b92d7b0f5a24a20d8f03837f526dca8b9e62b6dfd5b36826`.
Manifest:`build/p3-inputs-v2/pilot-manifest.json`.
Candidate-input manifest:`build/p3-inputs-v2/candidate-manifest.json` (not built).
451entries/222FTS/874input=874accepted,0rejected, integrity/FK/FTS/account verification
passed before publication. Selected records retain all source name collisions from
the complete old inputs, not merely favorable candidate samples.

## Validation with exact receipts

| Check | Actual result | Evidence |
|---|---|---|
| New independent fixtures / oldregressions |214pytest PASS (47new);6Rust tests PASS|check-pytest.json/check-rust-test.json|
| SevenWindowschecks |pytest/ruff/diff/fmt/Rusttests/clippy/release each exit0|check-*.json|
| Frozen50realpilot queries |50fullJSON+oracle+expected PASS;38/38positives (15Chinese-script),12/12nonresolved,0wrongtag|real-gold-cases.json/real-pilot-acceptance-final.json|
| Unchangedold151 |151/151=135fullJSON+16expectederrors;0retry|old151.json/old151-command.json|
| Newresolver reusedconnection vs independentCLI |480measured+16fixedwarmups,30/workload/mode;allsuccess,0retry|resolver-performance.json|
| Source-external installedwheel+newrelease binary |8P2JSONpairs+50Rustresolver expected/fullJSON PASS;explicit-Xutf8 verified|artifact-cli-utf8.json|
| Retained A-C artifact boundary |10correct independentfixturepairs PASS|artifact-abc.json|
| Exactartifact/source/receiptbyte audit |415referencedunique localrawfiles verified;12wheelmodules match exactarchiveexport with separatelyhashed LF/CRLFblob distinction|artifact-manifest.json/delivery.json|

Pilot-only p95 maxima:reusedconnection0.0003364s; independentCLI0.06950190011411905s.
These are two different measurement boundaries, not a Python-vs-Rust speedup claim,
not 21.5GBresolver capacity evidence, and not a candidatefull-build PASS.

## Fresh artifacts / byte boundary

Built from a new `git archive` of fixedb393source into dist/p3-b393581/source;
releasebinary/examples and wheel are new outputs, not relabeled P2artifacts.
Wheel:`dist/p3-b393581/sakura_knowledge-0.2.0-py3-none-any.whl`.
Rust:`dist/p3-b393581/source/rust/target/release/sknow-rs.exe`.
Newlocalvenv installed offline/no-deps; externalcwd,-I,-Xutf8 and site-packages path
verified. Python API has noresolve_tag. Artifactmanifest binds exactsizes/SHA.

Gitarchiveexport produced CRLF bytes for12Pythonmodules. Initialstrict exactblob
comparison **FAIL** is retained in artifact-byte-audit-failure.json, not relabeled.
Newmanifest hashes both committedLFblob and actualwheel/export bytes separately,
checks exactexport match and only-EOL normalized equivalence. NewP3JSON/JSONL receipt
blobs are byte-verbatim (-text) and bind exact committedbytes/OIDs, not justworktree.

## Failures preserved, never silently converted to PASS

- Before resolver:11FAIL;beforegraph:10FAIL;beforeinverse:1FAIL, missingfeatures.
- Firstbuilderfixture:1FAIL/3PASS (projection omitted from sourceaccount). Corrected
  separatev2:4PASS. Fixtures isolated; no real/fullsnapshot buildretry.
- Firstcompilation v1commandexit0 but rawmetadata nestingbug invalidated coverage;
  preserved INVALID_COVERAGE, superseded by v2input/receipts without source refresh.
- Categorynative mismatch beforefixtureFAIL;fixedruntime avoids entity fallback.
- Firstrealpilot acceptance49/50FAIL:officialaliasTagKey correct, Wiki description
  absent. Frozen50gold unchanged; runtime target-index description fix yields50/50.
  Old receipt's wrong_resolved counter overcounted missingdescription; newidentity
  metric compares status+TagKey, not completeness. No oldfailedreceipt is rewritten.
- Artifactsetup -I ignored UTF8environment:exit1/UnicodeDecodeError preserved.
  Explicit -Xutf8 uses newreceipt; not a parity/performance retry.
- StrictwheelGitblob exactbyte comparison FAIL preserved; exportEOL distinction
  explicitly documented above. No rebuiltartifact or hiddenclaim of blob equality.

## Boundaries still explicit

Linux, Pi Skill runtime, Pool/SakuraTool integration, dbstat/fullhumanfacts:NOT_RUN.
Fullupstreamrefresh:NOT_RUN. Source data license:unknown/local-only. Verification of
normalized runtime/source scope is not fullhuman source-fact review. Wrongtag0 on
38positive/12nonresolved scopedgold does not prove universalrecall or sufficiency;
0verifiedentitytag is the realfullbuildblocker, not something fixtures can erase.
