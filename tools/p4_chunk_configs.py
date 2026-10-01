"""Create chunk wrapper configurations from existing hash-bound model contracts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    summary = json.loads((ROOT / 'reports/P4/model-freeze-summary.json').read_bytes())
    for label, model in summary['models'].items():
        raw = (ROOT / model['contract']['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != model['contract']['file_sha256']:
            raise ValueError('model contract file hash mismatch')
        contract = json.loads(raw)
        if contract != model['contract']['reviewed']:
            raise ValueError('reviewed contract mismatch')
        config = {'repository': model['repository'], 'revision': model['revision'],
                  'contract': contract}
        output = ROOT / f'configs/p4-chunk-model-{label}.json'
        content = (json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        with output.open('xb') as f:
            f.write(content)
        print(json.dumps({'path': str(output.relative_to(ROOT)),
                          'sha256': hashlib.sha256(content).hexdigest()}))


if __name__ == '__main__':
    main()
