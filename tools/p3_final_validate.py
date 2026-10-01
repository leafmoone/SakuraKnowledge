"""Final S02 -> P2 -> gold -> external, once only; no performance executor.

Prerequisite final-performance-recomputed.json must attest status PASS,
formal_counts (900/900/0), structure_errors [], performance_rerun "NO", and
byte bindings old_receipt (close-performance.json), policy (the revised
p3_measure_resolver.py). It is supplied by the separately authorized pure
recomputation, never generated or rerun here.
"""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import p3_close_validate as helpers
from p3_evidence import verify
from p3_final_artifacts import (
    PROFILE,
    RAW,
    REPORTS,
    ROOT,
    RUNTIME,
    binding,
    check_binding,
    create_new,
    source_git,
    verify_artifacts,
)
from p3_retry1_sidecar_audit import metadata, validate_metadata, verify_snapshot

PHASES = ('S02', 'P2', 'gold', 'external')
PROFILE_SINK = ROOT / 'build/p3-final-S02-profile.json'
_BASE_CAPTURE = helpers.capture


def load(path):
    return json.loads(Path(path).read_bytes().decode('utf-8', errors='strict'))


def capture(argv, cwd, *, env=None, input_bytes=None, timeout=15, s02_profile=False):
    env = dict(os.environ if env is None else env, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    env.pop(PROFILE, None)
    if s02_profile:
        env[PROFILE] = str(PROFILE_SINK)
    started_ns = time.time_ns()
    rec, value = _BASE_CAPTURE(argv, cwd, env=env, input_bytes=input_bytes, timeout=timeout)
    rec.update(started_ns=started_ns, finished_ns=time.time_ns(),
               environment={k: env.get(k) for k in ('PYTHONUTF8', 'PYTHONIOENCODING', PROFILE)},
               source_external_cwd=True)
    return rec, value


def configure_helpers():
    # Assign, don't replace the shared frozen helper files or use string rewriting.
    helpers.RAW = RAW
    helpers.capture = capture


def performance_prerequisite():
    path = REPORTS / 'final-performance-recomputed.json'
    receipt = load(path)
    if (receipt.get('status') != 'PASS' or receipt.get('performance_rerun') != 'NO' or
            receipt.get('formal_counts') != {'attempted': 900, 'success': 900, 'failed': 0} or
            receipt.get('structure_errors') != []):
        raise ValueError('formal performance recomputation must PASS with no rerun')
    for field, expected in (('old_receipt', REPORTS / 'close-performance.json'),
                            ('policy', ROOT / 'tools/p3_measure_resolver.py')):
        ref = receipt[field]
        if Path(ref['path']).resolve() != expected.resolve():
            raise ValueError('wrong performance provenance: ' + field)
        check_binding(ref)
    dependencies = [ROOT / ('tools/' + name) for name in (
        'p3_final_recompute.py', 'p3_measure_resolver.py', 'p3_retry1_acceptance.py',
        'check_parity.py', 'p3_evidence.py', 'p3_accept_resolver.py', 'p3_resolver_oracle.py')]
    refs = receipt.get('verifier_bindings', [])
    if (len(refs) != len(dependencies) or
            {Path(ref['path']).resolve() for ref in refs} != {p.resolve() for p in dependencies}):
        raise ValueError('missing or unexpected recomputation verifier provenance')
    for ref in refs:
        check_binding(ref)
    old = load(receipt['old_receipt']['path'])
    if old['source_commit'] != RUNTIME:
        raise ValueError('old performance runtime does not match unchanged runtime baseline')
    return binding(path)


def static_coverage(gold, p2):
    """Derive references from verified frozen facts, never guessed case numbers."""
    if len(gold['cases']) != 55 or len(p2['cases']) != 151:
        raise ValueError('frozen case counts changed')
    ids = [r['id'] for r in gold['cases']]
    if len(set(ids)) != 55 or ids.count('G42') != 1:
        raise ValueError('gold must contain exactly one declared G42')
    if len({r['case_id'] for r in p2['cases']}) != 151:
        raise ValueError('P2 case IDs are not unique')
    positives, negatives, utf8, errors = [], [], [], []
    for row in gold['cases']:
        expected = row['expected']
        oracle = helpers.prior.frozen_value(row['oracle_json'])
        if helpers.prior.source_checks(oracle, expected):
            raise ValueError('frozen source facts not verified: ' + row['id'])
        if expected.get('description'):
            if not any(a.get('role') == 'description'
                       for a in expected.get('evidence_assertions', [])):
                raise ValueError('description claim lacks declared source evidence')
            positives.append(row['id'])
        if expected.get('status') != 'resolved' and expected.get('descriptions_empty'):
            if oracle.get('descriptions') != []:
                raise ValueError('non-resolved descriptions are not empty')
            negatives.append({'case_id': row['id'], 'status': expected['status']})
    for row in p2['cases']:
        if any(ord(c) > 127 for c in json.dumps(row['args'], ensure_ascii=False)):
            utf8.append(row['case_id'])
        if row['mode'] in ('error', 'cli', 'runtime_error'):
            errors.append(row['case_id'])
    if not positives or not negatives or not utf8 or not errors:
        raise ValueError('missing frozen description/UTF-8/error coverage')
    return {'description_source_positive_ids': positives,
            'non_resolved_empty_description_cases': negatives,
            'P2_UTF8_case_ids': utf8, 'P2_error_contract_ids': errors}


def runplan(artifacts, frozen_gold, frozen_p2, performance, coverage, db):
    return {'source_commit': artifacts['source_commit'], 'artifacts': artifacts,
            'frozen_gold': frozen_gold, 'frozen_P2': frozen_p2, 'database': db,
            'performance_prerequisite': performance, 'phases': list(PHASES),
            'gold55_invocations': 1, 'gold55_serves': ['D', 'E'], 'G42_gold_count': 1,
            'performance_rerun': 'NO', 'S02_profile_invocations': 1,
            'S02_profile_sink': str(PROFILE_SINK), 'retries': 0,
            'source_external_all_phases': True, 'coverage': coverage,
            'external_queries': 0, 'database_write_probes': 0}


def require_pass(phase, plan):
    path = REPORTS / ('final-' + phase + '.json')
    receipt = load(path)
    if receipt['status'] != 'PASS' or receipt['phase'] != phase:
        raise ValueError('prerequisite not PASS: ' + phase)
    for field in ('source_commit', 'artifacts', 'frozen_gold', 'frozen_P2', 'database',
                  'performance_prerequisite'):
        if receipt[field] != plan[field]:
            raise ValueError('prerequisite binding differs: ' + phase + '/' + field)
    if receipt['runplan'] != binding(REPORTS / 'final-runplan.json'):
        raise ValueError('prerequisite runplan changed')
    return receipt, binding(path)


def s02(binary, db, p2, cwd):
    case = next(r for r in p2['cases'] if r['case_id'] == 'S02')
    if PROFILE_SINK.exists() or PROFILE_SINK.is_symlink():
        raise FileExistsError(PROFILE_SINK)
    if not PROFILE_SINK.parent.is_dir():
        raise NotADirectoryError(PROFILE_SINK.parent)
    # The same Rust invocation reserves the absent sink with create_new before its query.
    rec, value = capture(helpers.commands(binary, db, case), cwd, s02_profile=True)
    profile = load(PROFILE_SINK) if PROFILE_SINK.stat().st_size else None
    passed = (helpers.prior.usable(rec, value) and
              value == helpers.prior.frozen_value(case['expected_json']) and
              profile is not None and profile['query_invocations'] == 1 and
              profile['profile'].get('fts_skipped_kind_not_indexed') is True)
    return {'status': 'PASS' if passed else 'FAIL', 'rust': rec, 'profile': profile,
            'profile_raw': helpers.evidence(PROFILE_SINK.read_bytes()) if profile is not None else None,
            'profile_environment': {PROFILE: str(PROFILE_SINK)}, 'retries': 0}


def external(artifacts, plan, cwd):
    p2, p2_ref = require_pass('P2', plan)
    gold, gold_ref = require_pass('gold', plan)
    # No DB open: isolated installed provenance and help/refusal checks only.
    code = ("import json,sys,inspect,sakura_knowledge.api as a,sakura_knowledge.cli as c;"
            "from sakura_knowledge.api import Knowledge;"
            "print(json.dumps({'modules':{'sakura_knowledge/api.py':a.__file__,"
            "'sakura_knowledge/cli.py':c.__file__},'resolve_tag':hasattr(Knowledge,'resolve_tag'),"
            "'public_api':{n:str(inspect.signature(v)) for n,v in inspect.getmembers(Knowledge) "
            "if not n.startswith('_') and callable(v)},'prefix':sys.prefix,'path':sys.path,"
            "'encoding':sys.stdout.encoding,'utf8':sys.flags.utf8_mode}))")
    rec, info = capture([artifacts['python'], '-X', 'utf8', '-I', '-c', code], cwd)
    expected_modules = {r['module']: r['installed']['path'] for r in artifacts['modules']}
    good = (helpers.prior.usable(rec, info) and not info['resolve_tag'] and
            info['encoding'].lower() == 'utf-8' and info['utf8'] == 1 and
            Path(info['prefix']).resolve() == Path(artifacts['directory']).resolve() / 'venv' and
            set(info['modules']) == {'sakura_knowledge/api.py', 'sakura_knowledge/cli.py'} and
            all(Path(path).resolve() == Path(expected_modules[name]).resolve()
                for name, path in info['modules'].items()) and
            not any(Path(p).resolve().is_relative_to(ROOT / 'src') for p in info['path'] if p))
    processes = [rec]
    for argv in ([artifacts['binary']['path'], '--help'],
                 [artifacts['python'], '-X', 'utf8', '-I', '-m', 'sakura_knowledge.cli', '--help']):
        help_rec, _ = capture(argv, cwd)
        text = verify(help_rec['stdout']).decode('utf-8', errors='strict')
        good = good and help_rec['exit'] == 0 and not help_rec['stderr']['bytes'] and bool(text)
        if argv[0] == artifacts['python']:
            good = good and 'resolve-tag' not in text and 'resolve_tag' not in text
        processes.append(help_rec)
    refusal, _ = capture([artifacts['python'], '-X', 'utf8', '-I', '-m',
                          'sakura_knowledge.cli', 'resolve-tag'], cwd)
    error = refusal.get('error', {})
    good = (good and refusal['exit'] == 2 and not refusal['timeout'] and
            not refusal['stdout']['bytes'] and error.get('error') == 'UsageError' and
            'invalid choice' in error.get('message', '') and 'resolve-tag' in error.get('message', ''))
    processes.append(refusal)
    # These claims use exactly the recorded workloads, never extra query probes.
    gold_ids = [r['case_id'] for r in gold['records']]
    p2_ids = [r['case_id'] for r in p2['records']]
    claimed_gold = plan['coverage']['description_source_positive_ids'] + [
        r['case_id'] for r in plan['coverage']['non_resolved_empty_description_cases']]
    claimed_p2 = plan['coverage']['P2_UTF8_case_ids'] + plan['coverage']['P2_error_contract_ids']
    good = (good and len(gold_ids) == len(set(gold_ids)) == 55 and gold_ids.count('G42') == 1 and
            len(p2_ids) == len(set(p2_ids)) == 151 and
            all(r['passed'] for r in gold['records']) and
            all(r['passed'] and r['installed_python_passed'] for r in p2['records']) and
            set(claimed_gold) <= set(gold_ids) and set(claimed_p2) <= set(p2_ids))
    return {'status': 'PASS' if good else 'FAIL', 'environment': info, 'processes': processes,
            'FULL_151_receipt': p2_ref, 'FULL_55_receipt': gold_ref,
            'coverage': plan['coverage'], 'gold55_serves': ['D', 'E'], 'G42_gold_count': 1,
            'Python_public_resolver_added': False, 'public_API_unchanged_by_exact_module_bytes': True,
            'source_external_verified': bool(good), 'extra_query_probes': 0, 'retries': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=PHASES)
    args = parser.parse_args()
    configure_helpers()
    out, marker = (REPORTS / ('final-' + args.phase + suffix)
                   for suffix in ('.json', '-start.json'))
    if out.exists() or marker.exists():
        raise FileExistsError('phase already recorded or reserved; no retry')
    artifacts = load(REPORTS / 'final-artifacts-retry1.json')
    verify_artifacts(artifacts)  # Before every phase, not just artifact creation.
    source = source_git(artifacts['source_commit'], allow_evidence=True)
    performance = performance_prerequisite()  # Must precede every runtime command.
    gold, p2, db_ref = helpers.validate_inputs()  # Only frozen byte/metadata checks.
    coverage = static_coverage(gold, p2)
    plan = runplan(artifacts, binding(helpers.prior.GOLD), binding(helpers.prior.P2),
                   performance, coverage, db_ref)
    plan_path = REPORTS / 'final-runplan.json'
    if not plan_path.exists():
        if args.phase != 'S02':
            raise ValueError('runplan must be recorded before S02')
        create_new(plan_path, plan)
    elif load(plan_path) != plan:
        raise ValueError('fixed runplan/artifacts/source/frozen inputs changed')
    prerequisites = {}
    for phase in PHASES[:PHASES.index(args.phase)]:
        _, prerequisites[phase] = require_pass(phase, plan)
    if args.phase == 'S02' and PROFILE_SINK.exists():
        raise FileExistsError('S02 profile sink is not fresh')
    create_new(marker, {**plan, 'phase': args.phase, 'created_ns': time.time_ns(),
                        'runplan': binding(plan_path), 'prerequisites': prerequisites})
    result, db, gate = {'status': 'FAIL'}, None, None
    try:
        db, gate = verify_snapshot(Path(db_ref['path']), db_ref)
        result['readonly_gate_before'] = gate
        with tempfile.TemporaryDirectory(prefix='sknow-final-external-') as cwd:
            if Path(cwd).resolve().is_relative_to(ROOT):
                raise ValueError('source-external cwd required')
            binary = Path(artifacts['binary']['path'])
            if args.phase == 'S02':
                outcome = s02(binary, db, p2, cwd)
            elif args.phase in ('P2', 'gold'):
                outcome = helpers.suite(binary, db, gold['cases'] if args.phase == 'gold' else p2['cases'],
                                        cwd, args.phase == 'gold', artifacts['python'])
            else:
                outcome = external(artifacts, plan, cwd)
            result.update(outcome)
    except Exception as exc:  # noqa: BLE001 - failed/interrupted once-only attempts stay reserved
        result.update(status='FAIL', exception={'type': type(exc).__name__, 'message': str(exc)})
    # Protection also runs after child/decoder failure; no write/SQL probe is ever used.
    if db is not None and gate is not None:
        try:
            binding_ref = {**db_ref, 'path': str(db.resolve())}
            check_binding(binding_ref)
            after = metadata(db)
            validate_metadata(after)
            if after != gate['sidecars_after']:
                raise ValueError('database sidecars changed during phase')
            result['readonly_gate_after'] = {'database': binding_ref, 'sidecars': after,
                                             'hash_unchanged': True, 'write_probes': 0}
            verify_artifacts(artifacts)
            for ref in (plan['frozen_gold'], plan['frozen_P2'], performance):
                check_binding(ref)
        except Exception as exc:  # noqa: BLE001 - retain protection failure alongside runtime failure
            result.update(status='FAIL', protection_exception={
                'type': type(exc).__name__, 'message': str(exc)})
    result.update(**{k: plan[k] for k in ('source_commit', 'artifacts', 'frozen_gold', 'frozen_P2',
                                        'database', 'performance_prerequisite')},
                  runplan=binding(plan_path), prerequisites=prerequisites, source_git=source,
                  snapshot_scope='FULLSNAPSHOT', source_external_cwd=True, phase=args.phase,
                  performance_rerun='NO', finished_ns=time.time_ns())
    create_new(out, result)
    print(json.dumps({'status': result['status'], 'phase': args.phase}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
