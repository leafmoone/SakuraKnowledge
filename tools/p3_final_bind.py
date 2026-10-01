"""Evidence-only final B-I closure: no SQL, runtime, build, commit or push.

protect is the ONLY mode that streams whole database/partial/private files.
prepare requires a clean committed parent including FINAL_DIRECTED_REPORT.md.
After independently committing only the binding and pushing, verify checks the
single-parent child and remote refs. Historical ignored raw is local evidence,
not a claim that a fresh clone can reproduce it or that Pool is verified clean.

Final check receipts use p3_close_check's head/argv/exit/stdout/stderr schema,
plus artifacts (the exact final artifact report or its path/bytes/sha256 binding).
No command recorded in a receipt is ever executed by this helper.
"""
import argparse
import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

import p3_close_validate as helpers
import p3_measure_resolver as policy
from p3_evidence import save
from p3_final_artifacts import verify_artifacts

ROOT = Path(__file__).resolve().parents[1]
BASE = '1badc465c2fdeae8250bba1ef3c1c8f142c42818'
RUNTIME = '9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102'
MAIN = '894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
OUT = 'reports/P3/final-committed-binding.json'
PROTECTION = 'reports/P3/final-protection.json'
REPORT = 'reports/P3/FINAL_DIRECTED_REPORT.md'
POLICY = 'tools/p3_measure_resolver.py'
RAW_DIRS = ('reports/P3/raw', 'reports/P3/close-raw', 'reports/P3/final-raw')
CHECKS = ('pytest', 'ruff', 'diff', 'fmt', 'rust-test', 'clippy', 'release')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(*args):
    # Only read-only Git operations are exposed, never receipt-provided argv.
    require(args and args[0] in ('rev-parse', 'ls-tree', 'show', 'diff', 'status',
                                'log', 'merge-base', 'ls-remote'), 'unsafe Git command')
    return subprocess.check_output(['git', *args], cwd=ROOT)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def absolute(path):
    path = Path(path)
    return (path if path.is_absolute() else ROOT / path).resolve()


def load(path):
    return json.loads(absolute(path).read_bytes().decode('utf-8', errors='strict'))


def ref_only(ref):
    return {k: ref[k] for k in ('path', 'bytes', 'sha256')}


class Evidence:
    """Memoize hashes by resolved identity, but check every declared reference."""

    def __init__(self):
        self.cache = {}

    def binding(self, path):
        path = absolute(path)
        if path not in self.cache:
            digest, size = hashlib.sha256(), 0
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    size += len(chunk)
                    digest.update(chunk)
            self.cache[path] = {'path': str(path), 'bytes': size, 'sha256': digest.hexdigest()}
        return self.cache[path]

    def verify(self, ref):
        actual = self.binding(ref['path'])
        require(type(ref['bytes']) is int and ref['bytes'] >= 0 and
                actual['bytes'] == ref['bytes'] and actual['sha256'] == ref['sha256'],
                'changed byte binding: ' + str(ref['path']))
        return ref_only(ref)


def protected_refs():
    build = load('reports/P3/full-retry1-build.json')
    preserved = build['preservation_after']
    refs = [build['database'], build['manifest'], preserved['old_snapshot']]
    previous = preserved['previous_partial_and_lock']
    require(len(previous) == 10 and
            sum('/.inputs/' in r['path'].replace('\\', '/') for r in previous) == 6 and
            any(r['path'].endswith('-wal') for r in previous) and
            any(r['path'].endswith('-shm') for r in previous) and
            any(r['path'].endswith('.lock') for r in previous),
            'original partial/WAL/SHM/private-six/lock protection incomplete')
    return [ref_only(r) for r in refs + previous]


