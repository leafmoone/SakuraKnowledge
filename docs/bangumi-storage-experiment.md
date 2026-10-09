# Bangumi content-reference / lossless compression experiment

## Scope and conclusion

Baseline commit `4583fe94e8eba40b31a062412eef76b70d0bb86a` on `dev`.
This is an **independent sample experiment**, not a production format migration.
No source/old pack/Core/schema/runtime/ANN/model was modified. Experimental SQLite
files are **not loadable by the existing production Core**. Large source/sample
assets stay local; source rights remain NOT_CLEARED.

The proposed direction works losslessly on the frozen sample, but its measured
benefit is modest and comes with a materialization cost:

| Same sample / same original indices and searchable FTS corpus | Actual whole SQLite bytes | Reduction from baseline |
|---|---:|---:|
| `sample-v2/baseline.sqlite` | 9,179,136 | — |
| `sample-v2/cas-identity.sqlite` (references/dedup, no compression) | 8,687,616 | 491,520 bytes / 5.354752% |
| `sample-v2/cas-zlib.sqlite` (references + smaller-only zlib level6) | 8,118,272 | 1,060,864 bytes / 11.557340% |

These sizes include tables, FTS text/index, original secondary indices, CAS blobs,
references, recipes, their indices and SQLite page overhead; no external payload
file is omitted. They are **not** an estimate of savings in the full9GB snapshot
or10.72GB source pack. No full compact snapshot was built and no production
adoption is recommended from this one biased sample/uncached Python prototype.

## Corrected premise: what the sealed Bangumi pack actually stores

Input is the sealed read-only source snapshot at
`build/moegirl-refresh-v1/runtime-all-linked/packs/bangumi/knowledge.sqlite`.
Manifest declares9,081,126,912 bytes and SHA256
`0802c08392ef9971d54a09ef96e59b2d0259e5ed3acee36cb1432f7954a24e0a`.
Current manifest binding and file size/stat were checked, but the9GB file was **not
rehash-read**. Page size4096, page count2217072, freelist383 are lightweight PRAGMA
observations, not a full table/page breakdown. Actual physical disk IO bytes are
UNKNOWN. No21GB mother, raw Archive files, ANN/mapping/model or upstream writer was
read/executed for this experiment.

One covering typed-key index pass observed2,712,814 entities:
subject690068, character221960, person102338 and episode1698448. The source pack's
trustedFTS declaration is1,014,366 rows. Its full source payload/table scan and
whole-database `dbstat` analysis are NOT_RUN.

**It is incorrect to describe this sealed runtime pack as retaining full raw
summary/infobox records redundantly inside evidence payloads.** Source export uses
`portable_export.document_payload/evidence_payload`: documents retain the compact
search truncation/text-proof payload, and entry evidence retains selected raw
attributes/categories/CV/gender. In this actual sample, all1741 evidence payloads
have `raw:{}` and no raw summary token was deduplicated. Aliases/links do retain
payloads, including raw relation details. A missing original raw record is not
silently reconstructed or inserted to inflate the experiment's baseline.

Actual reuse/compression here covers document originals, repeated small payloads,
alias/link payloads and duplicated persisted search representations. Canonical raw
summary ↔ document body sharing is supported and proven in fixtures, but is
**NOT_OBSERVED as a real-source gain in this sealed sample**.

## Reproducible selection, frozen before prototype construction

Workspace: `build/bangumi-compact-v1/`. `candidate-pool.json` records one covering
index pass (7.8009127s), deterministic per-kind reservoir768, seed
`bangumi-compact-v1:<kind>`. From each reservoir: fixed uniform128 plus longest16,
shortest nonempty16, empty16 and multi-document/alias16; then512 evenly spaced link
primary-key seeks and endpoint closure. Final choice is frozen in `selection.json`
(SHA256 `375b93634e55fa986dc39ed32e14a79c5f2c2050e4bb2bd7023b95fd785bf48b`).

