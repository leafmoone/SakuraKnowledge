# Adding a source

Core discovers installed `packs/*/manifest.json`. A new source does not require importing the mother database, rebuilding other packs or adding a Core source-name registry.

## Adapter and lexical pack

1. Obtain lawful raw inputs; record their revision/cut and applicable rights limitations.
2. Implement `SourceAdapter.input_inventory`, `inspect`, `iter_records` and `source_metadata` explicitly. Declare every file the adapter reads. Paths in transferable inventories are relative to the declared input root.
3. Return the existing normalized record contract with full typed keys and source/evidence IDs. Preserve unresolved reasons. Generated text cannot create source-backed identity; candidate links remain candidates.
4. Normalize and build into new directories. The adapter is supplied as `module:class`, not auto-discovered.

Run from the project root with your production adapter and relative input/output locations:

```text
python -m tools.normalized_source normalize --input data/raw-source --adapter my_adapter:Adapter --pack-id new-source --output build/new-bundle
python -m tools.normalized_source build-normalized --input build/new-bundle --output build/new-pack
python -m tools.normalized_source inspect --input build/new-pack
```

The raw input may be a file or directory. Directory inventory is explicit, not an automatic recursive read. A multi-source adapter returns declared source owners and records carry the correct `source_id`; installation `pack_id` is not evidence ownership. Expected unresolved accounts must be explicit. The resulting runtime pack is transferable without raw input or adjacent importer working files.

## Optional local semantic preparation

Lexical/structured packs do not need a model. Semantic packs use the explicit frozen shared BGE-M3 CPU contract and prepared native I8 helpers:

```text
cargo build --release --manifest-path rust/Cargo.toml --features semantic --example build_i8 --example inspect_i8
python -m tools.generic_semantic --pack build/new-pack --model model/bge-m3 --output build/new-semantic-pack --workspace build/new-semantic-work --keep-workspace --index-builder rust/target/release/examples/build_i8.exe --index-inspector rust/target/release/examples/inspect_i8.exe
```

On other platforms use the corresponding executable names. No machine-specific toolchain installation path is assumed. Required optional Python dependencies are numpy, tokenizers and onnxruntime, with explicit local ONNX/model assets. Queries never perform preparation.

Failed publication retains its workspace. An explicit `--resume-workspace` reuses prepared vectors/mapping/index rather than re-encoding; `--keep-workspace` retains it after success. Final runtime packs omit FP32 vectors and working artifacts. Existing final outputs are not overwritten. Producing a valid pack does not prove retrieval quality or upstream identity facts.

## Installation and queries

Copy the published pack into `packs/new-source/` and restart Core. Directory names need not equal manifest `pack_id`. Shared model assets go under `model/bge-m3/`; runtime programs and DLLs go under `bin/`.

```powershell
./scripts/sknow.ps1 packs
./scripts/sknow.ps1 lookup NAME --source new-source
./scripts/sknow.ps1 search QUERY --source new-source
./scripts/sknow.ps1 retrieve QUERY --source new-source
```

Removing the source directory and restarting uninstalls only that source. No title, spelling, confidence, generated text or candidate mapping is promoted to verified identity. See [source-pack contract](source-pack-contract.md) for manifest, trust, publication and runtime boundaries.
