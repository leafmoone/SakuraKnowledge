"""Bind retry1 NOT_READY evidence only; never run queries or build snapshots."""
import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

from p3_evidence import save, verify

BASE = '97c3c4969dfb637093e78e7151fc561c91913b78'
SOURCE = '9dfa610640eca1e32b6da89f78f3d4aff6062adf'
MAIN = '894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
OUT = Path('reports/P3/full-retry1-stop-committed-byte-binding.json')
EXCLUDED = {'tools/p3_retry1_delivery.py', 'tools/p3_retry1_bind.py',
            'tests/test_p3_retry1_delivery.py'}


def worktree_observation():
    status = git('status', '--porcelain', '-z')
    paths = set()
    for row in status.split(b'\0'):
        if row:
            require(row.startswith(b'?? '), 'tracked/index changes not permitted by STOP binder')
            paths.add(row[3:].decode('utf-8', errors='strict'))
    require(paths <= EXCLUDED, 'unapproved untracked file in binding worktree')
    return {'status': 'DIRTY_EXCLUDED_UNTRACKED' if paths else 'CLEAN',
            'excluded_untracked': sorted(paths), 'porcelain': status.decode('utf-8', errors='strict')}


def git(*args):
    return subprocess.check_output(['git', *args])


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode_json(data):
    return json.loads(data.decode('utf-8', errors='strict'))


def git_paths(commit, prefix):
    return [p.decode('utf-8', errors='strict') for p in
            git('ls-tree', '-rz', '--name-only', commit, '--', prefix).split(b'\0') if p]


def frozen_bindings(commit):
    root = Path.cwd().resolve()
    for name in ('full-retry1-real-gold', 'full-retry1-P2-frozen-expected'):
        frozen = decode_json(git('show', commit + ':reports/P3/' + name + '.json'))
        for ref in frozen['bindings'] + frozen['source_proof']:
            path = Path(ref['path']).resolve()
            require(path.is_relative_to(root), 'frozen binding outside repository')
            actual = path.read_bytes()
            require(len(actual) == ref['bytes'] and sha(actual) == ref['sha256'], 'frozen checkout binding changed')
            rel = path.relative_to(root).as_posix()
            if '/raw/' not in rel:
                blob = git('show', commit + ':' + rel)
                require(blob == actual or blob.replace(b'\r\n', b'\n') == actual.replace(b'\r\n', b'\n'),
                        'frozen binding differs beyond EOL from committed blob')
    build = decode_json(git('show', commit + ':reports/P3/full-retry1-build.json'))
    ref = build['manifest']
    data = Path(ref['path']).read_bytes()
    require(len(data) == ref['bytes'] and sha(data) == ref['sha256'], 'manifest changed')


def inventory(commit):
    rows, refs, streams = [], {}, []
    root = Path.cwd().resolve()
    def walk(value):
        if isinstance(value, dict):
            if {'raw_path', 'bytes', 'sha256'} <= value.keys():
                ref = {'path': value['raw_path'], 'bytes': value['bytes'], 'sha256': value['sha256']}
            elif {'path', 'bytes', 'sha256'} <= value.keys():
                ref = {k: value[k] for k in ('path', 'bytes', 'sha256')}
            else:
                ref = None
            if ref is not None:
                path = Path(ref['path']).resolve()
                actual_raw = ('raw_path' in value or path.suffix == '.raw')
                if actual_raw:
                    require(path.is_relative_to(root / 'reports/P3/raw'), 'raw reference outside allowed directory')
                if path.is_relative_to(root / 'reports/P3/raw'):
                    verify(ref)
                    name = path.relative_to(root).as_posix()
                    normalized = {**ref, 'path': name}
                    require(name not in refs or refs[name] == normalized, 'conflicting raw reference')
                    refs[name] = normalized
            for stream in ('stdout', 'stderr'):
                if stream + '_base64' in value:
                    data = base64.b64decode(value[stream + '_base64'], validate=True)
                    require(sha(data) == value[stream + '_sha256'], 'embedded stream hash mismatch')
                    streams.append({'bytes': len(data), 'sha256': sha(data)})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for name in git_paths(commit, 'reports/P3'):
        path = Path(name)
        require(not path.is_symlink(), 'symlink report')
        data = git('show', commit + ':' + name)
        actual = path.read_bytes()
        eol = name.endswith('.md') and actual.replace(b'\r\n', b'\n') == data.replace(b'\r\n', b'\n')
        require(actual == data or eol, 'checkout bytes differ: ' + name)
        rows.append({'path': name, 'blob_oid': git('rev-parse', commit + ':' + name).decode().strip(),
                     'bytes': len(data), 'sha256': sha(data), 'checkout_bytes': len(actual),
                     'checkout_sha256': sha(actual), 'byte_exact': actual == data,
                     'markdown_EOL_equivalence_only': actual != data and eol})
        if name.endswith('.json'):
            walk(decode_json(data))
        elif name.endswith('.jsonl'):
            for line in data.splitlines():
                if line.strip():
                    walk(decode_json(line))
    return rows, list(refs.values()), streams


