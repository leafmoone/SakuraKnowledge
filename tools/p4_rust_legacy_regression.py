"""One-shot default Rust regression against the frozen approved P4 corpus."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import p4_approved_baseline as approved
import p4_legacy_baseline as legacy

ROOT = approved.ROOT
FIXED = 'c417655e149b7dce64d0bab376076f2a2f7c7320'
LOCAL = ROOT / 'build/p4-rust-legacy-regression-v1'
TARGET = ROOT / 'build/p4-rust-default-target'
REPORT = ROOT / 'reports/P4/rust-legacy-regression-v1.json'


def store(data):
    ref = legacy.binding(data)
    path = LOCAL / (ref['sha256'] + '.raw')
    if not path.exists():
        path.write_bytes(data)
    elif path.read_bytes() != data:
        raise ValueError('raw collision')
    return {'path': path.relative_to(ROOT).as_posix(), **ref}


def capture(argv, env, deadline=30):
    start = time.perf_counter()
    rec = {'argv': argv, 'cwd': str(ROOT), 'deadline_s': deadline,
           'attempted': 1, 'retries': 0, 'timeout': False}
    try:
        proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                              timeout=deadline, check=False)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, err, code = exc.stdout or b'', exc.stderr or b'', None
        rec['timeout'] = True
    except OSError as exc:
        out, err, code = b'', b'', None
        rec['exception'] = str(exc)
    rec.update(exit=code, elapsed_s=time.perf_counter() - start,
               stdout=store(out), stderr=store(err))
    approved.save(LOCAL / f'command-{capture.index:04d}.json', rec)
    capture.index += 1
    return rec, out, err


capture.index = 0


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


def compare(suite, row, rec, out, err, baseline):
    error = suite == 'P2' and row['original_case']['mode'] in ('error', 'cli', 'runtime_error')
    value, problems = approved.compare(suite, row, rec, out, err,
                                       baseline if not error else None)
    if canonical(value) != canonical(baseline):
        problems.append('approved_whole_json_mismatch')
    return value, problems


def load_baseline(run):
    """Verify tracked anchors and every local corpus byte before any build/query."""
    anchors = {}
    for name in ('continuation-approved-baseline.json', 'legacy-baseline-freeze.json'):
        relative = 'reports/P4/' + name
        raw = (ROOT / relative).read_bytes()
        if run(['git', 'show', FIXED + ':' + relative]) != raw:
            raise ValueError('tracked anchor differs: ' + relative)
        anchors[name] = legacy.strict_json(raw)
    baseline = anchors['continuation-approved-baseline.json']
    frozen = anchors['legacy-baseline-freeze.json']
    if baseline['identity'] != approved.IDENTITY or baseline['status'] != 'PASS':
        raise ValueError('unapproved baseline')
    manifest_path = approved.LOCAL / 'corpus-manifest.json'
    if approved.file_binding(manifest_path) != baseline['baseline_corpus_manifest']:
        raise ValueError('approved corpus manifest differs')
    manifest = legacy.strict_json(manifest_path.read_bytes())
    for name, binding in manifest.items():
        if Path(name).name != name or approved.file_binding(approved.LOCAL / name) != binding:
            raise ValueError('approved corpus differs: ' + name)
    if approved.file_binding(ROOT / 'reports/P4/legacy-baseline-freeze.json') != baseline['legacy_freeze']:
        raise ValueError('legacy freeze differs')
    result = []
    for suite, count in (('P2', 151), ('gold', 55)):
        rows = legacy.unique_rows(frozen['suites'][suite]['cases'], 'case_id', count)
        entries = legacy.unique_rows([e for e in baseline['cases'] if e['suite'] == suite], 'case_id', count)
        if rows.keys() != entries.keys():
            raise ValueError('case IDs differ')
        for cid, row in rows.items():
            entry = entries[cid]
            name = suite + '-' + cid + '.json'
            if name not in manifest:
                raise ValueError('unbound case')
            local = legacy.strict_json((approved.LOCAL / name).read_bytes())
            if {k: v for k, v in local.items() if k != 'actual_json'} != entry or not entry['passed']:
                raise ValueError('local case differs')
            streams = {}
            for stream in ('stdout', 'stderr'):
                ref = entry['process'][stream]
                path = ROOT / ref['path']
                if path.parent.resolve() != approved.LOCAL.resolve() or path.name not in manifest:
                    raise ValueError('unbound raw stream')
                data = path.read_bytes()
                if legacy.binding(data) != {k: ref[k] for k in ('bytes', 'sha256')}:
                    raise ValueError('raw stream differs')
                streams[stream] = data
            expected = local['actual_json']
            _, problems = compare(suite, row, entry['process'], streams['stdout'], streams['stderr'], expected)
            if problems:
                raise ValueError('baseline contract cannot be reconstructed: ' + repr(problems))
            # Keep the missing-input path identical so error messages compare in full.
            if approved.case_argv(row, Path(entry['process']['argv'][0])) != entry['process']['argv']:
                raise ValueError('baseline argv cannot be reconstructed')
            result.append((suite, row, entry, expected))
    return baseline, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', required=True, action='store_true')
    parser.parse_args()
    if LOCAL.exists() or REPORT.exists() or TARGET.exists():
        raise FileExistsError('one-shot output/target already exists; no retry')
    LOCAL.mkdir()
    env = approved.environment()
    env['CARGO_TARGET_DIR'] = str(TARGET.resolve())
    report = {'schema': 'p4-rust-legacy-regression-v1', 'status': 'NOT_RUN',
              'baseline_identity': approved.IDENTITY, 'runtime_sha': FIXED,
              'retries': 0, 'timeout_count': 0, 'wrong_resolved': 0,
              'pool': False, 'external_preservation': False, 'counts': {},
              'environment': {k: env[k] for k in ('PATH', 'CC', 'CXX', 'CARGO_TARGET_DIR',
                               'CC_x86_64_pc_windows_gnu', 'CXX_x86_64_pc_windows_gnu')},
              'helper': approved.file_binding(Path(__file__))}
    approved.save(LOCAL / 'reservation.json', report)

    def run(argv, deadline=30):
        rec, out, _err = capture(argv, env, deadline)
        report['timeout_count'] += int(rec['timeout'])
        if rec['exit'] != 0 or rec['timeout'] or rec.get('exception'):
            raise ValueError('command failed: ' + repr(argv))
        return out

    def source_check():
        if run(['git', 'rev-parse', 'HEAD']).decode().strip() != FIXED:
            raise ValueError('HEAD differs from fixed runtime')
        for argv in (['git', 'diff', '--exit-code', FIXED, '--', 'src', 'rust'],
                     ['git', 'ls-files', '--others', '--exclude-standard', '--', 'src', 'rust']):
            if run(argv):
                raise ValueError('production source differs')

    before = sides = None
    try:
        source_check()
        baseline, cases = load_baseline(run)
        report['baseline_report'] = approved.file_binding(approved.REPORT)
        report['baseline_corpus_manifest'] = baseline['baseline_corpus_manifest']
        before, sides = approved.file_binding(approved.DB), approved.sidecars()
        report['snapshot_before'], report['sidecars_before'] = before, sides
        if before != baseline['snapshot_after'] or before['sha256'] != approved.DB_HASH:
            raise ValueError('snapshot differs')
        run(['C:/msys64/ucrt64/bin/gcc.exe', '--version'])
        run(['C:/msys64/ucrt64/bin/g++.exe', '--version'])
        run(['python', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_p4_rust_legacy_regression.py'])
        run(['cargo', 'build', '--manifest-path', str(ROOT / 'rust/Cargo.toml'),
             '--locked', '--release', '--bin', 'sknow-rs'], 1200)
        binary = TARGET / ('release/sknow-rs.exe' if os.name == 'nt' else 'release/sknow-rs')
        report['binary'] = {'path': binary.relative_to(ROOT).as_posix(), **approved.file_binding(binary)}
        source_check()
        report['status'] = 'FAIL'
        for suite, row, entry, expected in cases:
            counts = report['counts'].setdefault(suite, {'executed': 0, 'passed': 0,
                'whole_values': 0, 'error_contracts': 0, 'source_assertions': 0,
                'resolved': 0, 'nonresolved': 0, 'wrong_resolved': 0})
            argv = [str(binary), *entry['process']['argv'][1:]]
            rec, out, err = capture(argv, env, 15)
            value, problems = compare(suite, row, rec, out, err, expected)
            counts['executed'] += 1
            counts['passed'] += int(not problems)
            report['timeout_count'] += int(rec['timeout'])
            error = suite == 'P2' and row['original_case']['mode'] in ('error', 'cli', 'runtime_error')
            counts['error_contracts' if error else 'whole_values'] += 1
            if suite == 'gold':
                counts['source_assertions'] += 1
                resolved = isinstance(value, dict) and value.get('status') == 'resolved'
                counts['resolved' if resolved else 'nonresolved'] += 1
                want = row['original_case']['expected']
                wrong = resolved and (want['status'] != 'resolved' or value.get('tag_key') != want.get('tag_key'))
                counts['wrong_resolved'] += int(wrong)
                report['wrong_resolved'] += int(wrong)
            approved.save(LOCAL / (suite + '-' + row['case_id'] + '.json'),
                          {'suite': suite, 'case_id': row['case_id'], 'process': rec,
                           'problems': problems, 'actual_json': value, 'passed': not problems})
            if problems:
                raise ValueError('mismatch; STOP: ' + suite + '/' + row['case_id'] + ': ' + repr(problems))
        p2, gold = report['counts']['P2'], report['counts']['gold']
        if (p2['passed'], p2['whole_values'], p2['error_contracts'], gold['passed'],
                gold['resolved'], gold['nonresolved'], report['wrong_resolved'], report['timeout_count']) != (151, 135, 16, 55, 39, 16, 0, 0):
            raise ValueError('required final counts differ')
        source_check()
        report['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 - Preserve evidence; never retry.
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        if before is not None:
            report['snapshot_after'], report['sidecars_after'] = approved.file_binding(approved.DB), approved.sidecars()
            if report['snapshot_after'] != before or report['sidecars_after'] != sides:
                report['status'] = 'FAIL'
                report['snapshot_mutated'] = True
        approved.save(LOCAL / 'corpus-manifest.json',
                      {p.name: approved.file_binding(p) for p in sorted(LOCAL.iterdir()) if p.is_file()})
        report['local_evidence'] = {'path': (LOCAL / 'corpus-manifest.json').relative_to(ROOT).as_posix(),
                                    **approved.file_binding(LOCAL / 'corpus-manifest.json')}
        report['commands_preserved'] = capture.index
        approved.save(REPORT, report)
        print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
