"""Explicit opt-in ONNX v3 CPU benchmark over the frozen 120-query slice.

No export, native model loading, retrieval, retries, or implicit benchmark execution.
CLI requires --config and its independently supplied --config-sha256. The config
binds job/job_sha256, quality_receipt/quality_receipt_sha256,
export_manifest/export_manifest_sha256, and output. Policy is fixed in this tool.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools import p4_cpu_representation as cpu
from tools import p4_exact_pilot as exact
from tools import p4_onnx_agreement as agreement
from tools import p4_onnx_export as exporter

POLICY = {'qualification': 'REUSED_SESSION', 'samples': 120, 'warmups': 2,
          'operation_limit_ms': 5000, 'fresh_role': 'STARTUP_DIAGNOSTIC',
          'fresh_timeout_seconds': 15, 'retries': 0, 'threads': 8,
          'provider': 'CPUExecutionProvider', 'dtype': 'float32',
          'optimization': 'ORT_ENABLE_ALL'}
QUALITY_CONTRACT = 'configs/p4-onnx-representation-v3.json'


def quality_gate(path, expected_sha256, required=None, cases=None):
    """Check the producer's quality schema and its actual input snapshot, not rank identity."""
    exact.bound(path, expected_sha256)
    value = exact.load(path)
    exact.require(value.get('status') == 'PASS', 'ONNX v3 quality receipt must PASS')
    exact.require(value.get('schema') == 'p4-onnx-quality-v3', 'v3 quality schema required')
    quality = value.get('quality', {})
    gates = quality.get('gates', {})
    exact.require(quality.get('failures') == [] and isinstance(gates, dict) and gates and
                  all(isinstance(gate, dict) and gate.get('pass') is True
                      for gate in gates.values()), 'quality gates must all pass')
    for name, count in (('queries', 120), ('passages', 144), ('ranking', 120)):
        rows = value.get(name)
        exact.require(isinstance(rows, list) and len(rows) == count and
                      all(isinstance(row, dict) for row in rows), f'{name} coverage required')
        if name != 'ranking':
            exact.require(all(row.get('status') == 'PASS' for row in rows),
                          f'{name} numerical checks must pass')
        else:
            exact.require(all(row.get('diagnostic_only') is True for row in rows),
                          'ranking must remain diagnostic only')
    ids = [row.get('case_id') for row in value['queries']]
    exact.require(all(isinstance(cid, str) for cid in ids) and len(set(ids)) == 120 and
                  [row.get('case_id') for row in value['ranking']] == ids,
                  'quality query/ranking identity coverage')
    if cases is not None:
        exact.require(ids == [case['case_id'] for case in cases], 'frozen quality query order')
    exact.require([(row.get('batch_size'), row.get('offset')) for row in value['passages']] ==
                  [(size, offset) for size in (1, 8) for offset in range(0, 128, size)],
                  'quality passage coverage')
    exact.require(value.get('input_validations') == {'before': 'PASS', 'after': 'PASS'},
                  'quality input validations must pass')
    bindings = value.get('input_sha256')
    exact.require(isinstance(bindings, dict) and bindings, 'quality input_sha256 required')
    exact.require(value.get('bindings_sha256') == exact.canonical_hash(bindings),
                  'quality input snapshot digest mismatch')
    for name, digest in bindings.items():
        source = Path(name)
        exact.require(source.is_absolute() and source.resolve().is_relative_to(exact.ROOT.resolve()),
                      'quality input path must be absolute and repository-local')
        exact.bound(source, digest)
    contract_path = exact.local(QUALITY_CONTRACT)
    required = {**(required or {}), **exporter.snapshot([contract_path])}
    exact.require(all(bindings.get(name) == digest for name, digest in required.items()),
                  'quality input binding missing or mismatched')
    contract = exact.load(contract_path)
    manifest = exact.local(agreement.EXPORT) / 'manifest.json'
    exact.require(contract.get('schema') == 'p4-onnx-representation-contract-v3' and
                  contract.get('export_manifest_sha256') == bindings.get(str(manifest.resolve())),
                  'v3 contract/export quality binding mismatch')
    return value


def validate(config_path, config_sha256):
    exact.bound(config_path, config_sha256)
    config = exact.load(config_path)
    job_path = exact.local(config['job'])
    exact.require(job_path == exact.local(exporter.producer.JOB), 'authorized v2 job required')
    exact.bound(job_path, config['job_sha256'])
    job = exact.load(job_path)
    exact.require(type(job['threads']) is int and job['threads'] == 8, 'eight threads required')
    prepared = cpu.validate(job)  # Read-only metadata/assets; never constructs LocalEncoder.
    manifest = exact.local(config['export_manifest'])
    exact.require(manifest == exact.local(agreement.EXPORT) / 'manifest.json',
                  'existing frozen ONNX export required')
    exact.bound(manifest, config['export_manifest_sha256'])
    quality_path = exact.local(config['quality_receipt'])
    _, before = agreement.validate_export(manifest.parent, job_path, job, prepared)
    required = {**before, **exporter.snapshot([job_path, manifest])}
    quality = quality_gate(quality_path, config['quality_receipt_sha256'], required, prepared[3])
    before.update(quality['input_sha256'])
    before.update(exporter.snapshot([config_path, job_path, quality_path, Path(__file__)]))
    exact.local(config['output'])
    return config, prepared, manifest.parent, before


