"""Record one local check with an explicitly contained cargo target and no retry."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from p3_evidence import save, store

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv and args.argv[0] == '--' else args.argv
    if not argv or args.out.exists():
        raise ValueError('missing command or output already exists')
    target = Path(os.environ.get('CARGO_TARGET_DIR', '')).resolve()
    if not target.is_relative_to(ROOT) or '--target-dir' in argv:
        raise ValueError('unsafe effective cargo target; BLOCKED')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
    tree = subprocess.check_output(['git', 'status', '--porcelain']).decode('utf-8', errors='strict')
    started = time.perf_counter()
    proc = subprocess.run(argv, capture_output=True, check=False, env=env, cwd=ROOT)
    report = {'status': 'PASS' if proc.returncode == 0 else 'FAIL', 'head': head, 'working_tree_at_start': tree,
              'argv': argv, 'exit': proc.returncode, 'elapsed_s': time.perf_counter()-started, 'retries': 0,
              'stdout': store(proc.stdout, root=Path('reports/P3/close-raw')),
              'stderr': store(proc.stderr, root=Path('reports/P3/close-raw')),
              'environment': {k: env.get(k) for k in ('PYTHONUTF8', 'PYTHONIOENCODING', 'CARGO_TARGET_DIR', 'SKNOW_RS_TEST_BIN')},
              'resolved_target': str(target), 'target_inside_authorized_root': True}
    save(args.out, report)
    print(json.dumps(report))
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
