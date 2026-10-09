# Current local Moegirl source refresh

This is a source-targeted offline refresh, not a live crawler run or a full-page
review. Inputs are read-only `D:/dataset/danbooru_wiki/moegirl-dataset`; frozen bytes,
comparison, normalized bundle and receipts stay under `build/moegirl-refresh-v1/`.
Original mother, old source packs, shared model, FP32 and ANN assets are preserved.

## What actually changed

The nine existing Moegirl-derived files and four mapping files are byte-identical
to `build/source-cache-v2/`. Their previous metadata cut is retained, not falsely
claimed freshly processed. `extra_processed` has45676 records;485 have no current
raw fragment, and288 current raw records have no processed record. No upstream
Makefile, processor, crawler or writer script was executed. Current attrs/subjects
are read directly as native category path observations with raw locators, not
silently substituted for historical attributes/aliases/CV/gender or typed works.
No `character_of`, person join or native tag membership is inferred. Current
category paths are stored raw observations, not new CLI classification/filter/
related fields: existing `source_fields` still projects historical derived fields.
The upstream flattener's duplicate-URL/empty-node completion was not reproduced;
direct indexed-character paths are not a claim of complete processed equivalence.

Actual char_index45998 unique titles closes exactly into extra_info45479 plus
outcomes494missing/25skipped_by_user, with no overlap or uncovered title.
extra_info contains617 empty template lists and44862 nonempty records. All47589
nonempty strings are exact crawler-selected template fragments, not complete
articles. Empty/missing/skipped records retain explicit current no_reference
observations and no document; their historical source-backed identities remain.
An empty missing-work queue does not prove every page succeeded. Empty lists mean
no usable template was captured, not that pages have no article body. `missing`
means the frozen API outcome; skipped_by_user is not evidence of page absence.

The new cut uses a new `moegirl-local-templates-...` source ID derived from frozen
owned-input bindings. Prior Moegirl and mapping IDs are retained only after exact
byte checks of their owned inventories. Legacy entry/alias evidence uses original
line ordinals; canonical duplicate records are suppressed before reference injection.
Original9 missing-endpoint mapping inputs remain unresolved; no extra candidate
or trusted endpoint is introduced. Mapping rows remain candidate, never verified.
Mapping storage references are regenerated normalization references, while payload
retains `original_evidence_id` for the old-cut lineage. Do not claim identical SQLite IDs.

## New text proof

Each source_backed document is the raw UTF-8 template string at
`moegirl/extra_info.json#/<escaped title>/<list index>` under the pre-existing typed
moegirl.character key. Compact provenance includes method/version, raw file SHA,
exact text SHA, typed title, raw source ID, template index and char_index locator/hash.
No parser rewriting, LLM cleanup or spelling/name identity inference is used.
The independent checker reloads frozen JSON and verifies every document against
exact bytes, source ownership, locator and independent historical identity evidence.
Successful API page revision/full-response receipts are absent: historical producer
revision remains unknown. Observed checkout HEAD is not the authenticated producer.

## Build and use

```powershell
python -m tools.normalized_source normalize --input build/moegirl-refresh-v1/input-frozen --adapter sakura_knowledge.moegirl_refresh:MoegirlRefreshAdapter --pack-id moegirl --output NEW_BUNDLE
python -m tools.normalized_source build-normalized --input NEW_BUNDLE --output NEW_MOEGIRL_PACK
python -m tools.moegirl_refresh_validate --pack NEW_MOEGIRL_PACK --frozen build/moegirl-refresh-v1/input-frozen --output NEW_PROOF_RECEIPT.json
python -m tools.normalized_source validate --input NEW_MOEGIRL_PACK
```

The explicit build-time adapter needs installed builder tooling/checkout, not the
portable query Core. Pack contains manifest, snapshot and lexical membership only;
audit JSON/raw category trees/proofs/gold are not runtime dependencies. Install it
as `packs/moegirl` in a new portable root, replacing only the selected Moegirl pack
while preserving the old root separately. It requires neither model nor Dan pack.
No new semantic vectors/ANN are built; added lexical rows can change mixed rankings.
Current create-new delivery locations are:

