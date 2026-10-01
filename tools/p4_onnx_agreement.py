"""Representation equivalence only; no selection rerun or performance qualification."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools import p4_cpu_representation as cpu
from tools import p4_exact_pilot as exact
from tools import p4_onnx_export as exporter
from tools import p4_selection_v2 as selection

CONTRACT = 'configs/p4-onnx-representation-v2.json'
EXPORT = 'build/p4/bge-onnx-v2'


def numerical(actual, reference):
    """Return JSON-safe observations, including every failed gate, without normalization."""
    import numpy as np

    a, b = np.asarray(actual), np.asarray(reference)
    gates = {'shape': a.shape == b.shape and a.ndim == 2 and a.shape[1] == 1024,
             'dtype': a.dtype == b.dtype == np.dtype('float32'),
             'finite': bool(np.isfinite(a).all() and np.isfinite(b).all())}
    result = {'max_component_error': None, 'min_cosine': None, 'max_norm_error': None}
    if gates['shape'] and gates['finite']:
        a, b = a.astype(np.float64), b.astype(np.float64)
        an, bn = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
        result['max_component_error'] = float(np.max(np.abs(a - b)))
        result['max_norm_error'] = float(max(np.max(abs(an - 1)), np.max(abs(bn - 1))))
        if np.all(an > 0) and np.all(bn > 0):
            result['min_cosine'] = float(np.min(np.sum(a * b, axis=1) / (an * bn)))
    gates.update(max_component_error=result['max_component_error'] is not None and
                 result['max_component_error'] <= 1e-4,
                 min_cosine=result['min_cosine'] is not None and result['min_cosine'] >= .99999,
                 max_norm_error=result['max_norm_error'] is not None and
                 result['max_norm_error'] <= 1e-5)
    result.update(gates=gates, failures=[k for k, v in gates.items() if not v])
    result['status'] = 'FAIL' if result['failures'] else 'PASS'
    return result


def pad_batch(encoded, tokenizer):
    import numpy as np

    exact.require(tokenizer.padding_side == 'right' and type(tokenizer.pad_token_id) is int,
                  'frozen right padding and pad token required')
    ids, masks = encoded['input_ids'], encoded['attention_mask']
    exact.require(len(ids) == len(masks) > 0 and all(ids), 'empty token batch')
    width = max(map(len, ids))
    batch = {'input_ids': np.full((len(ids), width), tokenizer.pad_token_id, dtype=np.int64),
             'attention_mask': np.zeros((len(ids), width), dtype=np.int64)}
    for i, (tokens, mask) in enumerate(zip(ids, masks, strict=True)):
        exact.require(len(tokens) == len(mask) and all(v == 1 for v in mask),
                      'unexpected unpadded attention mask')
        batch['input_ids'][i, :len(tokens)] = tokens
        batch['attention_mask'][i, :len(tokens)] = mask
    return batch


def session(path, ort):
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 8
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    value = ort.InferenceSession(str(path), sess_options=options,
                                 providers=['CPUExecutionProvider'])
    value.disable_fallback()
    exact.require(value.get_providers() == ['CPUExecutionProvider'], 'nonexclusive CPU provider')
    actual = value.get_session_options()
    exact.require(actual.intra_op_num_threads == actual.inter_op_num_threads == 8 and
                  actual.graph_optimization_level == options.graph_optimization_level,
                  'ORT options mismatch')
    inputs = value.get_inputs()
    exact.require([i.name for i in inputs] == ['input_ids', 'attention_mask'], 'ORT input names')
    for item in inputs:
        exact.require(item.type == 'tensor(int64)' and len(item.shape) == 2 and
                      all(isinstance(d, str) and d for d in item.shape), 'ORT dynamic int64 inputs')
    outputs = value.get_outputs()
    exact.require(len(outputs) == 1 and outputs[0].name == 'embeddings' and
                  outputs[0].type == 'tensor(float)' and len(outputs[0].shape) == 2 and
                  isinstance(outputs[0].shape[0], str) and outputs[0].shape[1] == 1024,
                  'ORT dynamic batch FP32 output dimension')
    return value


def rank_agreement(actual, reference):
    import math

    def keys(hits):
        return [tuple((type(h['entry'][k]).__name__, h['entry'][k])
                      for k in ('kind', 'namespace', 'value')) for h in hits]
    a, b = keys(actual), keys(reference)
    gates = {f'ordered_typed_ids_at_{n}': len(a) >= n and len(b) >= n and a[:n] == b[:n]
             for n in (10, 100)}
    error = None
    if len(a) == len(b) == 100 and a == b:
        scores = [(h['score'], r['score']) for h, r in zip(actual, reference, strict=True)]
        if all(math.isfinite(x) and math.isfinite(y) for x, y in scores):
            error = max(abs(x - y) for x, y in scores)
    gates['matching_score_error'] = error is not None and error <= 1e-4
    return {'status': 'PASS' if all(gates.values()) else 'FAIL', 'gates': gates,
            'max_matching_score_error': error,
            'failures': [k for k, v in gates.items() if not v]}


def validate_export(directory, job_path, job, prepared):
    manifest_path = directory / 'manifest.json'
    exact.bound(manifest_path, 'b981d9c2b8f02691a200b9b88da8c778abcbaaaa3d49d0376f88590c89fbbb03')
    manifest = exact.load(manifest_path)
    contract_path = exact.local(CONTRACT)
    contract = exact.load(contract_path)
    reference_path = exact.local(contract['query_reference'])
    exporter.validate_contract(contract, job, reference_path)
    exact.require(manifest['schema'] == 'p4-onnx-export-v2' and manifest['status'] == 'PASS' and
                  type(manifest['export_attempts']) is int and manifest['export_attempts'] == 1 and
                  manifest['onnx_checker'] == 'PASS', 'one checked PASS export required')
    exact.require(manifest['contract'] == contract and contract['ort_optimization'] == 'ORT_ENABLE_ALL',
                  'frozen ONNX contract mismatch')
    exact.require(contract['numerical_gates'] == {'finite': True, 'max_norm_error': 1e-5,
                  'max_component_error': 1e-4, 'min_cosine': .99999}, 'numerical contract mismatch')
    exact.require(manifest['provenance'] == exact.provenance(job, prepared[0], prepared[2]),
                  'export provenance mismatch')
    files = [r for r in exporter.inventory(directory) if r['path'] != 'manifest.json']
    exact.require(files == manifest['files'], 'export inventory mismatch')
    bindings = manifest['input_sha256']
    for name, digest in bindings.items():
        source = Path(name).resolve()
        exact.require(source.is_relative_to(exact.ROOT.resolve()), 'export input path escape')
        exact.bound(source, digest)
    references = exporter.verify_reference(reference_path, contract, job, prepared)
    required = references + [job_path, contract_path, Path(exporter.__file__)]
    exact.require(all(str(p.resolve()) in bindings for p in required), 'missing export input binding')
    exact.bound(directory / 'passage-sample.json', manifest['passage_sample_sha256'])
    paths = list(bindings) + [manifest_path] + [directory / r['path'] for r in files]
    paths += [Path(__file__), exact.local(selection.SOURCE), exact.local(selection.CONFIG),
              exact.local(selection.JOB), Path(selection.__file__),
              exact.local(job['index']) / 'mapping.sqlite']
    return contract, exporter.snapshot(paths)


def execute(job_path, directory, receipt):
    import numpy as np

    receipt['phase'] = 'validation'
    exact.require(job_path == exact.local(exporter.producer.JOB), 'authorized job required')
    exact.require(directory == exact.local(EXPORT), 'authorized export required')
    job = exact.load(job_path)
    prepared = cpu.validate(job)
    contract, before = validate_export(directory, job_path, job, prepared)
    receipt['bindings_sha256'] = exact.canonical_hash(before)
    receipt['input_validations'] = {'before': 'PASS', 'after': 'NOT_COMPLETED'}
    vectors = reference = mapping = ort_session = None
    try:
        model, native, chunks, cases = prepared
        raw, tokenizer = exact.frozen_tokenizers(exact.local(model['asset_directory']))
        sample = exporter.select_passages(job, native, chunks, raw, tokenizer)
        saved_sample = exact.load(directory / 'passage-sample.json')
        sample['reference'] = saved_sample['reference']
        exact.require(sample == saved_sample, 'sample identity/token mismatch')
        vectors, mapping = exact.open_index(job, prepared)
        exact.require(vectors.shape == (52664, 1024), 'pilot matrix shape')
        exact.require(saved_sample['reference'] == {
            'path': contract['passage_sample']['reference'],
            'sha256': exact.sha(exact.local(job['index']) / 'vectors.npy')}, 'sample vector binding')
        reference_dir = exact.local(contract['query_reference']).parent
        reference = np.load(reference_dir / 'vectors.npy', mmap_mode='r', allow_pickle=False)
        query_records = exact.load(reference_dir / 'cases.json')
        receipt['phase'] = 'session'
        import onnxruntime as ort

        ort_session = session(directory / 'model.onnx', ort)
        receipt['runtime'] = {'onnxruntime': ort.__version__, 'numpy': np.__version__,
                              'providers': ort_session.get_providers(), 'threads': 8,
                              'interop_threads': 8, 'optimization': 'ORT_ENABLE_ALL'}
        queries = np.empty((120, 1024), dtype=np.float32)
        receipt['phase'] = 'queries'
        for i, case in enumerate(cases):
            receipt['active'] = {'case_id': case['case_id']}
            encoded, counts = exact.checked_tokens(raw, tokenizer, [case['query']],
                                                    native['query_prefix'], native['max_sequence_tokens'])
            exact.require(counts == [query_records[i]['actual_tokens']], 'query token count mismatch')
            output = ort_session.run(['embeddings'], pad_batch(encoded, tokenizer))[0]
            observation = {'case_id': case['case_id'], **numerical(output, reference[i:i + 1])}
            receipt['queries'].append(observation)
            exact.require(observation['status'] == 'PASS', 'query numerical gates failed')
            queries[i] = output[0]
        receipt['phase'] = 'passages'
        for size in (1, 8):
            for start in range(0, 128, size):
                rows = sample['rows'][start:start + size]
                receipt['active'] = {'batch_size': size, 'sample_offset': start}
                encoded, _ = exact.checked_tokens(raw, tokenizer, [r['text'] for r in rows],
                                                   native['passage_prefix'], native['max_sequence_tokens'])
                output = ort_session.run(['embeddings'], pad_batch(encoded, tokenizer))[0]
                expected = vectors[[r['row_index'] for r in rows]]
                observation = {**receipt['active'], **numerical(output, expected)}
                receipt['passages'].append(observation)
                exact.require(observation['status'] == 'PASS', 'passage numerical gates failed')
        receipt['phase'] = 'ranking'
        selected = exact.load(exact.local(job['selection_receipt']))
        dense_path = exact.local(selected['input_hash_validations']['dense_b']['path'])
        exact.require(dense_path == exact.local(contract['retrieval_agreement']['reference']),
                      'dense reference path mismatch')
        frozen = exact.load(dense_path)['cases']
        frozen_by_id = {c['case_id']: c for c in frozen}
        exact.require(len(frozen) == len(frozen_by_id) == 120 and
                      set(frozen_by_id) == {c['case_id'] for c in cases}, 'dense case coverage')
        for i, case in enumerate(cases):
            receipt['active'] = {'case_id': case['case_id']}
            old = frozen_by_id[case['case_id']]
            exact.require(old['status'] == 'PASS', 'frozen dense case failed')
            hits = exact.exact_rank(vectors, mapping, queries[i], depth=100)
            observation = {'case_id': case['case_id'], **rank_agreement(hits, old['hits'])}
            receipt['ranking'].append(observation)
            exact.require(observation['status'] == 'PASS', 'ranking agreement gates failed')
        receipt['phase'] = 'quality'
        recomputed = selection.verify(exact.ROOT)
        exact.require(recomputed == selected, 'pinned quality recomputation mismatch')
        metrics = exact.load(exact.local(selection.SOURCE))['metrics']
        gates = selection.quality_gates(metrics['BM25_ONLY'], metrics['RRF_HYBRID_MODEL_B'])
        receipt['quality'] = {'gates': gates, 'source_sha256': selection.SOURCE_SHA256,
                              'implication': 'All ordered typed top100 identities are identical. Unchanged '
                              'BM25 and rank-only RRF therefore preserve frozen fusion and metrics; '
                              'score tolerance is checked separately. No BM25 queries or selection rerun.'}
        exact.require(all(g['pass'] for g in gates.values()), 'v2 quality gates failed')
    finally:
        if mapping is not None:
            mapping.connection.close()
        for array in (vectors, reference):
            if array is not None:
                array._mmap.close()
        del ort_session
        # Also check after a numerical failure; preserve the original observations.
        try:
            exact.require(exporter.snapshot(before) == before, 'post-run bindings changed')
            exact.require(cpu.validate(exact.load(job_path)) == prepared, 'post-run validation changed')
            exporter.verify_reference(exact.local(contract['query_reference']), contract, job, prepared)
            receipt['input_validations']['after'] = 'PASS'
        except Exception as exc:
            receipt['input_validations']['after'] = 'FAIL'
            receipt['post_validation_error'] = str(exc)
            raise
    receipt['phase'] = 'complete'
    receipt.pop('active', None)


def run(job_path, export_dir, output):
    receipt = {'schema': 'p4-onnx-agreement-v2', 'status': 'FAIL',
               'scope': 'representation equivalence only', 'selection_rerun': False,
               'performance_qualified': False, 'fallback': False, 'retries': 0,
               'queries': [], 'passages': [], 'ranking': []}
    try:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        stream = output.open('x', encoding='utf-8')
    except OSError as exc:
        print(f'cannot reserve exclusive receipt: {exc}', file=sys.stderr)
        return 1
    with stream:
        try:
            execute(exact.local(str(job_path)), exact.local(str(export_dir)), receipt)
            receipt['status'] = 'PASS'
        except Exception as exc:  # noqa: BLE001 - one FAIL receipt; no retries or fallback.
            receipt['error'] = f'{type(exc).__name__}: {exc}'
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return 0 if receipt['status'] == 'PASS' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('job', 'export-dir', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    return run(args.job, args.export_dir, args.output)


if __name__ == '__main__':
    raise SystemExit(main())
