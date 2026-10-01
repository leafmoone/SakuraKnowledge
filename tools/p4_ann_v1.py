"""Local-only ANN grid; no embedding, exact search, fallback, or retries.

CLI: python -m tools.p4_ann_v1 --config configs/p4-ann-v1.json
     --config-sha256 HEX
Contract: {schema: p4-ann-contract-v1, output: reports/P4/ann-v1.json,
raw_directory: build/p4/ann-v1, inputs: {NAME: {path: PATH, sha256: HEX}}}.
The six NAME/PATH pairs are fixed in INPUTS. All policy is fixed here.
"""
from __future__ import annotations

import argparse
import copy
import importlib.metadata
import math
import platform
import time
from statistics import mean

from tools import p4_onnx_cpu_v3 as cpu
from tools import p4_onnx_quality_v3 as quality

exact, score, selection = quality.exact, quality.score, quality.selection
EntryKey = quality.arithmetic.EntryKey
CONFIG = 'configs/p4-ann-v1.json'
RAW = 'build/p4/ann-v1'
OUTPUT = 'reports/P4/ann-v1.json'
INPUTS = {
    'vectors': 'build/p4/continuation-dense-b-v1/vectors.npy',
    'mapping': 'build/p4/continuation-dense-b-v1/mapping.sqlite',
    'queries': 'build/p4/onnx-quality-v3/queries.npy',
    'ranks': 'build/p4/onnx-quality-v3/ranks.json',
    'quality_receipt': 'reports/P4/onnx-quality-v3-retry1.json',
    'cpu_receipt': 'reports/P4/onnx-cpu-v3-retry1.json',
}
POLICY = {'usearch': '2.26.2', 'dtype': 'f32', 'metric': 'cos', 'dimension': 1024,
          'multi': False, 'rows': 52664, 'threads': 8, 'chunk_neighbors': 512,
          'entry_depth': 100, 'warmups': 2, 'samples': 120, 'retries': 0,
          'M': [16, 32], 'Eadd': [128, 256], 'ef': [32, 64, 128, 256],
          'timing_scope': 'single-query index.search only', 'tie_window_ms': .05}


def grid():
    return [(m, add, ef) for m in POLICY['M'] for add in POLICY['Eadd'] for ef in POLICY['ef']]


def snapshot(paths):
    return {str(path): exact.sha(path) for path in paths}


def validate_contract(config):
    exact.require(set(config) == {'schema', 'output', 'raw_directory', 'inputs'} and
                  config['schema'] == 'p4-ann-contract-v1' and config['output'] == OUTPUT and
                  config['raw_directory'] == RAW, 'unsupported ANN contract')
    exact.require(set(config['inputs']) == set(INPUTS), 'six input bindings required')
    for name, path in INPUTS.items():
        binding = config['inputs'][name]
        exact.require(set(binding) == {'path', 'sha256'} and binding['path'] == path,
                      f'wrong binding: {name}')
        exact.bound(exact.local(path), binding['sha256'])


def load_backend():
    # Importing this module and all synthetic tests must not require USearch.
    exact.require(importlib.metadata.version('usearch') == POLICY['usearch'],
                  'usearch 2.26.2 required')
    from usearch.index import Index
    return Index


def entry_hits(keys, distances, mapping, depth=100):
    """Keep the first distance-ordered chunk for each typed source identity."""
    exact.require(len(keys) == len(distances) == 512, '512 chunk matches required')
    hits, seen, row_keys = [], set(), set()
    previous = -math.inf
    for raw_key, raw_distance in zip(keys, distances, strict=True):
        key, distance = int(raw_key), float(raw_distance)
        exact.require(key == raw_key and 0 <= key < len(mapping) and key not in row_keys,
                      'invalid/duplicate ANN row key')
        exact.require(math.isfinite(distance) and distance >= previous, 'unordered/nonfinite distances')
        previous = distance
        row_keys.add(key)
        row = mapping[key]
        identity = EntryKey(**row['entry_key'])
        if identity in seen:
            continue
        seen.add(identity)
        if len(hits) < depth:
            hits.append({'entry': row['entry_key'], 'rank': len(hits) + 1,
                         'score': 1.0 - distance, **{field: str(row[field]) for field in
                         ('chunk_id', 'document_id', 'source_id', 'evidence_id')}})
    exact.require(len(hits) == depth, 'fewer than 100 unique entries; no backfill')
    return hits


def recall_rows(actual, reference):
    def keys(hits):
        result = [EntryKey(**hit['entry']) for hit in hits]
        exact.require(len(result) == len(set(result)) == 100, '100 unique typed entries required')
        exact.require([hit['rank'] for hit in hits] == list(range(1, 101)), 'invalid ranks')
        return result
    a, b = keys(actual), keys(reference)
    return {str(k): len(set(a[:k]) & set(b[:k])) / k for k in (10, 20, 100)}


