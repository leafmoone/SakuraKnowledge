# Generic source-pack contract

The existing `sakura-source-pack-v1` is retained; old four packs require no rewrite.
Core discovers actual immediate `packs/*/manifest.json`, not a source-name catalog.
Directory names need not match installation `pack_id`. IDs are unique within a
root, ASCII letters/digits/`-_.`, length1..128, not `.`/`..`. `--source` selects
installation IDs; evidence retains original source IDs, which may be multiple.
Namespaces/source IDs are nonempty strings <=256 characters, without controls,
and unique in each declaration. Typed identity remains `(kind, namespace, value)`;
existing KINDS only. A crosspack endpoint stub without source-backed evidence is
not an identity claim. Target packs merge by full typed key, not local SQLite IDs.

Required capabilities: unique structured+lexical; optional semantic, no others.
Lexical-only requires_model=null and contains no semantic declaration/mapping/index.
Semantic requires_model=bge-m3 only; other models explicitly fail. It retains the
fixed shared encoder and global Cos-distance fusion, not a new model architecture.
Required metadata: schema, pack_id, display_name, version, source_ids, namespaces,
capabilities, requires_model, trusted_fts_documents, lexical_mode, lexical_membership.
Artifacts form a closed role set: snapshot and lexical_membership, plus mapping and
index for semantic. Each safe single-component relative path has size+SHA256, unique
between roles. Canonical snapshot knowledge.sqlite and lexical-membership.sqlite.
Semantic rows>0, dimension1024, Cos/I8, M16, add256/search2048, chunkdepth512,
entrydepth100. Legacy runtime semantic contract accepts its existing documented
chunkdepth range; new builder uses512. Invalid declarations fail, not silently hide.

## Normalized adapter boundary

`sakura-normalized-source-v1`: manifest.json + records.jsonl. Manifest includes pack
metadata, sources, namespaces, desired capabilities, adapter id/version, input
bindings, records binding and count, trust declarations. Records reuse existing
contract entities/links/tag resolutions, EntryKey/status/aliases/documents/occurrences/
verification/evidence; no parallel SQL schema. Multiple sources require each record
source_id; single-source ownership may be implicit but a foreign explicit owner fails.
`src/sakura_knowledge/source_adapter.py` is a small explicit interface, not registry,
plugin discovery or workflow framework. Third parties supply module:class explicitly.

Generic builder never opens the mother or other packs. It reuses `storage.build`
for source-account, frozen-input import, schema/FTS/FK/ledger checks, then excludes
FTS under generated-only/conflicted identities in its owned new snapshot. Generated
text under a source-backed identity remains indexed. Documents/evidence are retained.
Multisource input is partitioned by declared owner, never pack_id. Link stubs remain
untrusted until independently backed. Legacy mother projection remains in
`tools/source_pack.py` and its FAMILIES serves only historical grouping.

Standalone validate verifies binding, integrity/FK, actual source/namespace sets,
trusted FTS count and complete row/document/entry/source-backed identity closure,
member tuple equality both ways and snapshot binding. Semantic additionally verifies
mapping positions/typed key/document/source/evidence closure and actual native index
Cos/I8/M16/rows/local key coverage through explicit `inspect_i8` executable. Missing
native inspector is an error, not PASS. No Git/Cargo checkout/mother requirement;
use installed Python tooling and supplied native executable. inspect is readonly JSON.

## Create-new semantic preparation

`tools/generic_semantic.py` validates input pack; freezes/verifies explicit local
shared-model artifact bindings, reuses `p4_chunks.project_document`384tokens/64overlap,
encodes trusted documents under source-backed identities, writes local mapping and
FP32 NPY, invokes native I8 builder and validates published manifest/native index.
No query ever builds/downloads assets. Existing vectors/ANN/model are not modified.
Production encoding requires numpy/tokenizers/onnxruntime and the frozen local BGE-M3
ONNX assets. This stage executed synthetic four-row fixtures with only expensive
encoder/tokenizer mocked; production new-pack BGE encoding remains NOT_RUN.
