"""Bounded original-vector ANN width comparison; reuse saved lexical/pins."""
import argparse
import copy
import json
import sqlite3
import statistics
import subprocess
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from tools import p4_existing_assets_evaluate as replay
from tools import p4_retrieval_metrics as metrics
from tools.p4_targeted_exact import map_entities

ROOT = Path(__file__).resolve().parents[1]


def replay_dense(case, original, entities, manifest):
    response = copy.deepcopy(original)
    response['dense_hits'] = [{'entry': r['entry'], 'rank': r['entity_rank']} for r in entities]
    branches = {name: [metrics.Hit(metrics.EntryKey(**r['entry']), r['rank']) for r in response[name + '_hits']]
                for name in ('lexical', 'dense')}
    pins = [metrics.TrustedPin(metrics.EntryKey(**p['entry']), p['match'], p['source_id'], p['evidence_id'])
            for p in response['trusted_pins']]
    fused = metrics.reciprocal_rank_fusion(branches, pins)[:100]
    response['hybrid'] = [{'entry': asdict(c.entry)} for c in fused]
    response['candidates'] = [{'entry': asdict(c.entry), 'hybrid_rank': c.hybrid_rank} for c in fused]
    return replay.score_response(case, response, manifest)


def run(binary):
    directory = ROOT / 'build/p4-prepared-lexical-5c8526e-evaluation-v1'
    reference = ROOT / 'reports/P4/five-query-exact-c8bcff6.json'
    frozen = json.loads((ROOT / replay.GOLD).read_bytes())
    cases = sorted(frozen['cases'], key=lambda c: c['case_id'])
    originals = {c['case_id']: json.loads((directory / f"formal-{c['case_id']}.json").read_bytes()) for c in cases}
    assert len(cases) == 120
    for case in cases:
        assert originals[case['case_id']]['query'] == case['query']
    saved = json.loads((directory / 'evaluation.json').read_bytes())
    manifest = json.loads((Path(saved['candidate']) / 'manifest.json').read_bytes())
    completed = subprocess.run([str(binary.resolve()), '--saved-120-ef',
                                str(ROOT / 'build/p4-full-semantic-v1-retry1/vectors.usearch'),
                                str(directory), str(ROOT / 'build/p4-full-semantic-v1-retry1/vectors.npy'),
                                str(reference)], capture_output=True, encoding='utf-8', check=True)
    measured = json.loads(completed.stdout)
    refs = json.loads(reference.read_bytes())['cases']
    comparisons = []
    with closing(sqlite3.connect((ROOT / 'build/p4-full-semantic-v1-retry1/chunks.sqlite').as_uri() + '?mode=ro', uri=True)) as conn:
        for tier in measured['tiers']:
            scores = {n: [] for n in ('lexical', 'dense', 'final')}
            details, timings = [], []
            assert len(tier['cases']) == 120
            for case, probe in zip(cases, tier['cases'], strict=True):
                assert case['case_id'] == probe['case_id']
                chunks, entities = map_entities(conn, probe['positions'], [1 - d for d in probe['distances']])
                original = originals[case['case_id']]
                scored = replay_dense(case, original, entities, manifest)
                old = replay.score_response(case, original, manifest)
                delta = {m: getattr(scored['final'].metrics, m) - getattr(old['final'].metrics, m)
                         if getattr(old['final'].metrics, m) is not None else None for m in metrics.METRICS}
                targets = []
                if case['case_id'] in {r['case_id'] for r in refs}:
                    ref = next(r for r in refs if r['case_id'] == case['case_id'])
                    for target in ref['targets_all_entity_chunks']:
                        targets.append({'entry': target['entry'], 'position': target['position'], 'exact_global_rank': target['global_rank'],
                                        'chunk_rank': next((r['chunk_rank'] for r in chunks if r['position'] == target['position']), None),
                                        'entity_rank': next((r['entity_rank'] for r in entities if r['entry'] == target['entry']), None)})
                details.append({'case_id': case['case_id'], 'subset': replay.subset(case), 'new_final_metrics': asdict(scored['final'].metrics),
                                'delta_vs_saved_full': delta, 'dense_order_changed': [r['entry'] for r in entities] != [r['entry'] for r in original['dense_hits']],
                                'search_ms': probe['search_ms'], 'focused_targets': targets,
                                'negative_nonempty': not case['accepted_targets'] and scored['final'].returned_count > 0,
                                'identity_promotion_error': scored['final'].identity_promotion_error})
                timings.append(probe['search_ms'])
                for name, rows in scores.items():
                    rows.append(scored[name])
            aggregates = {n: metrics.aggregate_cases(rows) for n, rows in scores.items()}
            comparisons.append({'ef_search': tier['ef_search'], 'effective_width': tier['effective_width'],
                                'wanted': 512, 'entity_depth': 100, 'known_exact_top2_target_still_missing': tier['known_exact_top2_target_still_missing'],
                                'aggregates': {n: {g: asdict(v) for g, v in a.items()} for n, a in aggregates.items()},
                                'quality_gate': replay.quality_gate(aggregates['lexical'], aggregates['final']),
                                'ann_search_ms': {'min': min(timings), 'median': statistics.median(timings), 'p95_nearest': sorted(timings)[113], 'max': max(timings)},
                                'cases': details})
    return {'schema': 'p4-bounded-ef-replay-v1', 'target_bits': measured['target_bits'],
            'saved_queries': measured['saved_queries'], 'same_index_instance': measured['same_index_instance'],
            'probe_exit_code': completed.returncode, 'probe_stderr': completed.stderr,
            'baseline_configured_ef': 128, 'baseline_effective_width': 512,
            'baseline_saved_aggregates': saved['aggregates'], 'tiers': comparisons,
            'e2e': 'NOT_RUN', 'selection': 'PENDING', 'generalization': 'NOT_CLAIMED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('exclusive output required')
    result = run(args.binary)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, separators=(',', ':'))
        stream.write('\n')
    print(json.dumps({'target_bits': result['target_bits'], 'tiers': [r['ef_search'] for r in result['tiers']]}))


if __name__ == '__main__':
    main()