class Encoder:
    def __init__(self, model, contract, directory, progress, clock=time.perf_counter):
        self.contract = contract
        start = clock()
        self.raw, self.tokenizer = exact.frozen_tokenizers(exact.local(model['asset_directory']))
        exact.require(self.tokenizer.padding_side == 'right' and
                      type(self.tokenizer.pad_token_id) is int, 'frozen right padding required')
        cpu.emit(progress, {'event': 'load', 'tokenizer_load_ms': (clock() - start) * 1000})
        start = clock()
        import onnxruntime as ort

        self.session = agreement.session(directory / 'model.onnx', ort)
        cpu.emit(progress, {'event': 'load', 'session_load_ms': (clock() - start) * 1000,
                            'runtime': {'onnxruntime': ort.__version__, **POLICY}})

    def encode(self, texts, query=True):
        exact.require(query is True and len(texts) == 1, 'single frozen query only')
        encoded, counts = exact.checked_tokens(self.raw, self.tokenizer, texts,
                                               self.contract['query_prefix'],
                                               self.contract['max_sequence_tokens'])
        output = self.session.run(['embeddings'], agreement.pad_batch(encoded, self.tokenizer))[0]
        exact.validate_vectors(output, 1024)
        exact.require(output.shape == (1, 1024), 'single query output shape')
        return output, counts


def operation(encoder, case, clock=time.perf_counter):
    record = {'case_id': case['case_id'], 'status': 'PASS', 'embedding_ms': None}
    start = clock()
    embedding_start = clock()
    try:
        _, counts = encoder.encode([case['query']], query=True)
        record['actual_tokens'] = counts[0]
    except Exception as exc:  # noqa: BLE001 - retain every failed attempt without retrying.
        record.update(status='FAIL', error=f'{type(exc).__name__}: {exc}')
    finally:
        record['embedding_ms'] = (clock() - embedding_start) * 1000
    record['operation_ms'] = (clock() - start) * 1000
    if record['operation_ms'] > POLICY['operation_limit_ms']:
        record.update(status='FAIL', budget_failure='operation exceeds 5000ms')
    return record


def worker(config_path, digest, mode, progress, case_id=None, prepare=validate,
           encoder_factory=Encoder, clock=time.perf_counter, memory=exact.rss):
    phase = 'setup'
    before = None
    failed = False

    def memory_event():
        cpu.emit(progress, {'event': 'memory', **cpu.memory_record(memory)})

    try:
        cpu.emit(progress, {'event': 'phase', 'phase': phase})
        start = clock()
        _, prepared, directory, before = prepare(config_path, digest)
        model, contract, _, cases = prepared
        cpu.emit(progress, {'event': 'setup', 'status': 'PASS',
                            'setup_ms': (clock() - start) * 1000,
                            'bindings_sha256': exact.canonical_hash(before)})
        memory_event()
        phase = 'load'
        cpu.emit(progress, {'event': 'phase', 'phase': phase})
        encoder = encoder_factory(model, contract, directory, progress, clock)
        memory_event()
        if mode == 'fresh':
            exact.require(case_id in {c['case_id'] for c in cases}, 'unknown frozen case')
            schedule = [('sample', next(c for c in cases if c['case_id'] == case_id))]
        else:
            schedule = [('warmup', c) for c in cases[:2]] + [('sample', c) for c in cases]
        phase = 'query'
        for kind, case in schedule:
            cpu.emit(progress, {'event': 'query_start', 'kind': kind, 'case_id': case['case_id']})
            record = operation(encoder, case, clock)
            failed |= record['status'] != 'PASS'
            cpu.emit(progress, {'event': 'query', 'kind': kind, 'record': record})
            memory_event()
    except Exception as exc:  # noqa: BLE001 - worker failures must survive in the receipt.
        failed = True
        cpu.emit(progress, {'event': 'failure', 'phase': phase,
                            'blocking': phase in ('setup', 'load'),
                            'error': f'{type(exc).__name__}: {exc}'})
    finally:
        if before is not None:
            try:
                exact.require(exporter.snapshot(before) == before, 'post-run bindings changed')
                cpu.emit(progress, {'event': 'validation_after', 'status': 'PASS'})
            except Exception as exc:  # noqa: BLE001 - any post-validation error blocks qualification.
                failed = True
                cpu.emit(progress, {'event': 'failure', 'phase': 'validation_after',
                                    'blocking': True, 'error': str(exc)})
    cpu.emit(progress, {'event': 'done', 'status': 'FAIL' if failed else 'PASS'})
    return int(failed)


