# Current delivery status

## Bangumi storage trial (independent, not a production replacement)

Baseline `4583fe94e8eba40b31a062412eef76b70d0bb86a`. New experimental tool/fixtures
and actual frozen sample only; production schema/runtime/Core/source packs/model/
ANN and the prior Moegirl delivery/qualityFAIL below remain unchanged.
[Scope/results](bangumi-storage-experiment.md) and
[receipt index](bangumi-storage-experiment-receipt.json).

Read-only sealed Bangumi snapshot:9081126912bytes, declared SHA
`0802c08392ef9971d54a09ef96e59b2d0259e5ed3acee36cb1432f7954a24e0a`;
manifest/stat verified,9GBhash/mother/raw Archive/ANN/model not reread. Covering
index pass7.8009127s confirms2712814 keys; frozen stratified/body-length/alias sample
plus512 native-link seeks/endpoints gives1741 entries/docs/evidence,2132 aliases,
512links. Full FTS metadata-only pass1014366rows11.7508503s preserves all selected
occurrences1562; actual physical IO bytes UNKNOWN. No whole-source payload/dbstat
scan or全量 compact output. Sourcepack lacks unresolved_records; actual sample
status/source records are unchanged, not invented to provide negative coverage.

Corrected premise: sealed runtime export projects Bangumi evidence/document raw
payloads; it does not preserve full raw summary/infobox redundantly. All1741 sample
evidence raw objects are{}, cross-payload body substitution count0 (fixture-only
support, not actual gain). CAS stores exact UTF8body/payload once with SHA/codec/
length metadata; zlib6 only if smaller. FTS searchable text/config/IDs/multiplicity
remain persisted;1562 exact uniquely closed doc search strings reference FTS,
179 non-FTS episode search strings use CAS. NULL/empty/unknown JSON are preserved.

Same-sample whole-file bytes (all original indices, FTS and CAS/recipe overhead):
**9179136 baseline →8687616 CAS-only(-5.354752%) →8118272 CAS+zlib(-11.557340%)**.
Both variants exact typed/UTF8 roundtrip7873 ordinary rows and1562FTSoccurrences;
48 same-sample token queries preserve BM25 scores/key/doc ordering/fulltext/citations.
This is not a full-library ranking/model/identity validation. Selection is strongly
biased by long/short/empty strata, non-FTS episode underweight and link closure;
no full9GB/whole-pack saving is extrapolated or claimed.

Actual uncached decoded-content Python prototype costs more: warm full-row median
21.4224→191.5297ms;48queries/262hits+full materialization4.35505→23.84025ms.
First connection/pass is not OS-cold cache. Not attributable to zlib alone; includes
ref lookup/decoding/hash/schema lookup. Experimental format is NOT production Core
compatible and is not recommended for adoption from this trial. Full compact DB,
newCore/Rustbuild/all120/embeddings/ANN/Pi/Pool/migration/archive/upload NOT_RUN.
Rights NOT_CLEARED; sample bodies/selection/assets not committed.

Actual final sample output `build/bangumi-compact-v1/sample-v2/` PASS. Initial
sample-v1 remains FAIL (optional dbstat absent after successful validation).
SQLite3.50.4 dbstat explicitly NOT_AVAILABLE, not fabricated per-table pages.
New19fixturesPASS0.59s; full **1352PASS/19Win1314 symlinkSKIP/55subtests105.55s**
(scoped tests included, not added). Existing owned Rust dev binary/helper used,
no Rust code/compiler changes. Ruff/diffcheckPASS, repository-contained workspace/
temp, unrelated untracked files and previous failure receipts preserved.

## Actual local Moegirl refresh candidate

Baseline `d572b03e6dbd6690498dde95b848c74f7ac01060`, ordinary `dev` delivery.
Actual readonly local source audit/freeze and source-targeted rebuild, not a live
crawl or merely a rerun of stale derivatives. Current delivery:

- `build/moegirl-refresh-v1/SakuraKnowledge-pack-moegirl-final2`: **836572395 bytes**,
  snapshot SHA256 `8341eb4a7e0d78b1ea946d2a0f94ad5e32f835ecd0f1e9368e696599253a82b8`.
- `build/moegirl-refresh-v1/SakuraKnowledge-core-win-x64-final3`: **79210105 bytes**,
  matching **2097152-byte UTF-8+newline** semantic budget, shared single/resident
  sender (including config single retrieve), five-second query deadline unchanged.