def boundaries(head):
    protected = ('src', 'rust', 'tools/p3_compile_inputs.py', 'tools/record_check.py',
                 'tools/p3_full_candidate_retry1.py', 'tools/p3_full_candidate.py',
                 'tools/parity_cases.py', 'tools/parity_repair_expected.py', 'reports/P1', 'reports/P2')
    require(not git('diff', '--name-only', SOURCE, head, '--', *protected).strip(), 'frozen code changed')
    historical = git_paths(BASE, 'reports/P3')
    for name in historical:
        require(git('rev-parse', BASE + ':' + name) == git('rev-parse', head + ':' + name),
                'historical report changed: ' + name)
    require(git('rev-parse', 'main').decode().strip() == MAIN, 'main changed')
    frozen_bindings(head)
    delivery = decode_json(git('show', head + ':reports/P3/full-retry1-stop-delivery.json'))
    require(delivery['P3'] == 'NOT_READY' and delivery['build'] == 'PASS'
            and delivery['FULL_P2']['overall'] == 'FAIL' and delivery['total_attempts'] == 2,
            'STOP reporting changed')
    return len(historical)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    observed_tree = worktree_observation()
    head = git('rev-parse', 'HEAD').decode().strip()
    historical = boundaries(head)
    rows, refs, streams = inventory(head)
    summary = {'status': 'VERIFIED_STOP_EVIDENCE', 'overall_P3': 'NOT_READY',
               'code_review': 'WAITING_REVIEW', 'approval': 'NONE', 'HEAD': head,
               'build_code_sha': SOURCE, 'main': MAIN, 'historical_reports_unchanged': historical,
               'committed_files_verified': len(rows), 'raw_verified': len(refs),
               'embedded_streams_verified': len(streams), 'worktree_observation': observed_tree}
    if args.verify:
        binding = decode_json(git('show', head + ':' + OUT.as_posix()))
        parent = binding['evidence_commit']
        require(git('rev-parse', head + '^').decode().strip() == parent, 'binding not direct child')
        require(git('diff', '--name-status', parent, head).decode().splitlines() == ['A\t' + OUT.as_posix()],
                'final child may add only binding')
        p_rows, p_refs, p_streams = inventory(parent)
        expected = {**summary, 'HEAD': parent, 'committed_files_verified': len(p_rows),
                    'raw_verified': len(p_refs), 'embedded_streams_verified': len(p_streams)}
        require(all(binding.get(k) == v for k, v in expected.items()), 'binding authoritative metadata mismatch')
        require(binding['files'] == p_rows and binding['raw_inventory'] == p_refs
                and binding['embedded_streams'] == p_streams, 'parent evidence inventory differs')
        require({r['path'] for r in rows} == {r['path'] for r in p_rows} | {OUT.as_posix()},
                'final report set not closed')
        remote = dict(line.split()[::-1] for line in
                      git('ls-remote', 'origin', 'refs/heads/dev', 'refs/heads/main').decode().splitlines())
        require(remote.get('refs/heads/dev') == head and remote.get('refs/heads/main') == MAIN,
                'remote dev/main mismatch')
        require(worktree_observation() == observed_tree, 'worktree exclusion state changed')
        summary.update(origin_dev=head, origin_main=MAIN, working_tree=observed_tree['status'], evidence_commit=parent)
    else:
        save(OUT, {**summary, 'evidence_commit': head, 'files': rows, 'raw_inventory': refs,
                   'embedded_streams': streams,
                   'boundary': 'Parent exact immutable blobs plus final binding only; ignored raw verified locally, not claimed uploaded. No selfhash.'})
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