def performance(evidence):
    path = 'reports/P3/final-performance-recomputed.json'
    rec = load(path)
    old = load('reports/P3/close-performance.json')
    for field, expected in (('old_receipt', 'reports/P3/close-performance.json'),
                            ('policy', POLICY)):
        require(absolute(rec[field]['path']) == absolute(expected), 'wrong performance provenance')
        evidence.verify(rec[field])
    dependencies = {'tools/' + name for name in (
        'p3_final_recompute.py', 'p3_measure_resolver.py', 'p3_retry1_acceptance.py',
        'check_parity.py', 'p3_evidence.py', 'p3_accept_resolver.py', 'p3_resolver_oracle.py')}
    refs = rec['verifier_bindings']
    require(len(refs) == len(dependencies) and
            {absolute(r['path']) for r in refs} == {absolute(p) for p in dependencies},
            'performance verifier bindings incomplete')
    for ref in refs:
        evidence.verify(ref)
    evaluated = policy.evaluate(old['records'], old['workloads'], old['samples'])
    for field in ('status', 'formal_counts', 'warmup_counts', 'summary', 'warmup_summary',
                  'structure_errors'):
        require(rec[field] == evaluated[field], 'recomputed performance differs: ' + field)
    require(rec['status'] == 'PASS' and rec['structure_errors'] == [] and
            rec['formal_counts'] == {'attempted': 900, 'success': 900, 'failed': 0} and
            rec['warmup_counts'] == {'attempted': 30, 'success': 29, 'failed': 1} and
            rec['original_status'] == old['status'] == 'FAIL' and
            rec['performance_rerun'] == 'NO' and rec['retries'] == old['retries'] == 0 and
            rec['source_commit'] == old['source_commit'] == RUNTIME and
            rec['database'] == old['database'], 'performance acceptance/provenance changed')
    failed = [r for r in old['records'] if r['warmup'] and not r['success']]
    require(len(failed) == 1 and failed[0]['case_id'] == 'G42' and
            rec['warmup_failure']['record'] == failed[0] and
            rec['warmup_failure']['original_status'] == 'FAIL' and
            rec['warmup_failure']['stdout'] == old['reused_process']['stdout'],
            'original warmup diagnostic lost')
    return evidence.binding(path)


def protect():
    require(not absolute(PROTECTION).exists() and not absolute(PROTECTION).is_symlink(),
            'protection already exists')
    evidence = Evidence()
    refs = protected_refs()
    for ref in refs:
        evidence.verify(ref)
    helpers.validate_inputs()  # Frozen bytes and sidecar metadata only; never SQL.
    moved = load('reports/P3/close-preconditions.json')['preserved_cancelled_prep']
    for row in moved:
        require(not absolute(row['original_path']).exists(), 'cancelled prep moved back')
        evidence.verify({'path': row['destination'], 'bytes': row['bytes'], 'sha256': row['sha256']})
    artifacts = load('reports/P3/final-artifacts.json')
    verify_artifacts(artifacts)
    perf = performance(evidence)
    save(absolute(PROTECTION), {
        'status': 'PASS', 'source_commit': artifacts['source_commit'],
        'whole_binary_hashes_actual': refs, 'frozen_inputs_unchanged': True,
        'prep_moved_bytes_unchanged': True, 'artifacts_unchanged': True,
        'artifacts': evidence.binding('reports/P3/final-artifacts.json'),
        'performance': perf, 'no_SQL_or_query': True, 'no_snapshot_rebuild': True,
        'performance_reused': 'YES', 'performance_rerun': 'NO'})


def tree(commit, path='reports/P3'):
    rows = {}
    for entry in git('ls-tree', '-rz', commit, '--', path).split(b'\0'):
        if entry:
            meta, name = entry.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            require(kind == 'blob' and mode in ('100644', '100755'), 'nonregular evidence file')
            rows[name.decode('utf-8', errors='strict')] = oid
    return rows


def inventory(commit, evidence=None):
    evidence = evidence or Evidence()
    rows, raw, streams, blobs = [], {}, [], {}
    tracked = tree(commit)

    def walk(value):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys() and str(value['path']).endswith('.raw'):
                path = absolute(value['path'])
                require(any(path.is_relative_to(absolute(p)) for p in RAW_DIRS),
                        'raw path outside allowed directories')
                evidence.verify(value)
                name = path.relative_to(ROOT.resolve()).as_posix()
                ref = {**ref_only(value), 'path': name}
                require(name not in raw or raw[name] == ref, 'raw identity conflict')
                raw[name] = ref
            for stream in ('stdout', 'stderr'):
                if stream + '_base64' in value:
                    data = base64.b64decode(value[stream + '_base64'], validate=True)
                    digest = sha(data)
                    require(digest == value[stream + '_sha256'], 'embedded stream mismatch')
                    if stream + '_bytes' in value:
                        require(value[stream + '_bytes'] == len(data), 'embedded stream length mismatch')
                    streams.append({'bytes': len(data), 'sha256': digest})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    values_to_walk = []
    # Seed all tracked bytes first, so raw refs reuse their one current-file hash.
    for name, oid in tracked.items():
        blob = git('show', oid)
        path = absolute(name)
        current = path.read_bytes()
        eol = name.endswith('.md') and current.replace(b'\r\n', b'\n') == blob.replace(b'\r\n', b'\n')
        require(current == blob or eol, 'checkout differs from commit: ' + name)
        cached = evidence.cache.get(path)
        current_sha = cached['sha256'] if cached else sha(current)
        blob_sha = current_sha if current == blob else sha(blob)
        evidence.cache[path] = {'path': str(path), 'bytes': len(current), 'sha256': current_sha}
        blobs[name] = {'bytes': len(blob), 'sha256': blob_sha}
        rows.append({'path': name, 'OID': oid, **blobs[name],
                     'checkout_bytes': len(current), 'checkout_sha256': current_sha,
                     'MD_EOL_equivalence_only': current != blob and eol})
        if name.endswith(('.json', '.jsonl')):
            text = blob.decode('utf-8', errors='strict')
            values_to_walk.extend([json.loads(text)] if name.endswith('.json') else
                                  [json.loads(line) for line in text.splitlines() if line.strip()])
    for value in values_to_walk:
        walk(value)
    for name, ref in raw.items():
        if name.startswith(('reports/P3/final-raw/', 'reports/P3/close-raw/')):
            require(name in tracked, 'new/close raw not tracked: ' + name)
            require(blobs[name] == {k: ref[k] for k in ('bytes', 'sha256')},
                    'new/close raw blob differs: ' + name)
    return rows, list(raw.values()), streams


