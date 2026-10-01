"""Native BGE CPU query-representation feasibility; never ANN or hybrid retrieval.

CLI: python -m tools.p4_cpu_representation --job JOB --output OUTPUT
JOB is an exact-pilot job (model=b, device=cpu, benchmark_scope=query_embedding),
plus selection_receipt and selection_receipt_sha256. The receipt basename must be
selection-v2-recompute.json and its contents must equal p4_selection_v2.verify(ROOT),
a read-only hash/metric recomputation with no retrieval or embedding execution.
Require models.b.pass and a unique quality_only_selected_model matching prepared B.
Bind gold/corpus/summary hashes through input_hash_validations and dense_b file
provenance to exact.provenance. B is pinned BAAI/bge-m3 with 1024-dimensional,
CLS-pooled, L2-normalized embeddings and empty prefixes. No models run on import.
Fresh deadline is 15s including interpreter/imports, receipt/input/model hash
verification, load and query; operation deadline is 5s in both modes. Reused
worker deadline is 1800s (not 15s for the entire 122-operation sequence).
Two warmups per mode use the first two sorted cases, excluded from statistics.
Any detected failure stops all subsequent work. No retries or automatic ONNX.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools import p4_exact_pilot as exact
from tools import p4_selection_v2 as selection

B_REPOSITORY = 'BAAI/bge-m3'
B_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'


def validate(job):
    exact.require(job['model'] == 'b' and job['device'] == 'cpu', 'native B CPU only')
    exact.require(job.get('benchmark_scope', 'query_embedding') == 'query_embedding',
                  'query representation only; no index')
    exact.require('samples' not in job, 'sample override forbidden')
    path = exact.local(job['selection_receipt'])
    exact.require(path.name == 'selection-v2-recompute.json', 'recomputed receipt required')
    exact.bound(path, job['selection_receipt_sha256'])
    receipt = exact.load(path)
    exact.require(receipt == selection.verify(exact.ROOT), 'v2 recomputation mismatch')
    exact.require(receipt['models']['b']['pass'] is True, 'quality B must PASS')
    bindings = receipt['input_hash_validations']
    for key in ('gold', 'corpus', 'summary'):
        exact.require(job[key + '_sha256'] == bindings[key]['expected_sha256'],
                      f'quality receipt {key} hash mismatch')
    prepared = exact.prepare(job)
    model, contract, manifest, cases = prepared
    exact.require(model['repository'] == B_REPOSITORY and model['revision'] == B_REVISION,
                  'pinned BGE-M3 model required')
    exact.require(contract['dimension'] == 1024 and contract['pooling'] == 'cls' and
                  contract['normalize'] is True and contract['query_prefix'] == '' and
                  contract['passage_prefix'] == '', 'pinned BGE-M3 contract required')
    exact.require(receipt['quality_only_selected_model'] == {
        'label': 'b', 'repository': model['repository'], 'revision': model['revision']},
        'unique quality selection must match prepared B')
    dense_path = exact.local(bindings['dense_b']['path'])
    exact.bound(dense_path, bindings['dense_b']['expected_sha256'])
    exact.require(exact.load(dense_path)['provenance'] == exact.provenance(job, model, manifest),
                  'quality receipt frozen provenance mismatch')
    exact.require(len(cases) == 120 and len({c['case_id'] for c in cases}) == 120,
                  'exactly 120 unique cases required')
    exact.require(cases == sorted(cases, key=lambda c: c['case_id']), 'cases must be sorted')
    return prepared


def memory_record(memory):
    value = memory()
    exact.require(isinstance(value.get('peak_rss_bytes'), (int, float)) and
                  math.isfinite(value['peak_rss_bytes']) and value['peak_rss_bytes'] > 0 and
                  bool(value.get('peak_rss_source')), 'actual process peak memory unavailable')
    # Only the Windows source is peak_wset; never relabel POSIX RSS as peak_wset.
    value['peak_wset_bytes'] = (value['peak_rss_bytes']
                              if value['peak_rss_source'] == 'Windows peak_wset' else None)
    return value


def operation(encoder, case, clock=time.perf_counter, retrieve=exact.retrieve, memory=exact.rss):
    record = {'case_id': case['case_id'], 'status': 'PASS'}
    start = clock()
    try:
        record.update(retrieve(encoder, case, index=None))
    except Exception as exc:  # noqa: BLE001 - preserve inference failures in the FAIL receipt.
        record.update(status='FAIL', error=f'{type(exc).__name__}: {exc}')
    record['operation_ms'] = (clock() - start) * 1000
    if record['operation_ms'] > 5000:
        record.update(status='FAIL', budget_failure='operation exceeds 5000ms')
    if not isinstance(record.get('embedding_ms'), (float, int)) or not math.isfinite(record['embedding_ms']):
        record.update(status='FAIL', timing_error='actual encode timer unavailable')
    try:
        record.update(memory_record(memory))
    except Exception as exc:  # noqa: BLE001 - memory failures must fail qualification explicitly.
        record.update(status='FAIL', memory_error=str(exc))
    return record


def emit(path, event):
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def worker(job, mode, progress, case_id=None, prepare=validate,
           encoder_factory=exact.LocalEncoder, clock=time.perf_counter,
           retrieve=exact.retrieve, memory=exact.rss):
    phase = 'verification'
    try:
        emit(progress, {'event': 'phase', 'phase': phase})
        model, contract, _, cases = prepare(job)
        phase = 'model_load'
        emit(progress, {'event': 'phase', 'phase': phase})
        start = clock()
        encoder = encoder_factory(model, contract, 'cpu', job['threads'])
        load_ms = (clock() - start) * 1000
        emit(progress, {'event': 'setup', 'status': 'PASS', 'model_load_ms': load_ms,
                        'encoder': encoder.info})
        schedule = ([('sample', next(c for c in cases if c['case_id'] == case_id))]
                    if mode == 'fresh' else
                    [('warmup', c) for c in cases[:2]] + [('sample', c) for c in cases])
        for kind, case in schedule:
            phase = kind
            emit(progress, {'event': 'start', 'kind': kind, 'case_id': case['case_id']})
            record = operation(encoder, case, clock, retrieve, memory)
            emit(progress, {'event': 'record', 'kind': kind, 'record': record})
            if record['status'] != 'PASS':
                return 1
        emit(progress, {'event': 'done'})
        return 0
    except Exception as exc:  # noqa: BLE001 - retain the failing worker phase for the parent.
        emit(progress, {'event': 'failure', 'status': 'FAIL', 'phase': phase,
                        'error': f'{type(exc).__name__}: {exc}'})
        return 1


def text_capture(value):
    raw = value or b''
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    return {'text': raw.decode('utf-8', errors='replace'),
            'bytes_base64': base64.b64encode(raw).decode('ascii')}


def launch(job_path, mode, case=None, runner=subprocess.run, clock=time.perf_counter):
    with tempfile.TemporaryDirectory(prefix='p4-cpu-') as directory:
        progress = Path(directory) / 'progress.jsonl'
        command = [sys.executable, '-m', 'tools.p4_cpu_representation', '--job', str(job_path),
                   '--_worker', mode, '--progress', str(progress)]
        if case is not None:
            command += ['--case-id', case['case_id']]
        start = clock()
        result = {'status': 'PASS', 'timeout': False, 'exit_code': None}
        try:
            process = runner(command, cwd=exact.ROOT, capture_output=True, check=False,
                             timeout=15 if mode == 'fresh' else 1800,
                             env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            result.update(exit_code=process.returncode, stdout=text_capture(process.stdout),
                          stderr=text_capture(process.stderr))
            if process.returncode != 0:
                result['status'] = 'FAIL'
        except subprocess.TimeoutExpired as exc:
            result.update(status='FAIL', timeout=True, stdout=text_capture(exc.stdout),
                          stderr=text_capture(exc.stderr), error='process deadline exceeded')
        except Exception as exc:  # noqa: BLE001 - launch failures also require a FAIL receipt.
            result.update(status='FAIL', error=f'{type(exc).__name__}: {exc}',
                          stdout=text_capture(None), stderr=text_capture(None))
        result['process_elapsed_ms'] = (clock() - start) * 1000
        events = []
        if progress.exists():
            for line in progress.read_text(encoding='utf-8').splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    result.update(status='FAIL', progress_error='incomplete progress line retained',
                                  raw_progress=progress.read_text(encoding='utf-8'))
        result['events'] = events
        result['worker_phase'] = (events[-1] if events else 'unknown; no progress received')
        if not events or events[-1].get('event') != 'done':
            result['status'] = 'FAIL'
        if mode == 'fresh' and result['process_elapsed_ms'] > 15000:
            result.update(status='FAIL', budget_failure='fresh envelope exceeds 15000ms')
        return result


def unpack(process):
    warmups, samples = [], []
    pending = None
    for event in process['events']:
        if event['event'] == 'start':
            pending = event
        elif event['event'] == 'record':
            (warmups if event['kind'] == 'warmup' else samples).append(event['record'])
            pending = None
    if pending:
        (warmups if pending['kind'] == 'warmup' else samples).append({
            'case_id': pending['case_id'], 'status': 'FAIL', 'timeout': process['timeout'],
            'error': 'operation interrupted; completed timing/memory unknown'})
    return warmups, samples


def summary(records):
    attempts = [r for r in records if r['status'] != 'NOT_RUN']
    def percentiles(key):
        values = sorted(r[key] for r in attempts if isinstance(r.get(key), (int, float)))
        def at(p):
            if not values:
                return None
            position = (len(values) - 1) * p
            lo, hi = math.floor(position), math.ceil(position)
            return values[lo] + (values[hi] - values[lo]) * (position - lo)
        return {'measured': len(values), 'p50_ms': at(.5), 'p95_ms': at(.95)}
    peaks = [r['peak_rss_bytes'] for r in attempts if r.get('peak_rss_bytes')]
    return {'attempts': len(attempts), 'not_run': len(records) - len(attempts),
            'failures': sum(r['status'] != 'PASS' for r in attempts),
            'timeouts': sum(bool(r.get('timeout')) for r in attempts),
            'coverage_pass': len(records) == 120 and len(attempts) == 120 and
                             all(r['status'] == 'PASS' for r in records),
            'embedding': percentiles('embedding_ms'), 'operation': percentiles('operation_ms'),
            'process': percentiles('process_elapsed_ms'),
            'peak_rss_bytes': max(peaks) if peaks else None,
            'percentile_policy': 'linear interpolation (n-1)*p; measured failures included; missing timings and NOT_RUN excluded'}


def benchmark(job, job_path, prepared, launcher=launch):
    cases = prepared[3]
    reused_process = launcher(job_path, 'reused')
    warmups, reused = unpack(reused_process)
    stopped = reused_process['status'] != 'PASS' or any(
        r['status'] != 'PASS' for r in warmups + reused)
    stopped = stopped or len(warmups) != 2 or len(reused) != 120
    reused.extend(exact.not_run(cases[len(reused):]))
    fresh_warmups, fresh, processes = [], [], []
    for kind, case in [('warmup', c) for c in cases[:2]] + [('sample', c) for c in cases]:
        if stopped:
            break
        process = launcher(job_path, 'fresh', case)
        processes.append(process)
        _, completed = unpack(process)
        record = completed[0] if completed else {'case_id': case['case_id'], 'status': 'FAIL',
                                                 'error': 'no completed operation; phase in process record'}
        record = {**record, 'process_elapsed_ms': process['process_elapsed_ms'],
                  'timeout': process['timeout'], 'process_record': len(processes) - 1}
        if process['status'] != 'PASS':
            record['status'] = 'FAIL'
        (fresh_warmups if kind == 'warmup' else fresh).append(record)
        stopped = record['status'] != 'PASS'
    fresh.extend(exact.not_run(cases[len(fresh):]))
    result = {'schema': 'p4-native-cpu-representation-v1', 'scope': 'query_embedding only; no ANN/hybrid claims',
              'provenance': exact.provenance(job, prepared[0], prepared[2]),
              'selection_receipt_sha256': job['selection_receipt_sha256'],
              'model_asset_bytes': sum(f['size'] for f in prepared[0]['obtained_receipt']['files']),
              'versions': {'python': sys.version, 'platform': platform.platform()},
              'code_sha256': {p.name: exact.sha(p) for p in (Path(__file__), Path(exact.__file__))},
              'threads': job['threads'], 'retries': 0, 'disk_cold': False,
              'budgets_ms': {'operation': 5000, 'fresh_process': 15000},
              'memory_scope': 'actual process lifetime peak including setup; peak_wset only on Windows',
              'reused': {'process': reused_process, 'warmups': warmups, 'samples': reused, 'summary': summary(reused)},
              'fresh': {'processes': processes, 'warmups': fresh_warmups, 'samples': fresh, 'summary': summary(fresh)}}
    passed = not stopped and result['reused']['summary']['coverage_pass'] and result['fresh']['summary']['coverage_pass']
    result.update(status='PASS' if passed else 'FAIL', formal_qualification='PASS' if passed else 'FAIL',
                  next_step=None if passed else 'Native CPU failed qualification. Separate future ONNX requires user authorization; no automatic conversion.')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--_worker', choices=('fresh', 'reused'))
    parser.add_argument('--progress', type=Path)
    parser.add_argument('--case-id')
    args = parser.parse_args(argv)
    if args._worker:
        return worker(exact.load(args.job), args._worker, args.progress, args.case_id)
    if args.output is None:
        parser.error('--output is required')
    exact.require(not args.output.exists(), 'output exists; refusing overwrite')
    try:
        job = exact.load(args.job)
        prepared = validate(job)
        result = benchmark(job, args.job.resolve(), prepared)
    except Exception as exc:  # noqa: BLE001 - persist gate/runtime failures without retrying.
        result = {'schema': 'p4-native-cpu-representation-v1', 'status': 'FAIL',
                  'formal_qualification': 'FAIL', 'gate_error': f'{type(exc).__name__}: {exc}',
                  'execution': 'no qualification; no automatic conversion'}
    exact.save(args.output, result)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