def approximation(rows):
    exact.require(len(rows) == 120, '120 approximation observations required')
    result = {}
    for k, macro, minimum in ((10, .98, .8), (20, .98, .8), (100, .95, .9)):
        values = [row[str(k)] for row in rows]
        exact.require(all(math.isfinite(v) and 0 <= v <= 1 for v in values), 'invalid recall')
        result[str(k)] = {'macro': mean(values), 'minimum': min(values),
                          'macro_threshold': macro, 'minimum_threshold': minimum,
                          'pass': mean(values) >= macro and min(values) >= minimum}
    return result


def choose(candidates):
    passing = [row for row in candidates if row['status'] == 'PASS']
    if not passing:
        return None
    fastest = min(row['p95_ms'] for row in passing)
    pool = [row for row in passing if row['p95_ms'] <= fastest + .05]
    return min(pool, key=lambda row: (row['index_bytes'], row['M'], row['Eadd'], row['ef']))['id']


def score_cases(inputs, cases):
    # Compatibility adapter only: inherited exact metadata is not an ANN claim.
    dense = copy.deepcopy(inputs[3])
    dense['b']['cases'] = cases
    bindings = {**inputs[6], 'dense_b': exact.canonical_hash(dense['b'])}
    return score.score(*inputs[:3], dense, *inputs[4:6], bindings)


def quality_result(metrics, baseline):
    # quality() applies v2 capped gates, all-subset regressions, and dense safety.
    result = quality.quality(metrics, baseline)
    result['metrics'] = {'ANN_DENSE_B': metrics['EXACT_DENSE_MODEL_B'],
                         'ANN_HYBRID_B': metrics['RRF_HYBRID_MODEL_B']}
    for gate in result['gates'].values():
        if 'native' in gate:
            gate['onnx_exact'] = gate.pop('native')
            gate['ann'] = gate.pop('onnx')
    return result


def relevance_changes(baseline, actual):
    rows = quality.relevance_changes(baseline, actual)
    for row in rows:
        row['modes'] = {name.replace('ONNX_', 'ANN_'): mode for name, mode in row['modes'].items()}
        for mode in row['modes'].values():
            for metric in mode['metrics'].values():
                metric['onnx_exact'] = metric.pop('native')
                metric['ann'] = metric.pop('onnx')
    return rows


def measure(index, queries, cases, mapping, clock=time.perf_counter):
    warmups, rows = [], []
    for i in range(2):
        try:
            matches = index.search(queries[i], count=512, threads=8, exact=False)
            entry_hits(matches.keys, matches.distances, mapping)
            warmups.append({'case_id': cases[i]['case_id'], 'status': 'PASS'})
        except Exception as exc:  # noqa: BLE001 - retain every failure without retry.
            warmups.append({'case_id': cases[i]['case_id'], 'status': 'FAIL', 'error': str(exc)})
    for query, case in zip(queries, cases, strict=True):
        row = {'case_id': case['case_id'], 'status': 'FAIL'}
        try:
            start = clock()
            matches = index.search(query, count=512, threads=8, exact=False)
            elapsed = (clock() - start) * 1000
            exact.require(math.isfinite(elapsed) and elapsed >= 0, 'invalid timing')
            row['search_ms'] = elapsed
            # All result validation, mapping and dedup are outside the search timer.
            row['chunk_keys'] = [int(key) for key in matches.keys]
            # Nonfinite failures must remain serializable, never abort the remaining grid.
            row['distances'] = [float(d) if math.isfinite(float(d)) else str(float(d))
                                for d in matches.distances]
            row['hits'] = entry_hits(matches.keys, matches.distances, mapping)
            row['recall'] = recall_rows(row['hits'], case['hits'])
            row['status'] = 'PASS'
        except Exception as exc:  # noqa: BLE001 - formal failures count; continue once through all queries.
            row['error'] = f'{type(exc).__name__}: {exc}'
        rows.append(row)
    return warmups, rows


