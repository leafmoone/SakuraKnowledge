"""Run an explicit command and retain UTF-8 stdout/stderr plus exit status."""
import argparse
import base64
import json
import os
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('command required')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    with Path(args.output).open('x', encoding='utf-8') as f:
        start = time.perf_counter()
        result = subprocess.run(command, env=env, capture_output=True, check=False)
        receipt = {'schema': 'p4-command-receipt-v1', 'command': command,
                   'exit_code': result.returncode,
                   'elapsed_seconds': time.perf_counter() - start,
                   'environment': {k: env[k] for k in ('PYTHONUTF8', 'PYTHONIOENCODING')}}
        for name in ('stdout', 'stderr'):
            raw = getattr(result, name)
            receipt[name + '_base64'] = base64.b64encode(raw).decode('ascii')
            try:
                receipt[name] = raw.decode('utf-8', errors='strict')
                receipt[name + '_utf8_valid'] = True
            except UnicodeDecodeError:
                receipt[name + '_utf8_valid'] = False
        json.dump(receipt, f, ensure_ascii=False, allow_nan=False, sort_keys=True)
        f.write('\n')
    print(json.dumps({'exit_code': result.returncode, 'receipt': args.output}))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
