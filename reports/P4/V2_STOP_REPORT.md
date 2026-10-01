# P4 benchmark-v2 / CPU representation gate STOP

P4_RESULT=NOT_READY
STOP_STATE=WAITING_REVIEW (effective after final normal dev push and SHA equality)

## Scope and preserved history

Base269e34eeeac920c29f2d684cfe37c93a95c73057; previous submission
ffff13b36b40919ce6c31cd49f703b2167c174bf. V1 config, contract and quality receipt
remain unchanged: FAIL/NONE preserved. V2 changes only version and capped
Recall10 target min(1,baseline+.10), model-independent. Seven input hashes and
original receipt05c44cfffab21235fd584c1fa289b976179a1b7ae92bfd06875b79c449ee2284
verified without embedding/retrieval/fusion rerun for selection.

V2 result: MODEL_A FAIL (crosslingual Recall10,MRR10,nDCG10); MODEL_B PASS.
QUALITY_SELECTED_MODEL=BAAI/bge-m3 revision5617a9f61b028005a4858fdac845db406aefb181.
Semantic BM25 .975 is near saturation, capped target1.0; crosslingual BM25 .1,
target.2. Frozen B dense crosslingual .8666667 versus hybrid .7333333 retained;
no RRF retuning. Future harder semantic challenge set must be exploratory and
cannot retroactively affect this selection. Gold120 and corpus50000 unchanged.

## Native CPU failure, no retries

Native CPU FP32 CLS/L2, empty prefixes,8 threads, actual torch CPU provider.
120 reused formal samples PASS, p50 operation91.50125ms,p95 104.826985ms,
peak RSS2541527040bytes. Two warmups per mode PASS and excluded.
Fresh74 completed; P4-075 process timed out15216.9015ms >15000ms. Remaining45
NOT_RUN. Formal retries0. Fresh attempted75 envelope p50 12719.4636ms,
p95 13835.86375ms includes failed process; missing query completion timing is
unknown, not fabricated. These partial fresh percentiles do not qualify120.
Full load times, encoder/dtype/threads/model bytes and raw process evidence:
`cpu-native-b-v2.json`. Native qualification FAIL, not permanent model rejection.

## Single authorized ONNX representation

User separately authorized new120-query native reference before conversion:
not historical pilot evidence, not native qualification retry or selection rerun.
No passage corpus vectors regenerated. New120x1024 FP32 reference PASS;
manifest fe334da082e67eaf3ff967c316ea2cde365a8a484f2c5c1c54a014993d706d73,
vectors b066abc933023b0980dc286f9c2c82e92eb3b9905406b5472176fb6e47c0817a.
Actual reference/code inputs frozen before/after, payload hashes verified.

Contract committed before conversion: one legacy torch.onnx export FP32,
opset17, eager attention, CPU, external data, no quantization or fallback.
Export attempt1 exit0; ONNX checker and independent inventory hash checks PASS.
Manifest b981d9c2b8f02691a200b9b88da8c778abcbaaaa3d49d0376f88590c89fbbb03.

Representation agreement exit1: all120 query numeric tests PASS;128 passage
samples at batch1 and8 all PASS (144 batch observations). Max-component1e-4,
min-cosine.99999,normerror1e-5 were frozen beforehand. At P4-002 ranking,
ordered typed top10 PASS but top100 FAIL. Matching-score check was not computed
because ordering differed; no score-error magnitude claim. First case ranking
PASS, subsequent118 NOT_RUN. Input hashes before/after PASS. No relaxed
near-tie tolerance or re-export after observing failure. This is a conservative
representation agreement failure, not evidence the v2 quality metrics degraded.
ONNX v2 quality implication check and performance NOT_RUN after agreement STOP.

## Gated remainder

No qualified production representation, no final model selection. ANN backend,
ANN recall10/20/100, Rust semantic runtime/retrieve pilot: NOT_RUN.
P2/P3 regression this round: NOT_RUN (no production semantic SHA); historical
approved baseline151/151 and55/55 retained, not original P3 oracle recovery.
Wrong-tag count this round: NOT_MEASURED, not claimed zero.
FULL build attempts0; pack/documents/chunks/bytes/hash and all FULL acceptance
and performance: NOT_RUN. Trusted census1295638 remains frozen, Moegirl/local-tag
semantic text coverage0. No raw supplementation, draft promotion or SQLite build.

## Final checks / limitations

Final pytest exit0:1024 passed,143 skipped,61 subtests passed (113.81s).
Final snapshot digest check exit0:21718736896 bytes, SHA256
61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9 unchanged;
WAL0/SHM32768/no journal.
Ruff exit0, diff check PASS, production src/rust diff empty against base.
Default Cargo fmt exit0; Cargo test exit101 because gcc.exe unavailable to GNU
Windows toolchain when building bundled SQLite. Chained clippy/release build
NOT_RUN after failure. Explicit CARGO_TARGET_DIR was repository-local
build/p4-v2-rust-target, not inherited SakuraPool directory.
Semantic matrix NOT_RUN: gate blocked, semantic feature not implemented.
No skipped test is integration evidence. No package installs or global changes.

Model/ONNX files, reference and index vectors remain local, not committed.
Published receipts bind local artifacts; they do not independently distribute
all reproduction inputs. Wheel NOT_BUILT. Pi Skill/Pool runtime integration and
full human source-fact review NOT_RUN. No main changes or merge, no SakuraPool
edits or Sakuratool launch, no external P3 preservation access.
