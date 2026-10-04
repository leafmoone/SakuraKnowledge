import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools import p4_approved_baseline as approved
from tools import p4_legacy_baseline as legacy

ROOT = approved.ROOT
sys.path.insert(0, str(ROOT))
from tools import p4_full_preflight as fullpreflight

BASELINE_ANCHOR = 'c417655e149b7dce64d0bab376076f2a2f7c7320'


class RunContext:
    """Isolated local paths, command evidence, and concurrency-safe output reservation."""

    def __init__(self, run_id, target_dir, knowledge, *, root=ROOT, runner=subprocess.run):
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', run_id):
            raise ValueError('safe explicit run ID required')
        self.root = fullpreflight.controlled_path(root, root)
        self.run_id = run_id
        self.target = fullpreflight.controlled_path(target_dir, self.root, strict=False)
        if self.target == self.root or self.target.is_relative_to(self.root / 'reports'):
            raise ValueError('process-local build target required')
        self.report_path = fullpreflight.controlled_path(
            f'reports/P4/legacy-{run_id}.json', self.root, strict=False)
        self.knowledge = fullpreflight.controlled_path(knowledge, self.root)
        if self.knowledge != self.root / approved.DB.relative_to(ROOT):
            raise ValueError('approved Knowledge snapshot required')
        self.local = self.target / 'evidence'
        self.runner = runner
        self.index = 0
        self.env = approved.environment()
        # Never inherit a caller's shared/external Cargo target. The explicit target is
        # process-local and must be contained by this checkout.
        self.env.update(CARGO_TARGET_DIR=str(self.target), DLLTOOL='C:/msys64/ucrt64/bin/dlltool.exe',
                        DLLTOOL_x86_64_pc_windows_gnu='C:/msys64/ucrt64/bin/dlltool.exe')
        for key in list(self.env):
            if key.startswith(('CARGO_', 'RUST', 'SKNOW_')) and key != 'CARGO_TARGET_DIR':
                self.env.pop(key)

    def reserve(self):
        for path in (self.target, self.report_path):
            fullpreflight.check_components(path)
            if os.path.lexists(path):
                raise FileExistsError('output/target already exists; use a new run ID and target')
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        with self.report_path.open('x', encoding='utf-8'):
            pass
        self.target.mkdir()
        self.local.mkdir()

    def store(self, data):
        ref = legacy.binding(data)
        path = self.local / (ref['sha256'] + '.raw')
        fullpreflight.check_components(path)
        if not path.exists():
            path.write_bytes(data)
        elif path.read_bytes() != data:
            raise ValueError('raw collision')
        return {'path': path.relative_to(self.root).as_posix(), **ref}

    def capture(self, argv, deadline=30):
        start = time.perf_counter()
        rec = {'argv': argv, 'cwd': str(self.root), 'deadline_s': deadline,
               'attempted': 1, 'retries': 0, 'timeout': False, 'started_unix_s': time.time()}
        try:
            proc = self.runner(argv, cwd=self.root, env=self.env, capture_output=True,
                               timeout=deadline, check=False)
            out, err, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, err, code = exc.stdout or b'', exc.stderr or b'', None
            rec['timeout'] = True
        except OSError as exc:
            out, err, code = b'', str(exc).encode('utf-8'), None
            rec['exception'] = str(exc)
        rec.update(exit=code, elapsed_s=time.perf_counter() - start, ended_unix_s=time.time(),
                   stdout=self.store(out), stderr=self.store(err),
                   stderr_utf8=err.decode('utf-8', errors='replace'))
        approved.save(self.local / f'command-{self.index:04d}.json', rec)
        self.index += 1
        return rec, out, err

    def run(self, argv, deadline=30):
        rec, out, _err = self.capture(argv, deadline)
        if rec['exit'] != 0 or rec['timeout'] or rec.get('exception'):
            raise ValueError('command failed; STOP: ' + repr(argv))
        return out

    def build(self):
        argv = ['cargo', 'build', '--manifest-path', str(self.root / 'rust/Cargo.toml'),
                '--locked', '--release', '--bin', 'sknow-rs']
        rec, _out, _err = self.capture(argv, 1200)
        provenance = {'argv': argv, 'process': rec, 'default_features': True}
        approved.save(self.local / 'build.json', provenance)
        if rec['exit'] != 0 or rec['timeout'] or rec.get('exception'):
            raise ValueError('build failed; STOP')
        binary = fullpreflight.controlled_path(
            self.target / ('release/sknow-rs.exe' if os.name == 'nt' else 'release/sknow-rs'), self.root)
        provenance['binary'] = {'path': binary.relative_to(self.root).as_posix(),
                                **approved.file_binding(binary)}
        return binary, provenance


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


