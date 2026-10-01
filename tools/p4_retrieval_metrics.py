"""Pure entry-level retrieval arithmetic and frozen P4 model selection.

* Typed identities are (kind, namespace, value), never snapshot integer entry_id.
  Gold accepted targets are a SET, not alternative groups; every member counts.
  Caller maps documents to identities using frozen source-backed mappings.
* Rankings retain the first occurrence of each entry and compact positions.
* RRF uses k=60 and raw backend ranks <=100 BEFORE entry deduplication; each
  backend contributes once at its best raw rank. Ties use (kind, namespace, value).
* Explicit caller-attested source-backed exact/alias pins precede ordinary RRF.
  Pins sort by typed key. Names, scores, gold and hit references confer no trust.
* Macro query means exclude empty-target cases. Negative return and promotion
  rates have separate denominators. Missing means/rates are None.

Trust attestation is an input boundary, NOT verified by this arithmetic library.
Selection implements docs/p4-benchmark-contract.md, not permission to run FULL:
Rust CPU feasibility and measurement/source completeness remain caller obligations.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import fsum, isfinite, log2
from statistics import mean

RRF_K = 60
CANDIDATE_DEPTH = 100
SUBSETS = ("lexical", "semantic", "crosslingual", "ambiguous_negative")
METRICS = ("recall_at_5", "recall_at_10", "recall_at_20", "mrr_at_10", "ndcg_at_10")
RELEVANCE_WARNING = "Retrieval relevance is not verified identity or permission to promote identity."


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty string")


@dataclass(frozen=True, order=True)
class EntryKey:
    """Source-backed typed identity, not a snapshot row ID or inferred name.

    Construct with EntryKey(**{"kind": "tag", "namespace": "source", "value": "name"}).
    The caller must supply the actual typed value; row IDs are not converted.
    """

    kind: str
    namespace: str
    value: str

    def __post_init__(self) -> None:
        for value in (self.kind, self.namespace, self.value):
            _text(value)


def _keys(values: Iterable[EntryKey]) -> tuple[EntryKey, ...]:
    result = tuple(values)
    if any(not isinstance(value, EntryKey) for value in result):
        raise ValueError("Expected typed EntryKey identities")
    return result


def deduplicate_ranking(entries: Iterable[EntryKey]) -> tuple[EntryKey, ...]:
    """Keep first hit per typed entry and compact to consecutive positions."""
    return tuple(dict.fromkeys(_keys(entries)))


@dataclass(frozen=True)
class Hit:
    entry: EntryKey
    rank: int
    score: float | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    source_id: str | None = None
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        _keys((self.entry,))
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("Rank must be a positive integer, not a score or bool")
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not isfinite(self.score)
        ):
            raise ValueError("Score must be finite when supplied")
        for value in (self.document_id, self.chunk_id, self.source_id, self.evidence_id):
            if value is not None:
                _text(value)


@dataclass(frozen=True)
class TrustedPin:
    """Caller attests an exact/alias match is source-backed; references required."""

    entry: EntryKey
    match: str
    source_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        _keys((self.entry,))
        if self.match not in ("exact", "alias"):
            raise ValueError("Only trusted exact/alias matches may be pinned")
        _text(self.source_id)
        _text(self.evidence_id)


@dataclass(frozen=True)
class Provenance:
    backend: str
    hit: Hit


@dataclass(frozen=True)
class FusedCandidate:
    entry: EntryKey
    hybrid_rank: int
    rrf_score: float
    backend_ranks: tuple[tuple[str, int], ...]
    provenance: tuple[Provenance, ...]
    trusted_pins: tuple[TrustedPin, ...]
    warnings: tuple[str, ...] = (RELEVANCE_WARNING,)


class InvalidCandidateError(TypeError, ValueError):
    """A malformed candidate violates the typed fusion input contract."""


def reciprocal_rank_fusion(
    backends: Mapping[str, Iterable[Hit]], pins: Iterable[TrustedPin] = ()
) -> tuple[FusedCandidate, ...]:
    """Fuse fixed-depth backend lists, preserving all in-depth hit provenance.

    Scores are diagnostic only. Out-of-depth hits cannot contribute or introduce
    entries. Explicit pins are independent of the ordinary candidate-depth cap.
    """
    hits: dict[EntryKey, list[Provenance]] = {}
    ranks: dict[EntryKey, dict[str, int]] = {}
    trusted: dict[EntryKey, list[TrustedPin]] = {}
    for backend in backends:
        _text(backend)
    for backend in sorted(backends):
        for hit in backends[backend]:
            if not isinstance(hit, Hit):
                raise InvalidCandidateError("Expected Hit inputs")
            if hit.rank > CANDIDATE_DEPTH:
                continue
            hits.setdefault(hit.entry, []).append(Provenance(backend, hit))
            best = ranks.setdefault(hit.entry, {})
            best[backend] = min(best.get(backend, hit.rank), hit.rank)
    for pin in pins:
        if not isinstance(pin, TrustedPin):
            raise InvalidCandidateError("Expected explicit TrustedPin inputs")
        trusted.setdefault(pin.entry, []).append(pin)
    entries = hits.keys() | trusted.keys()
    scores = {
        entry: fsum(1 / (RRF_K + rank) for _, rank in sorted(ranks.get(entry, {}).items()))
        for entry in entries
    }
    ordered = sorted(
        entries,
        key=lambda entry: (0, 0.0, entry) if entry in trusted else (1, -scores[entry], entry),
    )

    def provenance_key(item: Provenance) -> tuple:
        hit = item.hit
        return (
            item.backend, hit.rank, hit.document_id or "", hit.chunk_id or "",
            hit.source_id or "", hit.evidence_id or "",
            hit.score is not None, hit.score if hit.score is not None else 0,
        )

    return tuple(
        FusedCandidate(
            entry=entry,
            hybrid_rank=index,
            rrf_score=scores[entry],
            backend_ranks=tuple(sorted(ranks.get(entry, {}).items())),
            provenance=tuple(sorted(hits.get(entry, ()), key=provenance_key)),
            trusted_pins=tuple(sorted(
                trusted.get(entry, ()), key=lambda pin: (pin.match, pin.source_id, pin.evidence_id)
            )),
        )
        for index, entry in enumerate(ordered, 1)
    )


@dataclass(frozen=True)
class RankingMetrics:
    recall_at_5: float | None
    recall_at_10: float | None
    recall_at_20: float | None
    mrr_at_10: float | None
    ndcg_at_10: float | None


def ranking_metrics(
    ranking: Iterable[EntryKey], accepted_targets: Iterable[EntryKey]
) -> RankingMetrics:
    entries = deduplicate_ranking(ranking)
    targets = frozenset(_keys(accepted_targets))
    if not targets:
        return RankingMetrics(None, None, None, None, None)
    relevant = [index for index, entry in enumerate(entries[:10], 1) if entry in targets]
    dcg = fsum(1 / log2(index + 1) for index in relevant)
    ideal = fsum(1 / log2(index + 1) for index in range(1, min(10, len(targets)) + 1))
    return RankingMetrics(
        *(len(targets.intersection(entries[:cutoff])) / len(targets) for cutoff in (5, 10, 20)),
        1 / relevant[0] if relevant else 0.0,
        dcg / ideal,
    )


@dataclass(frozen=True)
class CaseResult:
    query_id: str
    subset: str
    metrics: RankingMetrics
    target_count: int
    returned_count: int
    identity_promotion_error: bool


def evaluate_case(
    query_id: str,
    subset: str,
    ranking: Iterable[EntryKey],
    accepted_targets: Iterable[EntryKey],
    *,
    promoted_identities: Iterable[EntryKey] = (),
    trusted_identity_keys: Iterable[EntryKey] = (),
) -> CaseResult:
    """Score relevance and independently audit caller-reported identity promotion.

    Any promotion on an empty-target negative is an error. On positive cases,
    promotions require separately attested identity keys, not membership in gold.
    A nonempty negative result is reported separately, not itself identity promotion.
    Audit accuracy depends on the caller reporting ALL actual promotions.
    """
    _text(query_id)
    if subset not in SUBSETS:
        raise ValueError(f"Unknown subset: {subset}")
    entries = deduplicate_ranking(ranking)
    targets = frozenset(_keys(accepted_targets))
    promoted = frozenset(_keys(promoted_identities))
    trusted = frozenset(_keys(trusted_identity_keys))
    return CaseResult(
        query_id, subset, ranking_metrics(entries, targets), len(targets), len(entries),
        bool(promoted) if not targets else bool(promoted - trusted),
    )


@dataclass(frozen=True)
class Mean:
    value: float | None
    denominator: int


def _mean(values: Iterable[float]) -> Mean:
    values = tuple(values)
    # One correctly rounded mean avoids sum/division double rounding at gate boundaries.
    return Mean(mean(values) if values else None, len(values))


@dataclass(frozen=True)
class Aggregate:
    case_count: int
    positive_count: int
    negative_count: int
    metrics: Mapping[str, Mean]
    negative_nonempty_rate: Mean
    negative_identity_promotion_error_rate: Mean
    identity_promotion_error_rate: Mean


def aggregate_cases(cases: Iterable[CaseResult]) -> dict[str, Aggregate]:
    """Overall plus each fixed subset, including empty subsets with N/A means."""
    cases = tuple(cases)
    if len({case.query_id for case in cases}) != len(cases):
        raise ValueError("Duplicate query IDs would change macro denominators")
    if any(case.subset not in SUBSETS for case in cases):
        raise ValueError("Unknown subset")
    result = {}
    for subset in ("overall", *SUBSETS):
        selected = tuple(case for case in cases if subset == "overall" or case.subset == subset)
        negatives = tuple(case for case in selected if case.target_count == 0)
        result[subset] = Aggregate(
            len(selected), len(selected) - len(negatives), len(negatives),
            {
                name: _mean(
                    value for case in selected
                    if (value := getattr(case.metrics, name)) is not None
                )
                for name in METRICS
            },
            _mean(float(case.returned_count > 0) for case in negatives),
            _mean(float(case.identity_promotion_error) for case in negatives),
            _mean(float(case.identity_promotion_error) for case in selected),
        )
    return result


@dataclass(frozen=True)
class ModelMeasurement:
    """Caller-supplied CPU measurements and complete hybrid case results.

    All formal failures must remain in the external report. These summary costs
    neither attest successful operations nor prove Rust CPU budget feasibility.
    """

    cases: tuple[CaseResult, ...]
    cpu_total_retrieve_p95: float
    peak_rss: int
    model_plus_index_bytes: int

    def __post_init__(self) -> None:
        value = self.cpu_total_retrieve_p95
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidCandidateError("CPU p95 must be finite and nonnegative")
        if not isfinite(value) or value < 0:
            raise ValueError("CPU p95 must be finite and nonnegative")
        for value in (self.peak_rss, self.model_plus_index_bytes):
            if type(value) is not int or value < 0:
                raise ValueError("Measured bytes must be nonnegative integers")


@dataclass(frozen=True)
class ModelChoice:
    selected: str | None
    quality_leader: str | None
    qualifying: tuple[str, ...]
    failures: Mapping[str, tuple[str, ...]]


def choose_model(
    bm25_cases: Iterable[CaseResult], models: Mapping[str, ModelMeasurement]
) -> ModelChoice:
    """Apply the frozen quality/comparability gate without I/O or numeric tuning.

    Inputs must describe the same cases, subsets and accepted-target counts.
    Missing quality subsets or mismatched cases fail closed with ValueError.
    No qualifier returns selected=None: STOP and leave FULL NOT_RUN. Even a
    selection is only a recommendation, pending external Rust CPU feasibility.
    No source, gold, promotion-reporting or measurement attestation is inferred.
    """
    baseline_cases = tuple(bm25_cases)
    baseline = aggregate_cases(baseline_cases)
    signature = {(c.query_id, c.subset, c.target_count) for c in baseline_cases}

    def quality(report: Mapping[str, Aggregate], subset: str, metric: str) -> float:
        value = report[subset].metrics[metric].value
        if value is None or not isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"Missing or invalid quality metric: {subset}.{metric}")
        return value

    quality_subsets = ("lexical", "semantic", "crosslingual")
    gate_metrics = ("recall_at_10", "mrr_at_10", "ndcg_at_10")
    for subset in quality_subsets:
        for metric in gate_metrics:
            quality(baseline, subset, metric)
    reports = {}
    failures = {}
    for name in models:
        _text(name)
    for name in sorted(models):
        model = models[name]
        if not isinstance(model, ModelMeasurement):
            raise InvalidCandidateError("Expected ModelMeasurement inputs")
        cases = tuple(model.cases)
        report = aggregate_cases(cases)
        if {(c.query_id, c.subset, c.target_count) for c in cases} != signature:
            raise ValueError(f"Mismatched benchmark cases: {name}")
        reports[name] = report
        errors = []
        # Compare metric levels rather than subtracting near-equal binary floats.
        for subset in quality_subsets:
            for metric in gate_metrics:
                base = quality(baseline, subset, metric)
                value = quality(report, subset, metric)
                if subset == "lexical":
                    loss = 1 / 30 if metric == "recall_at_10" else 0.03
                    passes = value >= base - loss
                else:
                    gain = 0.10 if metric == "recall_at_10" else 0.0
                    passes = value >= base + gain
                if not passes:
                    errors.append(f"{subset}.{metric}")
        quality(report, "overall", "ndcg_at_10")
        for subset in SUBSETS:
            if any(c.identity_promotion_error for c in cases if c.subset == subset):
                errors.append(f"{subset}.identity_promotion_error")
        failures[name] = tuple(errors)

    def quality_order(name: str) -> tuple:
        report = reports[name]
        means = tuple(
            mean(quality(report, subset, metric) for subset in ("semantic", "crosslingual"))
            for metric in ("recall_at_10", "ndcg_at_10")
        )
        return (-means[0], -means[1], -quality(report, "overall", "ndcg_at_10"), name)

    qualifying = tuple(sorted((name for name in models if not failures[name]), key=quality_order))
    if not qualifying:
        return ModelChoice(None, None, (), failures)
    leader = qualifying[0]
    comparable = [
        name for name in qualifying
        if all(
            quality(reports[name], subset, "recall_at_10")
            >= quality(reports[leader], subset, "recall_at_10") - 0.025
            for subset in ("semantic", "crosslingual")
        )
        and quality(reports[name], "overall", "ndcg_at_10")
        >= quality(reports[leader], "overall", "ndcg_at_10") - 0.03
    ]
    selected = min(comparable, key=lambda name: (
        models[name].cpu_total_retrieve_p95, models[name].peak_rss,
        models[name].model_plus_index_bytes, name,
    ))
    return ModelChoice(selected, leader, qualifying, failures)
