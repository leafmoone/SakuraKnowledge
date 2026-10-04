# Current stage status

## Current round: GLOBAL_ADOPTION_NOT_VALIDATED / DEFAULT_RETAINED128

Baseline `60feb51cfedad62e1ae9a8594c4980e1499f0c63`. Single compact comparison:
`reports/P4/ef-comparison-60feb51.json`. Before search, existing Rust binding
`index.get` compared every actual mapped target row for the five entities with
little-endian FP32 NPY bytes: **5 rows x 1024 components exact-bits PASS**, positions
561631/93234/827490/468106/1137273. No full-key/sample audit or vector corpus scan.
All120 saved query vectors validated before search; same readonly Rust index
instance tested ef1024, then ef2048 **only because exact-top1 P4-039 remained absent
raw512 at1024**. Cos/F32/M16, wanted512 and entity100 unchanged. Effective width is
max(ef,wanted): original128 means512, not separate128/256/512 search tiers.

### Complete saved-vector arithmetic comparison

Each tier uses all120 saved embeddings with original lexical rows and actual pins,
current unchanged RRF/scorer/targets. No encoding/FTS/gold/threshold/model changes.

| Final metrics R10 / MRR / nDCG | saved old full128 | ef1024 replay | ef2048 replay |
| --- | --- | --- | --- |
| lexical30 | 1 / .977778 / .983333 | same | same |
| semantic40 | .925 / .8475 / .866662 | .950 / .8925 / .906991 | .975 / .90625 / .923860 |
| crosslingual30 | .600 / .320357 / .388228 | .600 / .319299 / .387151 | .600 / .320093 / .387914 |
| ambiguous-positive10 | .650 / .429286 / .430727 | same | same |

Frozen gate baseline remains **lexical**, not oldfull: semantic R10 .95 therefore
target1; both tiers still **quality FAIL** despite MRR/nDCG improvements. Negative
nonempty rate1.0 (10 denominator), promotion errors0 (120/10 denominators) remain
separate. Dense ordering changes94/99 cases respectively; improvement in any
relevance metric2/5 cases, regression1/1.1024 improves035/064;2048 also039/042/074.
P4-095 regresses MRR by .031746/nDCG .032303 in both tiers;074 gains .023810/.022874
at2048. No claim all cases improve. Raw ranks at1024 vs2048:035 1/1,039 absent/1,
064 2/2;033 108/109 remains outside100entities,042 absent/absent (exact9967).

ANN search min/median/nearest-p95/max ms:1024
37.0264/556.0116/2252.1442/2819.4060;2048
21.5459/144.8210/530.8106/867.5322. **Cold/warm order confounds these measurements**;
2048 is not demonstrated faster. It was provisionally selected for global recall
benefit, not warm timing, and required real E2E budget validation.

### Actual candidate E2E failure, preserved rather than retried

Published new `build/p4-prepared-ef2048-60feb51-v1/manifest.json` accurately declared
2048, canonical/declaration/runtime matched then. Existing immutable ANN/model/
corpus stayed referenced; the20.8MB derived membership was copied without rebuild
into the new pack because current protocol requires a local member role. Old pack
untouched. One existing-runner real E2E attempt:
`build/p4-ef2048-60feb51-evaluation-v1/` has2warmups PASS, **109 formal PASS,
P4-110 transport FAIL,10 NOT_RUN**. Successful query wall maximum2707.1703ms;
this is not a complete120 runtime pass. FULL quality **NOT_RUN**, no aggregate
pass inferred from partials. Error `EOF/oversize JSONL response` is ambiguous:
raw failure bytes were not retained then, stderr0bytes, no owned child remains.
Cleanup wait10s timeout is **not proven retrieval timeout**, oversize or deadlock.
Driver limit is **524288bytes (512KiB)**, not1MiB. No real query/search rerun.

Production canonical/currentassets retain original128 after incomplete acceptance;
config bytes match prior defaults. Rust now applies the actual validated contract
positive integer search width (1..65536), no hardcoded128 at set call; pilot contract
remains128. Tiny native-index fixture verifies actual setters128/2048 and rejects
bool/zero/negative/fraction/out-of-range. Failed2048pack bytes remain unchanged;
its canonical binding no longer matches current128 contract and it is **historical
unaccepted evidence, not a currently loadable validated candidate**. Next explicit
acceptance must use improved transport evidence, not treat this fragment as pass.

New instrumentation retains bounded MAX+1 failure prefix and read length,
distinguishes EOF/oversize/unterminated, labels incomplete/truncated evidence;
runner saves it exclusively for future failures. Existing owned-child cleanup
already closes stdin, kills/waits on failure, closes stdout; tiny regression checks
that path. The size safety limit is unchanged. Lost historical110 bytes cannot be
reconstructed. Execution also unintentionally verified large assets twice during
stage/final guards rather than one shared stable-path session: disclosed deviation,
no further hashing. Future publication must validate roles/small derived asset in
stage, then shared session verification of stable final paths, as existing prepare
already does; do not move paths registered in a session.

Rust semantic33+2dependency+1main PASS; probe2tiny tests PASS; related Python
metadata/preflight/runner/replay155PASS4Windows-symlink skips before transport
instrumentation; final transport/replay checks18PASS in0.18s, touched Ruff/diff
PASS. An oversized test parameter initially hit Windows pytest-cache path limits;
explicit short fixture IDs fixed it without changing assertions. No whole suite/legacy206.
These120 now form development/regression selection data, not independent
held-out generalization. Historical complete runtime PASS / quality FAIL and
FULL exact-overlap NOT_RUN remain unchanged; global adoption **not validated**.

