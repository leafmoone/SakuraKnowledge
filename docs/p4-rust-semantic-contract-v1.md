# P4 Rust semantic pilot contract v1

Base19de7a8891be151345576b50658cbca8643a9d75; main/P3 base
269e34eeeac920c29f2d684cfe37c93a95c73057. Initial src/rust diff empty.
Snapshot21718736896bytes SHA256
61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9 verified.

## Dependency gates before runtime implementation

Rust1.98.1/cargo1.98.1 observed; minimum1.88. No upgrades.
Optional exact ort2.0.0-rc.12 (default-features=false,std,ndarray,load-dynamic,
api-24), tokenizers0.22.2, usearch2.26.2. semantic feature only; default binary
must remain independent of ORT/model/index/tokenizer files. No download-binaries.
Explicit local DLL, no silent provider/runtime search or fallback:
C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/Lib/site-packages/onnxruntime/capi/onnxruntime.dll
Python onnxruntime1.24.1,15355936bytes,SHA256
4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847.
Rust must confirm ORT1.24.x CPUExecutionProvider,threads8.

Probe only before retrieve: frozen tokenizer load and120 exact ID/mask equality,
existing ONNX external-data model load, direct Python USearch index load52664
rows/dim1024/cos/ef128. No re-export/index rebuild. Authorized new Python token
reference is tokenization only, not embedding. Mismatch/incompatibility STOP.

## Runtime contract if gates pass

Long-lived SemanticEngine owns tokenizer/session/index/readonly mapping. Activation
performs full artifact hashes; open checks small manifest/sizes/identity/contracts.
No per-query GB hashing or reload. FP32 CLS/L2 empty prefix; query IDs/mask ->ORT
->normalized1024 ->USearch512 ->typed EntryKey first-hit dedup100.
Pilot manifest lexical_mode=pilot_sidecar, frozen lexical SQLite
c664b3c81181942d202321fe81448d2cfc4e00ab658b864732e758ce7a1829b3;
base FULL snapshot remains read-only. BGE revision5617a9f61b028005a4858fdac845db406aefb181,
ANN M16/Eadd256/ef128/cos/f32. Manifest binds model/tensors/tokenizer/DLL/index/
mapping/corpus/lexical hashes and snapshot identity. Local-only pack.

retrieve BASE_DB PACK QUERY --limit N [--kind K] [--namespace NS] under semantic
feature only. Fixed pins/BM25depth100/ANN100/RRF60/source-key tie rule, evidence
bundle with typed identities, ranks, scores, chunks/documents, source/evidence/
citations/warnings and contract/snapshot/pack versions. Relevance never promotes
identity/entity_tag/canonical tags; resolve-tag remains identity authority.
Existing lookup/search/related/ask/resolve-tag JSON unchanged.

## Acceptance

120 queries0retry; branch macro overlaps10/20/100 >=.98/.98/.95 and minima
>=.80/.80/.90 versus selected Python ANN; no ordered equality blocker.
Full hybrid benchmark-v2 gates and all subsets Recall10/MRR10/nDCG10 deltas
>=-.01 versus approved ANN Hybrid; identity errors0. Metrics5/10/20 and all
subsets with null no-denominator values. Resident2warmups+120formal,0retry,
each<=5s,totalp95<=1000ms. Tokenize/ORT/ANN/BM25/fusion-evidence/total separate.
Open/load timings separate. CLI15s diagnostic not resident percentile; no launch
full-hash workload. Fresh previous failures were setup/provenance, not measured
product cold start.

Fixed runtime SHA requires new-approved P4 baseline P2 151/P3 55,wrong0,
timeouts0,retries0 (not recovered original oracle). Default+semantic test/fmt/
clippy/release matrices, Python tests/ruff/diff; skips disclosed. Explicit local
GCC16.1/G++16.1 and repository-local Cargo target, no Pool/global edits.
Stop normal dev push/main unchanged/review even if allPASS. FULL attempts0.
