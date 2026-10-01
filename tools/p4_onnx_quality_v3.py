"""Quality-gated ONNX representation; never calls v2's fail-fast ranking runner."""
from __future__ import annotations

import argparse
import copy
import json
import math
import subprocess
from dataclasses import asdict
from pathlib import Path

from tools import p4_onnx_agreement as agreement
from tools import p4_pilot_score as score
from tools import p4_retrieval_metrics as arithmetic

exact = agreement.exact
exporter = agreement.exporter
selection = agreement.selection
CONTRACT = 'configs/p4-onnx-representation-v3.json'
OUTPUT = 'reports/P4/onnx-quality-v3.json'
RAW = 'build/p4/onnx-quality-v3'
MODES = {'ONNX_DENSE_B': 'EXACT_DENSE_MODEL_B', 'ONNX_HYBRID_B': 'RRF_HYBRID_MODEL_B'}


def rank_diagnostics(actual, native):
    """Typed set and common-ID comparisons do not require identical order."""
    def index(hits):
        keys = [arithmetic.EntryKey(**h['entry']) for h in hits]
        exact.require(len(keys) == 100 and len(set(keys)) == 100, '100 unique typed hits required')
        exact.require([h['rank'] for h in hits] == list(range(1, 101)), 'invalid raw ranks')
        exact.require(all(type(h['score']) in (int, float) and math.isfinite(h['score'])
                          for h in hits), 'nonfinite rank score')
        return keys, dict(zip(keys, hits, strict=True))

    a, ai = index(actual)
    b, bi = index(native)
    result = {'diagnostic_only': True,
              'ordered': {str(k): a[:k] == b[:k] for k in (10, 100)},
              'overlaps': {}, 'common_id_score_errors': {}, 'first_mismatch': None}
    for k in (10, 20, 100):
        common = set(a[:k]) & set(b[:k])
        result['overlaps'][str(k)] = {'count': len(common), 'denominator': k,
                                      'fraction': len(common) / k,
                                      'entries': [asdict(key) for key in sorted(common)]}
        if k in (10, 100):
            errors = [abs(ai[key]['score'] - bi[key]['score']) for key in common]
            result['common_id_score_errors'][str(k)] = {
                'count': len(errors), 'maximum': max(errors) if errors else None}
    for i, (ak, bk) in enumerate(zip(a, b, strict=True), 1):
        if ak != bk:
            entries = []
            for key in (bk, ak):
                old, new = bi.get(key), ai.get(key)
                entries.append({'entry': asdict(key),
                                'native_rank': old['rank'] if old else None,
                                'onnx_rank': new['rank'] if new else None,
                                'native_score': old['score'] if old else None,
                                'onnx_score': new['score'] if new else None,
                                'score_delta': new['score'] - old['score'] if old and new else None})
            result['first_mismatch'] = {'position': i, 'entries': entries}
            break
    return result


def quality(metrics, frozen):
    selection.validate_metrics(metrics)
    selection.validate_metrics(frozen)
    candidate = metrics['RRF_HYBRID_MODEL_B']
    gates = selection.quality_gates(frozen['BM25_ONLY'], candidate)
    for subset in selection.COUNTS:
        for metric in ('recall_at_10', 'mrr_at_10', 'ndcg_at_10'):
            old = frozen['RRF_HYBRID_MODEL_B'][subset]['metrics'][metric]['value']
            new = candidate[subset]['metrics'][metric]['value']
            delta = new - old
            gates[f'regression.{subset}.{metric}'] = {
                'native': old, 'onnx': new, 'delta': delta, 'minimum_delta': -.01,
                'pass': delta >= -.01}
    # Dense identity assertions must remain zero too, even though relevance gates target hybrid.
    for subset, (count, _, negatives) in selection.COUNTS.items():
        for name, denominator in (('identity_promotion_error_rate', count),
                                  ('negative_identity_promotion_error_rate', negatives)):
            value = metrics['EXACT_DENSE_MODEL_B'][subset][name]['value']
            gates[f'dense.{subset}.{name}'] = {'value': value,
                                               'pass': value == 0 if denominator else value is None}
    return {'metrics': {new: metrics[old] for new, old in MODES.items()}, 'gates': gates,
            'failures': [key for key, gate in gates.items() if not gate['pass']]}