## Previous round: FIVE_QUERY_EXACT_DIAGNOSED / HISTORICAL_QUALITY_FAIL

Baseline `c8bcff6fe1533dfd39fe6d149cf04de0af412242`, ordinary `dev` delivery.
One focused diagnostic: `reports/P4/five-query-exact-c8bcff6.json`. All five original
formal responses contain finite 1024-component Rust f32 query vectors matching
frozen query text; **no re-encoding, prefix change or model initialization**.

Readonly `vectors.npy` memmap: float32 `(1366520,1024)`. Five queries share **one**
sequential vector traversal, 4096-row blocks, float64 dot/norms computing genuine
Cosine (distance `1-cosine`), not a dot-only assumption of perfect normalization.
Target scores use indexed typed-identity lookup of **all entity chunks**, then
small random vector reads; global strict-greater ranks and tolerance intervals
are accumulated during that one pass. Each target has one mapped chunk here.
Exact top512 chunks and first-occurrence top100 entities use the existing dense
mapping/dedup/cap semantics. Exact equal-score position ordering is a deterministic
diagnostic convention, **not a claim about ANN tie order**. Near tolerance `1e-7`
is reported independently without rounding/reordering; all five target rank
intervals are singletons, so target inclusion conclusions are not float-last-bit
ties. Global chunk rank, 512 candidate cutoff and 100 entity cap stay distinct.

After the scan showed exact top1/2 targets absent saved ANN entities, one authorized
readonly batch extended the existing `usearch_path_probe --saved-five-query <index>
<saved-response-directory>` mode. Same patched Rust USearch dependency, Cos/F32,
M16, ef_search128, depth512, path view; no engine/model, integrity audit, index build
or parameter search. **New measurement, not historical raw chunks.** Its mapped
entity top100 order matches saved results in all five cases. Raw new512/exact512
chunks, chunk IDs/positions/scores and entity mappings are retained in the single
JSON. Historical ANN raw512 overlap is unavailable; never retroactively reported.

| Case / accepted target | Exact global chunk rank | Exact entity rank before cap | New ANN raw chunk / entity rank | Classification |
| --- | ---: | ---: | --- | --- |
| P4-033 subject 554333 | 112 | 112 | 101 / 101 | **B**, within512 but outside100 entity cap on both paths |
| P4-035 subject 93628 | 1 | 1 | absent within512 / absent | **A**, new ANN omits exact top1 |
| P4-039 character 96679 | 1 | 1 | absent within512 / absent | **A**, new ANN omits exact top1 |
| P4-042 subject 463806 | 9967 | not within512 | absent within512 / absent | **C**, exact representation/relevance rank too low for candidate budget |
| P4-064 danbooru.wiki page 77750 | 2 | 2 | absent within512 / absent | **A**, new ANN omits exact top2 |

Cosines respectively `.5805982874/.6555053021/.6222436527/.4816997630/.6262797101`.
A classifications refer directly to this new original-parameter raw measurement;
matching saved entity rankings supports reproducibility but does not conjure
historical raw512 data. No D mapping bug was found by these targeted checks; this
is **not** independent certification of the whole mapping/index. For P4-033 only
within512 entity ranks are established, not an unmeasured global entity rank.
New exact512 intersections are respectively 446/339/359/322/395, diagnostic counts
for these five queries only, **not FULL exact-overlap PASS**.

### Resources and execution limits

Exact scan: **18,824.9134 ms**; float64 block payload 33,554,432 bytes plus score/
rank/top buffers, readonly memmap 5.6 GB data backing; RSS **NOT_MEASURED**. ANN
view open 107.0158 ms; five searches 25.3377/30.9939/26.6663/28.1944/27.7846 ms,
probe exit0, empty stderr. UTF-8 explicitly enabled. No large-asset hashing, FTS,
membership preparation, corpus encoding, pack/index rebuild, MSVC, production
ranking/gold/depth/threshold changes, real120 rerun or broad integrity probe.

### Minimal general follow-up, not a case-route patch

035/039/064 now show an ANN recall gap at the fixed original settings; a separate
controlled index/search quality qualification is the first follow-up, with CPU/
latency/recall tradeoffs and held-out entity/document-group splits. This round did
**not** vary ef_search, rebuild the graph, or select parameters on gold. Reranking
cannot recover absent candidates (especially 039, also absent lexical). 033 would
require revisiting the100 entity candidate contract to admit rank101/112, adding
mapping/scoring/response cost and possible five-second-budget regression; no cap
was enlarged here. 042 remains low even under exact Cos, so ANN tuning alone does
not solve its dense miss. The previously explained RRF consensus/tie losses still
apply to lexical-only 035/042/064; protecting single-branch hits can trade away
crosslingual dense gains and requires independent validation, not per-case rules.
Historical runtime PASS / quality FAIL remains unchanged. These five are targeted
development diagnostics, not generalization or FULL exact-overlap acceptance.

Checks: five small Python cosine/rank/mapping tests PASS (including nonunit norms,
zero/nonfinite/empty rejection, deterministic ties, duplicate positions, entity
cap and unmapped rows); one Rust saved-vector parsing/norm test PASS; probe release
build PASS. Only related tests/static checks, not the whole suite.

## Previous round: CLI_FIXED / OFFLINE_DIAGNOSED / QUALITY_FAIL

Baseline `95042a5b961a693f03085fa74ca7e5977d27f49e`. The prepare CLI now prints its
result without attempting a second JSON write to the directory it just published.
A real `main()` tiny SQLite fixture traverses prepare/publication/manifest read,
checks exactly one staging-manifest write, and checks the derived row; production
asset validators are substituted only for tiny assets. No real candidate rebuilt.