def prepare(config):
    validate_contract(config)
    selection.verify(exact.ROOT)
    inputs = quality.score_inputs()
    quality_receipt = cpu.quality_gate(exact.local(INPUTS['quality_receipt']),
                                     config['inputs']['quality_receipt']['sha256'])
    cpu_receipt = exact.load(exact.local(INPUTS['cpu_receipt']))
    exact.require(cpu_receipt['schema'] == 'p4-onnx-cpu-v3' and cpu_receipt['status'] == 'PASS' and
                  cpu_receipt['performance_qualified'] is True and cpu_receipt['bindings_after'] == 'PASS',
                  'CPU retry1 receipt must qualify')
    exact.require(cpu_receipt['quality_receipt'] == INPUTS['quality_receipt'] and
                  cpu_receipt['quality_receipt_sha256'] == config['inputs']['quality_receipt']['sha256'],
                  'CPU/quality binding mismatch')
    for name in ('vectors', 'mapping'):
        exact.require(quality_receipt['input_sha256'].get(str(exact.local(INPUTS[name]))) ==
                      config['inputs'][name]['sha256'], 'quality native index binding mismatch')
    for name in ('queries', 'ranks'):
        exact.require(quality_receipt['raw_sha256'].get(str(exact.local(INPUTS[name]))) ==
                      config['inputs'][name]['sha256'], 'quality raw binding mismatch')
    ranks = exact.load(exact.local(INPUTS['ranks']))
    cases = ranks['cases']
    ids = [case['case_id'] for case in cases]
    exact.require(ranks['schema'] == 'p4-onnx-raw-v3' and ranks['representation'] == 'ONNX_DENSE_B' and
                  ranks['input_bindings_sha256'] == quality_receipt['bindings_sha256'] and
                  ranks['case_order'] == ids == sorted(score.case_map(inputs[0]['cases'])) and
                  len(ids) == 120, 'exact ONNX rank reference mismatch')
    score.case_map(cases, ids)
    baseline, baseline_details = score_cases(inputs, cases)
    for new, old in quality.MODES.items():
        exact.require(baseline['metrics'][old] == quality_receipt['quality']['metrics'][new],
                      'ONNX baseline scoring mismatch')
    return inputs, cases, baseline['metrics'], baseline_details


def execute(config, receipt, raw):
    import numpy as np

    inputs, cases, baseline, baseline_details = prepare(config)
    Index = load_backend()
    receipt['runtime'] = {'usearch': POLICY['usearch'], 'numpy': np.__version__,
                          'platform': platform.platform(), 'processor': platform.processor(),
                          'threads': 8, 'memory_scope': 'process RSS/peak; peak cumulative across grid'}
    vectors = queries = disk = None
    try:
        vectors = np.load(exact.local(INPUTS['vectors']), mmap_mode='r', allow_pickle=False)
        queries = np.load(exact.local(INPUTS['queries']), mmap_mode='r', allow_pickle=False)
        exact.require(vectors.shape == (52664, 1024) and queries.shape == (120, 1024), 'matrix shapes')
        exact.validate_vectors(vectors, 1024)
        exact.validate_vectors(queries, 1024)
        disk = exact.DiskMapping(exact.local(INPUTS['mapping']))
        mapping = disk.block(0, 52664)
        exact.require(len(disk) == len(mapping) == 52664, 'mapping rows')
        positions = disk.connection.execute('SELECT min(position), max(position) FROM chunks').fetchone()
        exact.require(positions == (0, 52663), 'mapping row key range')
        # Validate every row against the frozen corpus before any ANN build.
        corpus = score.Mapping(inputs[1])
        for row in mapping:
            doc = corpus.documents.get(str(row['document_id']))
            exact.require(doc is not None and doc['entry_key'] == row['entry_key'] and
                          all(str(doc[k]) == str(row[k]) for k in ('source_id', 'evidence_id')),
                          'chunk/corpus provenance mismatch')
        keys = np.arange(52664, dtype=np.uint64)
        for m in POLICY['M']:
            for add in POLICY['Eadd']:
                index = None
                build = {'M': m, 'Eadd': add, 'status': 'FAIL'}
                try:
                    start = time.perf_counter()
                    index = Index(ndim=1024, metric='cos', dtype='f32', connectivity=m,
                                  expansion_add=add, expansion_search=32, multi=False)
                    index.add(keys, vectors, threads=8, copy=True)
                    build['build_seconds'] = time.perf_counter() - start
                    exact.require(len(index) == 52664 and bool(index.contains(keys).all()), 'index keys')
                    path = raw / f'M{m}-Eadd{add}.usearch'
                    exact.require(not path.exists(), 'index overwrite forbidden')
                    index.save(str(path))
                    build.update(status='PASS', index_bytes=path.stat().st_size,
                                 index_sha256=exact.sha(path), memory=exact.rss(),
                                 index_memory_bytes=int(index.memory_usage),
                                 hardware_acceleration=str(index.hardware_acceleration))
                except Exception as exc:  # noqa: BLE001 - one failed build fails its four candidates.
                    build['error'] = f'{type(exc).__name__}: {exc}'
                receipt['builds'].append(build)
                for ef in POLICY['ef']:
                    candidate = {'id': f'M{m}-Eadd{add}-ef{ef}', 'M': m, 'Eadd': add,
                                 'ef': ef, 'status': 'FAIL', 'failures': []}
                    detail = {'candidate': candidate, 'source': 'ANN; exact schema used only as scorer adapter'}
                    try:
                        exact.require(build['status'] == 'PASS', 'build failed; candidate not retried')
                        candidate['index_bytes'] = build['index_bytes']
                        index.expansion_search = ef
                        exact.require(index.expansion_search == ef, 'search expansion mismatch')
                        warmups, rows = measure(index, queries, cases, mapping)
                        detail.update(warmups=warmups, queries=rows)
                        candidate['formal_failures'] = sum(row['status'] != 'PASS' for row in rows)
                        candidate['formal_samples'] = len(rows)
                        exact.require(all(row['status'] == 'PASS' for row in warmups + rows), 'search failures')
                        timings = [row['search_ms'] for row in rows]
                        candidate['p50_ms'] = float(np.percentile(timings, 50))
                        candidate['p95_ms'] = float(np.percentile(timings, 95))
                        candidate['max_ms'] = max(timings)
                        candidate['approximation'] = approximation([row['recall'] for row in rows])
                        exact.require(all(gate['pass'] for gate in candidate['approximation'].values()),
                                      'approximation gates failed')
                        new_cases = [{**case, 'hits': row['hits']} for case, row in zip(cases, rows, strict=True)]
                        actual, details = score_cases(inputs, new_cases)
                        gates = quality_result(actual['metrics'], baseline)
                        detail.update(quality=gates, score_details=details,
                                      per_case_changes=relevance_changes(baseline_details, details))
                        candidate['quality'] = gates
                        candidate['failures'].extend(gates['failures'])
                        candidate['status'] = 'FAIL' if candidate['failures'] else 'PASS'
                    except Exception as exc:  # noqa: BLE001 - retain failed candidates, never rerun.
                        candidate['failures'].append(f'{type(exc).__name__}: {exc}')
                    candidate.setdefault('formal_samples', 0)
                    candidate.setdefault('formal_failures', 120)
                    exact.save(raw / (candidate['id'] + '.json'), detail)
                    receipt['candidates'].append(candidate)
                del index
    finally:
        if disk is not None:
            disk.connection.close()
        for array in (vectors, queries):
            if array is not None:
                array._mmap.close()
    receipt['selected'] = choose(receipt['candidates'])
    receipt['failed_candidates'] = sum(row['status'] != 'PASS' for row in receipt['candidates'])
    receipt['formal_failures'] = sum(row['formal_failures'] for row in receipt['candidates'])
    receipt['status'] = 'PASS' if receipt['selected'] is not None else 'FAIL'


