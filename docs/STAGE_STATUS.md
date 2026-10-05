# Current delivery status

## Local pack assembly safety fix

Baseline `492f36d212efca7b654c48fd8b61fcf4a4b9792d`. Assembly now preflights
all required resources/destination collisions before expensive preparation, copies supplied
I8 without consuming its source (cross-volume safe), uses exclusive owned staging and
validates closed files/content bindings/membership before publication. Inventory publishes
before manifest; manifest is last atomic create-new marker. Copy/publication failure rolls
back only newly owned files/stage, preserving reusable DB/mapping and source I8. Existing
valid package refused; no overwrite/auto rebuild on retry. Same-volume hard-link support
is required for create-new publication. Validation is strict Python file/manifest checking,
not a new native model/index open. Tiny assembly/export tests24PASS in1.29s; no full prepare,
export, ANN build, content scan, parameters or120 rerun this round; current16.57GB pack unchanged.

Reusable commands after explicit native build (paths examples; NEW contains completed DB/mapping):

```powershell
python -m tools.portable_pack --repository . --output NEW --index EXISTING_I8.usearch --native-root C:/msys64/ucrt64
# Only for genuinely new preparation; refuses existing output/index before heavy work:
python -m tools.portable_pack --prepare --repository . --output NEW_EXCLUSIVE --index D:/NEW_I8.usearch --native-root C:/msys64/ucrt64
```

G42 one new directed serial pair using same current release binary and frozen input:
query `初音未来`, kind character, namespace moegirl.character, exact true. Mother exit0,
stdout800/stderr0, wall624.06999996ms; runtime exit0, stdout800/stderr0,
wall280.03639996ms. Complete parsed JSON equal: entity_found_tag_unmapped.
Exclusive evidence `build/portable-g42-492f36d/` retains each stdout/stderr and command JSON.
This successful new pair does not reconstruct the unretained historical timeout side,
nor establish a general speedup; no query/runtime contract changed.

## Portable Windows x64 CPU: usable I8 candidate, QUALITY_FAIL retained

Baseline `2e80df373f3ef036dff2c7dac83069922b69405e`. Local assembled directory:
`D:/Sakura 发行/知识 CPU 可移动 包` (not uploaded, no ZIP/installer). Repo default remains
FP32 ef2048; portable pack explicitly uses I8 and documents additional crosslingual loss.
Mother DB, original mapping, FP32 NPY/index and valid earlier packs remain unchanged.

## Runtime assets

| Asset | Original bytes | Runtime bytes |
| --- | ---: | ---: |
| knowledge.sqlite | 21718736896 | 12248907776 |
| chunks.sqlite | 3675488256 | 350711808 |
| ANN | 5800312336 FP32 | 1602256816 I8 |

DB exported readonly into a new exclusive output: all business IDs/rows, source metadata,
links/payload strings and full FTS shadow documents/rowids/token/BM25 statistics preserved.
Build-only occurrences/source_counts/unresolved tables omitted. Document payload retains
search_text_truncated, evidence retains public raw observations; original source bytes stay
in mother DB. Full public structured output comparison:150/151 exact JSON/exit equality,
inspect differs only expected page_count/free_count (mother5302426/726290 vs runtime2990456/0),
business snapshot identity equal. Full55 initial53equal plus2transient errors, targeted2
subsequently exact; later full55 had54equal/G42 timing mismatch; **not represented as
one uninterrupted55PASS**. This is an explicit timing limitation, not an ignored gate.
Mapping retains position/chunk/document/typed entry/source/evidence columns only; all
1366520 rows compared to original metadata runtime fields exactly. No projection text/rowjson.
Membership rowids reused because FTS IDs preserved; metadata re-bound to actual new DB digest.

I8 real USearch ScalarKind::I8 with Cos:1024 dimensions/M16/add256/search2048,
1366520 float32 input vectors through native normalized127 conversion, original position keys.
Tiny float add/search/save/metadata/view numeric test passed (axis quant127, Cos0/1).
Full build2050.7951s, saved actual I8 metadata/count/view verified. New graph changes are
**not solely quantization error**. Original FP32 index/NPY never rewritten or distributed.
First full build completed insertion but failed Unicode save; fixed native Windows UTF-8
wide save/read/metadata/CreateFileW; tiny Chinese/spaces+rename/view passes before rebuild.
Existing large-file offset fixes retained. DB first VACUUM failed C temp space; fixed temp
location to package volume and complete re-export succeeded. Initial D free318733864960B,
C free2261397504B; peak planned<60GB disk, serial heavy operations.

## Actual acceptance

