"""Build fresh artifacts from a clean fixed commit, never build a snapshot."""
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from p3_evidence import save, store
from p3_retry1_acceptance import binding

ROOT = Path(__file__).resolve().parents[1]
RAW = Path('reports/P3/close-raw')


def main():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
    if subprocess.check_output(['git', 'status', '--porcelain']).strip():
        raise ValueError('clean fixed source required')
    out = ROOT / 'reports/P3/close-artifacts.json'
    if out.exists():
        raise FileExistsError(out)
    directory = ROOT / ('dist/p3-close-' + head[:8])
    directory.mkdir()  # no reuse/overwrite
    archive = directory / 'source.zip'
    source = directory / 'source'
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               CARGO_TARGET_DIR=str(source / 'rust/target'))
    records = []
    commands = [
        ['git', 'archive', '--format=zip', '--output', str(archive), head],
        ['cargo', 'build', '--manifest-path', str(source / 'rust/Cargo.toml'), '--locked', '--release', '--examples', '--bin', 'sknow-rs'],
        [sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation', '--no-index', '--wheel-dir', str(directory), str(source)],
        [sys.executable, '-m', 'venv', str(directory / 'venv')],
        [str(directory / 'venv/Scripts/python.exe'), '-m', 'pip', 'install', '--no-index', '--no-deps',
         str(directory / 'sakura_knowledge-0.2.0-py3-none-any.whl')],
    ]
    good = True
    for argv in commands:
        target = Path(env['CARGO_TARGET_DIR']).resolve()
        if not target.is_relative_to(directory.resolve()) or '--target-dir' in argv:
            raise ValueError('unsafe compilation target')
        started = time.perf_counter()
        proc = subprocess.run(argv, capture_output=True, check=False, env=env, cwd=ROOT)
        records.append({'argv': argv, 'exit': proc.returncode, 'elapsed_s': time.perf_counter()-started,
                        'stdout': store(proc.stdout, root=RAW), 'stderr': store(proc.stderr, root=RAW),
                        'CARGO_TARGET_DIR': str(target), 'target_inside_authorized_artifact_root': True})
        if proc.returncode:
            good = False
            break
        if argv[0] == 'git':
            with zipfile.ZipFile(archive) as zip_file:
                zip_file.extractall(source)
    report = {'status': 'PASS' if good else 'FAIL', 'source_commit': head, 'clean_at_start': True,
              'processes': records, 'retries': 0, 'directory': str(directory),
              'no_snapshot_build': True, 'environment': {k: env[k] for k in ('PYTHONUTF8', 'PYTHONIOENCODING', 'CARGO_TARGET_DIR')}}
    if good:
        report.update(binary=binding(source / 'rust/target/release/sknow-rs.exe'),
                      reused_binary=binding(source / 'rust/target/release/examples/bench_resolver.exe'),
                      wheel=binding(directory / 'sakura_knowledge-0.2.0-py3-none-any.whl'),
                      python=str(directory / 'venv/Scripts/python.exe'))
        modules = []
        with zipfile.ZipFile(report['wheel']['path']) as wheel:
            for path in sorted((source / 'src/sakura_knowledge').glob('*.py')):
                name = 'sakura_knowledge/' + path.name
                installed = directory / 'venv/Lib/site-packages' / name
                identical = path.read_bytes() == wheel.read(name) == installed.read_bytes()
                if not identical:
                    good = False
                modules.append({'module': name, 'archive': binding(path), 'installed': binding(installed),
                                'bytes_equal_archive_wheel_installed': identical})
        report['modules'] = modules
        report['status'] = 'PASS' if good else 'FAIL'
    save(out, report)
    print(json.dumps(report))
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())
