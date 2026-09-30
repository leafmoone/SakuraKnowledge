"""Authorized A-L validation of one fixed code artifact and unchanged FULL DB.

One named run per phase; no build/refreeze, retries, outcome-based workloads or
budget relaxation. Historical frozen expected is read, never rewritten.
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path

import p3_retry1_acceptance as prior
from p3_evidence import save, store, verify
from p3_retry1_path_audit import check_binding
from p3_retry1_sidecar_audit import metadata, validate_metadata

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/P3'
RAW = Path('reports/P3/close-raw')
DB_SHA = '61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9'
IDS = ['G01', 'G21', 'G36', 'G37', 'G42', 'G43', 'G44', 'G45', 'G51', 'G52', 'G53', 'G54', 'G55', 'S02', 'S18']


def load(path):
    return json.loads(Path(path).read_bytes().decode('utf-8', errors='strict'))


def evidence(data):
    return store(data, root=RAW)


def capture(argv, cwd, *, env=None, input_bytes=None, timeout=15):
    env = dict(os.environ if env is None else env, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    started = time.perf_counter()
    outer = False
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, input=input_bytes, capture_output=True, timeout=timeout, check=False)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, err, code, outer = exc.stdout or b'', exc.stderr or b'', None, True
    rec = {'argv': argv, 'cwd': str(cwd), 'exit': code, 'elapsed_s': time.perf_counter()-started,
           'outer_timeout': outer, 'timeout': outer, 'attempted': 1, 'succeeded': 0, 'other_error': 0,
           'stdout': evidence(out), 'stderr': evidence(err), 'outer_timeout_s': timeout, 'inner_budget_s': 5}
    value = None
    try:
        text = (out if code == 0 else err).decode('utf-8', errors='strict')
        parsed = json.loads(text)
        if code == 0:
            value = parsed
            rec['succeeded'] = 1
        else:
            rec['error'] = parsed
            rec['timeout'] = outer or isinstance(parsed, dict) and parsed.get('message') == 'query_budget_exceeded'
    except (ValueError, TypeError) as exc:
        rec['decode_error'] = str(exc)
    rec['other_error'] = int(not rec['succeeded'] and not rec['timeout'])
    return rec, value


def validate_inputs():
    gold, p2 = load(prior.GOLD), load(prior.P2)
    for frozen in (gold, p2):
        if frozen['status'] != 'PASS' or not frozen['frozen_before_runtime']:
            raise ValueError('missing pre-runtime freeze')
        for ref in frozen['bindings'] + frozen['source_proof']:
            if Path(ref['path']).resolve() == ROOT / 'tools/p3_retry1_acceptance.py':
                data = Path(ref['path']).read_bytes()
                restored = data.replace(b'  # noqa: BLE001 - retain any case failure in the evidence receipt', b'')
                restored = restored.replace(b"raise TypeError('invalid frozen full JSON')", b"raise ValueError('invalid frozen full JSON')")
                if len(restored) != ref['bytes'] or hashlib.sha256(restored).hexdigest() != ref['sha256']:
                    raise ValueError('acceptance change exceeded exact authorized lint edits')
            else:
                check_binding(ref)
        for case in frozen['cases']:
            for field in ('oracle_json', 'expected_json'):
                if field in case:
                    verify(case[field])
    if len(gold['cases']) != 55 or len(p2['cases']) != 151:
        raise ValueError('case count changed')
    if [prior.p2_case_data(c) for c in prior.CASES] != [
            {k: r[k] for k in ('case_id', 'op', 'args', 'historical_expect', 'mode')} for r in p2['cases']]:
        raise ValueError('case inputs changed')
    db = p2['database']
    if db['bytes'] != 21718736896 or db['sha256'] != DB_SHA or Path(db['path']).stat().st_size != db['bytes']:
        raise ValueError('wrong FULL snapshot')
    validate_metadata(metadata(Path(db['path'])))
    return gold, p2, db


def require_pass(name, artifacts):
    receipt = load(REPORTS / ('close-' + name + '.json'))
    if (receipt['status'] != 'PASS' or receipt['artifacts'] != artifacts or
            receipt['source_commit'] != artifacts['source_commit'] or
            receipt['frozen_gold'] != prior.binding(prior.GOLD) or
            receipt['frozen_P2'] != prior.binding(prior.P2)):
        raise ValueError('prerequisite failed or artifact/input binding differs: ' + name)


def commands(binary, db, row, gold=False):
    if gold:
        return prior.gold_command(binary, db, row['input'])
    if row['mode'] in ('cli', 'runtime_error'):
        return [str(binary)] + [str(db) if a == 'DB' else str(db.parent / 'missing-parity-input.sqlite') if a == 'DB_MISSING' else a
                               for a in row['args']['argv_rs']]
    prior.parity.DB = db
    return [str(binary)] + prior.parity.rust_argv(row['op'], row['args'])


def installed_python_case(python, db, case, cwd):
    if case['mode'] in ('cli', 'runtime_error'):
        args = [str(db) if a == 'DB' else str(db.parent / 'missing-parity-input.sqlite') if a == 'DB_MISSING' else a
                for a in case['args']['argv_py']]
        argv = [python, '-X', 'utf8', '-I', '-m', 'sakura_knowledge.cli', *args]
    else:
        code = ("import json,sys;from sakura_knowledge.api import Knowledge\n"
                "try:\n"
                " with Knowledge(sys.argv[1]) as k:\n"
                "  op=sys.argv[2];a=json.loads(sys.argv[3])\n"
                "  if op=='lookup_key': v=k.lookup(key={x:a[x] for x in ('kind','namespace','value')})\n"
                "  elif op=='related': v=k.related({x:a[x] for x in ('kind','namespace','value')},relation=a.get('relation'),kind=a.get('kind_filter'),limit=a.get('limit',20))\n"
                "  else: v=getattr(k,op)(**a)\n"
                "  print(json.dumps(v,ensure_ascii=False,separators=(',',':')))\n"
                "except Exception as e:\n"
                " print(json.dumps({'error':type(e).__name__,'message':str(e)}),file=sys.stderr);sys.exit(2)\n")
        argv = [python, '-X', 'utf8', '-I', '-c', code, str(db), case['op'], json.dumps(case['args'], ensure_ascii=False)]
    rec, value = capture(argv, cwd)
    if 'expected_json' in case:
        good = prior.usable(rec, value) and value == prior.frozen_value(case['expected_json'])
    else:
        expect = case['historical_expect']
        error = rec.get('error', {})
        good = rec['exit'] == expect.get('exit_py', 2) and not rec['timeout'] and not rec['stdout']['bytes']
        if case['mode'] == 'error':
            good = good and error.get('message') == expect['error']
        else:
            good = good and all(error.get(field) == expect['stderr_py_' + field]
                                for field in ('error', 'message') if 'stderr_py_' + field in expect)
    return rec, bool(good)


def suite(binary, db, cases, cwd, gold=False, python=None):
    rows = []
    for case in cases:
        rec, value = capture(commands(binary, db, case, gold), cwd)
        checked = prior.compare_gold(rec, value, case) if gold else prior.compare_p2(rec, value, case)
        row = {'case_id': case.get('id', case.get('case_id')), 'rust': rec, **checked}
        if not gold:
            py, py_passed = installed_python_case(python, db, case, cwd)
            row.update(installed_python=py, installed_python_passed=py_passed)
            if not py_passed:
                row['passed'] = False
                row['problems'].append({'kind': 'installed_python_vs_frozen_expected_failed'})
        rows.append(row)
    result = {'status': 'PASS' if all(r['passed'] for r in rows) else 'FAIL', 'records': rows,
              'attempted': len(rows), 'passed': sum(r['passed'] for r in rows),
              'timeouts': sum(bool(r['rust']['timeout']) for r in rows), 'retries': 0,
              'wrong_resolved': sum(r.get('wrong_resolved', False) for r in rows)}
    if not gold:
        result['summary'] = prior.summarize(rows, 151)
    return result


def performance(binary, reused, db, gold, p2, cwd):
    workloads = []
    for ident in IDS:
        row = next(r for r in (gold['cases'] if ident.startswith('G') else p2['cases']) if r.get('id', r.get('case_id')) == ident)
        request = dict(row['input'], id=ident) if ident.startswith('G') else dict(row['args'], id=ident, op='search')
        workloads.append((request, prior.frozen_value(row['oracle_json'] if ident.startswith('G') else row['expected_json'])))
    requests = [dict(case, round=r, warmup=r == -1) for r in range(-1, 30) for case, _ in workloads]
    expected = {case['id']: want for case, want in workloads}
    batch = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in requests).encode('utf-8')
    process, _ = capture([str(reused), str(db)], cwd, input_bytes=batch, timeout=600)
    # Batch is JSONL, not one JSON object; decode independently from retained bytes.
    process.pop('decode_error', None)
    try:
        decoded = [json.loads(line) for line in verify(process['stdout']).decode('utf-8', errors='strict').splitlines()]
    except ValueError:
        decoded = []
    rows = []
    complete = process['exit'] == 0 and not process['stderr']['bytes'] and len(decoded) == len(requests)
    for index, request in enumerate(requests):
        value = decoded[index] if complete else {}
        elapsed = value.get('elapsed_s')
        success = (complete and value.get('case_id') == request['id'] and value.get('value') == expected[request['id']]
                   and isinstance(elapsed, (float, int)) and 0 <= elapsed <= 5)
        rows.append({'mode': 'reused_connection', 'case_id': request['id'], 'round': request['round'], 'warmup': request['warmup'],
                     'success': bool(success), 'elapsed_s': elapsed, 'process_row': index})
    for request in requests:
        if request.get('op') == 'search':
            prior.parity.DB = db
            argv = [str(binary)] + prior.parity.rust_argv('search', {k: request[k] for k in ('query', 'topk', 'kind', 'namespace') if k in request})
        else:
            argv = prior.gold_command(binary, db, request)
        rec, value = capture(argv, cwd)
        success = prior.usable(rec, value) and value == expected[request['id']]
        rows.append({'mode': 'independent_cli', 'case_id': request['id'], 'round': request['round'], 'warmup': request['warmup'],
                     'success': bool(success), 'elapsed_s': rec['elapsed_s'], 'rust': rec})
    summary = []
    for mode in ('reused_connection', 'independent_cli'):
        for ident in IDS:
            measured = [r for r in rows if r['mode'] == mode and r['case_id'] == ident and not r['warmup']]
            times = sorted(r['elapsed_s'] for r in measured if r['success'])
            summary.append({'mode': mode, 'case_id': ident, 'attempted': len(measured), 'success': len(times),
                            'failed_rounds': [r['round'] for r in measured if not r['success']],
                            'p50_s': times[math.ceil(len(times)*.5)-1] if times else None,
                            'p95_s': times[math.ceil(len(times)*.95)-1] if times else None})
    process['input'] = evidence(batch)
    return {'status': 'PASS' if all(r['success'] for r in rows) else 'FAIL', 'workloads': IDS, 'samples': 30,
            'measured': len(IDS)*30*2, 'warmups': len(IDS)*2, 'retries': 0, 'records': rows,
            'summary': summary, 'reused_process': process,
            'protocol': {'inner_s': 5, 'cli_outer_s': 15, 'reused_batch_outer_s': 600, 'cache': 'not claimed cold',
                         'percentile': 'nearest rank on successful samples; failures/attempts explicit', 'rss': 'NOT_RUN'}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('S02', 'P2', 'gold', 'performance', 'external'))
    args = parser.parse_args()
    out = REPORTS / ('close-' + args.phase + '.json')
    if out.exists():
        raise FileExistsError(out)
    artifacts = load(REPORTS / 'close-artifacts.json')
    if artifacts['status'] != 'PASS':
        raise ValueError('artifacts not PASS')
    for field in ('binary', 'reused_binary', 'wheel'):
        check_binding(artifacts[field])
    for module in artifacts['modules']:
        if not module['bytes_equal_archive_wheel_installed']:
            raise ValueError('installed module provenance failed')
        check_binding(module['archive'])
        check_binding(module['installed'])
    gold, p2, db_ref = validate_inputs()
    db = Path(db_ref['path'])
    binary = Path(artifacts['binary']['path'])
    chain = ['S02', 'P2', 'performance', 'gold', 'external']
    for prerequisite in chain[:chain.index(args.phase)]:
        require_pass(prerequisite, artifacts)
    # Atomically reserve phase before runtime; an interrupted phase is never silently rerun.
    marker = REPORTS / ('close-' + args.phase + '-start.json')
    save(marker, {'phase': args.phase, 'created_ns': time.time_ns(), 'artifacts': artifacts,
                  'frozen_gold': prior.binding(prior.GOLD), 'frozen_P2': prior.binding(prior.P2), 'database': db_ref})
    with tempfile.TemporaryDirectory(prefix='sknow-close-external-') as cwd:
        if args.phase == 'S02':
            case = next(r for r in p2['cases'] if r['case_id'] == 'S02')
            sink = ROOT / 'build/p3-close-S02-profile.json'
            env = dict(os.environ, SKNOW_SEARCH_PROFILE_OUT=str(sink))
            rec, value = capture(commands(binary, db, case), cwd, env=env)
            profile = load(sink) if sink.exists() and sink.stat().st_size else None
            passed = (prior.usable(rec, value) and value == prior.frozen_value(case['expected_json'])
                      and profile is not None and profile['query_invocations'] == 1
                      and profile['profile'].get('fts_skipped_kind_not_indexed') is True)
            result = {'status': 'PASS' if passed else 'FAIL', 'rust': rec, 'profile': profile,
                      'profile_raw': evidence(sink.read_bytes()) if profile is not None else None,
                      'profile_environment': {'SKNOW_SEARCH_PROFILE_OUT': str(sink)}, 'retries': 0}
        elif args.phase in ('P2', 'gold'):
            result = suite(binary, db, gold['cases'] if args.phase == 'gold' else p2['cases'], cwd,
                           args.phase == 'gold', artifacts['python'])
        elif args.phase == 'performance':
            result = performance(binary, Path(artifacts['reused_binary']['path']), db, gold, p2, cwd)
        else:
            code = ("import json,sys,sakura_knowledge.api as a;from sakura_knowledge.api import Knowledge;"
                    "print(json.dumps({'file':a.__file__,'resolve_tag':hasattr(Knowledge,'resolve_tag'),'path':sys.path,"
                    "'encoding':sys.stdout.encoding,'utf8':sys.flags.utf8_mode}))")
            env_rec, environment = capture([artifacts['python'], '-X', 'utf8', '-I', '-c', code], cwd)
            good = (prior.usable(env_rec, environment) and not environment['resolve_tag'] and
                    'site-packages' in environment['file'] and environment['encoding'].lower() == 'utf-8' and
                    environment['utf8'] == 1 and not any(Path(p).resolve() == ROOT / 'src' for p in environment['path'] if p))
            help_rec, _ = capture([str(binary), '--help'], cwd)
            good = good and help_rec['exit'] == 0 and not help_rec['stderr']['bytes']
            result = {'status': 'PASS' if good else 'FAIL', 'environment': environment, 'processes': [env_rec, help_rec],
                      'source_external_verified': bool(good), 'FULL_151_receipt': str(REPORTS / 'close-P2.json'),
                      'FULL_55_receipt': str(REPORTS / 'close-gold.json'), 'Python_public_resolver_added': False, 'retries': 0}
            require_pass('gold', artifacts)
    result.update(source_commit=artifacts['source_commit'], snapshot_scope='FULLSNAPSHOT', artifacts=artifacts,
                  database=db_ref, frozen_gold=prior.binding(prior.GOLD), frozen_P2=prior.binding(prior.P2),
                  source_external_cwd=True, phase=args.phase)
    save(out, result)
    print(json.dumps({k: v for k, v in result.items() if k in ('status', 'phase', 'attempted', 'passed', 'summary', 'wrong_resolved', 'measured', 'warmups')}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