### One 120-case replay table

`reports/P4/saved-results-95042a5-cases.json` is the sole delivered table, generated
by `python -m tools.p4_saved_results_analysis --results
build/p4-prepared-lexical-5c8526e-evaluation-v1 --output <exclusive-new-json>
--inspect-union-misses`. It covers all 120 frozen cases and every accepted target,
with raw lexical document ranks, compact entity ranks, dense ranks, final/output
and untruncated fused ranks, duplicate counts, union coverage, actual pins and
source locators, five variant metrics, and precise per-branch RRF contributions
for displaced targets. Saved full hybrid/candidate rankings reconstruct exactly
in **120/120** cases; original lexical/dense/final aggregates and `quality_gate`
reproduce exactly. The old raw `total_quality: NOT_RUN` is not authoritative.
Raw responses, evaluation, frozen gold/questions and published pack are unchanged.
This is five arithmetic views of the **same stored branches**, not five retrieval
runs. Original depth-100 raw ranks, first-occurrence typed identity dedup, k=60,
pins-first typed ordering and current scoring are preserved.

| Variant | lexical R10/MRR/nDCG | semantic R10/MRR/nDCG | crosslingual R10/MRR/nDCG | ambiguous-positive R10/MRR/nDCG |
| --- | --- | --- | --- | --- |
| lexical | .800/.648/.686 | .950/.866/.886 | .067/.067/.067 | .500/.369/.371 |
| dense | .333/.185/.219 | .850/.750/.775 | .600/.514/.535 | .400/.203/.216 |
| lexical + actual pins | 1/.978/.983 | .950/.866/.886 | .067/.067/.067 | .500/.369/.371 |
| dense + actual pins | 1/.978/.983 | .850/.750/.775 | .600/.514/.535 | .400/.203/.216 |
| current full RRF + pins | 1/.978/.983 | .925/.848/.867 | .600/.320/.388 | .650/.429/.431 |

Group query counts are 30/40/30/20; the last group has 10 positive and 10 empty-target
negative cases, with positives only in relevance means. Every variant's negative
nonempty-return rate is 1.0 and identity-promotion error rate is zero; these are
independent measures. A returned candidate is not an asserted answer or identity.
No arbitrary threshold was added to clear negative responses.

### Semantic target-level causes, not a single aggregate guess

All 40 semantic cases have zero actual pins; all observed semantic target lexical
raw ranks equal compact entity ranks, so document duplicates do not explain these
losses. Three cases improve rank: P4-032 target subject 665897 (3 -> 1), P4-046
subject 195693 (6 -> 2), P4-066 danbooru.wiki page 27453 (7 -> 1). Three regress:
- P4-035 subject 93628: lexical 1, absent dense top100, final 5. Three dual-branch
  entries outrank its single contribution `1/61=.016393442623`: character 155765
  (L12,D4,sum .029513888889), subjects 330545 (L25,D49,.020939017809) and 382360
  (L29,D81,.018328153638). Dense-only subject 489554 at D1 ties the target score
  and sorts ahead by typed key. R10 stays hit; MRR/nDCG regress.
- P4-042 subject 463806: lexical 1, absent dense top100, final 5. Subjects 586762
  (L16,D57,.021704903284), 503763 (L24,D74,.019367448472), 506242
  (L57,D60,.016880341880) outrank it; dense-only subject 157362 at D1 ties
  `1/61` and typed-key sorts ahead. R10 stays hit; MRR/nDCG regress.
- P4-064 danbooru.wiki page 77750: lexical 1, absent dense top100, final 12.
  Ten dual-branch pages have strictly larger sums, not eleven: 77751 (L3,D17),
  59596 (L14,D11), 59595 (L5,D31), 77476 (L16,D23), 10364 (L4,D53), 77745
  (L2,D66), 77595 (L10,D77), 149928 (L25,D49), 77816 (L21,D99), 77744 (L70,D50).
  Dense-only page 127833 at D1 ties `1/61` and typed-key sorts ahead. The JSON
  records both reciprocal contributions and sums for all eleven preceding entries,
  plus the new top10 displacing entries. This is the **one new R10 loss**, not
  the sole quality regression; MRR/nDCG also lose on 035/042.

Two already-missed semantic targets remain misses: P4-033 subject 554333 is in
lexical union at document/entity 99, absent dense; untruncated fusion rank 188,
therefore outside final output cap100, not absent branch coverage. P4-039 character
96679 is absent both stored branches. Indexed readonly document-PK and chunks
`document_id` lookups confirm document 785252 source-backed and one mapped chunk;
source text describes the 15-year-old Basel university researcher, locator retained
in table. Presence does not prove query answerability or ANN failure. Analogous
indexed checks are in the table for all other union-missed accepted targets.
No FTS/MATCH query, model initialization, ANN search, vector scan, corpus encoding,
or large snapshot/model/vector hashing was run. Exact comparison was **NOT_RUN**:
fusion regressions are fully explained offline; ANN versus representation for
union misses stays **UNKNOWN**, not inferred from absence.

### Ranking decision and follow-up

No production ranking change: equal-RRF consensus boost and typed ties match the
specified algorithm, not a discovered code defect. No case/group route, parameter
sweep or selection of a configuration on these 40 cases. A general follow-up could
compare branch-union candidate reranking using independently trained/calibrated
query-document relevance, with original source/identity checks unchanged. Cost:
extra candidate scoring CPU/model dependency and latency validation; it could lose
crosslingual dense gains or lexical exact-hit precision. A simpler one-branch
policy costs little CPU but the all-group table shows the tradeoff: lexical+pins
loses crosslingual R10 .600 -> .067; dense+pins loses semantic .925 -> .850.
Neither is proposed as a quality-pass replacement. Before any new ranking choice,
use separate development/validation/test splits grouped by entity/document to
avoid name/translation leakage. The diagnosed 120 cases are now development/
regression evidence, **not independent generalization**.

