"""Frozen structured business comparison for installed source packs; retain raw bytes."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA = {'source_pack', 'source_packs', 'installed_packs', 'participating_packs', 'semantic_capable_packs', 'snapshot'}


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in METADATA}
    if isinstance(value, list):
        return sorted((normalize(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
    return value


def structured(root, output):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    freeze = json.loads((ROOT / 'reports/P4/legacy-baseline-freeze.json').read_text(encoding='utf-8'))
    exe = root / 'bin/sknow-rs.exe'
    rows = []
    env = {**os.environ, 'PYTHONUTF8': '1'}
    for case in freeze['suites']['P2']['cases']:
        args = case['accepted_argv']
        command = [str(exe), '--config', str(root / 'sknow-config.json'), args[1], *args[3:]]
        # E17 explicitly tests an unavailable asset, not the now-valid Core-only state.
        if case['case_id'] == 'E17':
            command = [str(exe), args[1], str(ROOT/'build/p4-approved-baseline/missing-parity-input.sqlite'), *args[3:]]
        started = time.perf_counter()
        p = subprocess.run(command, capture_output=True, env=env, timeout=15, check=False)
        cid = case['case_id']
        (output / (cid + '.stdout.json')).write_bytes(p.stdout)
        (output / (cid + '.stderr.log')).write_bytes(p.stderr)
        saved = json.loads((ROOT / 'build/p4-approved-baseline' / ('P2-' + cid + '.json')).read_bytes())
        expected = saved['actual_json']
        try:
            actual = json.loads(p.stdout if p.stdout else p.stderr)
            equal = normalize(actual) == normalize(expected) and p.returncode == saved['process']['exit']
            difference = [k for k in set(actual) | set(expected) if normalize(actual.get(k)) != normalize(expected.get(k)) and k not in METADATA]
        except (ValueError, TypeError):
            equal, difference = False, ['invalid_json']
        rows.append({'case_id': cid, 'argv': command, 'exit': p.returncode, 'wall_ms': (time.perf_counter() - started) * 1000, 'equal': equal, 'different_fields': sorted(difference)})
    report = {'schema': 'sakura-modular-structured-v1', 'cases': rows, 'equal': sum(r['equal'] for r in rows), 'total': len(rows), 'normalization': 'pack metadata/snapshot removed; array order ignored, no business fields dropped'}
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('equal', 'total')}))
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    structured(a.root, a.output)


if __name__ == '__main__':
    main()
