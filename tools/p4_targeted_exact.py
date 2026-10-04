"""Five-query development diagnostic: one readonly vector pass, no retrieval runtime."""
import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import numpy as np

CASES = ('P4-033', 'P4-035', 'P4-039', 'P4-042', 'P4-064')
ROOT = Path(__file__).resolve().parents[1]


def cosine(block, queries):
    block = np.asarray(block, dtype=np.float64)
    queries = np.asarray(queries, dtype=np.float64)
    if block.ndim != 2 or queries.ndim != 2 or block.shape[1] != queries.shape[1]:
        raise ValueError('matrix shape mismatch')
    norms = np.linalg.norm(block, axis=1)
    qnorms = np.linalg.norm(queries, axis=1)
    if not np.isfinite(block).all() or not np.isfinite(queries).all() or np.any(norms == 0) or np.any(qnorms == 0):
        raise ValueError('nonfinite/zero vector')
    dots = np.column_stack([np.einsum('ij,j->i', block, query, optimize=False) for query in queries])
    return dots / norms[:, None] / qnorms[None, :]


def scan_cos(vectors, queries, target_positions, *, depth=512, block_size=4096, tolerance=1e-7):
    if len(vectors) == 0 or depth < 1 or block_size < 1 or len(queries) != len(target_positions):
        raise ValueError('invalid scan dimensions')
    targets = []
    for index, positions in enumerate(target_positions):
        if len(set(positions)) != len(positions) or any(p < 0 or p >= len(vectors) for p in positions):
            raise ValueError('invalid/duplicate target position')
        scores = cosine(vectors[positions], queries[index:index + 1])[:, 0] if positions else np.array([])
        targets.append([{'position': p, 'cosine': float(s), 'strict_greater': 0, 'near_greater': 0,
                         'near_count': 0, 'equal_before': 0} for p, s in zip(positions, scores, strict=True)])
    top = [([], []) for _ in queries]
    started = time.perf_counter()
    for start in range(0, len(vectors), block_size):
        stop = min(start + block_size, len(vectors))
        scores = cosine(vectors[start:stop], queries)
        positions = np.arange(start, stop)
        for index in range(len(queries)):
            column = scores[:, index]
            for target in targets[index]:
                value = target['cosine']
                target['strict_greater'] += int(np.count_nonzero(column > value))
                target['near_greater'] += int(np.count_nonzero(column > value + tolerance))
                target['near_count'] += int(np.count_nonzero(np.abs(column - value) <= tolerance))
                target['equal_before'] += int(np.count_nonzero((column == value) & (positions < target['position'])))
            old_positions, old_scores = top[index]
            combined_positions = np.concatenate((old_positions, positions)).astype(np.int64)
            combined_scores = np.concatenate((old_scores, column))
            # Exact score ordering, deterministic position tie diagnostic (not asserted ANN tie policy).
            order = np.lexsort((combined_positions, -combined_scores))[:depth]
            top[index] = combined_positions[order], combined_scores[order]
    for entries in targets:
        for target in entries:
            target['global_rank'] = 1 + target['strict_greater'] + target['equal_before']
            target['near_rank_interval'] = [1 + target['near_greater'], target['near_greater'] + target['near_count']]
    return top, targets, (time.perf_counter() - started) * 1000


def map_entities(connection, positions, scores, *, limit=100):
    if len(set(map(int, positions))) != len(positions):
        raise ValueError('duplicate chunk positions')
    entities, chunks, seen = [], [], set()
    for rank, (position, score) in enumerate(zip(positions, scores, strict=True), 1):
        found = connection.execute('SELECT metadata FROM chunks WHERE position=?', (int(position),)).fetchone()
        if found is None:
            raise ValueError('unmapped chunk')
        meta = json.loads(found[0])
        entry = meta['entry_key']
        identity = tuple(entry[n] for n in ('kind', 'namespace', 'value'))
        if entry['kind'] == 'episode':
            raise ValueError('FULL episode excluded')
        row = {'chunk_rank': rank, 'position': int(position), 'cosine': float(score),
               'distance': 1 - float(score), 'chunk_id': meta['chunk_id'],
               'document_id': meta['document_id'], 'entry': entry}
        chunks.append(row)
        if identity not in seen:
            seen.add(identity)
            if len(entities) < limit:
                entities.append({**row, 'entity_rank': len(entities) + 1})
    return chunks, entities