- `build/moegirl-refresh-v1/SakuraKnowledge-pack-moegirl-final2` (three-file source pack)
- `build/moegirl-refresh-v1/SakuraKnowledge-core-win-x64-final3` (matching updated Core)
- `build/moegirl-refresh-v1/normalized-final2` (offline normalized builder bundle)
- `build/moegirl-refresh-v1/runtime-source-final/sknow-config.json` (model-absent actual smoke root)
- `build/moegirl-refresh-v1/runtime-all-linked/sknow-config.json` (actual all-pack validation root)

The previous1MiB Core explicitly rejected a normal1,342,138-byte source-only
response. This stage uses the authorized bounded2MiB semantic wire limit and
matching reader/binaries; success content/ranking is unchanged, never silently
truncated. Use updated Core with the new source pack, not an old1MiB Core and a
claim that only a data-directory swap suffices. Other source/model/index artifacts
are shared readonly via same-volume hardlinks in validation roots; these roots
are not claimed byte-copy export distributions. Core bins are independent copies.
The diagnostic first pack and earlier failed/NOT_RUN receipts remain preserved;
only final2 is the delivered source candidate.

## Other database checked

Known second source DB `D:/dataset/danbooru_wiki/tag_wiki.sqlite` was opened readonly
and frozen with SQLite online backup including WAL, without source checkpoint/VACUUM.
New backup1560510464bytes SHA4e7de5432e24b3973c1f376c5deeb243f426dfbcc66122b297d3c4365ff6d5b8;
old backup same size SHAbfe3d0c4c8609770459c1c143e59d15bda0620dcea9b974c62c980b2226dd9b2.
Physical bytes differ. Exact indexed bidirectional comparisons show13 keyed tables
unchanged. tag_evidence nullable composite keys contain duplicates; full typed
row/count multiset additionally matches193494 rows/96747 distinct rows. Therefore
all14 logical tables are unchanged and the current tag-wiki pack/proof is retained,
not pointlessly rebuilt. An earlier EXCEPT sorting attempt was cancelled incomplete;
its backup receipt is retained, not interpreted as successful logical comparison.

## Final delivery bindings and preserved business state

This stage starts at `d572b03e6dbd6690498dde95b848c74f7ac01060` on `dev`.
The source pack totals **836,572,395 bytes** (only three files); Core totals
**79,210,105 bytes** (no data/model, no Python test helper/wheel).
Core `component-manifest.json` is a local delivery closed-set/file-binding receipt,
not a new runtime discovery protocol. Only the source-pack manifest is discovered
by the query runtime. Source snapshot integrity/FK/FTS/ledger/input/source-account
checks and independent full template/category/state proof passed before use.

| Delivered file | Bytes | SHA256 |
|---|---:|---|
| pack `manifest.json` | 1,259 | `08c0efdd3c8d17ab011e5ba2c4bc0d9e00fcae04cc2553ec1521884fe598636d` |
| pack `knowledge.sqlite` | 835,870,720 | `8341eb4a7e0d78b1ea946d2a0f94ad5e32f835ecd0f1e9368e696599253a82b8` |
| pack `lexical-membership.sqlite` | 700,416 | `fdf3c94069d60800678d67f7622671f7779bf2be357ad0215ae13b6de517b463` |
| Core `component-manifest.json` | 3,319 | `8a32dca07fb165d916f1020a1f1cba4de3ad48fd9350fd5b93f1b65dba447dec` |
| Core `bin/sknow-rs.exe` | 21,566,823 | `d89cb6f593fb993d355efe0f996f77b913c64edf260442613913c2704dedd459` |
| Core `bin/semantic_pilot.exe` | 21,519,573 | `48f0e982886058b51774f695bfaf805eac0e1a98a651d21e41f4c0b06028964a` |

Final normalized bundle: 238,972 records / 354,152,342 bytes,
SHA256 `f7ee68cb5966c5c41d7cfaffbf9a22b96451b0d8ca04427edd2b879298d18f5b`.
Its nineteen-file declared inventory includes frozen context; full shared inventory
and each evidence owner's subset are distinct. Source owners are
`moegirl-complete-5072f7cf3e3e`, `mapping-complete-c8263a535096` and
`moegirl-local-templates-356c34cce8d2`. Current template trust is under historical
source-backed `char_index` identities, not new template-name identities.
Observed upstream checkout `1ff222f8af5e399e230b9f88eb50995869ed22bf`
(`https://github.com/Zzzzzzyt/moegirl-dataset.git`) is not an authenticated crawl
producer revision; current source `upstream_revision` is null.

