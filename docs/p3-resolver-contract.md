# P3 resolver v1 contract (execution design, not acceptance claim)

Root override is authoritative: only Rust exposes resolve_tag/resolve-tag. Python
P2 public Runtime/API/CLI remain frozen. Python ETL/audit and independently sourced
expected-behavior oracle are tooling, not production runtime or a new public CLI.
P2 lookup/search/ask/introduce outputs, storage/search-text v2 and Unicode16 remain.

CLI: `sknow-rs resolve-tag DB QUERY --target-namespace danbooru.tag`
optional `--category 0|1|3|4|5`, `--kind K --namespace N`, `--key` with complete source
kind/namespace/value, `--limit 1..100`. Source filters/key constrain the source path;
they never fall back to global native names. Direct target names have no source_key.
No target namespace other than danbooru.tag is supported by resolver v1.

Priority: exact original native/official active alias; proven same-source Wiki
multilingual names; only then source-backed entity lookup with verified entity_tag.
Exact matching does not mutate key spellings or change P2 tokenizer rules.
Tag category is tested against final native target, never used as identity evidence.
Display limit never affects status, deduplication or eligibility. A known typed
native key (explicit or a verified entity_tag dst) is canonicalized only by native/
official projections, never Wiki spelling names. Native/official priority is chosen
before category filtering; a category cannot substitute a different Wiki-name target.
An explicit native category mismatch is not_found; a unique entity whose actual
mapped terminal is excluded remains entity_found_tag_unmapped, not resolved elsewhere.

Response fields always present: contract_version2, response_version3,
resolver_contract_version1, snapshot, query, requested_namespace,
requested_category(integer or null), source_key(full EntryKey or null), status,
tag_key(full tag EntryKey or null), matched_by(string or null), canonical_status,
evidence_chain(array), descriptions(array), citations(array), candidates(array),
candidates_truncated(bool), source_scope(array of exact source IDs), warnings(array),
relations(array, reserved to reuse P2 response bounding), unresolved_reasons(array
of {name,matched_by,reason}; empty unless canonical proof incomplete). Successful operations exit0;
execution/usage errors use P2 stderr/error exit2. Whole operation5s and compact JSON
524288B remain hard gates; essential identity/proof never silently truncated.

- resolved: exactly one proven canonical terminal native target, tag_key original.
- tag_ambiguous: >=2 eligible distinct terminal keys; tag_key null.
- entity_ambiguous: >=2 trusted source identities before mapping; source_key null.
- entity_found_tag_unmapped: one trusted source, no verified eligible tag.
- not_found: no trusted eligible match in declared frozen scope, not global absence.
- canonical_unknown: native existence/alias spelling observed but terminal or
  alias/lifecycle coverage incomplete/invalid; null tag_key and explicit reasons.
- unsupported: optional P3 compiled resolver capability absent in old snapshot;
  no unindexed fallback scan. Old public operations continue to work normally.

Evidence roles remain separate: native_identity, canonical_scope, official_alias_step,
wiki_tag_link, wiki_cut_compatibility, wiki_association_edge,
wiki_association_quarantined, multilingual_name, entity_tag, description. Every reference retains
source_id/evidence_id/raw path+SHA and raw IDs. Native numeric tag ID not Wiki page ID.
Source dates/scope stay per source; mixed time cut and nontransaction API window explicit.
Only current active directed aliases redirect. Deleted/retired/unknown, cycles,
multiple outgoing, missing endpoint, >16steps, deprecated/unknown lifecycle, partial
scope/conflicts fail canonical proof. Each traversed spelling carries its outgoing
scope reference, including intermediate nodes, with directed step endpoints/status.
Compile graph once; runtime no arbitrary walk. Description emission requires the
actual indexed native wiki_tag edge, plus both old and live cut references (old
normalized source ID/hash/line, matching updated_at/body/name digests, official raw
SHA/IDs). Response chain includes these proofs and the actual edge/document IDs.
Changed Wiki versions return no description and retain a quarantine proof with the
unequal dates; native existence remains independent. Empty/generic role names or
wiki_key alone do not establish a description's identity association.
Implication is not alias. Generated/draft/name-only/candidate evidence creates no
native tag or verified entity mapping. Local aggregate remains local.tag_aggregate.

Optional single-snapshot P3 projection is produced inside the existing builder's
unpublished staging database, from validated normalized records, then verified before
atomic publish. It is not an overlay, post-publication patch, generic migration or
mandatory version bump. Native records still enter entries+entry_evidence; all raw
is preserved/referenced. Resolver lookup assessment never creates a synthetic native
identity merely to store an unknown/missing alias. New dst index is offline optional;
necessary inbound related is Rust-only explicit direction and rejects old capability.

Expected behavior fixtures must precede implementation. Real pilot must include
colliding names from full old input, not only selected favorable source entities.
Cross-source decisions require explicit source ID/link rules or genuine human review;
execution agent self-review is never human_verified. Candidate queue<=100 and
replayable decision fields explicit. Full candidate build is a separate one-attempt
operation after code/pilot real positives/freeze/all old SHA/disk/cleanSHA gates.