def run():
    directory = ROOT / 'build/p4-prepared-lexical-5c8526e-evaluation-v1'
    gold = json.loads((ROOT / 'reports/P4/retrieval-gold.json').read_bytes())
    responses = [json.loads((directory / f'formal-{case}.json').read_bytes()) for case in CASES]
    cases = [next(c for c in gold['cases'] if c['case_id'] == name) for name in CASES]
    for case, response in zip(cases, responses, strict=True):
        vector = response['vector']
        if response['query'] != case['query'] or len(vector) != 1024 or not np.isfinite(vector).all():
            raise ValueError('saved query/vector mismatch')
    queries = np.asarray([r['vector'] for r in responses], dtype=np.float64)
    vectors = np.load(ROOT / 'build/p4-full-semantic-v1-retry1/vectors.npy', mmap_mode='r', allow_pickle=False)
    if vectors.shape != (1366520, 1024) or vectors.dtype != np.dtype('float32'):
        raise ValueError('unexpected frozen vector matrix')
    mapping = ROOT / 'build/p4-full-semantic-v1-retry1/chunks.sqlite'
    with closing(sqlite3.connect(mapping.as_uri() + '?mode=ro', uri=True)) as conn:
        all_targets, positions = [], []
        for case in cases:
            records = []
            for target in case['accepted_targets']:
                k = target['entry_key']
                matches = conn.execute('SELECT position,chunk_id,document_id FROM chunks WHERE kind=? AND namespace=? AND value=? ORDER BY position',
                                       tuple(k[n] for n in ('kind', 'namespace', 'value'))).fetchall()
                records.extend({'entry': k, 'position': p, 'chunk_id': cid, 'document_id': did} for p, cid, did in matches)
            all_targets.append(records)
            positions.append([r['position'] for r in records])
        top, ranks, elapsed = scan_cos(vectors, queries, positions)
        rows = []
        for index, case in enumerate(cases):
            chunks, all_entities = map_entities(conn, *top[index], limit=512)
            entities = all_entities[:100]
            targets = []
            for record, rank in zip(all_targets[index], ranks[index], strict=True):
                entity_rank = next((r['entity_rank'] for r in entities if r['entry'] == record['entry']), None)
                saved_rank = next((r['rank'] for r in responses[index]['dense_hits'] if r['entry'] == record['entry']), None)
                targets.append({**record, **rank, 'exact_in_top512': rank['position'] in set(map(int, top[index][0])),
                                'exact_entity_rank': entity_rank,
                                'exact_entity_rank_before_cap': next((r['entity_rank'] for r in all_entities if r['entry'] == record['entry']), None),
                                'saved_ann_entity_rank': saved_rank})
            # Stored entities cannot reveal whether an absent target was among historical raw 512 chunks.
            classification = 'C' if targets and all(t['near_rank_interval'][0] > 512 for t in targets) else 'E'
            rows.append({'case_id': case['case_id'], 'query': case['query'], 'query_vector_source': 'original formal response vector (Rust f32 serialized); no re-encoding',
                         'targets_all_entity_chunks': targets, 'exact_top512_chunks': chunks, 'exact_top100_entities': entities,
                         'saved_ann_top100_entities': responses[index]['dense_hits'], 'classification': classification,
                         'reason': 'Exact target chunks below 512 cutoff: candidate budget/representation relevance, not demonstrated ANN loss.'
                         if classification == 'C' else 'Historical raw ANN chunks absent; exact versus saved entities alone cannot resolve ANN versus entity truncation.',
                         'historical_raw_chunk_overlap': 'NOT_AVAILABLE'})
    return {'schema': 'p4-five-query-exact-v1', 'development_only': True, 'full_exact_overlap': 'NOT_RUN',
            'vector_shape': list(vectors.shape), 'vector_dtype': str(vectors.dtype),
            'scan_ms': elapsed, 'full_vector_passes': 1, 'block_rows': 4096,
            'float64_block_payload_bytes': 4096 * 1024 * 8, 'rss': 'NOT_MEASURED',
            'cosine': 'float64 dot divided by both actual norms; distance=1-cosine',
            'exact_tie_order': 'position ascending; ANN equal-distance order is not guaranteed',
            'near_tolerance': 1e-7, 'near_tie_handling': 'rank intervals reported separately; no score rounding or altered exact ordering',
            'cases': rows}


