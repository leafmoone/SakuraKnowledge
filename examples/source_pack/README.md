# Explicit source adapter template

Copy demo_adapter.py, replace only raw field translation and metadata, then pass
`--adapter your_module:YourAdapter` to tools.normalized_source. No Rust registration,
known-source list, mother DB or SQL knowledge is required. Raw fixture is raw_demo.json;
normalized manifest/records and pack manifest are generated, not handwritten receipts.
Copyable commands: ../../docs/adding-a-source.md; formal contract:
../../docs/source-pack-contract.md. Do not treat this fixture as real-source evidence.

For directory inputs copy multi_adapter.py: input_inventory explicitly declares
raw_multi/{subjects,characters,relations,metadata}.json. Do not recursively scan or
read undeclared dependencies. Normalize hashes every input before all adapter reads
and again after complete records consumption. Bundle builds no longer need raw files.

```powershell
python -m tools.normalized_source normalize --input examples/source_pack/raw_multi --adapter examples.source_pack.multi_adapter:MultiAdapter --pack-id demo-multi --output NEW_BUNDLE
python -m tools.normalized_source build-normalized --input NEW_BUNDLE --output NEW_PACK
python -m tools.normalized_source validate --input NEW_PACK
```

Semantic FP32/intermediates belong to --workspace, not the final runtime pack.
Failed publications retain it; --resume-workspace verifies bindings before reuse.

source_backed entry evidence establishes typed identity. generated_from_evidence is
text under that identity, never its sole identity proof. Candidate relations stay
candidate; verified native relation requires actual independent source facts.