Verification: `python -m pytest -q tests/test_p4_build_entry.py
 tests/test_p4_saved_results_analysis.py`: **13 passed in 0.74s**, exit 0;
touched-file Ruff and `git diff --check`: PASS, exit 0. Offline replay verified
all 120 full rankings and the saved quality gate; tiny fixtures cover duplicates,
multiple targets, stored pins/negative nonempty returns, boundary displacement and
hard rejection of reconstruction mismatches. No whole Python suite, legacy 206,
ANN probe or real 120-case rerun.

## Previous round: PARTIAL / RUNTIME_PASS / QUALITY_FAIL

Baseline `5c8526e8444e8bf7c6f1742998733180621b6555`; ordinary `dev` delivery only.
Explicit prepared membership and rank-cursor BM25 now run the unchanged FULL
workload under its existing five-second deadline. **FULL acceptance failed the
frozen semantic quality gate.** No gold, formula, corpus, ANN, embedding, source
trust, or deadline was changed to obtain a pass.

### Prepared asset and exact retrieval semantics

`tools/p4_full_build.py --prepare-lexical --existing-pack <pack> --output <new-pack>`
builds a rebuildable SQLite membership artifact only during explicit prepare.
Normal Rust open checks and loads it; missing, mismatched, corrupt or legacy
unprepared packs require explicit prepare, never a startup/query fallback scan.
Each valid original FTS row is stored as integer `(fts_rowid, entry_id, document_id)`;
original joins, text equality and trust qualify membership. Distinct valid FTS
rows for the same document remain separate. Metadata/schema/integrity, unique
rowid, integer IDs, actual row count, rule version and snapshot size/SHA binding
are checked independently. The new pack references unchanged immutable assets
and is published via exclusively owned staging with no overwrite.

Rank SQL is `SELECT rowid,rank FROM search_fts WHERE search_fts MATCH ?1 AND
rank MATCH 'bm25()' ORDER BY rank`. Original MATCH/OR/tokenization/corpus/BM25
weights remain. Actual FTS rowid membership filters the cursor; bounded document
row top-100 preserves original kind/namespace/value/document_id ties. All equal
100th-score rows are traversed until strictly worse/end, with no fixed oversample,
filtered LIMIT, or premature entry deduplication. Only selected top-100 rows get
original strict source/evidence output validation. Ineligible and discarded
low-priority boundary rows cannot introduce new output errors; erroneous selected
rows still fail. SQL and loops share the unchanged overall deadline. Read-only
real-snapshot EXPLAIN returned `SCAN search_fts VIRTUAL TABLE INDEX 32:rM3` without
a temp sorting B-tree. Fixture equality checks complete original JSON output,
including `chunk_id: null`, displaced rowids, duplicate valid rows, wrong-row
membership, hundreds of boundary ties and selected/discarded source errors.

### Real execution, failures and publication

New candidate: `build/p4-prepared-lexical-5c8526e-v1/manifest.json`, 28,074 bytes,
SHA256 `f3e04c68a1ec424706881d5a854ca8f86a8ef8698684b83082dd5dc65803f9fe`.
Membership: `lexical-membership.sqlite`, 20,799,488 bytes, 1,295,638 FTS rows,
SHA256 `e4fe2806e3aead3df4098803ed633e8eced87f2cda42ad733b0b60678bc7773a`.
Snapshot remains 21,718,736,896 bytes, SHA256
`61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9`.
Executed release binary `build/p4-usearch-native-fix/rust-target/release/semantic_pilot.exe`:
19,407,056 bytes, SHA256
`9a808c80868db4a943a0003cef94570ef5d822ebc1a6b4e83770f225f356ba3e`.

Execution was serialized, with verified UTF-8 environment and retained stderr.
First prepare failed before FTS scan at cross-drive ORT DLL relativization;
fix preserves only the already authorized absolute DLL binding. Second prepare
completed/committed the derived asset, then Windows publication failed because
SQLite contexts did not close handles; cleanup also failed and masked the first
error. Fixed explicit connection closing and preserving primary exceptions with
cleanup notes. Its owned failed staging remains at
`build/p4-prepared-lexical-5c8526e-v1.staging-ln_7b1zb/`.
With explicit authorization, recovery checked actual schema/integrity/meta/count
and content SHA, copied only that known completed derived asset and small manifest
into new exclusive staging, then published and validated the new candidate.
Evidence: `build/p4-prepared-lexical-5c8526e-diagnostic-v3/recovery.json`.
This was **explicit recovery, not a fresh successful prepare**. Current prepare
scan time is **NOT_RECORDED**; do not substitute prior-round scan timing. Asset
hash/guard elapsed time is also NOT_RECORDED; fresh-process guards were necessary
after failures, while the final diagnostic/formal process shared one session.
Original candidate and failed directories remain. Diagnostic v1/v2 did not query;
v3 engine open failed a second legacy seven-role closed-set check before query.
Its stderr retains `FULL artifact closed set mismatch`; this is not P4-003 query
failure. The formal validation entry now has a prepared-role fixture.

### Independent diagnostic and frozen formal results

