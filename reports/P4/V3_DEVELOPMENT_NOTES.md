# P4 ONNX v3 continuation notes (not acceptance)

User authorizes existing FP32 ONNX only. Previous submission8c06f25a71002b0f34e764966f7ad3700e6cb00c
matched local clean dev and live remote; main269e34eeeac920c29f2d684cfe37c93a95c73057.
No re-export, native reference generation, passage rebuild, quantization, gold/RRF
changes, model reselection, or FULL execution permitted.

Preserved old files SHA256:
- onnx-agreement-v2.json:2bc897a04323e076ddca73a077208a46eaa09bcdb9f19ef7ffece3aa7fcc2c3d
- cpu-native-b-v2.json:c96851b7d683c36a81b78b9f422b6f79e02f774fae9cc805f5824f8e4c0ce193
- V2_STOP_REPORT.md:cc7392186a1cad1fc66e4456828e2144cc112c40fe8b6fb85d48463f2a32900f
- configs/p4-onnx-representation-v2.json:aeae2ef0ec3c2ec81c8d66cb8c711b63eee78097c8790774959addc8ca3694bc

V3 quality completed PASS in onnx-quality-v3-retry1.json:120 queries and128
passages at batches1/8 numeric PASS; all120 ranking cases overlap1.0 at10/20/100;
ordered equality119/120 and111/120 at10/100. All quality/regression gates PASS.
Initial invocation failed before inference because committed LF bytes differed
from working CRLF. Byte-preservation attribute and renormalized index fixed this;
original failure retained, no contract threshold changes. CPU harness tests59
passed together with quality tests; CPU harness has never executed real inference.
User requests fixed v3 publication/review before resident CPU; do not start it.
Ordered top100 remains diagnostic; product
gates use unchanged benchmark-v2 plus model-independent subset metric loss<=.01.
Fresh120 processes retain15s failures as STARTUP_DIAGNOSTIC, not resident blocker.
Standalone Rust CLI startup remains a later product acceptance gate.

Delegated quality worker reported running uv, recreating ignored .venv and then
removing its generated uv.lock. This was not authorized preservation behavior;
no claim of restoring previous environment contents. Parent tests ran actual
bash python -Xutf8 successfully; no further uv use. This side effect is disclosed
rather than treated as a clean environment-preservation result.

Known local GCC/G++ files exist. First bash PATH prefix C:/... failed command127
because colon conflicts with bash PATH parsing. Correct shell-local /c/msys64/
ucrt64/bin prefix successfully verified gcc.exe and g++.exe16.1.0. No installs
or global environment changes. Future Cargo must explicitly use repository-local
CARGO_TARGET_DIR and provided compiler paths, never inherited Pool target.