Selection/probes13.6727117s include one complete FTS **metadata-only** cursor pass:
1,014,366 `(rowid,document_id,entry_id)` rows,11.7508503s. This is necessary to keep
all occurrences for selected documents without assuming rowid=document_id or
picking only the first duplicate. It is not a whole-library text/ranking audit;
metadata scans may touch large leaf pages and physical IO is not measured.

| Selected kind | Entities/documents | Original UTF-8 bytes | Empty originals | Longest bytes |
|---|---:|---:|---:|---:|
| subject | 757 | 514,768 | 84 | 6,574 |
| character | 301 | 147,477 | 74 | 7,586 |
| person | 504 | 242,886 | 160 | 6,111 |
| episode | 179 | 22,684 | 141 | 2,896 |

Total1741 entries/documents/evidence,2132 aliases,512 links, one source, five build
meta rows, zero tag-resolution rows:7873 ordinary rows. All actual selected
identity/document/alias statuses are source_backed and all selected link statuses
are native. Source pack has no unresolved_records table; unresolved upstream raw
relations cannot be measured from this pack. No_reference/generated, repeated FTS,
NULL fields and multi-document identities are covered separately by fixtures, not
claimed observed in the actual sample. Frozen FTS includes1562 rows, all unique by
document in this sample; the179 episode documents retain non-FTS search strings.

**Selection bias:** extra long/short/empty cases and native-link endpoint closure
are deliberately not full-library uniform weighting. Episodes are179/1741 here but
1698448/2712814 in the source; sample links512/1741 are also underweighted relative
to the source's3,967,075 stored links. Do not multiply the11.557% sample reduction
by9GB, or claim this sample validates full-library retrieval quality.

## Experimental storage and byte-level restoration

`tools/bangumi_compact_experiment.py` creates new outputs only. Original key/source/
evidence/entry/document/link IDs, metadata fields, aliases, statuses and references
remain unchanged. Designated body/payload TEXT columns become experiment-only
integer content-recipe references; ordinary indexed query columns are preserved.

- `content_blobs`: exact UTF-8 SHA256, codec (`identity` or `zlib`), version1,
  uncompressed byte length and stored BLOB. Shared content is stored once per exact
  digest; collisions are additionally checked against decoded bytes. Compression
  is selected only when smaller. No dependency/download, dictionary or whole-DB ZIP.
- `content_refs`: expected complete-field hash/length and bounded byte recipes.
  For canonical JSON `summary/original/description` string tokens matching a known
  body, the recipe references the same **unescaped body blob** plus a deterministic
  JSON-string transform. All other bytes—including unknown/duplicate keys, order,
  whitespace and escapes—are preserved verbatim. Noncanonical escaped spellings,
  lone-surrogate tokens or unparseable payloads use whole-payload fallback, never
  `json.loads`→whole-object reserialization. This is not universal semantic JSON
  deduplication: distinct exact escape representations may remain distinct blobs.
- FTS keeps original persistent searchable text, tokenizer configuration, rowids,
  document/entry IDs and multiplicity. `documents.search_text` references an
  existing FTS row only if there is exactly one occurrence, matching entry metadata
  and exactly equal UTF-8 bytes. Missing/duplicate/nonmatching occurrences use CAS;
  SQL NULL stays NULL. No FTS content is deleted to exaggerate the gain.

Actual compact file has4094 blobs and4094 recipes,3953 reused blob references,
1562 FTS search-text references and179 CAS search-text references. Persisted FTS
text remains1,603,158 UTF-8 bytes. Unique CAS uncompressed data1,338,486 bytes becomes
887,683 stored bytes (identity169,068; zlib718,615 for1,169,418 original bytes).
Recipe segment JSON alone is133,995 UTF-8 bytes; whole-file measurements above,
not this logical subtotal, account for complete overhead. Actual cross-payload
body-token substitution count is0.

Decoder rejects unsupported codec/version, malformed/truncated/trailing zlib,
excessive expansion, invalid UTF-8, negative/invalid lengths/IDs, missing refs,
unknown transforms, and hash/length mismatch. Content is bounded to16MiB per field
and128 recipe segments. FTS-referenced bytes are guarded by sample oracle/whole
artifact bindings, **not a per-read CAS digest check**. Exact old/new same-sample
validation checks all7873 rows and every full original field byte/type, all1562 FTS
occurrences/config, and48 deterministic token queries' BM25 scores, rowid/key ordering,
full document text, citation and status/trust eligibility. This does not create an
identity, verify a mapping or establish production runtime compatibility.