def compare_ann(result, probe, connection):
    """Attach new raw measurement; never infer historical chunk overlap."""
    result['ann_probe_open_ms'] = probe['open_ms']
    for row, measured in zip(result['cases'], probe['cases'], strict=True):
        if row['case_id'] != measured['case_id']:
            raise ValueError('ANN case mismatch')
        chunks, all_entities = map_entities(connection, measured['positions'],
                                           [1 - d for d in measured['distances']], limit=512)
        entities = all_entities[:100]
        matched = [v['entry'] for v in entities] == [v['entry'] for v in row['saved_ann_top100_entities']]
        row['new_ann_probe'] = {'new_measurement_not_historical': True, 'search_ms': measured['search_ms'],
                                'ef_search': 128, 'depth': 512, 'raw_chunks': chunks,
                                'entities': entities, 'saved_entity_order_matches': matched,
                                'exact512_chunk_intersection': len(set(measured['positions']) &
                                                                  {v['position'] for v in row['exact_top512_chunks']})}
        for target in row['targets_all_entity_chunks']:
            target['new_ann_chunk_rank'] = next((v['chunk_rank'] for v in chunks if v['position'] == target['position']), None)
            target['new_ann_entity_rank'] = next((v['entity_rank'] for v in entities if v['entry'] == target['entry']), None)
            target['new_ann_entity_rank_before_cap'] = next((v['entity_rank'] for v in all_entities if v['entry'] == target['entry']), None)
        targets = row['targets_all_entity_chunks']
        if targets and any(t['exact_entity_rank'] is not None for t in targets) and all(t['new_ann_chunk_rank'] is None for t in targets):
            row['classification'] = 'A' if matched else 'E'
            row['reason'] = 'New original-parameter ANN excludes exact top100 entity target chunks; saved entity order ' + ('matches.' if matched else 'differs: cannot attribute historical omission.')
        elif targets and any(t['exact_in_top512'] for t in targets) and all(t['exact_entity_rank'] is None for t in targets):
            row['classification'] = 'B'
            row['reason'] = 'Exact chunk present within512 but first-occurrence entity rank exceeds100; new ANN raw ranks recorded separately.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--ann-probe', type=Path, help='existing Rust usearch_path_probe executable; one readonly original-parameter batch')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('exclusive diagnostic output required')
    result = run()
    if args.ann_probe:
        import subprocess
        completed = subprocess.run([str(args.ann_probe.resolve()), '--saved-five-query',
                                    str(ROOT / 'build/p4-full-semantic-v1-retry1/vectors.usearch'),
                                    str(ROOT / 'build/p4-prepared-lexical-5c8526e-evaluation-v1')],
                                   capture_output=True, text=True, encoding='utf-8', check=True)
        with closing(sqlite3.connect((ROOT / 'build/p4-full-semantic-v1-retry1/chunks.sqlite').as_uri() + '?mode=ro', uri=True)) as conn:
            compare_ann(result, json.loads(completed.stdout), conn)
        result['ann_probe_exit_code'] = completed.returncode
        result['ann_probe_stderr'] = completed.stderr
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'cases': len(result['cases']), 'scan_ms': result['scan_ms']}))


if __name__ == '__main__':
    main()
