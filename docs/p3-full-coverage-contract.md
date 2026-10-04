# P3 full-coverage contract

## Typed identity and coverage

Verified entity/tag coverage is optional. Zero verified mappings is a valid
coverage limitation, not permission to infer identity from a shared spelling,
FTS result, semantic similarity or confidence score. Candidate mappings remain
candidates until supported by the required source evidence and review.

- A unique entity without a verified mapping returns `entity_found_tag_unmapped`.
- Multiple matching identities return `entity_ambiguous`.
- Native tag identities, local aggregate tags and Wiki associations remain distinct.
- Official aliases and native Wiki associations require their explicit source
  identity; names alone do not establish a join.

Report denominators separately for native identities, acquired official aliases,
Wiki associations, Chinese-language evaluation subsets and candidate/verified
mappings. Scoped coverage is not whole-source recall or full human fact review.

## Data-dependent compatibility

A snapshot containing additional source-backed native tags or aliases may expose
more typed candidates, documents or ambiguity than an earlier snapshot. Such
changes must not silently merge namespaces or turn an ambiguous result into a
verified identity.

Evaluation retains query inputs, typed keys, category filters and evidence
expectations. Expected data-dependent candidate sets and statuses should come
from independent source/identity checks, not be copied from actual runtime output.
Keep the useful raw cases and provenance; do not discard failed samples or select
only favorable results when evaluating a new candidate.

P2/P3 public interface behavior, budget/timeout handling, JSON errors and
source-backed provenance remain regression requirements. Python/Rust compatibility
is checked against the same candidate's expected behavior; byte equality between
different snapshots is not assumed.

## Publication and validation

Inputs remain read-only. The normal builder checks input digests, SQLite integrity,
foreign keys, FTS, source accounting and required mappings before atomic
publication to a new output. Do not overwrite an existing snapshot. Retain normal
concurrency protection and preserve error information and partial results on
failure.

A real-data acceptance session validates the candidate it actually reads. Pilot
results do not substitute for full-snapshot measurements, and a process exit or
successful file open is not a quality result. Unexecuted platform, integration,
performance or human-review work remains explicitly `NOT_RUN`.

Historical fixed-commit authorizations, permanent one-shot ledgers and repeated
checks of old delivery reports are not part of the current product contract.
Their retired scripts and reports are available in Git history, not required in
the working directory. Normal tests may be repaired and rerun without a new
historical retry envelope. This removal does not itself authorize a new full-data
build or modify any retained product.
