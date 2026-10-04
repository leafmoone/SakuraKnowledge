"""Read-only replay of frozen responses; no retrieval, models or asset hashing."""
import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from tools import p4_existing_assets_evaluate as replay
from tools import p4_retrieval_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ('lexical', 'dense', 'lexical_pins', 'dense_pins', 'full')


def key(row):
    return metrics.EntryKey(**row['entry'])


def position(rows, target):
    return next((i for i, entry in enumerate(rows, 1) if entry == target), None)


def analyze_case(case, response, manifest):
    original = replay.score_response(case, response, manifest)
    branches = {name: [metrics.Hit(key(row), row['rank']) for row in response[name + '_hits']]
                for name in ('lexical', 'dense')}
    pins = [metrics.TrustedPin(key(p), p['match'], p['source_id'], p['evidence_id'])
            for p in response['trusted_pins']]
    fused = metrics.reciprocal_rank_fusion(branches, pins)
    rankings = {name: list(metrics.deduplicate_ranking(key(row) for row in response[name + '_hits']))
                for name in ('lexical', 'dense')}
    for name in ('lexical', 'dense'):
        rankings[name + '_pins'] = [c.entry for c in metrics.reciprocal_rank_fusion({name: branches[name]}, pins)][:100]
    rankings['full'] = [c.entry for c in fused][:100]
    assert rankings['full'] == replay.keys(response['candidates']) == replay.keys(response['hybrid'])
    targets = [metrics.EntryKey(**t['entry_key']) for t in case['accepted_targets']]
    scored = {name: metrics.evaluate_case(case['case_id'], replay.subset(case), ranking, targets)
              for name, ranking in rankings.items()}
    assert scored['full'] == original['final']
    assert scored['lexical'] == original['lexical'] and scored['dense'] == original['dense']

    def contribution(candidate):
        return {'entry': asdict(candidate.entry), 'final_rank': candidate.hybrid_rank,
                'branch_ranks': dict(candidate.backend_ranks),
                'branch_contributions': {b: 1 / (metrics.RRF_K + r) for b, r in candidate.backend_ranks},
                'rrf_score': candidate.rrf_score,
                'pins': [asdict(p) for p in candidate.trusted_pins]}

    traces = []
    for target, support in zip(targets, case['accepted_targets'], strict=True):
        doc_ranks = [r['rank'] for r in response['lexical_hits'] if key(r) == target]
        dense_ranks = [r['rank'] for r in response['dense_hits'] if key(r) == target]
        lex_rank = position(rankings['lexical'], target)
        final_rank = position(rankings['full'], target)
        best = doc_ranks[0] if doc_ranks else None
        candidate = next((c for c in fused if c.entry == target), None)
        traces.append({'entry': asdict(target), 'gold_support': {
                           n: support[n] for n in ('document_id', 'entry_id', 'title', 'source_id', 'evidence_id', 'excerpt_field', 'excerpt_start') if n in support},
                       'lexical_document_ranks': doc_ranks,
                       'lexical_entity_rank': lex_rank,
                       'dense_entity_rank': position(rankings['dense'], target),
                       'dense_raw_ranks': dense_ranks, 'final_rank': final_rank,
                       'duplicates_before_first_lexical_hit': best - lex_rank if best else None,
                       'in_branch_union': bool(doc_ranks or dense_ranks),
                       'untruncated_fused_rank': candidate.hybrid_rank if candidate else None,
                       'preceding_fused_candidates': [contribution(c) for c in fused[:candidate.hybrid_rank - 1]]
                       if candidate and lex_rank and lex_rank <= 10 and candidate.hybrid_rank > lex_rank else [],
                       'contribution': contribution(candidate) if candidate else None,
                       'lost_from_lexical_top10': bool(lex_rank and lex_rank <= 10 and (final_rank is None or final_rank > 10)),
                       'displacing_top10': [contribution(c) for c in fused[:10] if c.entry not in rankings['lexical'][:10]]
                       if lex_rank and lex_rank <= 10 and (final_rank is None or final_rank > 10) else []})
    delta = {m: (getattr(scored['full'].metrics, m) - getattr(scored['lexical'].metrics, m))
             if getattr(scored['full'].metrics, m) is not None else None for m in metrics.METRICS}
    row = {'case_id': case['case_id'], 'subset': replay.subset(case), 'query': case['query'],
           'variants': {n: asdict(v) for n, v in scored.items()}, 'full_minus_lexical': delta,
           'targets': traces, 'trusted_pins': response['trusted_pins'],
           'branch_depths': {n: len(v) for n, v in branches.items()},
           'unique_branch_depths': {n: len(rankings[n]) for n in branches},
           'branch_union_size': len(set(rankings['lexical']) | set(rankings['dense']))}
    return row, scored