Actual command used existing `evaluate(...existing_pack=True, verified_session=session,
diagnostic_case='P4-003')`, then only on diagnostic PASS
`evaluate(...existing_pack=True, verified_session=session)` in the same process.
New evidence directories:
- `build/p4-prepared-lexical-5c8526e-diagnostic-v4/`: independent P4-003 PASS,
  startup wall 2,654.4294 ms/internal 2,319.0394 ms/membership load 261.6206 ms;
  query wall 1,419.9333 ms/internal total 1,412.2051 ms;
  ANN index search 29.7632 ms, dense mapping 14.7675 ms,
  BM25 1,218.9774 ms, pins 2.8573 ms, fusion/evidence 70.7941 ms.
  Cursor rows 101, eligible rows 100, extra boundary ties 0. Cursor read count
  includes the first strictly worse row used to terminate.
- `build/p4-prepared-lexical-5c8526e-evaluation-v1/`: two warmups PASS;
  **120/120 formal runtime/source/typed-identity PASS**, zero timeout/nonzero child
  exits, child exit 0. Parent command exit **1** because quality gate is FAIL.
  Startup wall 2,423.4557 ms/internal 2,394.9019 ms; membership load 259.7551 ms.
  Formal wall min/median/nearest-rank p95/max:
  156.7592 / 466.0806 / 961.2627 / 1,265.9187 ms.

| Frozen subset/metric | Lexical baseline | Final | Gate target | Result |
| --- | ---: | ---: | ---: | --- |
| lexical (30), Recall@10 | .8 | 1 | .7666666667 | PASS |
| lexical, MRR@10 | .6481481481 | .9777777778 | .6181481481 | PASS |
| lexical, nDCG@10 | .6862202839 | .9833333333 | .6562202839 | PASS |
| semantic (40), Recall@10 | .95 | .925 | 1 | **FAIL** |
| semantic, MRR@10 | .8660714286 | .8475 | .8660714286 | **FAIL** |
| semantic, nDCG@10 | .8862850007 | .8666623719 | .8862850007 | **FAIL** |
| crosslingual (30), Recall@10 | .0666666667 | .6 | .1666666667 | PASS |
| crosslingual, MRR@10 | .0666666667 | .3203571429 | .0666666667 | PASS |
| crosslingual, nDCG@10 | .0666666667 | .3882281914 | .0666666667 | PASS |

Overall identity-promotion errors 0/120 and negative identity-promotion errors
0/10; negative-query nonempty return ratio 1.0 does **not** mean negative quality
success. The saved raw report's `total_quality: NOT_RUN` is an accounting bug:
its actual `quality_gate.status: FAIL` and all gates were computed. Raw evidence
is preserved unchanged; runner is corrected for future output. Exact-dense FULL
oracle/overlap remains independently **NOT_RUN**, as does RSS measurement. Memory
payload/allocation are not measured RSS: FTS 31,095,312/50,331,648 bytes; deduplicated
entry/document membership 20,730,208/20,730,208 bytes. No repeat formal run, quality
parameter tuning, full Python suite, legacy 206 rerun, or ANN probe was performed.

### Directed checks

Rust semantic tests: 32 library + 2 dependency-probe + 1 main PASS; release build
PASS. Directed Python checks: **119 passed, 4 skipped in 7.45s** (Windows symlink
privilege skips), Ruff `src tests tools` PASS and `git diff --check` PASS, exit 0.
Additional Windows rename-after-prepare/validate fixture confirms derived handles
close; cleanup failure fixture preserves the primary error and unrelated staging.
No integration or full human source-fact review is claimed.

## Previous round: PARTIAL / BLOCKED_FULL_BM25_DEADLINE

Baseline `37318ebeb6812a1df1a4a1adeeafbc891854207a`, current `dev`.
The newly authorized engine-lifetime FULL membership index removed repeated pin
and output-document FTS scans. It **does not establish FULL route acceptance**:
the unchanged frozen P4-003 failed in original BM25 within the same five-second
overall query budget. No further real run or BM25 optimization was attempted.

### Implementation and equivalence

Only current-engine memory stores sorted, deduplicated `Vec<(entry_id,document_id)>`.
One startup traversal, no text retention, disk cache, sidecar, schema change,
rowid assumption, ANN/gold-derived membership or new dependency:

```sql
SELECT e.id,d.id
FROM search_fts f
CROSS JOIN documents d ON d.id=f.document_id
CROSS JOIN entries e ON e.id=d.entry_id
WHERE f.entry_id=e.id AND f.text=d.search_text AND
 e.conflicted=0 AND d.status IN ('source_backed','generated_from_evidence')
 AND e.kind!='episode' AND EXISTS (
 SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed')
```

Actual snapshot read-only EXPLAIN: `SCAN f VIRTUAL TABLE INDEX 0:`, then
`SEARCH d USING INTEGER PRIMARY KEY`, `SEARCH e USING INTEGER PRIMARY KEY`,
and covering `entry_evidence_entry(entry_id,status)` in the trust EXISTS.
Pins retain original exact/alias source joins, evidence/status/nonblank checks,
case sensitivity, UNION dedup and typed-key ordering, filtering by any qualifying
cached document for that entry. Document output uses the exact cached pair and
retains its own document-source existence, nonblank evidence, provenance equality,
trusted identity and source loading. It cannot borrow another document's output
proof. Original MATCH/BM25, ranking, raw depth, fusion and filters are unchanged.

Tiny SQLite tests compare original SQL complete outputs and fail-closed outcomes
with the new implementation: FTS rowid shifted by 10,000, duplicate rows,
missing/wrong text/entry/document binding, missing document source, blank document
evidence, untrusted/conflicted/episode entries, ambiguous aliases, differently
sourced aliases and absent identity-proof source. Same-entry valid and invalid
documents cannot cross-satisfy output checks. Integer ID reads fail rather than
silently skipping. The cache assumes the bound snapshot remains immutable for
that engine lifetime; there is no persistent mtime/stat cache.