## Read/materialization cost, not just compression time

Final `sample-v2` extraction/baseline build0.2672158s; CAS-only build0.5327711s;
CAS+zlib build0.6192743s. Sample construction precedes latency measurements, so
first-open/first-pass **does not mean cold OS cache**. No cache flushing or model
query was performed. Four whole-row passes include actual reference lookup,
bounded decode, SHA/UTF-8 checks and schema lookup; no decoded-content cache.

| Measurement (same materialized rows/results) | Baseline | CAS+zlib |
|---|---:|---:|
| Warm whole7873-row passes, median | 21.4224ms | 191.5297ms |
| Warm48 FTS queries /262 hits including full document materialization, median | 4.35505ms | 23.84025ms |

All individual first/warm/open values are retained in `sample-v2/report.json`.
The slower path is the actual Python reference/decode/hash/schema-lookup pipeline,
not an isolated benchmark proving zlib alone causes the difference. This prototype
has not been integrated or benchmarked in the Rust Core; production latency is
UNKNOWN. Shared-content caching/other codecs/runtime migration are not pursued in
this first trial merely to recover performance.

## Commands, verification and limits

```powershell
# Reproduction uses NEW output names; never overwrite the frozen receipts below.
python -m tools.bangumi_compact_experiment pool --pack build/moegirl-refresh-v1/runtime-all-linked/packs/bangumi --output NEW_POOL.json
python -m tools.bangumi_compact_experiment freeze --pack build/moegirl-refresh-v1/runtime-all-linked/packs/bangumi --pool NEW_POOL.json --output NEW_SELECTION.json
python -m tools.bangumi_compact_experiment sample --selection NEW_SELECTION.json --output NEW_SAMPLE_DIRECTORY
```

Actual run used the frozen `candidate-pool.json`/`selection.json`; final output is
`build/bangumi-compact-v1/sample-v2/`. Initial `sample-v1/report.json` remains FAIL:
roundtrip/FTS checks passed but final optional page accounting encountered
`no such table: dbstat`. It was not overwritten/reinterpreted. The corrected run
explicitly records `dbstat=NOT_AVAILABLE` for SQLite3.50.4; whole-file byte
measurements remain available. Full source table/page accounting is NOT_RUN.

Final commands exited0:

```powershell
python -m pytest -q tests/test_bangumi_compact_experiment.py --basetemp D:/SakuraTool/SakuraKnowledge/build/bangumi-compact-v1/fixture-tests-final --junitxml build/bangumi-compact-v1/fixture-tests-final.xml
python -m pytest -q -rs --basetemp D:/SakuraTool/SakuraKnowledge/build/bangumi-compact-v1/full-python-tests --junitxml build/bangumi-compact-v1/full-python-tests.xml
python -m ruff check src tests tools
git diff --check
```

Scoped19PASS0.59s; full **1352PASS /19 Windows symlink privilege SKIP /55subtests**,
105.55s (the19 scoped cases are included, not added). UTF8 environment explicitly
`PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`. Full tests used the existing owned Rust
development binary/example helper and final3 DLL path; tests/temp are under this
workspace. Rust compilation NOT_RUN because no Rust/production code changed.

No production migration/new Core, full9GB compact build, original raw-record
re-ingestion, mother/ANN/model scan/rebuild, all120 replay, upstream refresh,
GPU/service/ORM/Pool/Pi, compression archive/upload or main merge. Unknown unrelated
untracked files, previous failures and valid packs are preserved. Local selection,
source bindings and artifact/JUnit receipts are indexed in
[`bangumi-storage-experiment-receipt.json`](bangumi-storage-experiment-receipt.json),
not replaced by the claims in this report. This completes the authorized first
storage trial, **not** production acceptance or the prior retrieval quality gate.
