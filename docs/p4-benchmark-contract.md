# P4 retrieval engineering benchmark v1

This contract is frozen before embedding measurements. Not a full human source-fact
review. The embedding models do not author queries or relevance labels.

## Population and sampling

120 cases minimum, disjoint primary subsets: lexical 30, semantic 40,
crosslingual 30, ambiguous/negative 20. Case records bind query, subset, typed
entry key(s), accepted document IDs, source/evidence IDs and supporting excerpts.
All targets must satisfy the trusted corpus projection. Empty-target negatives
state their construction and expected non-identity behavior. Ambiguity cases may
have multiple accepted identities; do not collapse namespaces on spelling.

Freeze the gold bytes and hash before any embedding or vector-based selection.
Pilot is 50,000 unique documents: deterministic hash-ranked population plus
explicit frozen target/hard-negative inclusions, with all inclusion reasons
reported. Such guaranteed target inclusion is an engineering evaluation design,
not an unbiased estimate of naturally sampled target coverage. Audit source,
kind and language/script coverage. Keep same selected documents for both models;
chunk boundaries may differ under their separately frozen tokenizers.

## Ranking

Evaluate entry-level relevance. Deduplicate chunk/document hits to their typed
entry key before top-k evaluation. First occurrence establishes rank. Accepted
entry sets are frozen; document anchors are separately validated. Report document
hit coverage too, so another document of the same entity does not falsely prove
supporting-passage recall. No cross-namespace identity equivalence is inferred.

Recall@k = number of relevant entries in first k / total accepted relevant entries.
MRR@10 = reciprocal rank of first accepted entry in top 10, else zero.
nDCG@10 uses binary relevance, gain 1/log2(rank+1), ideal denominator over up to
10 accepted entries. Macro-average over cases with nonempty relevance sets;
report sample counts and denominators. Empty-target negatives have N/A ranking
metrics, never 0/0=1. Report their candidate counts, unexpected identity claims
and warnings separately. Semantic proximity alone does not imply a positive
identity judgment or require an arbitrary similarity threshold.

Each branch has fixed candidate depth 100. Hybrid uses equal-weight RRF,
k=60, score=sum(1/(60+rank)) over lexical and dense lists; ties break on typed
(kind, namespace, value). Trusted exact/alias candidates are separately pinned
before ordinary fusion, never promoted from ANN. Preserve all provenance/ranks.
BM25 and hybrid share the same exact/alias pinning contract; pure dense results
are separately identifiable. No fusion training, score calibration or tuning
against these test cases.

## Predeclared model gate

A qualifying hybrid must improve macro Recall@10 by at least 0.10 absolute on
BOTH semantic and crosslingual subsets over BM25, with nonnegative MRR@10 and
nDCG@10 deltas on those subsets. Lexical Recall@10 loss must be <=1/30 absolute,
and lexical MRR@10 and nDCG@10 losses each <=0.03. No wrong identity promotion is
permitted on any subset. Report all failures, not just this gate's metrics.
These thresholds operationalize 'meaningful improvement' for this small
engineering benchmark; they are not statistical population-wide proof.

Rank qualifying models by descending mean of semantic/crosslingual Recall@10,
then descending mean of those subsets' nDCG@10, then descending overall nDCG@10,
then ascending model identifier. The first is the quality leader, including when
models trade off subset quality. Recall loss above means macro metric difference,
not a count of lost cases when relevance sets have multiple entries.

Of qualifying models, a lightweight candidate is quality-comparable if its
Recall@10 is no more than 0.025 below the quality leader on EACH semantic and crosslingual subset
and overall nDCG@10 is no more than 0.03 below that leader. Prefer the comparable candidate with lower
measured CPU total-retrieval p95; use RSS then combined model/index bytes as
ordered tie breakers, then ascending model identifier. If no other candidate is
comparable, select the quality leader. A higher-quality but noncomparable model still needs Rust
CPU budget feasibility; size alone never determines selection. If neither model
qualifies, STOP and leave FULL NOT_RUN. Do not relax these thresholds after hits.

## Measurement protocol

Report BM25_ONLY, DENSE_ONLY_MODEL_A/B, HYBRID_MODEL_A/B using the same gold and
pilot document population. Report Recall@5/10/20, MRR@10, nDCG@10 overall and by
primary subset. Report paired case deltas and exact/alias preservation separately.

Fixed warmup: first two cases by case_id, one call each per model/mode; retained
as diagnostic records, excluded from formal percentiles. Formal quality/perf:
each frozen case exactly once per mode in sorted case_id order, no retries.
Reused and independent-process measurements are separate. Report p50/p95 using
linear interpolation at (n-1)*p; include all formal failures in counts and mark
latency acceptance failed, never silently exclude them. Latency percentiles of
successful operations must be explicitly labeled if failures exist.

Record query embedding reused, independent-process query, index search, total
retrieve, process peak RSS, model/index bytes and corpus embedding throughput.
CPU is mandatory; optional explicit GPU measurements are separate and cannot
substitute for CPU qualification. Record device/provider/thread counts and exact
dependency/model identities. No disk-cold claim without actual cache eviction.

Rust pilot/FULL: query hard budget <=5s, independent CLI outer <=15s, response
<=524288 bytes; all formal samples without retry. Runtime load/hash initialization
and operation budgets must be distinct, with CLI total including startup; do not
hide startup or snapshot verification outside CLI measurements.
