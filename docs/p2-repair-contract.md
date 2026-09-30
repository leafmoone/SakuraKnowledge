# Directed P2 repair contract (bd99b7a)

Implementation in progress, not an acceptance claim. Storage and search-text
remain version 2. Response version 3 is additive and explicitly separate.
Historical v1–v6 receipts retain their original results.

## R3 introduction

A trusted raw-input unique identity **or ambiguity** precedes template parsing.
The existing raw lookup is reused. Introduction subjects strip whitespace only:
`name.`, brackets and underscores remain identity data. Introduction performs
lookup/description only; `mapping_status=not_requested`, `target_namespace=null`,
no entity_tag query. Missing identity is unknown and ambiguity is retained.
Explicit target namespace with a parsed introduction is a validation error.
Tag templates retain their explicit target mapping semantics.

## R4 occurrence payload v2, existing storage v2

`partition` preserves the original seven-table group. `dataset_id` is one member
from sources_json, not the table name. Every explicit member produces an
observation; source_count remains the observed coverage count, never frequency.
If sources_json is absent, noncommon tables use the explicit TAG_DATASETS map;
common has dataset_id=null and membership_basis=unknown rather than inventing a
common dataset. No audited sample counts exist: sample_count=null. Original row,
category, variants and sources_json remain in raw. No native Danbooru identity
is inferred. Unknown source members cause validation failure, not silent loss.

New payloads carry occurrence_contract=2, source_count, partition, dataset_id,
sample_count and membership_basis. The unchanged SQLite columns project
partition→group_name and dataset_id→dataset; frequency is NULL. Existing legacy
payloads remain accepted under their old schema but their frequency is an
uninterpreted legacy quantity, **not a trusted sample count**. The production
snapshot is neither updated nor rebuilt. See the bounded input audit receipt
`reports/P2/repair-bd99b7a-occurrence-audit.json`; common-table behavior is fixture
validation only because that table has no rows in the audited frozen cut.

## R5 field observations and bounds

source_fields maps each of four permitted field names to an observation list.
Each observation contains source_id, evidence_id, status, value, value_state
(null/empty/present), and truncated. Missing fields have no observation; null,
empty list/object/string are distinct values. Different source values coexist,
no winner or merged fact. source_fields_evidence cites the field-bearing records,
not aliases used for identity resolution. Stable source/evidence ordering is
presentation only. Raw payloads stay in storage, not default identity responses.

Limits: 4 observations per field; 256 Unicode scalars per string; 16 list items
or object keys per node; depth 4; serialized value max 2048 UTF-8 bytes (overlarge
bounded values replaced by null with truncated=true, original value_state kept).
source_fields_truncated lists fields with omitted observations. At most 100
identity proofs are returned, with identity_evidence_truncated marking overflow.
Total compact response budget is 524288 UTF-8 bytes; drop tail candidates or
relations with response_budget_truncated. Do not truncate identity strings; an
irreducible overlarge response raises response_budget_exceeded. This is separate
from the query deadline. No unbounded explicit evidence-read API is introduced.

## R6 open gate

Both storage contract and search-text version must equal 2. Require snapshot
identity and all query-required table columns, actual FTS5 search_fts definition,
preparable MATCH and a functioning JSON extraction operation. Failure closes the
connection. These bounded checks never invoke full integrity_check, digest scan,
implicit migration, index creation or download.

## R1 query plan and unified deadline

Legacy S18 EXPLAIN shows a temporary B-tree for ORDER BY bm25 plus identity.
Both legacy diagnostic runs exhausted five seconds before returning a first row;
therefore this receipt does not attribute measured cost to body materialization
that never happened. The old Rust code additionally collected 10,001 bodies
when SQL succeeded; that independent memory defect is removed.

The new query orders by the FTS hidden rank column (default BM25), enabling the
FTS rank cursor and avoiding the joined wide temporary sort. It selects only
entry key/locator, score and document/FTS row IDs. Complete equal-score groups
are examined, retaining only the needed lexicographically smallest identities;
duplicate documents choose the smallest FTS rowid. This preserves old
(score,kind,namespace,value,rowid) ordering. At 10,000 scanned rows an incomplete
tie is explicitly warned and cannot pass formal parity. Selected identities
alone fetch matched document text. Exact matches sufficient for topk skip FTS.

Nested lookup/related/ask/search calls share a single five-second operation
deadline; a subsequent public operation starts a new deadline. Non-SQL assembly
and streaming also check the deadline. OR semantics and S18 input/topk unchanged.
One-shot before/after diagnostic receipts are not 30-sample performance evidence.

The first repaired formal run remains FAIL (148/151): S02 Python budget failure,
E18 Rust dbstat scan budget failure and E16 Rust CLI argument error type mismatch.
These are retained in repair-bd99b7a-parity-v1.json, not retried or reclassified.
For filtered FTS, use lightweight bm25 sorting after rejecting ineligible rows
rather than rank-ordering the whole corpus before filtering. Unfiltered S18
continues to use the rank stream. Inspect now explicitly reports dbstat_status
not_run on both runtimes; optional full-page dbstat scans are not part of this
lightweight API. E16 missing positional arguments are UsageError before opening
any database. Original case inputs are unchanged; response-v3 expectation deltas
are explicitly listed in tools/parity_repair_expected.py.

## R2 Unicode data

`tools/generate_unicode16.py` requires CPython UCD16 and enumerates every scalar
to generate full default casefold mappings, Python alphanumeric ranges and UCD16
assigned ranges. Rust normalizes assigned runs with the pinned normalization
crate, preserving UCD16-unassigned characters as CCC=0 boundaries, then applies
the complete generated casefold table. No Python runtime subprocess is used.
Generator `--check`, direct token/MATCH cases, nonempty FTS and full JSON tests
cover sharp-S, sigma, dotted-I, combining marks, width forms, kana, CJK, whitespace
and supplementary-plane letters. Runtime metadata states both UCD16 and the
normalization library Unicode version, and actual bundled SQLite version.

## Expected deltas

Old introduction mapping_status=unmapped becomes not_requested; no tag is
required for found introductions. Original question ambiguity wins over parsing.
Introduction terminal punctuation stays literal. Scalar source_fields become
observation arrays; their citations now identify actual field evidence, payloads
are omitted from default identity_evidence. response_version=3 and truncation
metadata are new. Update new locked expectations explicitly; do not alter old
parity receipts to retrofit these deltas.
