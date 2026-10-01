"""Capture approved P3 behavior once; never recover or overwrite original P3 oracles."""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import p4_legacy_baseline as legacy

ROOT = Path(__file__).resolve().parents[1]
APPROVED = '269e34eeeac920c29f2d684cfe37c93a95c73057'
IDENTITY = 'P4_APPROVED_P3_BEHAVIOR_BASELINE_V1'
PROVENANCE = ('new P4 regression baseline captured from externally approved P3 fixed behavior; '
              'NOT original P3 oracle recovery')
DB = ROOT / 'build/p3-full-authorized-retry1/knowledge.sqlite'
DB_HASH = '61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9'
LOCAL = ROOT / 'build/p4-approved-baseline'
TARGET = ROOT / 'build/p4-approved-baseline-target'
REPORT = ROOT / 'reports/P4/continuation-approved-baseline.json'


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.write('\n')


def file_binding(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def environment():
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               CARGO_TARGET_DIR=str(TARGET.resolve()),
               PATH='C:/msys64/ucrt64/bin' + os.pathsep + os.environ.get('PATH', ''),
               CC='C:/msys64/ucrt64/bin/gcc.exe', CXX='C:/msys64/ucrt64/bin/g++.exe',
               CC_x86_64_pc_windows_gnu='C:/msys64/ucrt64/bin/gcc.exe',
               CXX_x86_64_pc_windows_gnu='C:/msys64/ucrt64/bin/g++.exe')
    for key in ('PYTHONPATH', 'PYTHONHOME', 'SKNOW_SEARCH_PROFILE_OUT'):
        env.pop(key, None)
    return env


def source_check():
    commands = [
        ['git', 'diff', '--exit-code', APPROVED, 'HEAD', '--', 'src', 'rust'],
        ['git', 'diff', '--exit-code', 'HEAD', '--', 'src', 'rust'],
        ['git', 'ls-files', '--others', '--exclude-standard', '--', 'src', 'rust'],
    ]
    for argv in commands:
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, check=True, timeout=30)
        if proc.stdout or proc.stderr:
            raise ValueError('production source differs: ' + repr(argv))
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    return {'source_sha': head, 'approved_sha': APPROVED, 'empty_diff_commands': commands}


def store(data):
    ref = legacy.binding(data)
    path = LOCAL / (ref['sha256'] + '.raw')
    if not path.exists():
        with path.open('xb') as stream:
            stream.write(data)
    elif path.read_bytes() != data:
        raise ValueError('corpus collision')
    return {'path': path.relative_to(ROOT).as_posix(), **ref}


def capture(argv, env, deadline):
    start = time.perf_counter()
    rec = {'argv': argv, 'deadline_s': deadline, 'attempted': 1, 'retries': 0,
           'started_ns': time.time_ns(), 'timeout': False}
    try:
        proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                              check=False, timeout=deadline)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, err, code = exc.stdout or b'', exc.stderr or b'', None
        rec['timeout'] = True
    except OSError as exc:
        out, err, code = b'', b'', None
        rec['exception'] = str(exc)
    rec.update(exit=code, elapsed_s=time.perf_counter() - start,
               stdout=store(out), stderr=store(err))
    try:
        out.decode('utf-8', errors='strict')
        err.decode('utf-8', errors='strict')
    except UnicodeDecodeError as exc:
        rec['decode_error'] = str(exc)
    return rec, out, err


def compare(suite, row, rec, out, err, expected):
    problems = []
    value = None
    if rec['timeout'] or rec.get('exception') or rec.get('decode_error'):
        problems.append('process_failure')
    case = row['original_case']
    error_case = suite == 'P2' and case['mode'] in ('error', 'cli', 'runtime_error')
    try:
        value = legacy.strict_json(err if error_case else out)
        if not isinstance(value, dict):
            raise TypeError('object required')
        if value.get('message') == 'query_budget_exceeded':
            rec['timeout'] = True
            problems.append('inner_timeout')
        if error_case:
            contract = case['historical_expect']
            want = ({'error': 'ValueError', 'message': contract['error']}
                    if case['mode'] == 'error' else
                    {k: contract['stderr_rs_' + k] for k in ('error', 'message')
                     if 'stderr_rs_' + k in contract})
            if out or rec['exit'] != contract.get('exit_rs', 2) or 'error' not in value:
                problems.append('error_exit_or_stream')
            problems.extend('error.' + k for k, v in want.items() if value.get(k) != v)
        else:
            if err or rec['exit'] != 0:
                problems.append('value_exit_or_stderr')
            if suite == 'P2' and json.dumps(value, sort_keys=True) != json.dumps(
                    expected, sort_keys=True):
                problems.append('independent_full_value_mismatch')
            if suite == 'gold':
                problems.extend(legacy.source_checks(value, case['expected']))
    except (ValueError, TypeError) as exc:
        problems.append('invalid_json: ' + str(exc))
    return value, problems


def case_argv(row, binary):
    argv = [str(binary), *row['accepted_argv'][1:]]
    for i, arg in enumerate(argv[1:], 1):
        normalized = arg.replace('\\', '/')
        if normalized.endswith('/knowledge.sqlite'):
            argv[i] = DB.resolve().as_uri() + '?mode=ro&immutable=1'
        elif normalized.endswith('/missing-parity-input.sqlite'):
            missing = LOCAL / 'missing-parity-input.sqlite'
            if missing.exists():
                raise ValueError('missing-input fixture exists')
            argv[i] = str(missing)
    return argv