The final old/new comparison proves typed key sets equal: 95,695 entries,
129,455 aliases and 97,270 candidate business links; historical entry/alias original
references and link typed business fields/original references remain preserved.
Documents/FTS change 0→47,589; entry evidence 51,557→141,693; verified links 0→0.
No six diagnostic endpoint stubs or nine formerly unresolved candidate links ship.
The exact expected nine `missing_endpoint` records remain declared/accounted,
with generic defaults still rejecting undeclared unresolved records.
The independent current observations prove 411,020 attr and 50,223 subject paths;
these are compact direct-tree paths, not the different raw association counts.

Use the new Core and Moegirl pack together in a **new root**, with old valid roots
kept separately. Copy the Core's contents to `NEW_ROOT`, then copy the source-pack
contents to `NEW_ROOT/packs/moegirl`; use the supplied relative-path config. Other
existing source directories and the shared model may be copied separately without
rebuilding them. Do not overwrite an old root or write through asset hardlinks.

## Timeout diagnosis and compatible Core fixes

The initial all-pack 2MiB attempt completed 27 cases then timed out on `P4-028`,
`special_week_(ruler_of_japan)_(umamusume)`. Moegirl-only passed in 73.8885ms;
the three pre-existing packs still timed out without Moegirl. Opt-in
`SKNOW_DIAGNOSTICS` stderr tracing then measured encoding126.6964ms, Bangumi782.9ms,
Dan194.7ms and tag-wiki beginning at1105.21ms without finishing before the deadline.
This is not evidence of paging or a response overflow. Independent tag-wiki
`Runtime.search` was ~50.5ms; its second lexical document/proof SQL sorted all matches
with `bm25` into a TEMP B-tree (~3184.0ms), while a rank cursor yielded the same
complete top100 typed keys/document IDs/scores in ~39.8ms. The fixed four-pack
case passed1411.2816ms /816,558 bytes, with old-SQL top100 full document text,
source/evidence and text-provenance fields equal and source closure verified.

The small read-only Core fix uses explicit `rank MATCH 'bm25()'` to stream lightweight
rows, checks original eligibility, selects100 documents including complete numeric
boundary ties, then materializes complete bodies/evidence. It preserves multiplicity,
`d.entry_id` identity joins and typed tie order. It does not replace the independent
first100-entity search/pins with100 documents, add an index or change any rank/fusion.
The shared absolute5-second deadline covers both searches and SQL progress handling.

A separate final-source smoke found filtered basic search for the frozen query
`\u5bf9\u5e94\u7684\u4e3b\u7ebf\u4eba\u7269` timed out at5.001843s, while the resident response
passed207.2683ms with complete text. The filtered search TEMP-sort plan was likewise
optimized using the existing typed tie selector. Its original `search_fts.entry_id`
join, filters/pins/trust and10000-row scan-cap semantics remain unchanged: on cap
exhaustion the exact old sorted query is used with the **same** deadline. A >10400-row
tie fixture proves the naive stream would return2 keys instead of the old1; the
fallback returns the exact original result. Final source smoke runs this basic
search successfully in94.1397ms, exit0. No gold/token/filter/depth tuning occurred.

Final3 additionally routes modular single-query `--config ... retrieve` through the
same bounded semantic sender (the previously missed `println!` branch), without
changing structured commands or the resident binary. Real Moegirl single retrieve
passes exit0 /1,342,105 bytes /100 complete documents. Synthetic UTF-8 single-query
fixtures prove both a complete under-budget PASS and a >2MiB complete
`response_too_large` FAIL/exit1/retries0. The final resident executable is byte-identical
to the final2 binary that passed120 and27; only `sknow-rs.exe`'s single sender changed.

## Final checks and known quality regression

Commands use `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`; test helper is the current
owned Cargo release/example output via `SKNOW_RS_TEST_BIN`, never shipped in Core.
Cargo target/temp and all outputs are repository-contained; heavy steps ran serially.