def relevance_changes(native_details, onnx_details):
    native = {row['case_id']: row for row in native_details}
    exact.require(len(native) == len(onnx_details) == 120, 'quality detail coverage')
    result = []
    for row in onnx_details:
        old = native[row['case_id']]
        modes = {}
        for name, source in MODES.items():
            a, b = row['scores'][source], old['scores'][source]
            changes = {}
            for metric in selection.METRICS:
                new, previous = a['metrics'][metric], b['metrics'][metric]
                delta = None if new is None or previous is None else new - previous
                changes[metric] = {'native': previous, 'onnx': new, 'delta': delta,
                                   'loss': delta is not None and delta < 0}
            modes[name] = {'target_count': a['target_count'], 'metrics': changes}
        result.append({'case_id': row['case_id'], 'subset': row['scores']['BM25_ONLY']['subset'],
                       'modes': modes})
    return result


def verify_frozen(contract):
    exact.require(contract['schema'] == 'p4-onnx-representation-contract-v3' and
                  contract['output'] == OUTPUT and contract['raw_directory'] == RAW and
                  contract['reexport'] is False and contract['native_reference_regeneration'] is False,
                  'unsupported v3 contract')
    for name, digest in contract['frozen_sha256'].items():
        exact.bound(exact.local(name), digest)
    exact.bound(exact.local(agreement.EXPORT) / 'manifest.json', contract['export_manifest_sha256'])


def score_inputs():
    job = exact.load(exact.local(selection.JOB))
    source = exact.load(exact.local(selection.SOURCE))
    selection.validate_bindings(exact.ROOT, job, source)
    load = lambda name: exact.load(exact.local(job[name]))
    with exact.local(job['corpus']).open(encoding='utf-8') as stream:
        documents = [selection.parse(line) for line in stream if line.strip()]
    return (load('gold'), documents, load('lexical'),
            {'a': load('dense_a'), 'b': load('dense_b')}, load('model_summary'),
            load('config'), source['bindings'])


