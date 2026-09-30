"""Evidence-only A-L STOP closure: hashes and Git, never runtime/SQL/build."""
import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

from p3_close_validate import validate_inputs
from p3_evidence import save, verify
from p3_retry1_path_audit import check_binding

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102'
BASE = '442cad073a693653bc6cbb3e4fd8a49ddaf52d0d'
MAIN = '894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
OUT = 'reports/P3/close-committed-binding.json'


def git(*args):
    return subprocess.check_output(['git', *args])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(Path(path).read_bytes().decode('utf-8', errors='strict'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def protect():
    build = load('reports/P3/full-retry1-build.json')
    refs = [build['database'], build['manifest'], build['preservation_after']['old_snapshot']]
    refs += build['preservation_after']['previous_partial_and_lock']
    observed = []
    for ref in refs:
        check_binding({k: ref[k] for k in ('path', 'bytes', 'sha256')})
        observed.append({k: ref[k] for k in ('path', 'bytes', 'sha256')})
    validate_inputs()
    for move in load('reports/P3/close-preconditions.json')['preserved_cancelled_prep']:
        require(not Path(move['original_path']).exists(), 'cancelled prep moved back')
        check_binding({'path': move['destination'], 'bytes': move['bytes'], 'sha256': move['sha256']})
    artifacts = load('reports/P3/close-artifacts.json')
    for field in ('binary', 'reused_binary', 'wheel'):
        check_binding(artifacts[field])
    for row in artifacts['modules']:
        check_binding(row['archive'])
        check_binding(row['installed'])
    save(Path('reports/P3/close-protection.json'), {'status': 'PASS', 'source_commit': SOURCE,
              'whole_binary_hashes_actual': observed, 'frozen_inputs_unchanged_except_exact_declared_lint': True,
              'prep_moved_bytes_unchanged': True, 'artifacts_unchanged': True,
              'no_SQL_or_query': True, 'no_snapshot_rebuild': True})


def inventory(commit):
    rows, raw, streams = [], {}, []
    def walk(value):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys() and str(value['path']).endswith('.raw'):
                ref = {k: value[k] for k in ('path', 'bytes', 'sha256')}
                path = Path(ref['path']).resolve()
                require(any(path.is_relative_to(ROOT / p) for p in ('reports/P3/raw', 'reports/P3/close-raw')),
                        'raw path outside allowed directories')
                verify(ref)
                name = path.relative_to(ROOT).as_posix()
                normalized = {**ref, 'path': name}
                require(name not in raw or raw[name] == normalized, 'raw identity conflict')
                raw[name] = normalized
            for stream in ('stdout', 'stderr'):
                if stream + '_base64' in value:
                    data = base64.b64decode(value[stream + '_base64'], validate=True)
                    require(sha(data) == value[stream + '_sha256'], 'embedded stream mismatch')
                    streams.append({'bytes': len(data), 'sha256': sha(data)})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    names = [p.decode('utf-8', errors='strict') for p in
             git('ls-tree', '-rz', '--name-only', commit, '--', 'reports/P3').split(b'\0') if p]
    for name in names:
        blob = git('show', commit + ':' + name)
        current = Path(name).read_bytes()
        eol = name.endswith('.md') and current.replace(b'\r\n', b'\n') == blob.replace(b'\r\n', b'\n')
        require(current == blob or eol, 'checkout differs from commit: ' + name)
        rows.append({'path': name, 'OID': git('rev-parse', commit + ':' + name).decode().strip(),
                     'bytes': len(blob), 'sha256': sha(blob), 'checkout_bytes': len(current),
                     'checkout_sha256': sha(current), 'MD_EOL_equivalence_only': current != blob and eol})
        if name.endswith(('.json', '.jsonl')):
            text = blob.decode('utf-8', errors='strict')
            values = [json.loads(text)] if name.endswith('.json') else [json.loads(line) for line in text.splitlines() if line.strip()]
            for value in values:
                walk(value)
    for ref in raw.values():
        if ref['path'].startswith('reports/P3/close-raw/'):
            data = git('show', commit + ':' + ref['path'])
            require(len(data) == ref['bytes'] and sha(data) == ref['sha256'], 'new raw not committed byte-exact')
    return rows, list(raw.values()), streams


def boundaries(head):
    require(not git('status', '--porcelain').strip(), 'clean final tree required')
    require(git('rev-parse', 'main').decode().strip() == MAIN, 'main changed')
    require(not git('diff', '--name-only', SOURCE, head, '--', 'src', 'rust', 'tools/p3_retry1_acceptance.py',
                    'tools/p3_close_validate.py', 'tools/p3_close_artifacts.py', 'tests').strip(), 'fixed validated code changed')
    require(not git('diff', '--name-only', BASE, head, '--', 'src', 'reports/P1', 'reports/P2',
                    'tools/p3_compile_inputs.py', 'tools/record_check.py', 'tools/p3_full_candidate_retry1.py').strip(),
            'frozen Python/compiler/builder changed')
    old = [p.decode('utf-8', errors='strict') for p in git('ls-tree', '-rz', '--name-only', BASE, '--', 'reports/P3').split(b'\0') if p]
    for name in old:
        require(git('rev-parse', BASE + ':' + name) == git('rev-parse', head + ':' + name), 'historical report changed')
    validate_inputs()
    require(load('reports/P3/close-protection.json')['status'] == 'PASS', 'protection absent')
    p2 = load('reports/P3/close-P2.json')
    require(p2['status'] == 'PASS' and p2['summary']['actually_compared'] == 135 and p2['summary']['error_contract_verified'] == 16,
            'new151 incomplete')
    perf = load('reports/P3/close-performance.json')
    measured = [r for r in perf['records'] if not r['warmup']]
    warm = [r for r in perf['records'] if r['warmup']]
    failed = [r for r in warm if not r['success']]
    require(perf['status'] == 'FAIL' and len(measured) == 900 and all(r['success'] for r in measured)
            and len(warm) == 30 and len(failed) == 1 and failed[0]['case_id'] == 'G42', 'warmup FAIL reporting changed')
    require(not any(Path('reports/P3/close-' + p + '.json').exists() for p in ('gold', 'external')), 'unapproved downstream result')
    for name in ('pytest', 'ruff', 'diff', 'fmt', 'rust-test', 'clippy', 'release'):
        require(load('reports/P3/close-check-' + name + '.json')['exit'] == 0, 'K check not PASS')
    return len(old)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('protect', 'prepare', 'verify'))
    args = parser.parse_args()
    if args.mode == 'protect':
        protect()
        print(json.dumps({'status': 'PASS', 'scope': 'hash protection only'}))
        return
    head = git('rev-parse', 'HEAD').decode().strip()
    old = boundaries(head)
    if args.mode == 'prepare':
        rows, raw, streams = inventory(head)
        save(Path(OUT), {'status': 'VERIFIED_STOP_EVIDENCE', 'P3': 'NOT_READY', 'code_review': 'WAITING_REVIEW', 'approval': 'NONE',
                        'evidence_commit': head, 'runtime_artifact_source': SOURCE, 'main': MAIN, 'files': rows,
                        'raw_inventory': raw, 'embedded_streams': streams, 'historical_reports_unchanged': old,
                        'measured_PASS': 900, 'warmups_PASS': 29, 'warmups_FAIL': 1,
                        'FULL55_new_code': 'NOT_RUN', 'external_final_J': 'NOT_RUN',
                        'boundary': 'Direct parent exact blob closure; final child only adds binding, no selfhash. Old ignored raw locally verified, new raw committed.'})
    else:
        binding = load(OUT)
        parent = binding['evidence_commit']
        require(git('rev-parse', head + '^').decode().strip() == parent, 'not direct binding child')
        require(git('diff', '--name-status', parent, head).decode().splitlines() == ['A\t' + OUT], 'child changed other files')
        rows, raw, streams = inventory(parent)
        require(binding['files'] == rows and binding['raw_inventory'] == raw and binding['embedded_streams'] == streams,
                'closed parent inventory mismatch')
        require(binding['P3'] == 'NOT_READY' and binding['approval'] == 'NONE' and binding['runtime_artifact_source'] == SOURCE
                and binding['historical_reports_unchanged'] == old, 'authoritative binding fields changed')
        inventory(head)
        remote = dict(line.split()[::-1] for line in git('ls-remote', 'origin', 'refs/heads/dev', 'refs/heads/main').decode().splitlines())
        require(remote.get('refs/heads/dev') == head and remote.get('refs/heads/main') == MAIN, 'remote mismatch')
        print(json.dumps({'status': 'VERIFIED_STOP_EVIDENCE', 'P3': 'NOT_READY', 'code_review': 'WAITING_REVIEW', 'approval': 'NONE',
                          'HEAD_origin_dev': head, 'main_origin_main': MAIN, 'evidence_commit': parent,
                          'runtime_artifact_source': SOURCE, 'files': len(rows), 'raw': len(raw), 'streams': len(streams),
                          'historical_reports_unchanged': old, 'porcelain': git('status', '--porcelain').decode(),
                          'no_runtime_queries_or_builds': True}))


if __name__ == '__main__':
    main()