def boundaries(head):
    require(not git('status', '--porcelain', '--untracked-files=all').strip(), 'clean HEAD required')
    for ref in ('main', 'origin/main'):
        require(git('rev-parse', ref).decode().strip() == MAIN, ref + ' changed')
    require(git('merge-base', BASE, head).decode().strip() == BASE, 'not a baseline descendant')
    require(not git('diff', '--name-only', RUNTIME, head, '--', 'src', 'rust').strip(),
            'runtime src/rust changed')
    old, current = tree(BASE), tree(head)
    for name, oid in old.items():
        require(current.get(name) == oid, 'historical report changed: ' + name)
    changed = git('diff', '--name-only', BASE, head).decode().splitlines()
    baseline_files = tree(BASE, '.')
    for name in changed:
        allowed = (name.startswith('reports/P3/') and name not in old or
                   name in (POLICY, '.gitattributes') or name.startswith('tests/') and name not in baseline_files or
                   name.startswith('tools/p3_final_') and name not in baseline_files)
        require(allowed, 'unauthorized baseline/public/compiler/case change: ' + name)
    return len(old)


def check_receipt(name, rec, artifacts, evidence):
    source = artifacts['source_commit']
    require(rec['status'] == 'PASS' and type(rec['exit']) is int and rec['exit'] == 0 and
            rec.get('retries', 0) == 0 and rec.get('head', rec.get('source_commit')) == source,
            'final check status/source differs: ' + name)
    require(rec.get('artifacts') in (artifacts, evidence.binding('reports/P3/final-artifacts.json')),
            'final check artifact binding missing/differs: ' + name)
    argv = rec['argv']
    require(isinstance(argv, list) and all(isinstance(a, str) for a in argv), 'invalid check argv')
    python = Path(argv[0]).name.lower() if argv else ''
    commands = {'pytest': [['-m', 'pytest', '-q']],
                'ruff': [['-m', 'ruff', 'check', '.'], ['-m', 'ruff', 'check', 'src', 'tests', 'tools']]}
    if name in commands:
        require(python in ('python', 'python.exe', 'python3', 'python3.exe') and
                argv[1:] in commands[name], 'not the precise final check: ' + name)
    elif name == 'diff':
        require(argv == ['git', 'diff', '--check'], 'not git diff --check')
    else:
        require(len(argv) >= 4 and argv[0] == 'cargo' and '--manifest-path' in argv,
                'not a Cargo final check')
        index = argv.index('--manifest-path')
        require(index + 1 < len(argv), 'missing manifest')
        manifest = absolute(argv[index + 1])
        require(manifest in (absolute('rust/Cargo.toml'), absolute(artifacts['source']) / 'rust/Cargo.toml'),
                'wrong Cargo manifest')
        normalized = argv[:index] + argv[index + 2:]
        expected = {'fmt': ['cargo', 'fmt', '--all', '--', '--check'],
                    'rust-test': ['cargo', 'test', '--locked'],
                    'clippy': ['cargo', 'clippy', '--all-targets', '--locked', '--', '-D', 'warnings'],
                    'release': ['cargo', 'build', '--release', '--locked']}
        require(normalized == expected[name], 'not the precise final check: ' + name)
        env = rec['environment']
        target = absolute(env['CARGO_TARGET_DIR'])
        require(target == absolute('rust/target') or (
                    target.is_relative_to(absolute(artifacts['directory'])) and
                    target == absolute(artifacts['environment']['CARGO_TARGET_DIR'])),
                'Cargo check target escaped Knowledge or final artifact archive')
    for stream in ('stdout', 'stderr'):
        evidence.verify(rec[stream])
    require(not rec.get('timeout') and not rec.get('exception'), 'check process failure')


