"""Once-only clean committed-source artifacts; execution requires separate authorization."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from p3_evidence import save, store

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/P3'
RAW = REPORTS / 'final-raw'
RUNTIME = '9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102'
PROFILE = 'SKNOW_SEARCH_PROFILE_OUT'


def create_new(path, value):
    """Exclusive creation is also the reservation: interrupted attempts stay blocked."""
    save(path, value)


def binding(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def check_binding(ref):
    if binding(ref['path']) != ref:
        raise ValueError('artifact bytes/identity changed: ' + ref['path'])


def environment(target):
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               CARGO_TARGET_DIR=str(Path(target).resolve()),
               PATH='C:/msys64/ucrt64/bin' + os.pathsep + os.environ.get('PATH', ''),
               CC='C:/msys64/ucrt64/bin/gcc.exe', CXX='C:/msys64/ucrt64/bin/g++.exe',
               CC_x86_64_pc_windows_gnu='C:/msys64/ucrt64/bin/gcc.exe',
               CXX_x86_64_pc_windows_gnu='C:/msys64/ucrt64/bin/g++.exe')
    for name in ('PYTHONPATH', 'PYTHONHOME', PROFILE):
        env.pop(name, None)
    return env


def assert_target(argv, env, directory):
    directory, target = Path(directory).resolve(), Path(env['CARGO_TARGET_DIR']).resolve()
    if (not directory.is_relative_to(ROOT.resolve() / 'dist') or
            not target.is_relative_to(directory) or target == directory or
            any(a == '--target-dir' or a.startswith('--target-dir=') for a in argv)):
        raise ValueError('cargo target must be explicitly inside Knowledge final archive artifact')
    return target


def run(argv, env, cwd, *, directory=None):
    target = assert_target(argv, env, directory) if directory is not None else None
    started_ns, started = time.time_ns(), time.perf_counter()
    exception = None
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except OSError as exc:
        out, err, code = b'', b'', None
        exception = {'type': type(exc).__name__, 'message': str(exc)}
    rec = {'argv': argv, 'cwd': str(cwd), 'exit': code,
           'started_ns': started_ns, 'finished_ns': time.time_ns(),
           'elapsed_s': time.perf_counter() - started,
           'stdout': store(out, root=RAW), 'stderr': store(err, root=RAW),
           'environment': {k: env.get(k) for k in
                           ('PYTHONUTF8', 'PYTHONIOENCODING', 'CARGO_TARGET_DIR', 'PATH', 'CC', 'CXX',
                            'CC_x86_64_pc_windows_gnu', 'CXX_x86_64_pc_windows_gnu', PROFILE)},
           'child_cargo_target_explicit': target is not None,
           'target_inside_Knowledge_and_archive': target is not None}
    if exception is not None:
        rec['exception'] = exception
    return rec, out


def source_git(commit, *, allow_evidence=False):
    """Only new untracked final evidence is exempt after the clean source check."""
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('a full fixed source SHA is required')
    env = environment(ROOT / 'build/p3-final-git-target')
    records, outputs = [], []
    # Status first: retaining raw git output itself creates untracked final evidence.
    for argv in (['git', 'status', '--porcelain', '--untracked-files=all'],
                 ['git', 'rev-parse', 'HEAD'],
                 ['git', 'diff', '--exit-code', RUNTIME, commit, '--', 'src', 'rust']):
        rec, data = run(argv, env, ROOT)
        records.append(rec)
        outputs.append(data)
        if rec['exit'] != 0:
            raise ValueError('source git check failed')
    dirty = outputs[0].decode('utf-8', errors='strict').splitlines()
    if allow_evidence:
        dirty = [line for line in dirty if not line.startswith('?? reports/P3/final-')]
    if (outputs[1].decode('utf-8', errors='strict').strip() != commit or dirty or
            outputs[2].strip()):
        raise ValueError('fixed HEAD, clean source and unchanged src/rust required')
    return {'source_commit': commit, 'runtime_baseline': RUNTIME, 'clean_source': True,
            'runtime_src_rust_gitdiff_empty': True, 'processes': records,
            'new_untracked_final_evidence_exempt': allow_evidence}


def extract_archive(archive, source):
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            dest = (source / member.filename).resolve()
            if not dest.is_relative_to(source.resolve()):
                raise ValueError('unsafe git archive member')
        zipped.extractall(source)


def module_provenance(source, wheel, site):
    rows = []
    with zipfile.ZipFile(wheel) as zipped:
        for path in sorted((source / 'src/sakura_knowledge').rglob('*.py')):
            member = path.relative_to(source / 'src').as_posix()
            installed = site / member
            data = zipped.read(member)
            if path.read_bytes() != data or installed.read_bytes() != data:
                raise ValueError('archive/wheel/installed module mismatch: ' + member)
            rows.append({'module': member, 'archive': binding(path),
                         'wheel_member': {'name': member, 'bytes': len(data),
                                          'sha256': hashlib.sha256(data).hexdigest()},
                         'installed': binding(installed),
                         'bytes_equal_archive_wheel_installed': True})
        wheel_modules = {n for n in zipped.namelist()
                         if n.startswith('sakura_knowledge/') and n.endswith('.py')}
        if not rows or wheel_modules != {r['module'] for r in rows}:
            raise ValueError('wheel module inventory differs from archive')
    return rows


def verify_artifacts(report):
    """Byte-check executables, archive, wheel, runtime sources and installed modules."""
    if (report['status'] != 'PASS' or report['runtime_baseline'] != RUNTIME or
            report['source_git']['source_commit'] != report['source_commit'] or
            not report['source_git']['clean_source'] or
            not report['source_git']['runtime_src_rust_gitdiff_empty']):
        raise ValueError('final artifact/source provenance not PASS')
    directory = Path(report['directory']).resolve()
    suffix = '-retry1' if report.get('attempt') == 'retry1' else ''
    if directory != ROOT.resolve() / ('dist/p3-final-' + report['source_commit'] + suffix):
        raise ValueError('not the fixed final artifact directory')
    if (Path(report['source']).resolve() != directory / 'source' or
            not Path(report['site_packages']).resolve().is_relative_to(directory / 'venv')):
        raise ValueError('source archive or installed package location differs')
    assert_target([], report['environment'], directory)
    fields = ['binary', 'wheel', 'archive', 'python_binding']
    if 'reused_binary' in report:
        fields.append('reused_binary')
    for field in fields:
        check_binding(report[field])
        if not Path(report[field]['path']).resolve().is_relative_to(directory):
            raise ValueError('artifact escaped final directory')
    if report['python'] != report['python_binding']['path']:
        raise ValueError('installed interpreter identity differs')
    with zipfile.ZipFile(report['archive']['path']) as zipped:
        expected_names = {n for n in zipped.namelist() if not n.endswith('/') and
                          (n.startswith(('src/', 'rust/')) or
                           n in ('pyproject.toml', 'README.md'))}
        names = set()
        for ref in report['source_files']:
            check_binding(ref)
            name = Path(ref['path']).resolve().relative_to(directory / 'source').as_posix()
            data = zipped.read(name)
            if len(data) != ref['bytes'] or hashlib.sha256(data).hexdigest() != ref['sha256']:
                raise ValueError('extracted runtime source differs from git archive')
            names.add(name)
        if not names or names != expected_names or len(names) != len(report['source_files']):
            raise ValueError('runtime source inventory differs')
    actual = module_provenance(Path(report['source']), Path(report['wheel']['path']),
                               Path(report['site_packages']))
    if actual != report['modules']:
        raise ValueError('module provenance changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--bench', action='store_true', help='build optional bench, never execute')
    parser.add_argument('--attempt', choices=('initial', 'retry1'), default='initial')
    args = parser.parse_args()
    suffix = '-retry1' if args.attempt == 'retry1' else ''
    out = REPORTS / ('final-artifacts' + suffix + '.json')
    marker = REPORTS / ('final-artifacts' + suffix + '-start.json')
    if out.exists() or marker.exists():
        raise FileExistsError('final artifacts already reserved or recorded')
    source_proof = source_git(args.source_commit)  # Clean BEFORE creating untracked evidence.
    create_new(marker, {'source_commit': args.source_commit, 'created_ns': time.time_ns(),
                        'runtime_baseline': RUNTIME, 'retries': 0, 'attempt': args.attempt,
                        'original_FAIL_preserved': str(REPORTS / 'final-artifacts.json')})
    report = {'status': 'FAIL', 'source_commit': args.source_commit, 'runtime_baseline': RUNTIME,
              'retries': 0, 'authorized_independent_retry': args.attempt == 'retry1', 'attempt': args.attempt,
              'historical_gcc_version': '16.2.0 retained object comment; exact compiler path unknown',
              'new_toolchain_not_historical_environment': True,
              'no_snapshot_build': True, 'started_ns': time.time_ns(),
              'source_git': source_proof, 'processes': []}
    try:
        directory = ROOT / ('dist/p3-final-' + args.source_commit + suffix)
        directory.mkdir()  # Exclusive fresh archive/build/venv, never reuse old close artifacts.
        source, archive = directory / 'source', directory / 'source.zip'
        target = source / 'rust/target'
        env = environment(target)
        python = directory / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')
        site = directory / ('venv/Lib/site-packages' if os.name == 'nt' else
                            f'venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
        suffix = '.exe' if os.name == 'nt' else ''
        cargo = ['cargo', 'build', '--manifest-path', str(source / 'rust/Cargo.toml'),
                 '--locked', '--release', '--bin', 'sknow-rs']
        if args.bench:
            cargo += ['--example', 'bench_resolver']
        wheel = directory / 'sakura_knowledge-0.2.0-py3-none-any.whl'
        commands = [
            ['git', 'archive', '--format=zip', '--output', str(archive), args.source_commit],
            cargo,
            [sys.executable, '-X', 'utf8', '-m', 'pip', 'wheel', '--no-deps',
             '--no-build-isolation', '--no-index', '--wheel-dir', str(directory), str(source)],
            [sys.executable, '-X', 'utf8', '-m', 'venv', str(directory / 'venv')],
            [str(python), '-X', 'utf8', '-I', '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)],
        ]
        report.update(directory=str(directory.resolve()), source=str(source.resolve()),
                      site_packages=str(site.resolve()),
                      environment={k: env[k] for k in ('PYTHONUTF8', 'PYTHONIOENCODING', 'CARGO_TARGET_DIR', 'PATH', 'CC', 'CXX',
                                                        'CC_x86_64_pc_windows_gnu', 'CXX_x86_64_pc_windows_gnu')})
        toolchain = []
        for argv in ([env['CC'], '--version'], [env['CC'], '-dumpmachine'],
                     [env['CXX'], '--version'], ['rustc', '-vV']):
            rec, data = run(argv, env, ROOT, directory=directory)
            toolchain.append(rec)
            if rec['exit'] != 0:
                raise ValueError('compiler metadata check failed; no compilation')
            if argv[-1] == '-dumpmachine' and data.decode('utf-8').strip() != 'x86_64-w64-mingw32':
                raise ValueError('unexpected GCC target')
            if argv == ['rustc', '-vV'] and 'host: x86_64-pc-windows-gnu' not in data.decode('utf-8'):
                raise ValueError('unexpected Rust target')
        report['toolchain'] = toolchain
        for argv in commands:
            rec, _ = run(argv, env, ROOT, directory=directory)
            report['processes'].append(rec)
            if rec['exit'] != 0:
                raise ValueError('artifact command failed; STOP, no retry')
            if argv[0] == 'git':
                extract_archive(archive, source)
        report.update(binary=binding(target / ('release/sknow-rs' + suffix)),
                      wheel=binding(wheel), archive=binding(archive), python=str(python.resolve()),
                      python_binding=binding(python), modules=module_provenance(source, wheel, site))
        if args.bench:
            report['reused_binary'] = binding(target / ('release/examples/bench_resolver' + suffix))
        with zipfile.ZipFile(archive) as zipped:
            report['source_files'] = [binding(source / name) for name in sorted(zipped.namelist())
                                      if not name.endswith('/') and
                                      (name.startswith(('src/', 'rust/')) or
                                       name in ('pyproject.toml', 'README.md'))]
        report['source_git_after'] = source_git(args.source_commit, allow_evidence=True)
        report['status'] = 'PASS'
        verify_artifacts(report)
    except Exception as exc:  # noqa: BLE001 - retain failed once-only attempt, never retry
        report.update(status='FAIL', exception={'type': type(exc).__name__, 'message': str(exc)})
    report['finished_ns'] = time.time_ns()
    create_new(out, report)
    print(json.dumps({'status': report['status'], 'source_commit': args.source_commit}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