Final `build/portable-i8-source-evaluation.json`, `.jsonl`, `.stderr`:
fresh entire120 with independent arithmetic and SQL source/document/evidence/typed closure
against package DB **120PASS**, zero promoted identities, natural EOF/reader joined.
Responses bounded1MiB including UTF-8 newline; resident p50/p95/max
403.55395/997.118/1165.6457ms. Startup13490.5098ms includes full content hash guards.
Previous initial I8 run lacked SQL closure and raw responses; retained only as limited
shape/arithmetic evidence, superseded by final complete validation (no retrieval change).

| Final R10/MRR/nDCG | Saved FP32 ef2048 | Portable I8 |
| --- | --- | --- |
| lexical30 |1/.97777778/.98333333 |1/.97777778/.98333333 |
| semantic40 |.975/.90625/.92385989 |.975/.90833333/.92559298 |
| crosslingual30 |.6/.32009259/.38791388 |.53333333/.29976190/.35666688 |
| ambiguous positive10 |.65/.42928571/.43072693 |.65/.41444444/.41914614 |

QUALITY_FAIL semantic R10 .975<1; other frozen gates PASS. I8 adds crosslingual loss2/30
relative to saved FP32: P4-083/P4-095 Recall1→0; P4-074/091/100 MRR regressed.
Complete lexical hit objects/trusted pins identical120/120 saved FP32 vs new runtime.
Disclosure is not hidden by lexical-baseline gate PASS. Negative nonempty
rate1.0 remains a gap. Development/regression set, not independent generalization.
No model/new sources/RAG/Pi/Pool/global config. Fresh machine validation NOT_RUN; same-machine
external Unicode directory with child PATH only Windows system dirs successfully loaded all
resources. RSS NOT_MEASURED. Total package including model/DLL/licenses/inventory16565060877bytes;
model2284412601, bin57807180, licenses81376bytes; same-volume directory rename followed
launcher basic+single Japanese/Chinese/quotes and resident2queries+natural EOF exit0.
Child PATH only Windows system dirs; all required resources came from moved package. Basic/single/resident keep shared1MiB sender and strict parser.

## Checks and maintenance

Final explicit current-release SKNOW_RS_TEST_BIN + UTF8/UCRT64: **1200PASS,
18SKIP,55subtestsPASS in65.76s**. All18 skips are actual Windows symlink privilege
failures (WinError1314), not missing binary/schema bypass. Earlier missing-binary150skip
run superseded; targeted native integration91PASS4.88s also retained.
Rust35libraryPASS (0.42s); actual I8 Unicode tinyPASS. Ruff/diff PASS.
Removed named obsolete transport experiment CLI/config/clone tests and3old transport receipts,
P3/P4 old plans, dead source-list constant/preflight recovery and obsolete f99 review doc;
necessary f99 product rules merged into runtime-contract before deletion.
retained gold, full references, mature source/export/protocol/performance tests and analysis
helpers used for comparison. AGENTS updated to current asset/publication boundaries.

## Reproduce

Build (existing native toolchain required, queries never build/download):

```powershell
$env:PATH='C:/msys64/ucrt64/bin;'+$env:PATH
$env:CARGO_TARGET_DIR='build/p4-usearch-native-fix/rust-target'
cargo build --release --manifest-path rust/Cargo.toml --features semantic --bin sknow-rs --bin semantic_pilot --example build_i8
python -m tools.portable_export export-db --source build/p3-full-authorized-retry1/knowledge.sqlite --output NEW/knowledge.sqlite
python -m tools.portable_export export-mapping --source build/p4-full-semantic-v1-retry1/chunks.sqlite --output NEW/chunks.sqlite
./build/p4-usearch-native-fix/rust-target/release/examples/build_i8.exe build/p4-full-semantic-v1-retry1/vectors.npy NEW_INDEX.usearch
python -m tools.portable_pack --output NEW --index NEW_INDEX.usearch
# Or one create-new entry after building the native programs/example:
python -m tools.portable_pack --prepare --output NEW_EXCLUSIVE --index NEW_I8.usearch
```

NEW must be exclusive directory with sufficient local temp space. Pack includes native
binaries/non-system DLL closure, new DB/I8/mapping/membership, model ONNX/external weights/
tokenizer, local config and licenses; no Python/MSYS/toolchain/cache/original inputs.
From package: `powershell -NoProfile -File ./sknow.ps1 lookup hatsune_miku`,
`powershell -NoProfile -File ./sknow.ps1 retrieve 'blue hair' --limit 5`, or
`powershell -NoProfile -File ./sknow.ps1 serve` with JSONL stdin then EOF.