### Actual run and budget

The existing immutable candidate was reused, not recreated:
`build/p4-existing-assets-a19f919-v1/manifest.json`, 27,727 bytes, SHA256
`f7738e6c565c698a5952ee704f00f5216347b7153a8c43d1791378ae45b506ed`.
Existing complete ANN key/1,200-sample reader evidence was reused, not re-probed.
Actual command, explicit UTF-8 environment and existing UCRT64/project Cargo cache:

```text
cargo test --manifest-path rust/Cargo.toml --features semantic
cargo build --release --manifest-path rust/Cargo.toml --features semantic --bin semantic_pilot
python -m tools.p4_existing_assets_evaluate --binary build/p4-usearch-native-fix/rust-target/release/semantic_pilot.exe --output build/p4-existing-assets-a19f919-v1 --existing-pack --results build/p4-existing-assets-37318eb-membership-evaluation-v1
```

Run exit **1**, original raw evidence retained in that exclusively created directory.
Release binary 19,577,696 bytes, SHA256
`46a5837134d1761453cac4019b084e1716532f5d9a568a283c79cbb96716b991`.
Initialization scan/sort/dedup **116855.8434 ms**, **1,295,638 pairs**;
logical tuple payload **20,730,208 bytes**, actual Vec capacity allocation
**33,554,432 bytes**. These are index storage sizes, **not process RSS increment**;
RSS delta was **NOT_RUN / not measured**. Startup internal total **119764.5383 ms**
(includes membership; metadata total 117047.9484 ms), observed wall
**120130.8201 ms**. Existing policy specifies a **120-second response-wait timeout**,
not an explicit wall comparison: the response was received, but wall exceeded
120 seconds. Neither startup performance nor a strict 120-second wall gate is
claimed PASS; wall-budget compliance is **FAIL if 120 seconds is the required wall
budget**. The pre-existing code did not define/enforce that additional comparison;
no tolerance or alternate timing metric was adopted to turn it into PASS.

Two warmups passed, not counted as formal cases. Formal P4-001 and P4-002 passed
actual response source/evidence/identity validation. Formal backend timings (ms):

| Case | pins SQL | BM25 SQL | fusion/evidence | total |
|---|---:|---:|---:|---:|
| P4-001 | 0.2115 | 191.3441 | 21.7260 | 314.7155 |
| P4-002 | 0.1499 | 992.1124 | 17.6968 | 1108.5756 |

Formal **P4-003 FAIL**, actual Rust envelope:
`full_lexical: BM25 SQL: interrupted; pins_ms=0.5073; bm25_ms=3676.3955;
tokenize_ms=0.4981; ort_ms=74.7758; ann_ms=1248.2777;
lexical_ms=3677.5516; total_ms=5001.5066`.
ANN is charged to that same overall five seconds; BM25 did not receive five
additional seconds. Original SQL, unchanged:

```sql
SELECT e.kind,e.namespace,e.value,bm25(search_fts) AS score,
 d.id,d.source_id,d.evidence_id
FROM search_fts JOIN documents d ON d.id=search_fts.document_id
JOIN entries e ON e.id=d.entry_id
WHERE search_fts MATCH ? AND search_fts.entry_id=e.id
 AND search_fts.text=d.search_text AND FULL_DOCUMENT_TRUST
ORDER BY score,e.kind,e.namespace,e.value,d.id LIMIT 100
```

Actual query: `生産スキルを極めた俺の異世界創造ハーレムライフ! ~上手に現代巣作りできました~`.
Read-only EXPLAIN with the reference compiled MATCH binding (34 unique overlapping
CJK bigrams joined by OR, original tokenizer unchanged) reports:
`SCAN search_fts VIRTUAL TABLE INDEX 0:M3`, document/entry PK probes,
covering `entry_evidence_entry`, `USE TEMP B-TREE FOR ORDER BY`.
This is a plan observation, not authorization to alter scoring or truncate
candidates. No large BM25 query was repeated.

The original runner mislabeled the valid P4-003 FAIL envelope as response-version
mismatch and attempted P4-004 against the dying driver. P4-004 had no completed
response: its recorded EOF is a **transport attempt, NOT_RUN retrieval**, not a
second genuine product failure. Original JSON/raw files were not rewritten.
Correct interpretation: **2 formal PASS, 1 formal FAIL, 117 formal NOT_RUN**.
Runner now recognizes valid Rust FAIL envelopes before success-schema validation,
retains their exact error and stops. This small reporting fix was tested, not
used to rerun the large assets. Full frozen quality is **NOT_RUN**: two successes
are insufficient for any stratum gate or complete identity error claim.
FULL exact-dense overlap remains independently **NOT_RUN**, oracle absent.

### Checks, non-execution and prior limitations

Rust semantic final regression **30 library + 2 dependency-probe + 1 main PASS**,
exit 0 (library 0.49s). First new fixture failed because it unwrapped an expected
blank-evidence BM25 rejection; corrected to compare both fail-closed outcomes,
not loosen production evidence checks. Runner-focused **13 passed in 0.12s**,
Ruff all and diff-check PASS. No full Python or actual 206-case rerun: shared
Python/P2/P3 behavior was untouched except narrow runner error-envelope reporting.
Previous actual 151+55 evidence below remains prior-round evidence, not a new run.
No embeddings/ANN rebuild, candidate recreation, MSVC installation or Python
extension compilation occurred. Large-file performance used one serial stream.
The two earlier overwritten unknown logs remain unrecoverable and unstaged;
no guessed restoration or new log overwrite was performed.

## Prior round outcome (baseline): PARTIAL / BLOCKED_FULL_FTS_PIN_MEMBERSHIP

