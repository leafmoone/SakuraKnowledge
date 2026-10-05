# Current delivery status

## Local hardening: input inventory and semantic publication

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