def compare(suite, row, rec, out, err, baseline):
    error = suite == 'P2' and row['original_case']['mode'] in ('error', 'cli', 'runtime_error')
    value, problems = approved.compare(suite, row, rec, out, err, baseline if not error else None)
    if canonical(value) != canonical(baseline):
        problems.append('approved_whole_json_mismatch')
    return value, problems


def load_baseline(run):
    """Verify tracked anchors and every local corpus byte before any build/query."""
    anchors = {}
    for name in ('continuation-approved-baseline.json', 'legacy-baseline-freeze.json'):
        relative = 'reports/P4/' + name
        raw = (ROOT / relative).read_bytes()
        if run(['git', 'show', BASELINE_ANCHOR + ':' + relative]) != raw:
            raise ValueError('tracked anchor differs: ' + relative)
        anchors[name] = legacy.strict_json(raw)
    baseline, frozen = anchors['continuation-approved-baseline.json'], anchors['legacy-baseline-freeze.json']
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
            if approved.case_argv(row, Path(entry['process']['argv'][0])) != entry['process']['argv']:
                raise ValueError('baseline argv cannot be reconstructed')
            result.append((suite, row, entry, expected))
    return baseline, result


def execute(context):
    context.reserve()
    env = context.env
    report = {'schema': 'p4-rust-legacy-regression-v1', 'status': 'FAIL',
              'baseline_identity': approved.IDENTITY, 'baseline_anchor': BASELINE_ANCHOR,
              'provenance': approved.PROVENANCE, 'run_id': context.run_id,
              'knowledge': str(context.knowledge), 'retries': 0, 'timeout_count': 0,
              'wrong_resolved': 0, 'pool': False, 'external_preservation': False, 'counts': {},
              'environment': {k: env[k] for k in ('PATH', 'CC', 'CXX', 'DLLTOOL', 'CARGO_TARGET_DIR',
                               'CC_x86_64_pc_windows_gnu', 'CXX_x86_64_pc_windows_gnu',
                               'DLLTOOL_x86_64_pc_windows_gnu')}, 'helper': approved.file_binding(Path(__file__))}
    approved.save(context.local / 'reservation.json', report)
    before = sides = None
    try:
        baseline, cases = load_baseline(context.run)
        report['baseline_report'] = approved.file_binding(approved.REPORT)
        report['baseline_corpus_manifest'] = baseline['baseline_corpus_manifest']
        before, sides = approved.file_binding(context.knowledge), approved.sidecars()
        report['snapshot_before'], report['sidecars_before'] = before, sides
        if before != baseline['snapshot_after'] or before['sha256'] != approved.DB_HASH:
            raise ValueError('snapshot differs')
        context.run(['C:/msys64/ucrt64/bin/gcc.exe', '--version'])
        context.run(['C:/msys64/ucrt64/bin/g++.exe', '--version'])
        context.run(['C:/msys64/ucrt64/bin/dlltool.exe', '--version'])
        binary, report['build'] = context.build()
        for suite, row, entry, expected in cases:
            counts = report['counts'].setdefault(suite, {'executed': 0, 'passed': 0, 'whole_values': 0,
                'error_contracts': 0, 'source_assertions': 0, 'resolved': 0, 'nonresolved': 0, 'wrong_resolved': 0})
            rec, out, err = context.capture([str(binary), *entry['process']['argv'][1:]], 15)
            value, problems = compare(suite, row, rec, out, err, expected)
            counts['executed'] += 1; counts['passed'] += int(not problems)
            error = suite == 'P2' and row['original_case']['mode'] in ('error', 'cli', 'runtime_error')
            counts['error_contracts' if error else 'whole_values'] += 1
            if suite == 'gold':
                counts['source_assertions'] += 1
                resolved = isinstance(value, dict) and value.get('status') == 'resolved'
                counts['resolved' if resolved else 'nonresolved'] += 1
                want = row['original_case']['expected']
                wrong = resolved and (want['status'] != 'resolved' or value.get('tag_key') != want.get('tag_key'))
                counts['wrong_resolved'] += int(wrong); report['wrong_resolved'] += int(wrong)
            approved.save(context.local / (suite + '-' + row['case_id'] + '.json'),
                          {'suite': suite, 'case_id': row['case_id'], 'process': rec,
                           'problems': problems, 'actual_json': value, 'passed': not problems})
            if problems:
                raise ValueError('mismatch; STOP: ' + suite + '/' + row['case_id'] + ': ' + repr(problems))
        p2, gold = report['counts']['P2'], report['counts']['gold']
        if (p2['passed'], p2['whole_values'], p2['error_contracts'], gold['passed'], gold['resolved'],
                gold['nonresolved'], report['wrong_resolved']) != (151, 135, 16, 55, 39, 16, 0):
            raise ValueError('required final counts differ')
        report['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        try:
            if before is not None:
                report['snapshot_after'], report['sidecars_after'] = approved.file_binding(context.knowledge), approved.sidecars()
                if report['snapshot_after'] != before or report['sidecars_after'] != sides:
                    raise ValueError('snapshot mutated')
        except Exception as exc:  # noqa: BLE001
            report['status'] = 'FAIL'; report['end_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        commands = [legacy.strict_json(p.read_bytes()) for p in sorted(context.local.glob('command-*.json'))]
        report['timeout_count'] = sum(int(rec['timeout']) for rec in commands)
        if report['timeout_count']: report['status'] = 'FAIL'
        approved.save(context.local / 'corpus-manifest.json',
                      {p.name: approved.file_binding(p) for p in sorted(context.local.iterdir()) if p.is_file()})
        report['local_evidence'] = {'path': (context.local / 'corpus-manifest.json').relative_to(context.root).as_posix(),
                                    **approved.file_binding(context.local / 'corpus-manifest.json')}
        report['commands_preserved'] = context.index
        fullpreflight.check_components(context.report_path)
        if context.report_path.read_bytes() != b'': raise FileExistsError('reserved output changed')
        with context.report_path.open('r+', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2, allow_nan=False); stream.write('\n')
        print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


def existing_binary(*, binary, results_dir, knowledge=approved.DB, verified_session=None):
    """Compare all frozen cases without coupling output ownership to Cargo cache."""
    from contextlib import nullcontext

    from tools import p4_full_acceptance as acceptance
    binary = fullpreflight.controlled_path(binary, ROOT)
    knowledge = fullpreflight.controlled_path(knowledge, ROOT)
    if knowledge != approved.DB:
        raise ValueError('approved Knowledge snapshot required')
    output = fullpreflight.controlled_path(results_dir, ROOT, strict=False)
    if os.path.lexists(output):
        raise FileExistsError('results already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    report = {'status': 'FAIL', 'counts': {suite: {'executed': 0, 'passed': 0, 'expected': count}
              for suite, count in (('P2', 151), ('gold', 55))}, 'cases': [],
              'binary': str(binary), 'failures': [], 'commands': []}

    def capture(argv, name, deadline):
        start = time.perf_counter()
        rec = {'argv': argv, 'cwd': str(ROOT), 'deadline_s': deadline, 'timeout': False,
               'attempted': 1, 'retries': 0}
        try:
            proc = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=deadline, check=False)
            out, err, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, err, code = exc.stdout or b'', exc.stderr or b'', None
            rec['timeout'] = True
        except Exception as exc:  # noqa: BLE001
            out, err, code = getattr(exc, 'stdout', None) or b'', getattr(exc, 'stderr', None) or b'', None
            rec['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
        rec.update(exit=code, duration_seconds=time.perf_counter() - start)
        report['commands'].append(rec)
        for stream, data in (('stdout', out), ('stderr', err)):
            if isinstance(data, str):
                data = data.encode('utf-8')
            path = fullpreflight.controlled_path(output / (name + '.' + stream), ROOT, strict=False)
            if path.parent != output:
                raise ValueError('raw output path escape')
            with path.open('xb') as dest:
                dest.write(data)
            rec[stream] = {'path': path.relative_to(ROOT).as_posix(), **legacy.binding(data)}
            if stream == 'stdout':
                out = data
            else:
                err = data
        return rec, out, err

    def run(argv):
        rec, out, _err = capture(argv, f'command-{len(report["commands"]):04d}', 30)
        if rec['exit'] != 0 or rec['timeout'] or rec.get('exception'):
            raise ValueError('baseline command failed: ' + repr(argv))
        return out

    try:
        if verified_session is not None and not isinstance(verified_session, acceptance.AcceptanceSession):
            raise ValueError('acceptance session required')
        binding = approved.file_binding(binary)
        report['binary_binding'] = {'path': binary.relative_to(ROOT).as_posix(),
                                    'size': binding['bytes'], 'sha256': binding['sha256']}
        snapshot = json.loads(fullpreflight.FULL_CONTRACT.read_bytes())['snapshot']
        report['snapshot_binding'] = snapshot
        with (nullcontext(verified_session) if verified_session is not None else acceptance.AcceptanceSession()) as session:  # noqa: SIM117
            with session.guard([(knowledge, snapshot, 'snapshot'),
                                (binary, report['binary_binding'], 'binary')]):
                try:
                    baseline, cases = load_baseline(run)
                    report['baseline'] = baseline['baseline_corpus_manifest']
                    for suite, row, entry, expected in cases:
                        name = suite + '-' + row['case_id']
                        rec, out, err = capture([str(binary), *entry['process']['argv'][1:]], name, 15)
                        value, problems = compare(suite, row, rec, out, err, expected)
                        report['cases'].append({'suite': suite, 'case_id': row['case_id'], 'process': rec,
                                                'actual_json': value, 'passed': not problems, 'problems': problems})
                        count = report['counts'][suite]
                        count['executed'] += 1
                        count['passed'] += int(not problems)
                        if problems:
                            report['failures'].append(name)
                    if any(c['executed'] != c['expected'] or c['passed'] != c['expected']
                           for c in report['counts'].values()):
                        report['failures'].append('required final counts differ')
                    report['status'] = 'PASS' if not report['failures'] else 'FAIL'
                except Exception as exc:
                    report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
                    raise
    except Exception as exc:  # noqa: BLE001
        report['status'] = 'FAIL'
        failure = {'type': type(exc).__name__, 'message': str(exc)}
        if 'failure' not in report:
            report['failure'] = failure
        elif report['failure'] != failure:
            report['end_failure'] = failure
    finally:
        path = fullpreflight.controlled_path(output / 'evaluation.json', ROOT, strict=False)
        approved.save(path, report)
        print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--target-dir')
    parser.add_argument('--binary')
    parser.add_argument('--results-dir')
    parser.add_argument('--knowledge', type=Path, default=approved.DB)
    args = parser.parse_args()
    if args.binary:
        if not args.results_dir:
            parser.error('--binary requires --results-dir')
        return existing_binary(binary=args.binary, results_dir=args.results_dir, knowledge=args.knowledge)
    if not (args.execute and args.run_id and args.target_dir):
        parser.error('--execute requires --run-id and --target-dir')
    return execute(RunContext(args.run_id, args.target_dir, args.knowledge))


if __name__ == '__main__':
    raise SystemExit(main())
