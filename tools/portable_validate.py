"""Run frozen portable cases or compare saved FP32 evidence without inference."""
import argparse
import json
import math
import os
import sqlite3
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from tools import p4_existing_assets_evaluate as evaluation
from tools import p4_retrieval_metrics as metrics
from tools.p4_full_acceptance import _verify_response_snapshot
from tools.p4_rust_pilot import MAX_BYTES, Driver

FP32 = evaluation.ROOT / 'build/p4-1mib-3ee34e2-evaluation-v1'


def _summary(values):
    values = sorted(values)
    return ({'count': len(values), 'p50': statistics.median(values),
             'p95': values[math.ceil(.95 * len(values)) - 1], 'max': values[-1]}
            if values else {'count': 0})


def _gate(checks, expected=None):
    passed = sum(c['pass'] for c in checks)
    return {'status': 'PASS' if passed == len(checks) and
            (expected is None or len(checks) == expected) else 'FAIL',
            'pass_count': passed, 'check_count': len(checks), 'checks': checks}


def _aggregates(rows):
    def restore(score):
        return metrics.CaseResult(**{**score, 'metrics': metrics.RankingMetrics(**score['metrics'])})
    return {name: metrics.aggregate_cases([restore(r['scores'][name]) for r in rows])
            for name in ('lexical', 'dense', 'final')}


def run(package, output):
    report = {'schema': 'portable_validation_v1', 'package': str(package),
              'status': 'FAIL', 'cases': [], 'failures': []}
    conn = child = None
    previous = os.environ.get('PATH')
    complete = False
    try:
        manifest = json.loads((package / 'manifest.json').read_bytes())
        cases = json.loads((evaluation.ROOT / evaluation.GOLD).read_bytes())['cases']
        evaluation.require(len(cases) == 120 and len({c['case_id'] for c in cases}) == 120,
                           '120 unique frozen cases required')
        conn = sqlite3.connect((package / 'knowledge.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
        conn.execute('PRAGMA query_only=ON')
        with output.with_suffix('.stderr').open('wb') as stderr, output.with_suffix('.jsonl').open('wb') as raw:
            try:
                windows = os.environ.get('SystemRoot', os.environ.get('SYSTEMROOT', 'C:/Windows'))
                started = time.perf_counter()
                try:
                    os.environ['PATH'] = os.path.join(windows, 'System32') + ';' + windows
                    child = Driver([str(package / 'bin/semantic_pilot.exe'),
                                    str(package / 'knowledge.sqlite'), str(package / 'manifest.json')], stderr)
                finally:
                    if previous is None:
                        os.environ.pop('PATH', None)
                    else:
                        os.environ['PATH'] = previous
                report['opened'], report['startup_response_bytes'] = child.receive(180)
                report['startup_ms'] = (time.perf_counter() - started) * 1000
                evaluation.require(report['opened']['event'] == 'opened' and
                                   report['opened']['retries'] == 0, 'resident startup mismatch')
                for case in cases:
                    row = {'case_id': case['case_id'], 'status': 'FAIL'}
                    report['cases'].append(row)
                    child.last_raw = b''
                    started = time.perf_counter()
                    try:
                        response, response_bytes = child.request(case)
                        row.update(wall_ms=(time.perf_counter() - started) * 1000,
                                   response_bytes=response_bytes, backend_ms=response.get('timings_ms'))
                        raw.write(child.last_raw)
                        raw.flush()  # Keep completed responses before validation can fail.
                        _verify_response_snapshot(response, conn)
                        row['source_closure'] = 'PASS'
                        result = evaluation.score_response(case, response, manifest)
                        row['scores'] = {n: asdict(v) for n, v in result.items()}
                        evaluation.require(row['wall_ms'] <= 5000 and response['timings_ms']['total'] <= 5000,
                                           'resident query budget exceeded')
                        evaluation.require(0 < response_bytes <= MAX_BYTES, 'response byte budget exceeded')
                        row['status'] = 'PASS'
                    except BaseException as exc:
                        row.setdefault('wall_ms', (time.perf_counter() - started) * 1000)
                        row['error'] = f'{type(exc).__name__}: {exc}'
                        if child.transport_failure or ('response_bytes' not in row and child.last_raw):
                            prefix = output.with_suffix('.partial.bin')
                            prefix.write_bytes(child.last_raw[:MAX_BYTES + 1])
                            row['transport_failure'] = {**(child.transport_failure or {}), 'raw_prefix': str(prefix)}
                        raise
                complete = True
            finally:
                if child is not None:
                    try:
                        report['shutdown'] = child.close(terminal=not complete)
                        evaluation.require(report['shutdown']['exit_code'] == 0 and
                                           not report['shutdown']['actively_terminated'] and
                                           report['shutdown']['reader_joined'], 'resident shutdown failed')
                    except BaseException as exc:  # noqa: BLE001 - retain cleanup/failure evidence
                        report['failures'].append(f'driver cleanup: {type(exc).__name__}: {exc}')
        aggregates = _aggregates(report['cases'])
        report['metrics'] = {n: {g: asdict(v) for g, v in a.items()} for n, a in aggregates.items()}
        quality = evaluation.quality_gate(aggregates['lexical'], aggregates['final'])
        report['quality_gate'] = _gate(quality['checks'])
        report['status'] = 'PASS' if not report['failures'] and quality['status'] == 'PASS' else 'FAIL'
    except BaseException as exc:
        report['failures'].append(f'{type(exc).__name__}: {exc}')
        raise
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - retain cleanup/failure evidence
            report['failures'].append(f'database cleanup: {exc}')
            report['status'] = 'FAIL'
        report['source_closure'] = _gate([{'case_id': r['case_id'], 'pass': r.get('source_closure') == 'PASS'}
                                          for r in report['cases']], 120)
        report['case_gate'] = _gate([{'case_id': r['case_id'], 'pass': r['status'] == 'PASS'}
                                     for r in report['cases']], 120)
        report['wall_ms'] = _summary([r['wall_ms'] for r in report['cases'] if 'wall_ms' in r])
        report['response_bytes'] = _summary([r['response_bytes'] for r in report['cases'] if 'response_bytes' in r])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False))
    return report


