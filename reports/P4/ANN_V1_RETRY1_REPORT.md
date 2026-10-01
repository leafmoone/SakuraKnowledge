# ANN V1 retry1: pilot PASS, stop for review

Contract fc95fdb3ff4c879560cde44f0ac04cd37d61a9d3 pushed/remote verified before
single invocation exit0. Tests53PASS/RuffPASS; actual isolated USearch preflight
PASS (8 vectors,4D FP32 cosine,add/search/save/load/key validation). No psutil
installed; process RSS NOT_AVAILABLE does not affect build qualification.

Historical V1 FAIL unchanged:1920 formal_failures means
PLANNED_BUT_NOT_RUN_DEFAULT_COUNT, actual formal/warmup attempts0. Old indexes
untouched and never reused. Retry1 builds four fresh hash-bound indexes in new
build/p4/ann-v1-retry1. Inputs/preflight/source bindings checked before/after PASS.

Fixed16 candidates,1920 actual formal searches,0 failures,0 not-run;32 warmups,
0 failures,0 not-run.12 candidates PASS all gates. No parameter/grid/threshold,
gold/BM25/RRF change. No query retries, embeddings or ONNX export.
Selected by frozen p95/tie rule: M16,Eadd256,ef128. FP32cos1024,multi=false,
512chunk neighbors then typedEntry dedup100. Reference remains frozen ONNX
exact ranks, not newly computed exact output.

Selected macro Recall10=.9925,20=.9916666666666667,100=.97725;
minimum per-case .9,.9,.91. Search-only p50=3.471299998636823ms,
p95=4.656149996299064ms,max=5.215299999690615ms. Excludes embedding/dedup.
Build31.356917500001146s; index223537008bytes,
SHA2560d3d019cc3a401d1297bf5b6cff1dd725bb1cfddb229471da87b30e30134bcf0.
USearch index.memory_usage285778304bytes, hardware_acceleration=serial;
these are actual API observations, not process RSS (unavailable).

Selected benchmark-v2 PASS, all15 subset regression deltas>=-.01,
identity promotion errors0. Hybrid Recall10 overall.9136363636363637,
lexical1,semantic1,crosslingual.7333333333333333,ambiguous_negative.85.
Semantic MRR delta-.004166666666666652 and nDCG delta-.0032732438392865104
are retained losses within tolerance. Full metrics/gates for qualified candidates
in ann-v1-retry1.json, raw percase evidence local-only. No claim all metrics
identical or improved. Negative zero-denominator metrics remain null.

Post-run snapshot21718736896bytes SHA256
61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9 unchanged.
Old receipts/config, production src/rust/pyproject unchanged. No global installs,
Pool modification, SakuraTool launch or main edit. No model/vector index commits.

P4_RESULT=READY_FOR_NEXT_GATE (ANN PILOT only)
RUST_SEMANTIC_RUNTIME_STARTED=NO
FULL_SEMANTIC_BUILD_ATTEMPTS=0
FULL_SEMANTIC_PACK=NOT_RUN
STOP_STATE=WAITING_REVIEW after result push verification.
No default/full semantic matrix or production integration claimed this round.
Fresh diagnostic remains setup-validation timeout, product cold-start unmeasured.