def gates(head, evidence):
    old_count = boundaries(head)
    artifacts = load('reports/P3/final-artifacts.json')
    source = artifacts['source_commit']
    require(re.fullmatch('[0-9a-f]{40}', source) is not None, 'full artifact source SHA required')
    require(git('merge-base', source, head).decode().strip() == source, 'artifact source not ancestor')
    require(not git('diff', '--name-only', RUNTIME, source, '--', 'src', 'rust').strip(),
            'artifact runtime differs from fixed runtime')
    require(git('show', source + ':' + POLICY) == absolute(POLICY).read_bytes(), 'policy differs from artifact source')
    policy_commit = git('log', '-1', '--format=%H', source, '--', POLICY).decode().strip()
    require(re.fullmatch('[0-9a-f]{40}', policy_commit) is not None, 'missing policy commit')
    perf = performance(evidence)
    protection = load(PROTECTION)
    require(protection['status'] == 'PASS' and protection['source_commit'] == source and
            protection['whole_binary_hashes_actual'] == protected_refs() and
            protection['artifacts'] == evidence.binding('reports/P3/final-artifacts.json') and
            protection['performance'] == perf and protection['performance_reused'] == 'YES' and
            protection['performance_rerun'] == 'NO' and
            all(protection[k] is True for k in ('frozen_inputs_unchanged', 'prep_moved_bytes_unchanged',
                                               'artifacts_unchanged', 'no_SQL_or_query', 'no_snapshot_rebuild')),
            'protection receipt differs/incomplete')
    plan = load('reports/P3/final-runplan.json')
    require(plan['source_commit'] == source and plan['artifacts'] == artifacts and
            plan['performance_prerequisite'] == perf and plan['phases'] == ['S02', 'P2', 'gold', 'external'] and
            plan['performance_rerun'] == 'NO' and plan['retries'] == 0 and
            plan['gold55_invocations'] == plan['G42_gold_count'] == 1 and plan['gold55_serves'] == ['D', 'E'],
            'final runplan differs')
    for field in ('frozen_gold', 'frozen_P2'):
        evidence.verify(plan[field])
    require(plan['database'] == load('reports/P3/close-performance.json')['database'], 'FULL identity differs')
    prerequisites = {}
    for phase in plan['phases']:
        path = 'reports/P3/final-' + phase + '.json'
        rec = load(path)
        require(rec['status'] == 'PASS' and rec['phase'] == phase and
                rec['runplan'] == evidence.binding('reports/P3/final-runplan.json') and
                rec['prerequisites'] == prerequisites and
                rec['performance_rerun'] == 'NO' and rec['snapshot_scope'] == 'FULLSNAPSHOT' and
                rec['source_external_cwd'] is True, 'final phase incomplete: ' + phase)
        for field in ('source_commit', 'artifacts', 'frozen_gold', 'frozen_P2', 'database', 'performance_prerequisite'):
            require(rec[field] == plan[field], 'final phase binding differs: ' + phase + '/' + field)
        if phase in ('P2', 'gold'):
            count = 151 if phase == 'P2' else 55
            records = rec['records']
            require(rec['attempted'] == rec['passed'] == count and len(records) == count and
                    len({r['case_id'] for r in records}) == count and
                    rec['timeouts'] == rec['wrong_resolved'] == rec['retries'] == 0 and
                    all(r['passed'] is True and not r['problems'] and not r['rust']['timeout'] for r in records),
                    'final suite counts/failures differ: ' + phase)
            if phase == 'P2':
                require(rec['summary'] == helpers.prior.summarize(records, 151) and
                        rec['summary']['actually_compared'] == 135 and
                        rec['summary']['error_contract_verified'] == 16 and
                        all(r['installed_python_passed'] is True and not r['installed_python']['timeout']
                            for r in records), 'P2 151/135/16 incomplete')
            else:
                require(sum(r['case_id'] == 'G42' for r in records) == 1, 'gold G42 count differs')
        elif phase == 'S02':
            require(rec['retries'] == 0 and rec['rust']['exit'] == 0 and not rec['rust']['timeout'] and
                    rec['profile']['query_invocations'] == 1 and
                    rec['profile']['profile']['fts_skipped_kind_not_indexed'] is True, 'S02 profile not proven')
        else:
            require(rec['retries'] == rec['extra_query_probes'] == 0 and
                    rec['source_external_verified'] is True and rec['gold55_serves'] == ['D', 'E'] and
                    rec['G42_gold_count'] == 1 and
                    rec['FULL_151_receipt'] == evidence.binding('reports/P3/final-P2.json') and
                    rec['FULL_55_receipt'] == evidence.binding('reports/P3/final-gold.json'), 'external incomplete')
        prerequisites[phase] = evidence.binding(path)
    for name in CHECKS:
        check_receipt(name, load('reports/P3/final-check-' + name + '.json'), artifacts, evidence)
    waiver = load('reports/P3/final-F-user-waiver.json')
    require(waiver['status'] == 'WAIVED_BY_USER' and waiver['audit_completion'] == 'NOT_COMPLETED' and
            waiver['SAKURAPOOL_TRACKED_SOURCE_MODIFIED'] == 'UNVERIFIED' and
            waiver['historical_BUILD_ARTIFACTS_WRITTEN'] == 'YES', 'F waiver misrepresented')
    require(REPORT in tree(head), 'final directed parent report missing')
    return {'historical_reports_unchanged': old_count, 'runtime_artifact_source': source,
            'PERF_HARNESS_FIX_SHA': policy_commit, 'runtime_baseline': RUNTIME,
            'protection_receipt': evidence.binding(PROTECTION), 'performance_receipt': perf,
            'F': 'WAIVED_BY_USER', 'Pool_audit': 'NOT_COMPLETED',
            'SAKURAPOOL_TRACKED_SOURCE_MODIFIED': 'UNVERIFIED', 'historical_BUILD_ARTIFACTS_WRITTEN': 'YES',
            'Pool_verified_clean_claim': False, 'performance_reused': 'YES', 'performance_rerun': 'NO',
            'measured_PASS': 900, 'measured_FAIL': 0, 'warmups_PASS': 29, 'warmups_FAIL': 1,
            'FULL151': 'PASS', 'FULL55': 'PASS', 'external_final_J': 'PASS',
            'final_checks': list(CHECKS), 'audit_required': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('protect', 'prepare', 'verify'))
    args = parser.parse_args()
    if args.mode == 'protect':
        protect()
        print(json.dumps({'status': 'PASS', 'path': PROTECTION, 'scope': 'byte protection only'}))
        return
    head = git('rev-parse', 'HEAD').decode().strip()
    evidence = Evidence()
    facts = gates(head, evidence)
    state = {'status': 'READY_FOR_REVIEW', 'P3': 'READY', 'code_review': 'WAITING_REVIEW', 'approval': 'NONE'}
    if args.mode == 'prepare':
        require(OUT not in tree(head), 'binding already committed')
        rows, raw, streams = inventory(head, evidence)
        save(absolute(OUT), {**state, **facts, 'evidence_commit': head, 'main': MAIN,
                            'files': rows, 'raw_inventory': raw, 'embedded_streams': streams,
                            'boundary': 'Direct parent blob closure; only binding added in child, no selfhash. '
                                        'Old ignored raw verified locally, not guaranteed in a fresh clone. '
                                        'New final/close raw byte-exact tracked blobs. Protection hashes are '
                                        'a retained receipt, not a fresh database check in prepare/verify.'})
        print(json.dumps({**state, 'path': OUT, 'evidence_commit': head}))
    else:
        binding = load(OUT)
        parent = binding['evidence_commit']
        require(git('rev-parse', head + '^@').decode().splitlines() == [parent], 'not a single direct binding child')
        require(git('diff', '--name-status', parent, head).decode().splitlines() == ['A\t' + OUT],
                'binding child changed other files')
        rows, raw, streams = inventory(parent, evidence)
        require(binding['files'] == rows and binding['raw_inventory'] == raw and
                binding['embedded_streams'] == streams, 'parent inventory mismatch')
        for field, value in {**state, **facts, 'main': MAIN}.items():
            require(binding[field] == value, 'authoritative binding differs: ' + field)
        require(absolute(OUT).read_bytes() == git('show', head + ':' + OUT), 'binding checkout differs')
        remote = dict(line.split()[::-1] for line in
                      git('ls-remote', 'origin', 'refs/heads/dev', 'refs/heads/main').decode().splitlines())
        require(remote.get('refs/heads/dev') == head and remote.get('refs/heads/main') == MAIN, 'remote mismatch')
        print(json.dumps({**state, **facts, 'HEAD_origin_dev': head, 'main_origin_main': MAIN,
                          'evidence_commit': parent, 'files': len(rows), 'raw': len(raw),
                          'streams': len(streams), 'no_runtime_queries_or_builds': True}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({'status': 'NOT_READY', 'P3': 'NOT_READY', 'code_review': 'WAITING_REVIEW',
                          'approval': 'NONE', 'error': str(exc)}))
        raise SystemExit(1) from exc