def inspect_union_misses(rows, snapshot, mapping):
    """Only indexed source/document/chunk lookups, never FTS or vector scanning."""
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)) as source, \
            closing(sqlite3.connect(mapping.resolve().as_uri() + '?mode=ro', uri=True)) as chunks:
        for row in rows:
            for target in row['targets']:
                if target['in_branch_union']:
                    continue
                support = target['gold_support']
                document = source.execute('SELECT id,entry_id,title,status,source_id,evidence_id,original FROM documents WHERE id=?',
                                          (support['document_id'],)).fetchone()
                records = chunks.execute('SELECT position,chunk_id,document_id,entry_id,kind,namespace,value,token_start,token_end FROM chunks WHERE document_id=? ORDER BY position',
                                         (support['document_id'],)).fetchall()
                target['union_miss_check'] = {'document': dict(zip(
                    ('id', 'entry_id', 'title', 'status', 'source_id', 'evidence_id', 'excerpt'),
                    (*document[:6], document[6][:160]), strict=True)) if document else None,
                    'chunks': [dict(zip(('position', 'chunk_id', 'document_id', 'entry_id', 'kind', 'namespace', 'value', 'token_start', 'token_end'), v, strict=True)) for v in records],
                    'attribution': 'UNKNOWN: stored branch cutoff cannot distinguish ANN approximation, representation, or query relevance.'}


def analyze(directory, gold_path, questions_path, *, inspect_sources=False):
    saved = json.loads((directory / 'evaluation.json').read_bytes())
    gold = json.loads(gold_path.read_bytes())
    questions = json.loads(questions_path.read_bytes())
    assert questions['gold'] == replay.GOLD
    assert questions['gold_sha256'] == replay.GOLD_SHA == hashlib.sha256(gold_path.read_bytes()).hexdigest()
    cases = sorted(gold['cases'], key=lambda c: c['case_id'])
    assert len(cases) == 120 and len({c['case_id'] for c in cases}) == 120
    assert {p.name for p in directory.glob('formal-*.json')} == {f"formal-{c['case_id']}.json" for c in cases}
    manifest = saved['manifest']
    # Saved evaluation binding contains metadata, not the manifest content.
    if 'contract' not in manifest:
        manifest = json.loads((Path(saved['candidate']) / 'manifest.json').read_bytes())
    rows, scores = [], {n: [] for n in VARIANTS}
    for case in cases:
        response = json.loads((directory / f"formal-{case['case_id']}.json").read_bytes())
        row, scored = analyze_case(case, response, manifest)
        rows.append(row)
        for name in VARIANTS:
            scores[name].append(scored[name])
    aggregates = {n: metrics.aggregate_cases(v) for n, v in scores.items()}
    gate = replay.quality_gate(aggregates['lexical'], aggregates['full'])
    assert gate == saved['quality_gate']
    for name, saved_name in (('lexical', 'lexical'), ('dense', 'dense'), ('full', 'final')):
        assert {s: asdict(v) for s, v in aggregates[name].items()} == saved['aggregates'][saved_name]
    if inspect_sources:
        inspect_union_misses(rows, ROOT / manifest['snapshot']['identity'],
                             Path(saved['candidate']) / manifest['artifacts']['mapping']['path'])
    return {'schema': 'p4-saved-results-analysis-v1', 'retrieval_executed': False,
            'saved_final_reconstruction_matches': 120, 'quality_gate': gate,
            'aggregates': {n: {s: asdict(v) for s, v in a.items()} for n, a in aggregates.items()},
            'cases': rows,
            'limitations': ['Stored top-100 branches only; no ANN versus representation attribution.',
                            'Pins are stored source-backed attestations, not relevance answers.',
                            'Post-diagnosis workload is development/regression, not independent generalization.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--inspect-union-misses', action='store_true', help='indexed readonly document/chunk lookups only')
    args = parser.parse_args()
    result = analyze(args.results, ROOT / replay.GOLD, ROOT / replay.QUERY_CONFIG, inspect_sources=args.inspect_union_misses)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'cases': len(result['cases']), 'quality_gate': result['quality_gate']['status']}))


if __name__ == '__main__':
    main()
