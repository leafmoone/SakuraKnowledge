# Benchmark v2 continuation development notes

User review: CHANGES_REQUIRED, PILOT_EVIDENCE=VALID; v1 ceiling defect.
Authorization permits versioned capped selection rule, read-only frozen rescore,
then BGE-M3 CPU feasibility only after quality PASS. No new gold, passage
embedding rebuild, selection retrieval, or RRF retuning. Downstream ANN/runtime/
FULL remain gated. This document is not an acceptance receipt.

## Preflight

- Clean dev HEAD and live origin/dev both
  ffff13b36b40919ce6c31cd49f703b2167c174bf.
- Live origin/main269e34eeeac920c29f2d684cfe37c93a95c73057 unchanged.
- Original quality receipt SHA256:
  05c44cfffab21235fd584c1fa289b976179a1b7ae92bfd06875b79c449ee2284.
- Selection-v2 independently computed PASS for B only, A crosslingual gates FAIL.
  All7 frozen input hashes matched; original receipt unchanged; no selection
  embedding/retrieval/fusion rerun. Contract commit48b2da3; native tool8030964.
- Native CPU run exit1, no retries: reused120PASS, operation p50 91.50125ms,
  p95 104.826985ms, peak2541527040bytes. Fresh74 completed then P4-075 timeout
  at15216.9015ms,45 NOT_RUN. Fresh attempted75 envelope p50 12719.4636ms,
  p95 13835.86375ms includes failure; not full qualification. Both modes2 warmups
  PASS separately. No automatic native retry or gate relaxation.
- One explicitly authorized ONNX feasibility is being planned, not executed.
  Frozen passage vectors exist; no query-vector artifact was found by query
  filename search. Original query code does not persist vectors, only rankings.
  User explicitly authorized a new separately labeled native120-query numerical
  reference, frozen before ONNX export; never historical pilot evidence. This is
  not a selection rerun or native CPU qualification retry.
- Predeclared configs/p4-onnx-representation-v2.json: one legacy FP32 opset17
  export, no fallback/quantization; dynamic batch/sequence, CPU provider8threads.
  Fixed128 uniformly spaced passage rows, batches1/8; numeric maxcomponent1e-4,
  mincosine.99999, normerror1e-5. Ordered typed top10/top100 exact equality and
  scoreerror1e-4 plus unchanged v2 quality gates before performance. Query/native
  reference and export helpers under development; neither has executed yet.

## Environment observations

Embedded python tool uses a different environment (GBK, tokenizers0.23.2, no
Torch metadata); it must not be mistaken for the command execution environment.
Actual bash `python -X utf8` verified:
C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/python.exe;
UTF8 mode1/stdout utf-8, torch2.11.0+cu128, transformers5.12.1,
tokenizers0.22.2. All model work must use this explicit command environment.
An optional ONNX dependency probe exited1 because find_spec alone did not imply
onnxruntime distribution metadata. This is not evidence of runtime feasibility;
no conversion or package installation attempted.