Baseline: `a19f919af505b076d1129583b100abe7d6d13384`, branch `dev`.
This round fixed current configuration, lifecycle and reusable acceptance and
executed the authorized existing-assets route. **The FULL end-to-end route did
not pass.** Asset assembly and Rust startup passed; the frozen first warmup
exceeded the unchanged five-second query deadline in FULL pin membership SQL.
All 120 formal FULL cases and FULL quality remain **NOT_RUN**, not zero scores.
Python-native rebuild remains **NOT_RUN / toolchain-blocked**. No embeddings,
ANN products, gold, thresholds or source snapshots were changed.

## Fixes and boundaries

- Distinct `FULL_CONTRACT` and `CURRENT_ASSETS` constants: the actual FULL
  contract is no longer mistakenly read from the current asset inventory.
- `execute()` retains the independently verified snapshot baseline for terminal
  comparison. Terminal failures retain the original work error, record secondary
  errors and release only the lock owned by this invocation (token plus file
  identity). Replacement locks are not deleted; receipt failure cannot skip
  owned-lock cleanup.
- `AcceptanceSession` verifies actual immutable size/SHA bytes once per unique
  resolved asset in that session, rejects conflicting bindings and detects
  state/path changes. A new session hashes again. Every response independently
  checks typed identities, documents, evidence and sources; no provenance cache
  or semantic identity promotion was introduced.
- `--existing-assets` is separate from `--execute`: small staged candidate,
  atomic create-new publication and role-bound controlled relative references
  to existing assets. No `execute`, `build_stream`, encoder or Python-native
  USearch add/save/view is used. Unknown/swapped roles and unsafe paths reject;
  general containment policy was not relaxed. Necessary FULL product pins moved
  into current assets, not historical authorization receipts. Legacy metadata
  extras are projected out of live size/SHA bindings, not trusted as authority.
- Existing-binary legacy evaluation separates create-new results from the Cargo
  cache. It preserves frozen baseline comparisons and never compiles/reloads a
  Python index. Rust changes add role checks and error-stage timing only; native
  index interpretation and product bytes are unchanged. Consequently the prior
  1,366,520-key / 1,200-sample reader conclusion was reused, not re-probed.

## Actual candidate and commands

Candidate: `build/p4-existing-assets-a19f919-v1/manifest.json`, **27,727 bytes**,
SHA256 `f7738e6c565c698a5952ee704f00f5216347b7153a8c43d1791378ae45b506ed`.
It references the retained `build/p4-full-semantic-v1-retry1` corpus, mapping,
1,366,520-row ANN and vectors, the fixed P3 snapshot, and current model,
tokenizer, ONNX external tensors and ORT DLL. Actual content validation succeeded;
that is not a claim that the earlier builder completed or FULL acceptance passed.
The actual creation runner calls `existing_assets(output=..., session=...)` internally
and keeps that same session for manifest/response validation. Standalone available
CLI example (not separately executed this round):
`python -m tools.p4_full_build --existing-assets --output build/NEW-unused-candidate`.
Use a new absent output; do not rerun creation over the existing candidate.

All Python execution used explicit `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`.
Cargo used existing `C:/msys64/ucrt64/bin` on process-local PATH and
`CARGO_TARGET_DIR=D:/SakuraTool/SakuraKnowledge/build/p4-usearch-native-fix/rust-target`.
No external Pool cache, main branch or global toolchain configuration was changed.

```text
cargo test --manifest-path rust/Cargo.toml
cargo test --manifest-path rust/Cargo.toml --features semantic
cargo build --manifest-path rust/Cargo.toml --features semantic --bins
python -m pytest -q
python -m ruff check src tests tools
git diff --check
cargo build --release --manifest-path rust/Cargo.toml --features semantic --bins
# Actual v2 creation + evaluation command (before the output existed):
python -m tools.p4_existing_assets_evaluate --binary build/p4-usearch-native-fix/rust-target/debug/semantic_pilot.exe --output build/p4-existing-assets-a19f919-v1 --results build/p4-existing-assets-a19f919-evaluation-v2
# Actual v5 revalidation of the already-published immutable candidate:
python -m tools.p4_existing_assets_evaluate --binary build/p4-usearch-native-fix/rust-target/release/semantic_pilot.exe --output build/p4-existing-assets-a19f919-v1 --existing-pack --results build/p4-existing-assets-a19f919-evaluation-v5
python -m tools.p4_rust_legacy_regression --binary build/p4-usearch-native-fix/rust-target/release/sknow-rs.exe --results-dir build/p4-existing-assets-a19f919-legacy-v2 --knowledge build/p3-full-authorized-retry1/knowledge.sqlite
```

Regression: **1161 passed, 18 skipped, 55 subtests passed in 57.74s**, exit 0,
with actual `SKNOW_RS_TEST_BIN=D:/SakuraTool/SakuraKnowledge/build/p4-usearch-native-fix/rust-target/debug/sknow-rs.exe`. All 18 skips are Windows
symlink privilege limitations, not safety-test PASS. Rust default 7+1 and
semantic 29+2+1 passed, exit 0; semantic rerun after diagnostic changes also
passed (29 library tests, 0.40s). Ruff and diff-check passed. Later wrapper and
projection changes received focused regression, not another whole-suite run:
`python -m pytest -q tests/test_p4_build_entry.py tests/test_p4_existing_assets_evaluate.py tests/test_p4_full_acceptance.py`
reported **115 passed, 4 symlink skips in 7.89s**, exit 0; the subsequent warmup
failure guard received runner-only **12 passed in 0.08s**. Final wrapper-focused
checks: **20 tiny-fixture adapter tests passed**; final combined focused run
**135 passed, 4 symlink skips, 4 subtests passed in 9.12s**, exit 0, followed by
Ruff and diff-check PASS. The hardened adapter was not rerun on the large
snapshot: the prior actual 206-case evidence remains authoritative, while its
new timeout/finalization/binary guards are covered by small actual-hashing tests.