```powershell
cargo test --manifest-path rust/Cargo.toml --offline --features semantic -j 1
cargo build --manifest-path rust/Cargo.toml --release --offline --features semantic --bin sknow-rs --bin semantic_pilot --example text_probe -j 1
python -m tools.moegirl_refresh_smoke --root build/moegirl-refresh-v1/runtime-source-final --gold build/moegirl-refresh-v1/source-gold-body-before-retrieval.json --output build/moegirl-refresh-v1/source-only-no-model-smoke-final2
python -m pytest -q -rs --basetemp D:/SakuraTool/SakuraKnowledge/build/moegirl-refresh-v1/full-python-tests-final2 --junitxml=build/moegirl-refresh-v1/full-python-tests-final2.xml
python -m ruff check src tests tools
git diff --check
python -m tools.modular_semantic_validate --root build/moegirl-refresh-v1/runtime-all-linked --output build/moegirl-refresh-v1/allpack120-fixed-final2.json
```

All final commands exited0. Rust **70PASS** (64 library, six binary tests);
Python **1331PASS /19SKIP /55subtests**,100.97s. Skips are unavailable Windows
symlink privileges, not passing coverage. These full-suite checks used final2;
final3's main-only sender change adds a main-bin test PASS and **12 scoped Python
PASS**,6.30s (including two new actual single-query sender tests; overlapping cases
are not added to the full-suite count). Ruff/diffcheckPASS after final3.
Source-only **27/27PASS**, including twelve frozen body-text positives with
R@10=R@100=1.0, separate historical lookup/filtered-search CLI exits0, model sessions
and encoding0, naturalEOF/exit0/readerjoined. This is a small development suite.
Its gold SHA256 is `91ae360e88d174db9a15ec92da9182268fdbdaf6c1d56aeeb47a18448c65dbe2`;
no gold changes were made after querying.

Fresh fixed final-Core/final-source all-pack **120/120PASS**, unique cases and
source closure120, one shared query encoding per case, naturalEOF/exit0/readerjoined.
Cold startup14,168.9595ms is reported separately, not claimed under5 seconds.
Query wall p50982.2752ms /p953160.7134ms /max3835.8334ms; max response1,024,477
UTF-8 bytes including newline. Final candidate metrics use canonical
`tools.p4_retrieval_metrics.aggregate_cases`; multi-pack empty lexical/dense branch
diagnostic arrays are **N/A**, not measured zero-quality branches.
The saved baseline was not rerun and no ranking/model/fusion/RRF/gold tuning was done.

| Frozen subset | Cases | Final R@10 old→new | MRR@10 old→new | nDCG@10 old→new |
|---|---:|---|---|---|
| lexical | 30 | 1.0→1.0 | .977778→.956667 | .983333→.967259 |
| semantic | 40 | .975→.975 | .893750→.892500 | .914633→.913538 |
| crosslingual | 30 | .533333→.500000 | .258095→.196481 | .325644→.269933 |
| ambiguous/negative | 20 (10 positive) | .600000→.600000 | .370000→.370000 | .387755→.387755 |

Overall110 positive-target cases: R@10=.8181818182, MRR@10=.6726767677,
nDCG@10=.7048619520. Ten negatives have nonempty retrieval candidates, not
verified identities. Raw120 responses report `identity_status=not_asserted`,
no promoted identities/canonical/entity tag. **Quality remains FAIL** against the
original target, and crosslingual recall/ranking demonstrably regressed. Runtime
passing plus the small source suite does not establish equivalent/better or
independently generalized quality.

Local immutable receipts retain every previous failure: initial1MiB overflow
(1,342,138-byte response, followed by harness KeyError), junction-root startup
NOT_RUN, 27-completed all-pack timeout, source CLI timeout/partial suite, parallel
compiler memory errors, missing-dev-helper Python failures, and diagnostic
compile/fixture mistakes (including the initial single-sender fixture setup/schema
and record-size failures). Those attempts are not converted into PASS. Early
harness partial recall/stale prior-response byte counts are not quality/pipe
measurements; corrected harnesses report current-line scope and incomplete metrics.
Final raw streams, stderr, proof, old/new comparison and JUnit evidence remain under
`build/moegirl-refresh-v1/`; [the compact receipt index](moegirl-local-refresh-receipt.json)
binds them, not replaces them. New wheel/production embedding/ANN rebuild,
Pi Skill/Pool runtime, full human source-fact review, archive/upload and main merge
are **NOT_RUN**. Source rights remain **NOT_CLEARED**; source/model/runtime assets
are not committed/uploaded. Prior unrelated external-write status remains UNKNOWN
and was not investigated or cleaned.
