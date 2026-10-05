# Current delivery status

## Generic source-pack extension

Baseline c84e5d6643736f8d6ddb2ff9b0dc7e3d8714d2c7. Core now discovers actual
installed v1 manifests without four-name whitelist or fixed missing-source catalog.
Unknown safe installation IDs/namespaces work, directory !=pack_id works, duplicate
IDs/capabilities and invalid capability/model/artifact combinations fail closed.
Identity/resolve/tag provenance and semantic fusion weights are unchanged.

Generic raw adapter → normalized bundle → standalone builder reuses storage importer,
not mother DB. Explicit module:class requires no Rust registration. Actual demo:
2subject/2character,4aliases/4documents (one generated text under backed identity),
1verified native relation/1candidate,6normalized records,4trusted FTS. Multisource
ownership is tested with two sources; generated-only identities/stubs do not gain
trust or FTS. New snapshot retains original documents/evidence, only indexing
excludes missing backed identity. Full contract: docs/source-pack-contract.md;
copyable commands/template: docs/adding-a-source.md and examples/source_pack/.

### Actual evidence

- Generic Python35PASS (2.38s): raw conversion, no-mother SQLite path allowlist,
  digest/count/source checks, two-owner closure, rehashed orphan FTS/membership
  rejection, generated-only/stub identity boundary and tiny semantic native closure.
- Final full Python **1290PASS/18Win1314 symlink skips/55subtests**,59.44s,
  explicit SKNOW_RS_TEST_BIN, DLLPATH and D temp. Earlier wrong env run1158/150
  preserved as incomplete coverage. Rust **62PASS**,0.59s; Ruff and diffcheckPASS.
- Unicode/space external root D:/Sakura 通用 来源 示例, directory not-the-pack-id
  holds demo-wiki. Actual packs/lookup/search/related/retrieve exit0, no model,
  retrieve query/process encodings0 (7.567ms). Move demo out and restart: only
  second-wiki installed, lookup still works. Restore supports both independently.
- Current old4 manifests load unchanged: Dan lookup, actual Moegirl alias lookup
  found typed key, new tag-provenance search. Dan single retrieve200081bytes/
  207.6064ms and Dan+Bangumi40104bytes/334.9596ms each one shared query encoding.
  An attempted nonexistent Moegirl title returned not_found, not successful evidence.
- Synthetic semantic4rows: only encoder/tokenizer mocked, actual trusted projection
 384/64 → mapping/FP32 NPY → native Cos/I8/M16/add256/search2048 → manifest/native
  inspect PASS. Real two unknown-pack ANN view/search/reload → existing federation
  compatible/proof merge/order invariance PASS. Not a full ONNX loader mock claim.
- NPY wrongdimension/f64/Fortran/truncated inputs all native exit1. Native I8 builder
  reads actual N now, no1366520 row hardcode. Existing ANN graphs remain untouched.
- Standalone semantic validate outside Git cwd with supplied native inspect executable
  PASS,4rows228127bytes. Missing native inspector explicitly errors, never PASS.

### Assets and limitations

Create-new Core: build/generic-components/SakuraKnowledge-core-win-x64,
83261548bytes/17files, receipt build/generic-core-inventory.json. It includes generic
query binaries plus explicit offline build_i8/inspect_i8 tools; old Core preserved.
No model or source asset copied into Core. Original packs/model/mother/vectors/ANN
remain unchanged. Runtime pack requires compact manifests/DB/membership and optional
mapping/index, not audit/proofs/gold raw receipts. New semantic FP32 preparation
output preserved separately by builder, not used by query as required ANN asset.

Production new-source BGE embedding NOT_RUN; no new real source/data/download,
120 ranking rerun (fusion unchanged), Pi/Pool/upload/compression or main merge.
Existing runtime120 PASS / quality FAIL remains historical, not upgraded by fixtures.
Rights NOT_CLEARED and RSS unmeasured. Frozen tag proof66979 remains baseline.
A delegated build mistakenly attempted target
D:/SakuraTool/SakuraPool-P4-work/rust-target; GNU missing g++/dlltool and MSVC Git
linker failures were reported. Actual external build-artifact write is UNKNOWN,
not asserted absent; no external cleanup/restoration performed. Subsequent successful
builds used explicit in-repository D target. No next real-source stage started.
