# Adding a source without changing Core

1. Freeze lawful raw inputs, record digest/cut/revision and rights limitations.
2. Implement explicit SourceAdapter input_inventory/inspect/iter_records/source_metadata methods.
   Declare every regular input dependency; directory inputs do not trigger automatic
   recursive scanning. Only declared files may be read by official adapters.
   Return existing contract records, full typed keys and stable evidence/locators.
   Source-backed identity is independent from generated text; candidate links remain
   candidate, not verified native relationships. Do not guess identities from names.
3. Normalize through module:class. Adapt real raw fields; do not rename normalized
   JSONL to claim adapter validation. Check record count/digests before building.
4. Build a fresh standalone pack, validate and inspect. No mother import or rewrite
   of any other source is needed. All outputs are create-new.
5. Optionally prepare semantic assets with explicitly frozen local shared BGE model.
   Only new trusted text is encoded; no old packs/model/ANN change.
6. Copy pack directory anywhere under a portable root's packs directory, restart
   Core and select installation pack_id. Directory name may differ. Remove directory
   and restart to uninstall; other installed packs remain independent.

## Copyable lexical example (run from repository or installed tooling)

```powershell
python -m tools.normalized_source normalize --input examples/source_pack/raw_demo.json --adapter examples.source_pack.demo_adapter:DemoAdapter --pack-id demo-wiki --output NEW_BUNDLE
python -m tools.normalized_source build-normalized --input NEW_BUNDLE --output NEW_PACK
python -m tools.normalized_source inspect --input NEW_PACK
python -m tools.normalized_source validate --input NEW_PACK
Copy-Item NEW_PACK 'D:/Sakura 通用 来源 示例/packs/arbitrary-directory-name' -Recurse
# portable root contains bin/, sknow-config.json, and optionally shared model/
./sknow.ps1 packs
./sknow.ps1 lookup Mira --source demo-wiki
./sknow.ps1 search 'crystalline harbor' --source demo-wiki
./sknow.ps1 related c1 --kind character --namespace demo.character --source demo-wiki
./sknow.ps1 retrieve 'crystalline harbor' --source demo-wiki
```

Demo has two subjects, two characters, four source-backed aliases, four text documents
(one generated_from_evidence under existing source-backed identity), one verified
native character_of and one candidate. It is a fixture, not real-source validation.
Example module is not a production known-source list. Third-party modules work with
no Rust changes. Core structured/lexical operation needs no installed model.

## Directory-input example

```powershell
python -m tools.normalized_source normalize --input examples/source_pack/raw_multi --adapter examples.source_pack.multi_adapter:MultiAdapter --pack-id demo-multi --output NEW_MULTI_BUNDLE
python -m tools.normalized_source build-normalized --input NEW_MULTI_BUNDLE --output NEW_MULTI_PACK
python -m tools.normalized_source validate --input NEW_MULTI_PACK
```

The adapter explicitly declares subjects.json, characters.json, relations.json and
metadata.json. All four byte bindings are captured before and after every adapter
read. Original raw files may be removed after normalization; bundle build is offline.
Each source's metadata retains the full declared inventory (shared-all-inputs scope).
`source_metadata()` may return one metadata object or an ordered list of source
owners. Multi-owner records must carry a declared source_id; pack_id never stands
in for source_id. The builder partitions and freezes per-owner JSONL and reports
source accounts independently. `inspect()` may explicitly declare
`expected_unresolved: {source_id: {reason: positive_count}}`; undeclared reasons,
owners/count mismatches or unexpected imported unresolved records fail closed.
No candidate is promoted to make an unresolved record disappear.
Adjacent OUTPUT-import-input holds builder receipts, not distribution dependencies.
The three-file lexical pack can be moved and validated without raw files or those receipts.

## Optional semantic command

```powershell
python -m tools.generic_semantic --pack NEW_PACK --model FROZEN_BGE_MODEL --output NEW_SEMANTIC_PACK --workspace NEW_SEMANTIC_WORK --keep-workspace --index-builder /path/to/build_i8.exe --index-inspector /path/to/inspect_i8.exe
python -m tools.normalized_source validate --input NEW_SEMANTIC_PACK --index-inspector /path/to/inspect_i8.exe
```

After a failed publication, reuse the same verified workspace with
`--workspace NEW_SEMANTIC_WORK --resume-workspace`; prepared vectors/mapping/index
are verified and no re-encoding is performed. Existing final outputs are never
overwritten. Without --keep-workspace, success removes workspace. FP32 vectors and
intermediates never belong to runtime distribution: lexical has3 files and semantic
has5 files (manifest/snapshot/membership/mapping/I8). Extra files fail new-pack validation.

Native helpers are explicit prebuilt assets; building them is an offline developer
step (`cargo build --release --features semantic --example build_i8 --example inspect_i8`),
not query/install work. Semantic standalone validation needs inspect_i8 available
and its runtime DLL dependencies on PATH. No Python USearch dependency is required.
Production BGE encoding was not executed in this stage; tiny synthetic vectors
proved actual NPY/mapping/native I8/reload/fusion, not semantic text quality.
See [contract](source-pack-contract.md) for trust/manifest and validation boundaries.
