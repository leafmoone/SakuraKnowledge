"""Run exactly one final code check with artifact bindings and contained child Cargo."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from p3_evidence import save, store
from p3_final_artifacts import ROOT, binding, environment, source_git, verify_artifacts

CHECKS = {
    'pytest': ['python', '-m', 'pytest', '-q'],
    'ruff': ['python', '-m', 'ruff', 'check', 'src', 'tests', 'tools'],
    'diff': ['git', 'diff', '--check'],
    'fmt': ['cargo', 'fmt', '--manifest-path', 'rust/Cargo.toml', '--all', '--', '--check'],
    'rust-test': ['cargo', 'test', '--manifest-path', 'rust/Cargo.toml', '--locked'],
    'clippy': ['cargo', 'clippy', '--manifest-path', 'rust/Cargo.toml', '--all-targets', '--locked', '--', '-D', 'warnings'],
    'release': ['cargo', 'build', '--manifest-path', 'rust/Cargo.toml', '--release', '--locked'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('check', choices=CHECKS)
    args = parser.parse_args()
    out = ROOT / ('reports/P3/final-check-' + args.check + '.json')
    marker = ROOT / ('reports/P3/final-check-' + args.check + '-start.json')
    if out.exists() or marker.exists():
        raise FileExistsError('final check already reserved; no automatic retry')
    path = ROOT / 'reports/P3/final-artifacts-retry1.json'
    artifacts = json.loads(path.read_bytes())
    verify_artifacts(artifacts)
    proof = source_git(artifacts['source_commit'], allow_evidence=True)
    target = (ROOT / ('build/p3-final-checks-' + artifacts['source_commit']) / 'rust-target').resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError('child Cargo target escaped Knowledge')
    env = environment(target)
    env['SKNOW_RS_TEST_BIN'] = artifacts['binary']['path']
    argv = CHECKS[args.check]
    save(marker, {'argv': argv, 'artifacts': binding(path), 'source_commit': artifacts['source_commit'],
                  'created_ns': time.time_ns(), 'CARGO_TARGET_DIR': str(target)})
    started = time.perf_counter()
    proc = subprocess.run(argv, capture_output=True, check=False, env=env, cwd=ROOT)
    report = {'status': 'PASS' if proc.returncode == 0 else 'FAIL', 'head': artifacts['source_commit'],
              'source_git': proof, 'artifacts': binding(path), 'argv': argv, 'exit': proc.returncode,
              'elapsed_s': time.perf_counter()-started, 'retries': 0,
              'stdout': store(proc.stdout, root=Path('reports/P3/final-raw')),
              'stderr': store(proc.stderr, root=Path('reports/P3/final-raw')),
              'environment': {k: env.get(k) for k in ('PYTHONUTF8', 'PYTHONIOENCODING', 'CARGO_TARGET_DIR', 'SKNOW_RS_TEST_BIN', 'PATH', 'CC', 'CXX', 'CC_x86_64_pc_windows_gnu', 'CXX_x86_64_pc_windows_gnu')},
              'toolchain': artifacts['toolchain'],
              'resolved_target': str(target), 'target_inside_authorized_root': True}
    save(out, report)
    print(json.dumps({k: report[k] for k in ('status', 'argv', 'exit', 'elapsed_s')}))
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