def launch(config_path, digest, mode, case=None, runner=subprocess.run, clock=time.perf_counter):
    config_path = Path(config_path)
    if config_path.is_absolute():
        config_path = config_path.resolve().relative_to(exact.ROOT.resolve())
    config_name = exact.local(config_path).relative_to(exact.ROOT.resolve()).as_posix()
    with tempfile.TemporaryDirectory(prefix='p4-onnx-v3-') as directory:
        progress = Path(directory) / 'events.jsonl'
        command = [sys.executable, '-Xutf8', '-m', 'tools.p4_onnx_cpu_v3', '--config', config_name,
                   '--config-sha256', digest, '--_worker', mode, '--progress', str(progress)]
        if case is not None:
            command += ['--case-id', case['case_id']]
        result = {'status': 'PASS', 'timeout': False, 'exit_code': None,
                  'stdout': cpu.text_capture(None), 'stderr': cpu.text_capture(None)}
        start = clock()
        try:
            process = runner(command, cwd=exact.ROOT, capture_output=True, check=False,
                             timeout=15 if mode == 'fresh' else 1800,
                             env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
                                  'OMP_NUM_THREADS': '8', 'MKL_NUM_THREADS': '8',
                                  'OPENBLAS_NUM_THREADS': '8'})
            result.update(exit_code=process.returncode, stdout=cpu.text_capture(process.stdout),
                          stderr=cpu.text_capture(process.stderr))
            if process.returncode != 0:
                result['status'] = 'FAIL'
        except subprocess.TimeoutExpired as exc:
            result.update(status='FAIL', timeout=True, stdout=cpu.text_capture(exc.stdout),
                          stderr=cpu.text_capture(exc.stderr))
        except Exception as exc:  # noqa: BLE001 - preserve launch errors as diagnostic evidence.
            result.update(status='FAIL', error=f'{type(exc).__name__}: {exc}')
        result['process_elapsed_ms'] = (clock() - start) * 1000
        raw = progress.read_bytes() if progress.exists() else b''
        result['event_prefix'] = cpu.text_capture(raw)
        events = []
        for line in raw.splitlines():
            try:
                event = json.loads(line)
                exact.require(isinstance(event, dict), 'invalid event')
                events.append(event)
            except (ValueError, UnicodeError, RuntimeError):
                result.update(status='FAIL', progress_error='invalid/incomplete event retained')
                break
        result['events'] = events
        result['blocking_failure'] = any(e.get('blocking') is True for e in events)
        if not events or events[-1] != {'event': 'done', 'status': 'PASS'}:
            result['status'] = 'FAIL'
        if mode == 'fresh' and result['process_elapsed_ms'] > 15000:
            result.update(status='FAIL', budget_failure='fresh envelope exceeds 15000ms')
        for key in ('setup_ms', 'tokenizer_load_ms', 'session_load_ms', 'rss_bytes',
                    'peak_rss_bytes', 'peak_rss_source', 'peak_wset_bytes'):
            values = [e[key] for e in events if e.get(key) is not None]
            result[key] = (max(values) if key in ('rss_bytes', 'peak_rss_bytes',
                                                'peak_wset_bytes') else values[-1]) if values else None
        if case is not None:
            result['case_id'] = case['case_id']
            queries = [e['record'] for e in events if e.get('event') == 'query']
            result['query'] = queries[0] if len(queries) == 1 else {
                'case_id': case['case_id'], 'status': 'FAIL', 'operation_ms': None,
                'embedding_ms': None, 'error': 'query completion unavailable'}
            if len(queries) != 1 or queries[0]['case_id'] != case['case_id']:
                result['status'] = 'FAIL'
        return result


def summarize(records, key):
    values = sorted(r[key] for r in records if isinstance(r.get(key), (int, float))
                    and math.isfinite(r[key]))

    def percentile(p):
        if not values:
            return None
        position = (len(values) - 1) * p
        low, high = math.floor(position), math.ceil(position)
        return values[low] + (values[high] - values[low]) * (position - low)

    return {'attempts': len(records), 'measured': len(values),
            'missing_timing': len(records) - len(values),
            'failures': sum(r['status'] != 'PASS' for r in records),
            'p50_ms': percentile(.5), 'p95_ms': percentile(.95),
            'policy': 'linear (n-1)*p; measured failures included; missing timing excluded'}


