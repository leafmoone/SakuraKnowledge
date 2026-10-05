# Explicit source adapter template

Copy demo_adapter.py, replace only raw field translation and metadata, then pass
`--adapter your_module:YourAdapter` to tools.normalized_source. No Rust registration,
known-source list, mother DB or SQL knowledge is required. Raw fixture is raw_demo.json;
normalized manifest/records and pack manifest are generated, not handwritten receipts.
Copyable commands: ../../docs/adding-a-source.md; formal contract:
../../docs/source-pack-contract.md. Do not treat this fixture as real-source evidence.

source_backed entry evidence establishes typed identity. generated_from_evidence is
text under that identity, never its sole identity proof. Candidate relations stay
candidate; verified native relation requires actual independent source facts.
