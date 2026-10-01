# ANN V1: execution failure, no qualification

ANN_RESULT=FAIL
P4_RESULT=NOT_READY
STOP_STATE=WAITING_REVIEW (after result push verification)

Contract/tool commit86ddf86d2b357fb5dc01d6326a3825ffeaed1759 was normally pushed
and remote equality verified before execution. Parent17 synthetic tests PASS,
Ruff PASS, actual input/hash/scoring metadata preflight PASS. These did not
exercise telemetry dependency or prove real integration.

One invocation exited1. Four HNSW indexes were constructed and saved locally,
but each build record failed at process RSS collection: ModuleNotFoundError:
No module named 'psutil'. The isolated environment contained usearch2.26.2,
numpy2.5.3 and required transitive tqdm4.70.1/colorama0.4.6; psutil was not
installed. Parent missed this optional telemetry dependency before execution.
No environment repair/retry or additional grid point attempted.

Python3.14.5 WindowsAMD64; usearch wheel cp314-cp314-win_amd64,
compiled extension SHA2569350ea33165f21340deed856416c9925fb0acd60a9a9466f25d09b0a6ff6e26c.
No global installs or production dependency changes.

All16 candidates marked FAIL/not retried. Actual formal query attempts0,
warmups0, approximation/hybrid/regression metrics NOT_RUN, selectedNONE.
IMPORTANT: receipt formal_failures defaults to120 for each unavailable candidate
(total1920). This is unavailable planned coverage, NOT1920 failed executed
queries. The preserved raw receipt must not be interpreted otherwise.

Local saved indexes: M16/Eadd128 and256 each223537008bytes;
M32/Eadd128 and256 each230269840bytes. Recorded construction elapsed seconds:
17.1382373,30.7613060,23.2649837,46.8899094 respectively. No candidate qualifies;
no ANN latency, recall or hardware acceleration value was collected. No claim
that USearch quality is insufficient: failure is harness dependency/telemetry.

Six frozen inputs and all additional scoring bindings before/after PASS.
Snapshot post-run21718736896bytes SHA256
61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9 unchanged.
Production src/rust unchanged. Old reports retained. No embedding generation,
ONNX export, quantization, gold/BM25/RRF change, main modification, Pool edits
or SakuraTool integration. Rust runtime NOT_STARTED; FULL attempts0/NOT_RUN.

ONNX residentCPU remains120/120PASS. Fresh122/122 setup/provenance timeouts
remain FAIL_SETUP_VALIDATION, product cold-start NOT_MEASURED.
Raw indexes and per-candidate details remain local-only build/p4/ann-v1.
Tracked evidence: ann-v1.json and ann-v1-command.json. Stop for review; no
automatic repair, backend substitution or repeat of the grid.
