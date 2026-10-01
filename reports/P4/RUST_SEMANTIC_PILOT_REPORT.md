# Rust semantic runtime PILOT acceptance

Implementation/artifact source c417655e149b7dce64d0bab376076f2a2f7c7320.
Dependency contract1b33e64 (see git for full SHA). Base19de7a8891be151345576b50658cbca8643a9d75.
Rust dependency probe exit0: exact120 tokenizer IDs/masks,ORT1.24.1 CPU8threads,
direct Python USearch2.26.2 index read-only load52664x1024/cos/ef128 PASS.
Pinned optional ort2.0.0-rc.12/tokenizers0.22.2/usearch2.26.2; no binary download.
ORT DLL15355936bytes SHA4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847.
Default binary independent of semantic files. Semantic feature adds retrieve.

Activation verifies full hashes only outside query/open. Initial activation
failed repository containment for explicitly authorized external DLL; failure
receipt retained. Narrow exact-path/size/hash exception tested, retry activation
exit0. No export/index rebuild. Local-only pilot_sidecar manifest includes all
ONNX external tensors, frozen lexical DB/mapping/corpus/index/DLL/tokenizer.
Open validates manifest, sizes and contracts without full artifact hashing.

Persistent pilot:2warmups+120formal,0failures/not-run/retries. Bindings before/
after PASS. Rust vectors numerical PASS; macro/min top10/20/100 overlap all1.0
against selected Python ANN. Actual Rust fusion IDs verified independently.
Benchmark-v2 and subset metric-regression gates PASS, identity promotion0.
See rust-semantic-pilot-v1.json for complete metrics/gates.

Linear(n-1)*p timings (ms), recomputed from formal records:
- tokenize p50 .1813,p95 .343095
- ORT p50 81.4217,p95 106.897425
- ANN stage p50 42.12825,p95 53.90709
- BM25 p50 55.02615,p95 136.96209
- fusion/evidence p50 64.7931,p95 113.879785
- total p50 239.13,p95 378.150915,max460.4315
Runner receipt uses discrete percentile (p95 total377.6631); both pass1000ms.
Every operation <=5000ms. ANN stage includes mapping/dedup; not comparable to
Python pure ANN index.search-only4.65615ms without qualification.
Engine open2429.4338ms; tokenizer577.6867,ORT1805.7507,ANN5.6992ms.
RSS NOT_AVAILABLE. Standalone CLI one-case diagnostic total4089.8607ms exit0,
160697bytes; not120process qualification or disk-cold claim. All resident
responses checked<=524288bytes, standalone CLI also enforces cap.

Default approved-baseline regression:151/151 (135whole/16error) and55/55
(39resolved/16nonresolved),wrong0,timeout0,retry0. NOT original oracle recovery.
Immutable snapshot/sidecars unchanged. Build binaries in separate local targets.
Default/semantic matrices exit0 (fmt/test/clippy/release). Initial command
wrapper bash launches exited127; preserved, Python subprocess wrappers then
ran full matrices successfully. No failed command reclassified PASS.
Full pytest1187PASS/143SKIP/61subtests; skips not integration evidence.
Ruff initial helper lint errors fixed without production changes; final recheck
required. Legacy helper changes after run are formatting/noqa only.

RUST_SEMANTIC_RUNTIME=PASS (pilot acceptance, not FULL)
P4_RESULT=READY_FOR_FULL_BUILD_GATE
FULL_SEMANTIC_BUILD_ATTEMPTS=0
FULL_SEMANTIC_PACK=NOT_RUN
STOP_STATE=WAITING_REVIEW after normal dev push verification.
No main/Pool/SakuraTool changes, model/DLL/index commits or automatic FULL.
Raw outputs/local pack required to reproduce; full human source-fact review and
production integration remain NOT_RUN.
