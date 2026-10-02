# P4 clean-room preflight recovery — draft / WAITING_REVIEW

Producer implementation: `ccc80fd8d2d700654a9003cc70e3785628275f99`. Evidence commit binding: Git commit containing this report; exact submission SHA recorded externally in handoff. Producer and evidence commits are distinct.

## Origin and evidence boundary

The original untracked `tools/p4_full_semantic.py` was lost; this is a new clean-room implementation, not recovered original source. The incident's reported 30 errors / 3 failures are historical failure evidence, not current test results. External preserve remains untouched: `D:/SakuraTool/SakuraKnowledge-p4-full-loss-preserve-20261002/preserve`, manifest SHA `26d7f147be8aca7d715f35d839f3758dd247eae9a573a7e3e3b0057c564879e1`.

Current producer evidence and exact receipt bindings are in `full-semantic-count-preflight.json`. Matrix r3 status COMPLETE_WITH_SKIPS: 12 commands returned exit0; targeted tests 251 PASS / 7 SKIP and full tests 1561 PASS / 21 SKIP. Skips are NOT_RUN, not PASS. Inventory6, count7, disk3 and smoke2 have root's specific external run acceptance. Pilot2 and legacy2 executed successfully, with detailed evidence awaiting root completion of independent verification.

## Current measurements

Count7: 1,295,638 documents; 1,366,520 chunks; 147,849,991 tokens; maximum chunk384; empty/duplicate documents/chunk IDs all0; 15,411 paragraph splits. Nested count.audit peak113,798,888 bytes within1GiB; close/cleanup VERIFIED and temporary absent. Actual snapshot and sidecar observations were independently reviewed.

Disk3: required64,156,962,688 bytes, observed free384,525,631,488 bytes. This is a particular observed condition, not a future capacity guarantee. Mapping measurement544 rows /526 pages /4096bytes, with25% estimated uplift rather than a strict bound.

Smoke2: actual RTX4060 CUDA0 / FP32 / batch8 / threads8 / max sequence512. Pilot128 and FULL-only512 output rows finite float32 /1024dim; error0, cosine1, maximum norm error1.1920928955078125e-7. Tokenizer projection repeated hashes agree, 60,758 token IDs. Native READY_FOR_BUILD_REVIEW does not authorize a build.

Pilot2:2 warmups plus120 formal passed, retries0 and missing0, overlap@10/20/100 macro/minimum1.0, quality failures empty. Wall p95 334.9341ms; resident p95 324.8028ms. Legacy2:151 P2 (135 whole values /16 errors) and55 gold (39 resolved /16 nonresolved), wrong_resolved0, timeout0. Historical anchor c417655e149b7dce64d0bab376076f2a2f7c7320 differs from current runtime producer.

All six outer command raw references, pilot and legacy binaries, and622 legacy evidence-manifest entries were re-read and verified by this worker. Legacy has151 P2 and55 gold case files; snapshot/sidecars before and after equal. New pilot job differs from its frozen new-job original only in raw_directory and output. Actual pilot binary SHA33c54c408dc40e606bf6feddd10b48c40fb31694e256bf41df81cb89b81e71cd; legacy binary SHA cf0526051d6c774f2ad805fbaf2b521c606ece1097aea1d541407c658f2e9636.

## Failures remain failures

Retain all historic receipts/diagnostics: source-loss incident; inventory launch/serialization failures; count DLL/environment/projection failures; count5 unknown-child launch gap; disk1 reference-schema and disk2 cwd failures; matrix launcher unknown-child failure and r2 preparation failure; environment-probe1 missing distribution metadata/usearch; intermediate CPU torch result; smoke1 wrapper absolute-CONFIG misuse; formal build1 missing semantic feature exit101. Later successful runs do not erase these failures. Old producer counts are not migrated to current acceptance. Smoke1 prelaunch is NOT_RECORDED; never backfilled. Wrapper-only smoke2 corrected absolute CONFIG to controlled_path, without relaxing contained or changing source.

## Limitations and publication

Top-level count audit remains stale NOT_RUN/NOT_VERIFIED. Real audit source is count.audit; external checks do not repair general validator missing fields. Smoke inner snapshot observations were not retained, and no outer observations were taken for smoke. GPU duration/peak memory NOT_RECORDED; pilot memory NOT_AVAILABLE. Smoke model footprint is narrower than disk's4,576,033,489 referenced-asset bytes; neither measures whole Python/venv footprint. New venv ORT DLL differs from the approved system DLL and does not replace it. Helpers may run Git during failure finalization. Source-fact human review and Pi/Pool integration remain unestablished.

Credential-like environment keys were found in full local diagnostic captures (77 JSON files in inspected current/diagnostic directories). Do not stage original full-env launches/captures/preexecution or the formal dispatch receipt. Do not expose values. Preserve originals locally; any publication copies must be separately named, explicitly redacted derivatives with original SHA and a redaction declaration, never replacements claimed to have the original SHA. Selected receipts/reports and sanitized capture/dispatch/matrix derivatives are proposed for publication; original full-environment records and remaining referenced raw/build evidence stay local-only. Redaction manifest binds original and derivative bytes/SHA, without claiming equivalence of hashes. Do not stage venvs, build targets or whole directories.

Working tree was not globally clean: existing untracked diagnostic directories and logs remain. No deletion, git clean/stash/reset, add-all, source edits, commit or push was performed here. A final evidence commit must be distinct from producer SHA; normal dev push and live remote SHA equality are mandatory before formal review.

Final state: WAITING_REVIEW, builder_authorized=false, FULL_SEMANTIC_BUILD_ATTEMPTS=0, FULL_SEMANTIC_PACK=NOT_RUN, no FULL product writers or locks.