def evaluate(cases, reused, warmups, fresh):
    ids = [c['case_id'] for c in cases]
    reused_warmups = [e['record'] for e in reused['events']
                      if e.get('event') == 'query' and e['kind'] == 'warmup']
    samples = [e['record'] for e in reused['events']
               if e.get('event') == 'query' and e['kind'] == 'sample']
    coverage = {'expected': len(ids), 'reused_attempted': len(samples),
                'reused_exact_order': [r['case_id'] for r in samples] == ids,
                'reused_warmups_exact_order': [r['case_id'] for r in reused_warmups] == ids[:2],
                'fresh_attempted': len(fresh),
                'fresh_exact_order': [r['case_id'] for r in fresh] == ids,
                'fresh_warmups_exact_order': [r['case_id'] for r in warmups] == ids[:2]}
    blocking = any(p.get('blocking_failure', False) for p in [reused, *warmups, *fresh])
    reused_pass = (len(ids) == len(set(ids)) == 120 and reused['status'] == 'PASS' and
                   coverage['reused_exact_order'] and coverage['reused_warmups_exact_order'] and
                   all(r['status'] == 'PASS' and isinstance(r.get('operation_ms'), (float, int))
                       and 0 <= r['operation_ms'] <= 5000 for r in reused_warmups + samples))
    complete = coverage['fresh_exact_order'] and coverage['fresh_warmups_exact_order']
    return {'status': 'PASS' if reused_pass and complete and not blocking else 'FAIL',
            'performance_qualified': bool(reused_pass and complete and not blocking),
            'coverage': coverage, 'blocking_failure': blocking,
            'reused': {'role': 'QUALIFICATION', 'status': 'PASS' if reused_pass else 'FAIL',
                       'process': reused, 'warmups': reused_warmups, 'samples': samples,
                       'operation_summary': summarize(samples, 'operation_ms'),
                       'embedding_summary': summarize(samples, 'embedding_ms')},
            'fresh': {'role': 'STARTUP_DIAGNOSTIC', 'blocking': False,
                      'status': 'PASS' if all(p['status'] == 'PASS' for p in warmups + fresh)
                      and complete else 'FAIL', 'warmups': warmups, 'samples': fresh,
                      'process_summary': summarize(fresh, 'process_elapsed_ms'),
                      'operation_summary': summarize([p['query'] for p in fresh], 'operation_ms'),
                      'embedding_summary': summarize([p['query'] for p in fresh], 'embedding_ms')}}


def benchmark(config_path, digest, cases, launcher=launch):
    reused = launcher(config_path, digest, 'reused')
    # Each warmup has its own independent interpreter. Never stop diagnostic coverage.
    warmups = [launcher(config_path, digest, 'fresh', c) for c in cases[:2]]
    fresh = [launcher(config_path, digest, 'fresh', c) for c in cases]
    return evaluate(cases, reused, warmups, fresh)


def run(config_path, digest):
    config_path = exact.local(config_path)
    # Do not trust an output destination from an unbound config.
    exact.bound(config_path, digest)
    config = exact.load(config_path)
    output = exact.local(config['output'])
    exact.require(not output.exists(), 'output already exists; retries/overwrite forbidden')
    receipt = {'schema': 'p4-onnx-cpu-v3', 'status': 'FAIL', 'performance_qualified': False,
               'policy': POLICY, 'retries': 0, 'fallback': False,
               'v3_config': str(config_path), 'v3_config_sha256': digest,
               **{k: config[k] for k in ('job', 'job_sha256', 'quality_receipt',
                  'quality_receipt_sha256', 'export_manifest', 'export_manifest_sha256')}}
    before = None
    try:
        _, prepared, _, before = validate(config_path, digest)
        receipt['bindings_before'] = before
        receipt['bindings_sha256'] = exact.canonical_hash(before)
        receipt.update(benchmark(config_path, digest, prepared[3]))
    except Exception as exc:  # noqa: BLE001 - persist a fail-closed receipt on setup errors.
        receipt.update(status='FAIL', performance_qualified=False,
                       setup_error=f'{type(exc).__name__}: {exc}')
    finally:
        if before is not None:
            try:
                exact.require(exporter.snapshot(before) == before, 'post-run bindings changed')
                receipt['bindings_after'] = 'PASS'
            except Exception as exc:  # noqa: BLE001 - never qualify after failed revalidation.
                receipt.update(status='FAIL', performance_qualified=False, bindings_after='FAIL',
                               post_validation_error=str(exc))
    exact.save(output, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--_worker', choices=('reused', 'fresh'))
    parser.add_argument('--progress')
    parser.add_argument('--case-id')
    args = parser.parse_args(argv)
    if args._worker:
        exact.require(args.progress is not None, 'worker progress required')
        return worker(exact.local(args.config), args.config_sha256, args._worker,
                      args.progress, args.case_id)
    return int(run(args.config, args.config_sha256)['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
