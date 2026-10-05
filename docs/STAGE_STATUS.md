# Current delivery status

## Modular offline Windows x64 local candidate

Baseline: `e5a2d6e8a776425afffa20c199dc6aeadafceecd`, ordinary `dev` delivery.
Six independently copyable components live in `build/modular-components/`: Core,
one shared BGE-M3 model and Danbooru, Bangumi, Moegirl, tag-wiki packs. No large
assets are uploaded. Mother snapshot, FP32 vectors and old monolithic I8 package
are preserved. This audited frozen cut is **not a live upstream refresh**.

**Engineering validation passed; quality is degraded, not quality PASS.** Fixed
source-level equal RRF60 with full typed-key ties does not reproduce monolithic
ranking. Do not treat this candidate as a lossless replacement.

### Exact local component bytes

Includes actual runtime files and licenses, excludes build-only `positions.u64le`
(which assembly does not copy). No compression/archive/download was performed.

| Component | Bytes |
|---|---:|
| Core | 60,465,441 |
| Shared BGE-M3 | 2,284,443,838 |
| Danbooru | 1,894,324,211 |
| Bangumi | 10,723,650,815 |
| Moegirl | 181,699,717 |
| tag-wiki | 1,718,178,889 |

| Combination | Bytes |
|---|---:|
| Core only | 60,465,441 |
| Core + Danbooru (structured, no model) | 1,954,789,652 |
| Core + Danbooru + model | 4,239,233,490 |
| Core + Bangumi + model | 13,068,560,094 |
| Core + Moegirl | 242,165,158 |
| Core + tag-wiki | 1,778,644,330 |
| Core + all packs + model | 16,862,762,911 |

The old monolithic package remains 16,565,060,877 bytes: all components together
are not a size reduction; independently selected combinations are the benefit.

### Runtime and structured evidence

Actual Unicode/space-path installations A/B/C (core-only, Moegirl/tag without
model), D/E/F/G (Dan/Bangumi/both/all with model) were opened and queried. Source
selection, comma lists/deduplication, unknown-source errors and remove/restart
were exercised. Final PowerShell launcher sync was checked in external G with
`packs` and `lookup blue_hair --source tag-wiki --limit 1` (exit 0, only tag-wiki
participates). Root config uses relative directories; no development path links
are needed. Query-time builds/downloads are prohibited.

`build/modular-structured-final/summary.json`: **134/151 strict normalized business
JSON equal**; 16 search differences independently checked against actual pack
DB rows (`build/modular-search-business-checks.json`): all candidates have trusted
source/typed-entry proof, all common-key payloads equal except score, differences
are ranking/top-k membership/local FTS score. E18 differs only in physical SQLite
page/freelist counts. Do not call this 151 JSON-identical.

Actual new I8 graphs: Danbooru 302,482 positions, 296.3635394s; Bangumi 1,064,038
positions, 1830.2298934s. Native save/view/reload local keys validated, original
readonly FP32 NPY reused, no re-embedding/full new NPY. Local mapping retains
original position for diagnostics; identity is `(kind, namespace, value)`, never
cross-DB numeric IDs. Shared model revision
`5617a9f61b028005a4858fdac845db406aefb181`; FP32 encoder distinct from I8 ANN.

`python -m tools.modular_semantic_validate --root 'D:/Sakura 模块化 测试/Core 可选 来源 G' --output build/modular-all120-final`
completed exit 0: **120/120 engineering checks**, independent actual source,
evidence, typed-document closure, one encoding each (cumulative 120), one model
session, 5-second request-to-complete-line bound and 1 MiB UTF-8 response ceiling.
EOF shutdown exit 0, reader joined, no active termination. Startup 11,937.9312ms;
E2E p50/p95/max 740.47995/2232.8282/2571.4677ms; bytes p95/max 495,869/752,147.
Validator time is separately recorded, total 4.8129s, not retrieval performance.
First attempt was interrupted after four saved responses when independent proof
SQL caused full scans; `modular-all120-first` is **partial, not 120 PASS**. EXPLAIN
showed three full-table scans per proof. PK/typed-entry indexed checks fixed it
without altering asset indexes; saved-four replay 0.110066s and wrong evidence
rejected. Final 120 is a fresh complete run, not concatenated partials.

### Quality versus saved monolithic I8

| Gold subset | R10 old → modular | MRR10 old → modular | nDCG10 old → modular |
|---|---|---|---|
| lexical | 1 → 1 | .97778 → .97333 | .98333 → .97956 |
| semantic | .975 → .975 | .90833 → .61458 | .92559 → .70667 |
| crosslingual | .53333 → .56667 | .29976 → .26306 | .35667 → .33587 |

**Semantic first-result effectiveness drops materially.** Saved response diagnosis
(`build/modular-semantic-rank-diagnostic.json`) found 26 changed semantic MRR
cases, zero additional semantic R10 losses. Equal per-pack rank 1 shares score
1/61; typed ties/interleaving move many original rank-1 results to global rank 2.
No gold-tuned weights or model changes were made. This is a fixed-fusion ranking
cost, not evidence that quality is unchanged. Unrecorded local hybrid ranks are
NOT_RECORDED; do not infer actual local rank by counting global candidates.
Source-only selection can avoid irrelevant packs, but no source-only 120 quality
claim is made. Crosslingual gold quality remains limited.

`build/modular-source-perf.json`: eight resident queries each, exit 0, one session,
one encoding per request (cumulative 8). Backend p50/p95/max Danbooru
264.2697/1504.0129/1504.0129ms; Bangumi 213.7028/300.4936/300.4936ms. These are
finite eight-query observations, not all120 distributions or independent E2E.
RSS is **NOT_MEASURED**. First D/E/F/G single-query smokes are not p50/p95 evidence.

### Checks and limitations

Final full Python suite with `SKNOW_RS_TEST_BIN` pointing to final release,
external G/bin DLL PATH and process-local D temporary directories:
**1227 passed, 18 skipped (Windows symlink privilege WinError 1314), 55 subtests
passed, 63.20s, exit 0**. Receipts: `build/modular-pytest-integration-dll.log`.
Earlier 150 skips included 132 missing Rust-integration environment cases;
setting only the binary then failed 127 native loads (3221225781), corrected by
explicit DLL PATH. Earlier default C temp failed 21 disk-reservation checks;
these failures remain evidence, not interpreted PASS. Final D-temp run resolves
those prerequisites. Full `python -m ruff check src tests tools` and
`git diff --check` passed. Rust semantic/library suite: 42 passed; release build
passed. Launcher one-item-array concatenation bug was fixed and actual tests
passed. Final 120 uses the same retrieval binaries/DB/model/index as delivery;
subsequent changes are launcher/doc/validator checks, not retrieval tuning.

Moegirl and tag-wiki are **exact/alias lexical only**, trusted FTS documents = 0.
Tag-wiki keeps 601,512 `no_reference` and 73,377 `unverified_draft` documents out
of trusted FTS. Local tags are not native `danbooru.tag` identities. Drafts were
not upgraded and cross-source candidates were not silently verified. Source IDs
and counts: `docs/source-groups.json`.

Public redistribution rights **NOT_CLEARED**. Pi/Pool integration, human source
fact review, live refresh, wheel build and RSS are NOT_RUN/NOT_MEASURED. No GPU,
services or query-time downloads. User-requested tag-wiki upstream status
investigation is a **separate post-delivery readonly task**, not a trust change
in this candidate. See README for build/finalize/assembly/copy/query commands.
