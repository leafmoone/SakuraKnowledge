"""Collect retry1 STOP evidence without any runtime/query/database connection."""
import hashlib
import json
import subprocess
from pathlib import Path

from p3_evidence import save, verify

SOURCE = '9dfa610640eca1e32b6da89f78f3d4aff6062adf'
MAIN = '894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
BASE = '97c3c4969dfb637093e78e7151fc561c91913b78'
ROOT = Path('reports/P3')
OUT = ROOT / 'full-retry1-stop-delivery.json'


def load(name):
    return json.loads((ROOT / (name + '.json')).read_bytes())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args]).decode().strip()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    build = load('full-retry1-build')
    command = load('full-retry1-build-command')
    gold = load('full-retry1-real-acceptance')
    p2 = load('full-retry1-P2-compatibility')
    check(command['exit'] == 0 and command['head'] == SOURCE, 'build command mismatch')
    check(build['attempts'] == build['previous_attempts'] == 1 and build['total_attempts'] == 2,
          'formal attempt accounting changed')
    check(build['automatic_retries'] == 0 and build['readonly_projection_counts'] == {
        'tag_resolutions': 352, 'verified_entity_tag': 0, 'native_wiki_tag': 28, 'capability': '1'},
        'projection or retry mismatch')
    check(gold['status'] == 'PASS' and gold['attempted'] == gold['passed'] == 55
          and gold['wrong_resolved'] == 0 and not gold['preservation_problems'], 'gold not full PASS')
    check(p2['status'] == 'FAIL' and p2['attempted'] == 151 and p2['passed'] == 150
          and not p2['preservation_problems'], 'actual P2 failure changed')
    failures = [r for r in p2['records'] if not r['passed']]
    check(len(failures) == 1 and failures[0]['case_id'] == 'S02', 'unexpected P2 failure set')
    for record in gold['records'] + p2['records']:
        verify(record['rust']['stdout'])
        verify(record['rust']['stderr'])
    manifest = build['manifest']
    check(Path(manifest['path']).stat().st_size == manifest['bytes'] and
          digest(manifest['path']) == manifest['sha256'], 'manifest bytes changed')
    db = build['database']
    check(Path(db['path']).stat().st_size == db['bytes'] and digest(db['path']) == db['sha256'],
          'published DB bytes changed')
    check(git('rev-parse', 'main') == MAIN, 'main changed')
    protected = ('src', 'rust', 'tools/p3_compile_inputs.py', 'tools/record_check.py',
                 'tools/p3_full_candidate_retry1.py', 'tools/parity_cases.py', 'tools/parity_repair_expected.py')
    check(not git('diff', '--name-only', SOURCE, '--', *protected), 'frozen code changed')
    historical = git('ls-tree', '-r', '--name-only', BASE, '--', 'reports/P3').splitlines()
    for path in historical:
        check(git('rev-parse', BASE + ':' + path) == git('rev-parse', 'HEAD:' + path),
              'historical commit changed: ' + path)
    for frozen_name in ('full-retry1-real-gold', 'full-retry1-P2-frozen-expected'):
        frozen = load(frozen_name)
        for ref in frozen['bindings'] + frozen['source_proof']:
            path = Path(ref['path'])
            check(path.stat().st_size == ref['bytes'] and digest(path) == ref['sha256'],
                  'frozen source changed: ' + str(path))
    checks = {}
    for name in ('pytest', 'pytest-integration', 'ruff', 'diff', 'fmt', 'rust-test', 'clippy', 'release'):
        receipt = load('full-retry1-check-' + name)
        checks[name] = {'exit': receipt['exit'], 'status': receipt['status'], 'argv': receipt['argv'],
                        'receipt': str(ROOT / ('full-retry1-check-' + name + '.json'))}
    save(OUT, {'status': 'VERIFIED_STOP_EVIDENCE', 'P3': 'NOT_READY', 'code_review': 'WAITING_REVIEW',
               'approval': 'NONE', 'build_code_sha': SOURCE, 'main': MAIN,
               'build': 'PASS', 'database': db, 'manifest': build['manifest'],
               'previous_attempts': 1, 'retry1_attempts': 1, 'retry1_maximum': 1,
               'total_attempts': 2, 'automatic_retries': 0,
               'FULL_gold': {'status': 'PASS', 'attempted': 55, 'passed': 55, 'wrong_resolved': 0},
               'FULL_P2': p2['summary'], 'blocking_failure': failures[0],
               'FULL_performance': 'NOT_RUN_AFTER_P2_FAILURE',
               'FULL_external_runtime': 'NOT_RUN_AFTER_P2_FAILURE',
               'checks': checks, 'historical_reports_unchanged': len(historical),
               'frozen_source_bindings_unchanged': True, 'database_binary_rehash_unchanged': True,
               'preservation_after_build': build['preservation_after'],
               'scope': 'STOP audit only; byte hashing, no SQL or runtime; no diagnosis/retry/budget change',
               'working_tree': git('status', '--porcelain')})
    print(json.dumps({'status': 'VERIFIED_STOP_EVIDENCE', 'P3': 'NOT_READY', 'database': db,
                      'P2': p2['summary'], 'checks': checks}))


if __name__ == '__main__':
    main()
