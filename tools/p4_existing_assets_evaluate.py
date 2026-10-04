"""Evaluate existing FULL assets through one resident Rust process; never rebuild."""
from __future__ import annotations

import argparse
import hashlib
import math
import time
from dataclasses import asdict

from tools import p4_full_acceptance as acceptance
from tools import p4_full_build as build
from tools import p4_retrieval_metrics as metrics
from tools import p4_rust_pilot as pilot

ROOT = build.ROOT
GOLD = 'reports/P4/retrieval-gold.json'
QUERY_CONFIG = 'configs/p4-pilot-query-b.json'
GOLD_SHA = 'ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba'
INPUTS = (GOLD, QUERY_CONFIG, 'configs/p4-benchmark-v2.json',
          'docs/p4-benchmark-selection-v2.md', 'tools/p4_retrieval_metrics.py',
          'tools/p4_existing_assets_evaluate.py', 'configs/p4-full-semantic-v1.json',
          'configs/p4-current-assets.json')
require = build.require


def freeze_inputs():
    """Hash actual small input bytes, not historical receipts or large assets."""
    records, bindings = [], {}
    for name in INPUTS:
        path = build.full.contained(name, ROOT)
        data = path.read_bytes()
        ref = {'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        records.append((path, ref, 'input'))
        bindings[name] = ref
    gold = build.read_json(ROOT / GOLD)
    query = build.read_json(ROOT / QUERY_CONFIG)
    require(query['gold'] == GOLD and query['gold_sha256'] == GOLD_SHA and
            bindings[GOLD]['sha256'] == GOLD_SHA, 'frozen gold bytes mismatch')
    config = build.read_json(ROOT / 'configs/p4-full-semantic-v1.json')
    require((config['snapshot']['sha256'], config['snapshot']['size']) ==
            (gold['base_snapshot_sha256'], gold['base_snapshot_bytes']),
            'FULL snapshot differs from gold snapshot')
    cases = sorted(gold['cases'], key=lambda c: c['case_id'])
    require(len(cases) == 120 and len({c['case_id'] for c in cases}) == 120,
            '120 unique frozen cases required')
    counts = {s: sum(subset(c) == s for c in cases) for s in metrics.SUBSETS}
    require(counts == {'lexical': 30, 'semantic': 40, 'crosslingual': 30,
                       'ambiguous_negative': 20}, 'frozen subset counts mismatch')
    return cases, config, bindings, records


def subset(case):
    return 'ambiguous_negative' if case['subset'] == 'ambiguous/negative' else case['subset']


def keys(rows):
    return [metrics.EntryKey(**row['entry']) for row in rows]


def score_response(case, response, manifest):
    """Independent arithmetic on FULL branch lists; no pilot/exact-dense oracle."""
    require(response['status'] == 'PASS' and response['case_id'] == case['case_id'] and
            response['query'] == case['query'], 'response case/status mismatch')
    require(response['contract'] == manifest['contract'] and
            response['pack_version'] == manifest['pack_version'], 'runtime contract mismatch')
    require(response['identity_status'] == 'not_asserted' and
            response['promoted_identities'] == [] and response['canonical'] is None and
            response['entity_tag'] is None, 'identity promotion forbidden')
    timings = response['timings_ms']
    require(timings and all(type(v) in (int, float) and math.isfinite(v) and v >= 0
                           for v in timings.values()), 'invalid backend timings')
    branches = {}
    for name in ('lexical', 'dense'):
        rows = response[name + '_hits']
        require(len(rows) <= 100 and [r['rank'] for r in rows] == list(range(1, len(rows) + 1)),
                'invalid branch ranks/depth')
        branches[name] = [metrics.Hit(metrics.EntryKey(**r['entry']), r['rank']) for r in rows]
    pins = [metrics.TrustedPin(metrics.EntryKey(**p['entry']), p['match'],
                               p['source_id'], p['evidence_id']) for p in response['trusted_pins']]
    expected = [c.entry for c in metrics.reciprocal_rank_fusion(branches, pins)][:100]
    require(keys(response['hybrid']) == expected and keys(response['candidates']) == expected,
            'independent FULL fusion mismatch')
    require([r['hybrid_rank'] for r in response['candidates']] == list(range(1, len(expected) + 1)),
            'invalid final ranks')
    targets = [metrics.EntryKey(**t['entry_key']) for t in case['accepted_targets']]
    return {name: metrics.evaluate_case(case['case_id'], subset(case), ranking, targets)
            for name, ranking in {'lexical': keys(response['lexical_hits']),
                                  'dense': keys(response['dense_hits']), 'final': expected}.items()}


def quality_gate(lexical, final):
    """Frozen v2 quality-only gate against same-population FULL lexical results."""
    checks = []
    for group in ('lexical', 'semantic', 'crosslingual'):
        for metric in ('recall_at_10', 'mrr_at_10', 'ndcg_at_10'):
            baseline = lexical[group].metrics[metric].value
            value = final[group].metrics[metric].value
            require(baseline is not None and value is not None, 'missing quality denominator')
            if group == 'lexical':
                target = baseline - (1 / 30 if metric == 'recall_at_10' else .03)
            else:
                target = min(1, baseline + .10) if metric == 'recall_at_10' else baseline
            checks.append({'subset': group, 'metric': metric, 'baseline': baseline,
                           'value': value, 'target': target, 'pass': value >= target})
    for group, report in final.items():
        for name in ('identity_promotion_error_rate', 'negative_identity_promotion_error_rate'):
            rate = getattr(report, name)
            checks.append({'subset': group, 'metric': name, 'value': rate.value,
                           'denominator': rate.denominator,
                           'pass': rate.value == 0 if rate.denominator else rate.value is None})
    return {'status': 'PASS' if all(c['pass'] for c in checks) else 'FAIL', 'checks': checks}


def finish_driver(driver, report):
    """EOF is the successful shutdown path; kill is failure recovery only."""
    process = driver.process
    try:
        process.stdin.close()
        report['exit_code'] = process.wait(timeout=10)
        require(report['exit_code'] == 0, 'resident driver nonzero exit')
    except Exception:
        if process.poll() is None:
            process.kill()
        report['exit_code'] = process.wait(timeout=10)
        raise
    finally:
        process.stdout.close()


def evaluate(*, binary, output, results, existing_pack=False, verified_session=None):
    """Create-new candidate and result directory. Return retained report on failure."""
    candidate = build.full.controlled_path(ROOT / output, ROOT, strict=False)
    destination = build.full.controlled_path(ROOT / results, ROOT, strict=False)
    require((candidate.is_dir() if existing_pack else not candidate.exists()) and not destination.exists(),
            'no overwrite: new directories required')
    require(not candidate.is_relative_to(destination) and not destination.is_relative_to(candidate),
            'candidate and results must be disjoint new directories')
    executable = build.full.contained(binary, ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    report = {'schema': 'p4-existing-assets-evaluation-v1', 'status': 'FAIL',
              'candidate': str(candidate), 'results': str(destination), 'failures': [],
              'warmups': [], 'formal': [], 'exit_code': None,
              'stderr': str(destination / 'stderr.log'),
              'dense_overlap': {'status': 'NOT_RUN', 'reason': 'FULL exact oracle absent'},
              'total_quality': 'NOT_RUN', 'retries': 0}
    driver = None
    try:
        from contextlib import nullcontext
        with (nullcontext(verified_session) if verified_session is not None else acceptance.AcceptanceSession()) as session:
            cases, config, bindings, records = freeze_inputs()
            report['inputs'] = bindings
            binary_ref = build.binding(executable, ROOT)
            report['binary'] = binary_ref
            records.append((executable, binary_ref, 'input'))
            for phase, rows in (('warmups', cases[:2]), ('formal', cases)):
                report[phase] = [{'case_id': c['case_id'], 'status': 'NOT_RUN'} for c in rows]
            with session.guard(records):
                if existing_pack:
                    manifest = build.read_json(candidate / 'manifest.json')
                    acceptance.validate_full_manifest(manifest, config, pack_root=candidate, session=session)
                else:
                    manifest = build.existing_assets(output=output, session=session)
                report['manifest'] = build.binding(candidate / 'manifest.json', ROOT)
                build.save_new(destination / 'frozen-inputs.json', {'inputs': bindings, 'cases': cases})
                scored = {name: [] for name in ('lexical', 'dense', 'final')}
                with session.guard([(candidate / 'manifest.json', report['manifest'], 'input')]), \
                        build.full.readonly(ROOT / config['snapshot']['path']) as conn, \
                        (destination / 'stderr.log').open('xb') as stderr:
                    try:
                        start = time.perf_counter()
                        driver = pilot.Driver([str(executable), str(ROOT / config['snapshot']['path']),
                                               str(candidate / 'manifest.json')], stderr)
                        opened, size = driver.receive(pilot.POLICY['startup_timeout_seconds'])
                        report.update(opened=opened, startup_response_bytes=size,
                                      startup_wall_ms=(time.perf_counter() - start) * 1000)
                        require(opened['event'] == 'opened' and opened['retries'] == 0 and
                                isinstance(opened['open_timings_ms'], dict), 'resident startup mismatch')
                        for phase, rows in (('warmups', cases[:2]), ('formal', cases)):
                            if phase == 'formal':
                                require(all(row['status'] == 'PASS' for row in report['warmups']),
                                        'warmup failure prevents formal quality evaluation')
                            for case, row in zip(rows, report[phase], strict=True):
                                row['status'] = 'FAIL'
                                start = time.perf_counter()
                                try:
                                    response, size = driver.request(case)
                                    row.update(wall_ms=(time.perf_counter() - start) * 1000,
                                               response_bytes=size, backend_ms=response.get('timings_ms'))
                                    build.save_new(destination / f'{phase}-{case["case_id"]}.json', response)
                                    require_success_response(response)
                                    acceptance.validate_response(response, snapshot_conn=conn, session=session)
                                    scores = score_response(case, response, manifest)
                                    require(row['wall_ms'] <= 5000 and response['timings_ms']['total'] <= 5000,
                                            'resident query budget exceeded')
                                    row.update(status='PASS', scores={n: asdict(v) for n, v in scores.items()})
                                    if phase == 'formal':
                                        for name, score in scores.items():
                                            scored[name].append(score)
                                except Exception as exc:  # retain failures, never retry
                                    row.setdefault('wall_ms', (time.perf_counter() - start) * 1000)
                                    row['error'] = str(exc)
                                    report['failures'].append(f'{phase}/{case["case_id"]}: {exc}')
                                    if (driver.process.poll() is not None or
                                            isinstance(exc, (TimeoutError, OSError, RustFailure)) or
                                            'EOF/oversize JSONL response' in str(exc)):
                                        raise
                        if all(r['status'] == 'PASS' for r in report['formal']):
                            aggregates = {n: metrics.aggregate_cases(v) for n, v in scored.items()}
                            report['aggregates'] = {n: {s: asdict(v) for s, v in a.items()}
                                                    for n, a in aggregates.items()}
                            report['quality_gate'] = quality_gate(aggregates['lexical'], aggregates['final'])
                    finally:
                        if driver is not None:
                            closing, driver = driver, None
                            finish_driver(closing, report)
            report['status'] = ('PASS' if not report['failures'] and
                                report.get('quality_gate', {}).get('status') == 'PASS' else 'FAIL')
    except Exception as exc:  # noqa: BLE001 - retain the complete failed run
        report['failures'].append(str(exc))
    finally:
        if driver is not None:
            try:
                finish_driver(driver, report)
            except Exception as exc:  # noqa: BLE001 - cleanup must not discard evidence
                report['failures'].append(str(exc))
        build.save_new(destination / 'evaluation.json', report)
    return report


class RustFailure(RuntimeError):
    """A received terminal Rust FAIL envelope, not a malformed success response."""


def require_success_response(response):
    if response.get('status') == 'FAIL':
        require(isinstance(response.get('error'), str) and response.get('retries') == 0,
                'invalid Rust failure envelope')
        raise RustFailure(response['error'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--output', required=True, help='new candidate directory')
    parser.add_argument('--results', required=True, help='disjoint new results directory')
    parser.add_argument('--existing-pack', action='store_true', help='revalidate an existing immutable candidate rather than republish')
    args = parser.parse_args(argv)
    report = evaluate(binary=args.binary, output=args.output, results=args.results, existing_pack=args.existing_pack)
    print(build.full.chunks.canonical(report).decode('utf8'))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