- Final normalized bundle/proofs/gold/raw streams remain adjacent, not runtime
  prerequisites. [Refresh report](moegirl-local-refresh.md) gives exact binaries,
  manifests/commands/exit codes and [receipt bindings](moegirl-local-refresh-receipt.json).

All **47589 exact partial-template documents** under historical source-backed typed
identities independently match frozen text/hashes/locators. 44862 indexed titles
have templates;617 empty lists mean no usable captured template,494 frozen API
missing and25 user-skipped are not live page facts. char_index45998 has exact
raw/outcome coverage. Current attr411020/subject50223 direct-tree category paths
are stored raw observations, not new typed relations, CLI filters or regenerated
`source_fields`; CLI alias/CV/gender/processed fields remain historical-cut. No
full articles, authenticated successful page revisions or complete upstream
flattener equivalence are claimed.485/288 old-processed/current-raw gaps remain.

Final old/new typed keys95695, aliases129455 and candidate business links97270
are preserved; nine unresolved mapping inputs remain exactly accounted, no extra
six stubs/nine candidate links, no verified mappings. Stored numeric IDs/fallback
link evidence refs are reprojected with original refs in payload, not byte-equality
claims. Tag DB physical backups differ but all14 typed logical row multisets match,
including193494 duplicated tag_evidence rows; keep the current provenance tag pack,
66979 trusted texts, without rebuild or tag-proof/identity changes.

Real timeout diagnostics isolated a tag proof-FTS TEMP BM25 sort and, separately,
Moegirl basic filtered-search TEMP sort. Minimal readonly rank-stream fixes preserve
eligibility, complete boundary ties/multiplicity, original distinct-entity vs
100-document depth and basic10000-row cap (exact old-query fallback under the same
deadline). No new index, candidate pruning, document/evidence clipping, fusion/RRF,
model/ANN, ranking or gold tuning. Optional stderr traces add no stdout fields.

Final checks: **Rust70PASS**, **Python1331PASS/19 Windows symlink SKIP/55subtests**,
100.97s, Ruff/diffcheckPASS. Final3 changes only single-query main sender after the
full final2 matrix: main-bin testPASS plus12 scoped PythonPASS6.30s, not summed
as extra full-suite passes. Resident pilot bytes unchanged. Source-only27/27PASS,
12 frozen body-positive R@10=R@100=1.0, model/encoding0, lookup/filtered-search
CLI exit0, EOF0/readerjoined. This is a small development suite, not general quality.

Fresh final fixed **all-pack120/120 runtimePASS** with source closure120,
one shared encoding/request, EOF0/readerjoined. Cold startup14168.9595ms separate;
query p50982.2752/p953160.7134/max3835.8334ms, max response1024477bytes.
**QUALITY FAIL persists and crosslingual regresses**: final-candidate R@10 lexical
1.0, semantic.975, crosslingual.5 (saved baseline.533333), mixed positive10/20.6.
Lexical/semantic/crosslingual MRR=.956667/.8925/.196481; nDCG=.967259/.913538/.269933.
Empty per-branch arrays are N/A, not measured zero recalls. Ten negatives return
candidates but raw120 responses assert no identity promotion/canonical/entity tag.
No saved-baseline rerun or tuning to mask the drop. This candidate is not proof of
meeting the original quality target or independently generalized adoption.

Earlier1MiB overflow, junction startup NOT_RUN,27-completed allpack timeout,
source CLI timeout/partial recall-harness error, compiler-memory and missing-helper
Python attempts remain as failures/NOT_RUN; no failed receipts replaced by claims.
Inputs/mother/oldpack/model/originalmapping/FP32/ANN preserved. Rights NOT_CLEARED;
large assets not committed/uploaded. New wheel/production embeddings, Pi Skill/Pool
runtime, full human source-fact review, archive/upload and main merge NOT_RUN.
Unrelated external-write status UNKNOWN remains uninvestigated. All new work,
freezes/testtemp/compiler targets are repository-contained; unrelated working-tree
files preserved. New Core is required; old1MiB Core plus pack swap is insufficient.

## Historical: local hardening of input inventory and semantic publication