def run(config_path, digest):
    exact.require(config_path == CONFIG, 'fixed ANN config path required')
    path = exact.local(config_path)
    exact.bound(path, digest)
    config = exact.load(path)
    exact.require(not exact.local(OUTPUT).exists(), 'summary exists; overwrite forbidden')
    raw = exact.local(RAW)
    raw.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'p4-ann-v1', 'status': 'FAIL', 'policy': POLICY,
               'config_sha256': digest, 'builds': [], 'candidates': [], 'selected': None,
               'performance_scope': 'ANN search only; not end-to-end hybrid qualification',
               'raw_directory': RAW, 'raw_local_only': True, 'retries': 0,
               'embedding_rerun': False, 'exact_search_rerun': False}
    before = None
    try:
        validate_contract(config)
        job = exact.load(exact.local(selection.JOB))
        paths = [path, exact.local(selection.JOB), exact.local(selection.CONFIG),
                 exact.local(selection.SOURCE), *[exact.local(p) for p in INPUTS.values()],
                 *[exact.local(job[key]) for key in selection.BINDINGS.values()]]
        before = snapshot(paths)
        receipt['input_sha256_before'] = before
        execute(config, receipt, raw)
    except Exception as exc:  # noqa: BLE001 - persist setup failure, fail closed.
        receipt.update(status='FAIL', error=f'{type(exc).__name__}: {exc}', selected=None)
    finally:
        if before is not None:
            try:
                after = snapshot(before)
                receipt['input_sha256_after'] = after
                exact.require(after == before, 'post-run input hashes changed')
                validate_contract(config)
                receipt['input_validations'] = {'before': 'PASS', 'after': 'PASS'}
            except Exception as exc:  # noqa: BLE001 - tampering invalidates any selected candidate.
                receipt.update(status='FAIL', selected=None, post_validation_error=str(exc),
                               input_validations={'before': 'PASS', 'after': 'FAIL'})
    exact.save(exact.local(OUTPUT), receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=CONFIG)
    parser.add_argument('--config-sha256', required=True)
    args = parser.parse_args(argv)
    return int(run(args.config, args.config_sha256)['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