def save_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def execute(receipt):
    import numpy as np

    contract = exact.load(exact.local(CONTRACT))
    # A committed contract is mandatory, not merely an unchanged working-tree file.
    committed = subprocess.check_output(['git', 'show', f'HEAD:{CONTRACT}'], cwd=exact.ROOT)
    exact.require(committed == exact.local(CONTRACT).read_bytes(), 'commit v3 contract before inference')
    receipt['contract_commit'] = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=exact.ROOT, text=True).strip()
    verify_frozen(contract)
    job_path, directory = exact.local(exporter.producer.JOB), exact.local(agreement.EXPORT)
    job = exact.load(job_path)
    prepared = agreement.cpu.validate(job)
    inherited, before = agreement.validate_export(directory, job_path, job, prepared)
    selected = selection.verify(exact.ROOT)
    exact.require(selected == exact.load(exact.local(job['selection_receipt'])), 'selection binding')
    inputs = score_inputs()
    baseline, native_details = score.score(*inputs)
    frozen = exact.load(exact.local(selection.SOURCE))['metrics']
    exact.require(baseline['metrics'] == frozen, 'frozen scoring reproduction mismatch')
    paths = list(before) + [exact.local(CONTRACT), Path(__file__),
                            Path(score.__file__), Path(arithmetic.__file__)]
    score_job = exact.load(exact.local(selection.JOB))
    paths += [exact.local(score_job[key]) for key in selection.BINDINGS.values()]
    before = exporter.snapshot(paths)
    receipt.update(input_sha256=before, bindings_sha256=exact.canonical_hash(before),
                   input_validations={'before': 'PASS', 'after': 'NOT_COMPLETED'})
    raw_dir = exact.local(RAW)
    raw_dir.mkdir(parents=True, exist_ok=False)
    vectors = reference = mapping = None
    try:
        model, native, chunks, cases = prepared
        exact.require(len(cases) == 120, '120 queries required')
        raw, tokenizer = exact.frozen_tokenizers(exact.local(model['asset_directory']))
        sample = exporter.select_passages(job, native, chunks, raw, tokenizer)
        saved = exact.load(directory / 'passage-sample.json')
        sample['reference'] = saved['reference']
        exact.require(sample == saved and len(sample['rows']) == 128, 'passage sample mismatch')
        vectors, mapping = exact.open_index(job, prepared)
        exact.require(vectors.shape == (52664, 1024), 'native matrix shape')
        exact.require(saved['reference'] == {'path': inherited['passage_sample']['reference'],
                      'sha256': exact.sha(exact.local(job['index']) / 'vectors.npy')}, 'sample binding')
        reference_dir = exact.local(inherited['query_reference']).parent
        reference = np.load(reference_dir / 'vectors.npy', mmap_mode='r', allow_pickle=False)
        records = exact.load(reference_dir / 'cases.json')
        import onnxruntime as ort

        session = agreement.session(directory / 'model.onnx', ort)
        receipt['runtime'] = {'onnxruntime': ort.__version__, 'numpy': np.__version__,
                              'provider': 'CPUExecutionProvider', 'threads': 8,
                              'interop_threads': 8, 'optimization': 'ORT_ENABLE_ALL'}
        queries = np.empty((120, 1024), dtype=np.float32)
        for i, case in enumerate(cases):
            encoded, counts = exact.checked_tokens(raw, tokenizer, [case['query']],
                                                    native['query_prefix'], native['max_sequence_tokens'])
            exact.require(counts == [records[i]['actual_tokens']] and
                          records[i]['case_id'] == case['case_id'], 'query reference identity')
            output = session.run(['embeddings'], agreement.pad_batch(encoded, tokenizer))[0]
            observation = {'case_id': case['case_id'], **agreement.numerical(output, reference[i:i + 1])}
            receipt['queries'].append(observation)
            exact.require(observation['status'] == 'PASS', 'query numerical failure')
            queries[i] = output[0]
        for size in (1, 8):
            for start in range(0, 128, size):
                rows = sample['rows'][start:start + size]
                encoded, _ = exact.checked_tokens(raw, tokenizer, [r['text'] for r in rows],
                                                   native['passage_prefix'], native['max_sequence_tokens'])
                output = session.run(['embeddings'], agreement.pad_batch(encoded, tokenizer))[0]
                observation = {'batch_size': size, 'offset': start,
                               **agreement.numerical(output, vectors[[r['row_index'] for r in rows]])}
                receipt['passages'].append(observation)
                exact.require(observation['status'] == 'PASS', 'passage numerical failure')
        dense = copy.deepcopy(inputs[3])
        old_cases = score.case_map(dense['b']['cases'], {c['case_id'] for c in cases})
        new_cases = []
        for i, case in enumerate(cases):
            old = old_cases[case['case_id']]
            hits = exact.exact_rank(vectors, mapping, queries[i], depth=100)
            receipt['ranking'].append({'case_id': case['case_id'], **rank_diagnostics(hits, old['hits'])})
            new_cases.append({**old, 'hits': hits})
        dense['b']['cases'] = new_cases
        bindings = {**inputs[6], 'dense_b': exact.canonical_hash(dense['b'])}
        actual, details = score.score(*inputs[:3], dense, *inputs[4:6], bindings)
        receipt['quality'] = quality(actual['metrics'], frozen)
        receipt['relevance_changes'] = relevance_changes(native_details, details)
        with (raw_dir / 'queries.npy').open('xb') as stream:
            np.save(stream, queries, allow_pickle=False)
        save_json(raw_dir / 'ranks.json', {'schema': 'p4-onnx-raw-v3',
                  'representation': 'ONNX_DENSE_B', 'native_template_not_native_inference': True,
                  'case_order': [c['case_id'] for c in cases], 'cases': new_cases,
                  'input_bindings_sha256': receipt['bindings_sha256']})
        save_json(raw_dir / 'quality-details.json', details)
        receipt['raw_sha256'] = exporter.snapshot(
            [raw_dir / name for name in ('queries.npy', 'ranks.json', 'quality-details.json')])
        exact.require(not receipt['quality']['failures'], 'ONNX quality gates failed')
    finally:
        if mapping is not None:
            mapping.connection.close()
        for array in (vectors, reference):
            if array is not None:
                array._mmap.close()
        try:
            exact.require(exporter.snapshot(before) == before, 'post-run input tamper')
            exact.require(agreement.cpu.validate(exact.load(job_path)) == prepared, 'post-run validation')
            exporter.verify_reference(exact.local(inherited['query_reference']), inherited, job, prepared)
            receipt['input_validations']['after'] = 'PASS'
        except Exception as exc:
            receipt['input_validations']['after'] = 'FAIL'
            receipt['post_validation_error'] = str(exc)
            raise


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    receipt = {'schema': 'p4-onnx-quality-v3', 'status': 'FAIL', 'performance_qualified': False,
               'selection_rerun': False, 'reexport': False, 'native_reference_regeneration': False,
               'bm25_queries': 0, 'fallback': False, 'retries': 0,
               'queries': [], 'passages': [], 'ranking': []}
    path = exact.local(OUTPUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        try:
            execute(receipt)
            receipt['status'] = 'PASS'
        except Exception as exc:  # noqa: BLE001
            receipt['error'] = f'{type(exc).__name__}: {exc}'
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return 0 if receipt['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