Baseline46e63856ca58d47fa0938b400096f51ab678730b. Only Python adapter freeze,
normalized distribution, semantic workspace/publication, fixtures/docs changed.
No Rust/ranking/fusion/RRF/model contract/tag proof/identity/resolve changes.
No mother/oldpack/ANN/model writes, large export/embedding/download or120 rerun.

### A: complete declared input boundary

SourceAdapter input_inventory explicitly plans all dependent regular files.
File and directory roots work; no default recursive scan. Tools reject unsafe,
duplicate, symlink/reparse/escaping paths, recompute actual sizes/SHA256 before
metadata→inspect→complete records consume, then replan/hash all files afterward.
Same-size mutation, deletion, newly declared file or change during any read phase
fails with no normalized manifest. Portable inventory has relative POSIX paths,
no absolute paths/mtime. Legacy single-file plans/bundles remain compatible.
A third-party adapter privately reading undeclared files is outside reproducibility
proof; no sandbox claim. Official multi adapter read wrapper observed exact declared
four-file set. Build-normalized checks inventory/count/digest/ownership offline;
raw inputs were actually deleted before successful fixture build. Each source
stores complete inventory with explicit shared-all-inputs scope.

Actual example raw_multi input bindings total809bytes: characters231/metadata223/
relations112/subjects243; six records1986bytes. build/hardening-multi-bundle and
build/hardening-multi-pack actual build/inspect/validatePASS. Pack156772bytes:
manifest.json, knowledge.sqlite, lexical-membership.sqlite only. Four entries,
four documents (backed identity with one generated text), fourFTS, two links with
verified/candidate distinction preserved. Original builder receipts are moved to
adjacent import-input workspace, not deleted or bundled as runtime data.
Core build/hardening-portable-root no model: packs/lookup/search/related/retrieve
all exit0, retrieve9919bytes2.6266ms query/process encoding0. Single-file demo
remains covered by existing generic pipeline tests.

### B: workspace and manifest-last publication

--workspace defaults OUTPUT.semantic-work, create-new; --resume-workspace explicit.
Bound inputs: actual pack manifest/artifacts, model manifest/tokenizer, fixed build
parameters and synthetic-vs-production mode. Verified mapping/vectors/I8 size/hash,
FP32shape/norm and native index plus full mapping/document/identity closure before
publication. New runtime staging validates independently, then same-volume directory
rename publishes complete manifest-last output. Existing outputs and nested/colliding
input/output/workspace paths fail before encoding. Failures preserve workspace path;
success cleanup defaults, --keep-workspace explicit. Original inputs untouched.

Actual synthetic4row native I8 completed before injected publication failure;
workspace retained vectors.npy. Resume mockencoder calls **0**, I8 bytes identical,
final exact file set manifest.json/knowledge.sqlite/lexical-membership.sqlite/
mapping.sqlite/vectors.i8.usearch, no NPY. Changed model bytes reject before encode;
fresh existing workspace/old output reject. Default successful cleanup also tested.
New distribution_closed_set recursively rejects extra NPY/hidden/temp/symlink files;
legacy old4 unflagged v1 packs are not forced to rewrite. Runtime inspect excludes
workspace size; prepare reports workspace_bytes separately. Native helpers are explicit.

### Verification and limits

Final full Python **1309PASS/19Win1314 symlink skips/55subtests**,64.20s,
SKNOW_RS_TEST_BIN final binary, runtime DLLPATH and D temp. Related subset54PASS/
1skip,2.61s (not added to full total). Rust62PASS0.64s with explicit in-repository
target; Ruff/diffcheckPASS. Subsequent receipt relocation only retested scoped checks.
Existing four-pack discovery/source filters/Dan+Moe structured/current tag FTS pass.
Dan semantic single200095bytes217.3563ms and Dan+Bangumi40113bytes335.535ms,
each shared query encoding1. Core binaries and old pack manifests/assets unchanged.

Production new-source BGE embedding NOT_RUN. Only tiny encoder/tokenizer mocked,
actual native mapping/I8/inspect exercised; not new semantic quality validation.
No120 (retrieval unchanged), Pi/Pool/compression/upload/main merge/next real source.
Historical runtime120PASS/qualityFAIL, rightsNOT_CLEARED and RSS unmeasured persist.
Prior external-target attempt's actual write remains UNKNOWN; this stage neither
accessed/investigated/cleaned that path. All current outputs/tests/targets repository
contained. Contract/docs: source-pack-contract.md, adding-a-source.md, example README.