## Real runtime, quality and performance

The resident `semantic_pilot` driver calls formal `SemanticEngine::open/retrieve`.
Debug run v2 and optimized release runs v3–v5 opened the actual candidate.
Latest v5 startup wall: **2466.151 ms**; internal startup total **2085.7931 ms**
(ORT **1398.7916**, tokenizer **414.9204**, ANN **116.6372**, metadata **155.4431**).
Startup is separate from query timing and excludes Python asset hashing.

The unchanged frozen first case `P4-001` failed. Latest stderr:
`full_lexical: pins SQL: interrupted; tokenize_ms=6.3005; ort_ms=62.079;
ann_ms=48.3022; lexical_ms=4889.0056; total_ms=5005.8139`.
Driver wait reached its five-second boundary first (wall **5002.2805 ms**), so
stdout error was not received in v5; stderr and exit **1** were retained.
The first warmup failed, the second warmup and all 120 formal cases are NOT_RUN.
There is no valid resident-query distribution or FULL retrieval quality result.

Read-only EXPLAIN confirmed selective entry-value/alias indexes and document /
entry-evidence indexes, but correlated FTS membership uses a virtual-table scan
on UNINDEXED `document_id` / `entry_id` fields. No sound equivalent local SQL rewrite was
established. Original pin eligibility SQL remains:
`EXISTS(SELECT 1 FROM documents d WHERE d.entry_id=e.id AND FULL_DOCUMENT_TRUST
AND EXISTS(SELECT 1 FROM search_fts f WHERE f.document_id=d.id AND
f.entry_id=e.id AND f.text=d.search_text))`, driven by the existing exact
`e.value=?1` / alias `a.text=?1` candidate predicates. `FULL_DOCUMENT_TRUST`
requires unconflicted non-episode entries, eligible document policy and
source-backed entry evidence. Original BM25 remains MATCH-driven, joining
`d.id=search_fts.document_id` and checking `search_fts.entry_id=e.id`,
`search_fts.text=d.search_text` and the same trust predicate before the unchanged
ranking limit. No proposed rewrite was adopted: selective candidate driving was
already present, and no indexed equivalent for real FTS membership was proven.
Pins consumed the five-second query budget; BM25 was **NOT_RUN in that request**,
not separately allowed an extra five seconds. FTS rowid is not a document-ID contract. No index/schema/cache
rebuild, weakened membership/pins, early candidate truncation or relaxed deadline
was attempted. Further structural performance work requires explicit scope.

Frozen gold: `reports/P4/retrieval-gold.json`, SHA256
`ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba`,
120 unchanged cases (30 lexical, 40 semantic, 30 crosslingual, 20 ambiguous/negative).
The runner retains the existing v2 metrics/gates and same-FULL-population lexical
baseline, not pilot rankings. Semantic/crosslingual R10 requires
`min(1, baseline + .10)` with no MRR/nDCG decline; lexical losses remain bounded
by 1/30 R10 and .03 MRR/nDCG. Identity error must remain zero with per-response
source verification. These checks are **NOT_RUN on formal FULL responses**;
fixture regression does not establish real-source identity/provenance success.
FULL exact-dense overlap is separately NOT_RUN because its oracle is unavailable.
Gold is non-exhaustive engineering relevance, not full human source-fact review.

Independent actual P2/P3 regression: **151/151 P2 + 55/55 gold comparisons PASS**,
runner exit **0**, timeout **0**, exact JSON/error/source contracts preserved.
Evidence: `build/p4-existing-assets-a19f919-legacy-v2/evaluation.json` and all
206 stdout/stderr pairs. G51 wall **4.0611941 seconds** belongs to this legacy
run, not FULL semantic resident performance.

## Failed attempts and limitations

- Initial full pytest invocation used nonexistent `sknow_rs.exe` instead of
  actual `sknow-rs.exe`; failed, then corrected and rerun successfully. It was
  not interpreted as PASS.
- Evaluation v1 rejected inherited `git_blob_sha1` metadata in strict live file
  bindings before runtime. Projection was corrected and tested. v2 assembled
  successfully but its runner continued against a dead driver: the 120 Err22
  records are wrapper failures, not 120 retrieval measurements. v3–v5 abort
  transport failure and keep remaining cases NOT_RUN. All result directories
  were retained, not overwritten or discarded.
- Legacy old module imports / coupled Cargo-cache reservation and an adapter
  missing-helper error blocked early invocations before cases. Corrected v2
  actually executed all 206 cases. Failed v1 directory was retained.
- Same-session asset hashes were reused across assembly/manifest/response checks.
  Separate diagnostic processes necessarily created fresh sessions and rehashed;
  no persisted stat cache was substituted for actual content verification.
- A worker accidentally overwrote two pre-existing untracked diagnostics:
  `p4-owned-pytest-diagnostic.log` and `p4-owned-ruff-diagnostic.log`.
  Their original contents were not recoverable; no guessed restoration was made.
  They are not staged. This is an execution-boundary violation, not a product
  validation result. Other unknown files were not intentionally cleaned.
- **MSVC_REQUIRED_FOR_PYTHON_REBUILD YES**: the real Python rebuild chain still
  needs the patched native extension; it was neither built nor verified. No
  MSVC/SDK installation was attempted. Existing Rust asset opening works without
  that rebuild but the current FULL query/quality route remains blocked above.
