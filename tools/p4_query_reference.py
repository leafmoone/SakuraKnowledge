"""One authorized native query reference, not a pilot or CPU qualification retry.

Run only on explicit authorization: python -m tools.p4_query_reference --job
configs/p4-cpu-native-b-v2.json --output-dir build/p4/bge-query-reference-v2
No warmups, ranking, timing qualification, downloads, or fallback execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

from tools import p4_cpu_representation as cpu
from tools import p4_exact_pilot as exact

SCOPE = 'new_native_representation_validation_reference_not_historical'
JOB = 'configs/p4-cpu-native-b-v2.json'
OUTPUT = 'build/p4/bge-query-reference-v2'


def snapshot(job_path, job, prepared):
    """Capture verified product inputs, without historical source closure."""
    model, contract, manifest, cases = prepared
    paths = {key: exact.local(job[key]) for key in (
        'summary', 'corpus', 'gold', 'chunks_manifest', 'chunks')}
    paths['job'] = job_path
    paths['contract'] = exact.local(model['contract']['path'])
    inputs = {key: {'path': path.relative_to(exact.ROOT).as_posix(),
                    'sha256': exact.sha(path)} for key, path in paths.items()}
    return {'inputs': inputs, 'job': job,
            'provenance': exact.provenance(job, model, manifest),
            'model': model, 'contract': contract, 'chunks_manifest': manifest,
            'ordered_cases_sha256': exact.canonical_hash(cases)}


def run(job_path, output_dir):
    """Fail closed; reserve a new output directory before loading any assets."""
    output = None
    phase = 'output_reservation'
    attempted = completed = 0
    active_case = None
    before = None
    try:
        exact.require(str(Path(output_dir).as_posix()) == OUTPUT, 'unauthorized output directory')
        candidate = exact.local(output_dir)
        candidate.mkdir(parents=True, exist_ok=False)
        output = candidate
        phase = 'input_validation_before'
        exact.require(str(Path(job_path).as_posix()) == JOB, 'authorized native B v2 job required')
        job_path = exact.local(job_path)
        job = exact.load(job_path)
        exact.require(type(job['threads']) is int and job['threads'] == 8, 'eight CPU threads required')
        # validate includes receipt recomputation and all asset safety/hash checks;
        # it does not rerun selection, retrieval, or embeddings.
        prepared = cpu.validate(job)
        model, contract, _, cases = prepared
        exact.require(len(cases) == 120 and len({c['case_id'] for c in cases}) == 120,
                      'exactly 120 unique cases required')
        exact.require(cases == sorted(cases, key=lambda c: c['case_id']), 'cases must be sorted')
        before = snapshot(job_path, job, prepared)
        phase = 'model_load'
        encoder = exact.LocalEncoder(model, contract, 'cpu', 8)
        info = encoder.info
        exact.require(info['provider'] == 'huggingface/torch' and
                      info['actual_device'] == 'cpu' and info['actual_dtype'] == 'torch.float32' and
                      info['threads'] == 8 and info['interop_threads'] == 8,
                      'actual native FP32 CPU provider/thread mismatch')
        import numpy as np

        vectors = np.empty((120, 1024), dtype=np.float32)
        ordered = []
        phase = 'query_encoding'
        for row, case in enumerate(cases):
            active_case = case['case_id']
            attempted += 1
            result, counts = encoder.encode([case['query']], query=True)
            exact.validate_vectors(result, 1024)
            exact.require(result.shape == (1, 1024), 'one query vector required')
            exact.require(len(counts) == 1 and type(counts[0]) is int and
                          0 < counts[0] <= contract['max_sequence_tokens'], 'invalid token count')
            vectors[row] = result[0]
            ordered.append({'row': row, 'case_id': active_case, 'actual_tokens': counts[0],
                            'query_text_sha256': hashlib.sha256(
                                case['query'].encode('utf-8')).hexdigest()})
            completed += 1
        active_case = None
        phase = 'input_validation_after'
        after_job = exact.load(job_path)
        after = snapshot(job_path, after_job, cpu.validate(after_job))
        exact.require(before == after, 'frozen inputs or code changed during reference generation')
        phase = 'payload_write'
        with (output / 'vectors.npy').open('xb') as stream:
            np.save(stream, vectors, allow_pickle=False)
        exact.save(output / 'cases.json', ordered)
        exact.save(output / 'inputs.json', before)
        versions = {'python': platform.python_version(), 'numpy': np.__version__,
                    **{key: info[key] for key in ('torch', 'transformers', 'tokenizers')}}
        payloads = {name: exact.sha(output / name)
                    for name in ('vectors.npy', 'cases.json', 'inputs.json')}
        manifest = {'status': 'PASS', 'authorization_scope': SCOPE,
                    'purpose': 'new reference for representation validation before ONNX',
                    'historical_pilot': False, 'native_qualification_retry': False,
                    'selection_rerun': False, 'ranking': False, 'warmups': 0,
                    'attempted_queries': attempted, 'completed_queries': completed,
                    'shape': [120, 1024], 'dtype': 'float32', 'encoder': info,
                    'versions': versions, 'versions_sha256': exact.canonical_hash(versions),
                    'frozen_provenance': before['provenance'],
                    'model_inventory_sha256': model['obtained_receipt']['inventory_sha256'],
                    'tokenizer_inventory_sha256': prepared[2]['tokenizer_inventory_sha256'],
                    'input_validations': {
                        'before': {'status': 'PASS', 'snapshot_sha256': exact.canonical_hash(before)},
                        'after': {'status': 'PASS', 'snapshot_sha256': exact.canonical_hash(after)}},
                    'vectors_sha256': payloads['vectors.npy'], 'payload_sha256': payloads}
        phase = 'manifest_write'
        exact.save(output / 'manifest.json', manifest)
        return 0
    except Exception as exc:  # noqa: BLE001 - failures are receipts, never retries.
        failure = {'status': 'FAIL', 'authorization_scope': SCOPE, 'phase': phase,
                   'attempted_queries': attempted, 'completed_queries': completed,
                   'case_id': active_case, 'error': f'{type(exc).__name__}: {exc}',
                   'input_validation_before': 'PASS' if before is not None else 'NOT_COMPLETED',
                   'retry_attempted': False}
        if output is not None:
            # Even a partially written manifest must not look like success.
            (output / 'manifest.json').unlink(missing_ok=True)
            try:
                exact.save(output / 'failure.json', failure)
            except OSError:
                pass  # stderr remains the failure receipt if storage itself failed.
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    return run(args.job, args.output_dir)


if __name__ == '__main__':
    raise SystemExit(main())