def analyze(saved, baseline=FP32, raw=None):
    """Compare saved metrics and entire ordered raw lexical rows/pins; no hashes."""
    saved, baseline = Path(saved), Path(baseline)
    baseline_report = baseline / 'evaluation.json' if baseline.is_dir() else baseline
    baseline_raw = baseline_report.parent
    candidate = json.loads(saved.read_bytes())
    reference = json.loads(baseline_report.read_bytes())
    rows, prior = candidate['cases'], reference.get('formal', reference.get('cases'))
    expected = {c['case_id']: c for c in json.loads((evaluation.ROOT / evaluation.GOLD).read_bytes())['cases']}

    def index(items):
        result = {r['case_id']: r for r in items}
        evaluation.require(len(items) == len(result) == 120 and set(result) == set(expected),
                           'saved evidence must contain exactly the frozen 120 unique cases')
        evaluation.require(all('scores' in r for r in items), 'incomplete saved scores')
        return result

    current, old = index(rows), index(prior)
    report = {'schema': 'portable_saved_comparison_v1', 'saved': str(saved),
              'baseline': str(baseline_report), 'raw': str(raw or saved.with_suffix('.jsonl')),
              'baseline_status': reference.get('status'), 'per_case_changes': [], 'aggregate_deltas': {}}
    aggregates = _aggregates(rows)
    baseline_aggregates = _aggregates(prior)
    for branch in aggregates:
        report['aggregate_deltas'][branch] = {}
        for group, value in aggregates[branch].items():
            deltas = {}
            for name, rate in value.metrics.items():
                before = baseline_aggregates[branch][group].metrics[name].value
                deltas[name] = {'baseline': before, 'candidate': rate.value,
                                'delta': rate.value - before if before is not None and rate.value is not None else None}
            report['aggregate_deltas'][branch][group] = deltas
    for case_id in sorted(expected):
        changes = {}
        for branch in ('lexical', 'dense', 'final'):
            changed = {}
            for name, value in current[case_id]['scores'][branch]['metrics'].items():
                before = old[case_id]['scores'][branch]['metrics'][name]
                if before != value:
                    changed[name] = {'baseline': before, 'candidate': value,
                                     'delta': value - before if value is not None and before is not None else None}
            if changed:
                changes[branch] = changed
        if changes:
            report['per_case_changes'].append({'case_id': case_id, 'subset': expected[case_id]['subset'], 'changes': changes})
    quality = evaluation.quality_gate(aggregates['lexical'], aggregates['final'])
    report['quality_gate'] = _gate(quality['checks'])
    lexical_checks, query_checks, status_checks = [], [], []
    totals, sizes, seen = [], [], set()
    with Path(report['raw']).open('rb') as stream:
        for line in stream:
            response = json.loads(line)
            case_id = response['case_id']
            evaluation.require(case_id in expected and case_id not in seen, 'unknown/duplicate raw case')
            seen.add(case_id)
            evaluation.require(response['query'] == expected[case_id]['query'], 'raw query mismatch')
            original = json.loads((baseline_raw / f'formal-{case_id}.json').read_bytes())
            evaluation.require(original['case_id'] == case_id and original['query'] == response['query'],
                               'baseline raw case/query mismatch')
            lexical_checks.append({'case_id': case_id,
                                   'lexical_hits_equal': response['lexical_hits'] == original['lexical_hits'],
                                   'trusted_pins_equal': response['trusted_pins'] == original['trusted_pins']})
            lexical_checks[-1]['pass'] = lexical_checks[-1]['lexical_hits_equal'] and lexical_checks[-1]['trusted_pins_equal']
            status_checks.append({'case_id': case_id, 'pass': response['status'] == 'PASS' and
                                  current[case_id].get('status', 'PASS') == 'PASS'})
            wall, backend, size = current[case_id]['wall_ms'], response['timings_ms']['total'], len(line)
            totals.append(backend)
            sizes.append(size)
            query_checks.append({'case_id': case_id, 'wall_ms': wall, 'backend_ms': backend,
                                 'response_bytes': size, 'saved_response_bytes': current[case_id]['response_bytes'],
                                 'pass': all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 5000
                                             for v in (wall, backend)) and
                                 0 < size <= MAX_BYTES and size == current[case_id]['response_bytes']})
    evaluation.require(seen == set(expected), 'raw evidence does not cover the frozen 120')
    report['lexical_equality'] = _gate(lexical_checks, 120)
    report['case_status_gate'] = _gate(status_checks, 120)
    report['query_5s_and_bytes_gate'] = _gate(query_checks, 120)
    report['wall_ms'] = _summary([r['wall_ms'] for r in rows])
    report['backend_ms'] = _summary(totals)
    report['response_bytes'] = _summary(sizes)
    # Old reports have only a global closure assertion, not per-case attestations.
    report['saved_source_closure'] = candidate.get('source_closure')
    report['status'] = 'PASS' if all(report[g]['status'] == 'PASS' for g in
                                     ('quality_gate', 'lexical_equality', 'case_status_gate', 'query_5s_and_bytes_gate')) else 'FAIL'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compare', type=Path, help='analyze saved evaluation JSON; never run a child')
    parser.add_argument('--baseline', type=Path, default=FP32, help='saved FP32 directory or JSON')
    parser.add_argument('--raw', type=Path, help='candidate JSONL (defaults to saved JSON stem)')
    args = parser.parse_args()
    if args.compare:
        if args.package or args.output:
            parser.error('--compare cannot be combined with --package/--output')
        print(json.dumps(analyze(args.compare, args.baseline, args.raw), ensure_ascii=False, indent=2))
    else:
        if not args.package or not args.output or args.raw:
            parser.error('runner requires --package and --output; --raw is comparison-only')
        run(args.package, args.output)


if __name__ == '__main__':
    main()