def sidecars():
    return {suffix: file_binding(Path(str(DB) + suffix))
            if Path(str(DB) + suffix).exists() else None
            for suffix in ('-wal', '-shm', '-journal')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.parse_args()
    proof = source_check()  # Must precede any build or formal execution.
    tracked = legacy.tracked_files(ROOT)
    frozen_bytes = legacy.read_tracked(ROOT, 'reports/P4/legacy-baseline-freeze.json', tracked)
    frozen = legacy.strict_json(frozen_bytes)
    if frozen != legacy.freeze(ROOT):
        raise ValueError('tracked legacy freeze no longer reproduces')
    if REPORT.exists() or LOCAL.exists() or TARGET.exists():
        raise FileExistsError('capture already reserved; retries prohibited')
    LOCAL.mkdir()
    TARGET.mkdir()
    report = {'identity': IDENTITY, 'provenance': PROVENANCE, 'status': 'FAIL',
              'original_FULL55_recovery': '0/55', 'source': proof,
              'legacy_freeze': legacy.binding(frozen_bytes), 'retries': 0,
              'processes': [], 'cases': [], 'counts': {}, 'timeout_count': 0}
    save(LOCAL / 'reservation.json', report)
    try:
        before = file_binding(DB)
        if before != {'bytes': 21718736896, 'sha256': DB_HASH}:
            raise ValueError('snapshot identity mismatch')
        report['snapshot_before'] = before
        sides = sidecars()
        env = environment()
        report['environment'] = {k: env[k] for k in (
            'CARGO_TARGET_DIR', 'CC', 'CXX', 'CC_x86_64_pc_windows_gnu',
            'CXX_x86_64_pc_windows_gnu', 'PATH', 'PYTHONUTF8', 'PYTHONIOENCODING')}
        cargo = ['cargo', 'build', '--manifest-path', str(ROOT / 'rust/Cargo.toml'),
                 '--locked', '--release', '--bin', 'sknow-rs']
        rec, _, _ = capture(cargo, env, 1200)
        report['processes'].append(rec)
        if rec['exit'] != 0 or rec['timeout']:
            raise ValueError('isolated release build failed')
        binary = TARGET / ('release/sknow-rs.exe' if os.name == 'nt' else 'release/sknow-rs')
        report['binary'] = {'path': binary.relative_to(ROOT).as_posix(), **file_binding(binary)}
        source_check()
        for suite, count in (('P2', 151), ('gold', 55)):
            rows = frozen['suites'][suite]['cases']
            legacy.unique_rows(rows, 'case_id', count)
            counts = {'executed': 0, 'passed': 0, 'full_values': 0, 'error_contracts': 0,
                      'resolved': 0, 'nonresolved': 0, 'wrong_resolved': 0}
            report['counts'][suite] = counts
            for row in rows:
                expected = None
                if suite == 'P2' and 'expected_json' in row['original_case']:
                    expected = legacy.strict_json(legacy.verify_raw(
                        ROOT, row['alternative_historical_baseline']['stdout'], tracked))
                    data, _ = legacy.reconstruct(expected, row['original_case']['expected_json'])
                    if data is None:
                        raise ValueError('independent P2 expectation not recovered')
                rec, out, err = capture(case_argv(row, binary), env, 15)
                value, problems = compare(suite, row, rec, out, err, expected)
                counts['executed'] += 1
                report['timeout_count'] += int(rec['timeout'])
                entry = {'suite': suite, 'case_id': row['case_id'], 'process': rec,
                         'problems': problems, 'passed': not problems}
                if suite == 'gold':
                    entry['source_assertions'] = row['original_case']['expected']
                    entry['source_assertion_problems'] = problems
                    status = value.get('status') if isinstance(value, dict) else None
                    counts['resolved' if status == 'resolved' else 'nonresolved'] += 1
                    want = row['original_case']['expected']
                    wrong = status == 'resolved' and (want['status'] != 'resolved' or
                                                      value.get('tag_key') != want.get('tag_key'))
                    counts['wrong_resolved'] += int(wrong)
                else:
                    counts['full_values' if expected is not None else 'error_contracts'] += 1
                report['cases'].append(entry)
                save(LOCAL / (suite + '-' + row['case_id'] + '.json'),
                     {**entry, 'actual_json': value})
                if problems:
                    raise ValueError('actual mismatch; STOP: ' + suite + '/' + row['case_id'])
                counts['passed'] += 1
        if (report['counts']['P2']['full_values'] != 135 or
                report['counts']['P2']['error_contracts'] != 16 or
                report['counts']['gold']['resolved'] != 39 or
                report['counts']['gold']['nonresolved'] != 16 or
                report['counts']['gold']['wrong_resolved'] or report['timeout_count']):
            raise ValueError('required final counts differ')
        report['snapshot_after'] = file_binding(DB)
        report['sidecars_before'], report['sidecars_after'] = sides, sidecars()
        if report['snapshot_after'] != before or report['sidecars_after'] != sides:
            raise ValueError('snapshot or sidecars mutated')
        report['source_after'] = source_check()
        report['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 - preserve failure receipts; never retry
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        inventory = {p.name: file_binding(p) for p in sorted(LOCAL.iterdir()) if p.is_file()}
        save(LOCAL / 'corpus-manifest.json', inventory)
        report['baseline_corpus_manifest'] = file_binding(LOCAL / 'corpus-manifest.json')
        save(REPORT, report)
        print(json.dumps({k: v for k, v in report.items()
                          if k not in ('cases', 'environment', 'processes')}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
