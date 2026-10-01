"""Verify frozen close performance bytes under the formal-only policy; never run queries.

The database binding is compared, not opened or rehashed. All other receipt and
freeze references are verified, including embedded artifact process raw streams.
An invalid proof raises before a new receipt is created. Existing output is never
replaced. Run only after review authorizes this offline verification.
"""
import hashlib
import json
import math
from pathlib import Path

import p3_measure_resolver as policy
import p3_retry1_acceptance as prior
from p3_evidence import save, verify

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/P3'
OLD = REPORTS / 'close-performance.json'
OUT = REPORTS / 'final-performance-recomputed.json'
POLICY = ROOT / 'tools/p3_measure_resolver.py'
RUNTIME = '9d7bd507c62f20ca4d41b26ba7df55ae4e6d8102'
IDS = ('G01', 'G21', 'G36', 'G37', 'G42', 'G43', 'G44', 'G45',
       'G51', 'G52', 'G53', 'G54', 'G55', 'S02', 'S18')
MODES = ('reused_connection', 'independent_cli')
DB = ROOT / 'build/p3-full-authorized-retry1/knowledge.sqlite'
DB_SHA = '61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9'
ARTIFACT = ROOT / 'dist/p3-close-9d7bd507/source/rust/target/release'
BINARY = ARTIFACT / 'sknow-rs.exe'
REUSED = ARTIFACT / 'examples/bench_resolver.exe'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def absolute(path):
    path = Path(path)
    return (path if path.is_absolute() else ROOT / path).resolve()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def same(left, right):
    # JSON booleans must not compare equal to integers in request/value proofs.
    return canonical(left) == canonical(right)


def decode(data):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key: ' + key)
            value[key] = item
        return value

    def constant(value):
        raise ValueError('nonfinite JSON constant: ' + value)

    return json.loads(data.decode('utf-8', errors='strict'),
                      object_pairs_hook=pairs, parse_constant=constant)


def jsonl(data):
    lines = data.decode('utf-8', errors='strict').splitlines()
    require(len(lines) == 465, 'JSONL must contain exactly 465 rows')
    return [decode(line.encode('utf-8')) for line in lines]


class Evidence:
    """Read/hash each distinct path once; check every reference against that hash."""

    def __init__(self):
        self.cache = {}
        self.restored = set()

    def read(self, path):
        path = absolute(path)
        if path not in self.cache:
            data = path.read_bytes()
            self.cache[path] = (data, hashlib.sha256(data).hexdigest())
        return self.cache[path]

    def binding(self, path):
        data, digest = self.read(path)
        return {'path': str(absolute(path)), 'bytes': len(data), 'sha256': digest}

    def verified(self, ref, *, restoration=False):
        require(type(ref['bytes']) is int and ref['bytes'] >= 0, 'invalid byte count')
        path = absolute(ref['path'])
        if path not in self.cache and not restoration:
            # Use the shared raw verifier, but memoize its digest instead of hashing
            # the same retained stdout hundreds of times.
            data = verify({**ref, 'path': str(path)})
            self.cache[path] = (data, ref['sha256'])
        data, digest = self.read(path)
        if restoration and path == absolute(prior.__file__):
            restored = data.replace(
                b'  # noqa: BLE001 - retain any case failure in the evidence receipt', b'')
            restored = restored.replace(b"raise TypeError('invalid frozen full JSON')",
                                        b"raise ValueError('invalid frozen full JSON')")
            require(len(restored) == ref['bytes'] and
                    hashlib.sha256(restored).hexdigest() == ref['sha256'],
                    'acceptance change exceeded authorized lint restoration')
            self.restored.add(str(path))
        else:
            require(len(data) == ref['bytes'] and digest == ref['sha256'],
                    'changed byte binding: ' + str(path))
        return data

    def walk(self, value, database, *, restoration=False):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys():
                if absolute(value['path']) == absolute(database['path']):
                    require(same(value, database), 'database binding differs')
                else:
                    self.verified(value, restoration=restoration)
            for child in value.values():
                self.walk(child, database, restoration=restoration)
        elif isinstance(value, list):
            for child in value:
                self.walk(child, database, restoration=restoration)


def frozen_inputs(old, evidence):
    database = old['database']
    require(absolute(database['path']) == absolute(DB) and
            database['bytes'] == 21718736896 and database['sha256'] == DB_SHA,
            'wrong frozen FULL database binding')
    frozen = []
    for field, path, count, key in (('frozen_gold', prior.GOLD, 55, 'id'),
                                    ('frozen_P2', prior.P2, 151, 'case_id')):
        ref = old[field]
        require(absolute(ref['path']) == absolute(path), 'wrong freeze path: ' + field)
        report = decode(evidence.verified(ref))
        require(report['status'] == 'PASS' and report['frozen_before_runtime'] is True and
                report['source_commit'] == prior.SOURCE, 'invalid pre-runtime freeze')
        require(same(report['database'], database) and same(report['db'], database),
                'freeze database mismatch')
        evidence.walk(report, database, restoration=True)
        cases = report['cases']
        require(len(cases) == count and len({row[key] for row in cases}) == count,
                'frozen case count or uniqueness changed')
        for row in cases:
            require(row['passed'] is True and not row['problems'], 'failed frozen case')
            expected_key = 'oracle_json' if key == 'id' else 'expected_json'
            if key == 'id' or row['mode'] not in prior.ERROR_MODES:
                value = decode(evidence.verified(row[expected_key]))
                require(isinstance(value, dict), 'frozen full JSON must be an object')
                if key == 'id':
                    require(not prior.source_checks(value, row['expected']),
                            'frozen gold source assertions differ')
        if key == 'case_id':
            fields = ('case_id', 'op', 'args', 'historical_expect', 'mode')
            require(same([prior.p2_case_data(row) for row in prior.CASES],
                         [{name: row[name] for name in fields} for row in cases]),
                    'historical P2 workload changed')
        frozen.append({row[key]: row for row in cases})
    return frozen


def workload(gold, p2, evidence):
    requests, expected, bindings = [], {}, []
    for ident in IDS:
        row = gold[ident] if ident.startswith('G') else p2[ident]
        key = 'oracle_json' if ident.startswith('G') else 'expected_json'
        request = (dict(row['input'], id=ident) if ident.startswith('G') else
                   dict(row['args'], id=ident, op='search'))
        if not ident.startswith('G'):
            require(row['op'] == 'search' and row['mode'] == 'value', 'wrong P2 representative')
        requests.append(request)
        expected[ident] = decode(evidence.verified(row[key]))
        bindings.append({'case_id': ident, 'expected_key': key,
                         'reference': evidence.binding(row[key]['path'])})
    return ([dict(row, round=round_, warmup=round_ == -1)
             for round_ in range(-1, 30) for row in requests], expected, bindings)


def commands(binary, database, request):
    if request.get('op') != 'search':
        return prior.gold_command(binary, database, request)
    # rust_argv is a pure argv helper with a historical module-level DB setting.
    previous = prior.parity.DB
    try:
        prior.parity.DB = database
        return [str(binary)] + prior.parity.rust_argv(
            'search', {key: request[key] for key in ('query', 'topk', 'kind', 'namespace')
                       if key in request})
    finally:
        prior.parity.DB = previous


def finite_elapsed(value, limit):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= limit


def process_checks(rec, argv, timeout, evidence, *, batch=False):
    require(same(rec['argv'], argv), 'recorded argv differs from frozen command')
    require(type(rec['exit']) is int and rec['exit'] == 0 and
            rec['outer_timeout'] is False and rec['timeout'] is False and
            rec['outer_timeout_s'] == timeout and rec['inner_budget_s'] == 5 and
            rec['attempted'] == 1 and finite_elapsed(rec['elapsed_s'], timeout),
            'process exit, timeout, budget or timing differs')
    require(not any(key in rec for key in ('exception', 'decode_error', 'invalid_json')),
            'recorded process error')
    require(evidence.verified(rec['stderr']) == b'', 'nonempty process stderr')
    if not batch:
        require(rec['succeeded'] == 1 and rec['other_error'] == 0, 'CLI success counters differ')
    return evidence.verified(rec['stdout'])


def verify_records(old, requests, expected, evidence, binary, reused, database):
    require(old['workloads'] == list(IDS) and old['samples'] == 30 and
            old['measured'] == 900 and old['warmups'] == 30 and old['retries'] == 0,
            'fixed workload/sample counts changed')
    require(old['protocol'] == {
        'inner_s': 5, 'cli_outer_s': 15, 'reused_batch_outer_s': 600,
        'cache': 'not claimed cold',
        'percentile': 'nearest rank on successful samples; failures/attempts explicit',
        'rss': 'NOT_RUN'}, 'fixed performance protocol changed')
    process = old['reused_process']
    responses = jsonl(process_checks(process, [str(reused), str(database)], 600,
                                     evidence, batch=True))
    require(same(jsonl(evidence.verified(process['input'])), requests),
            'input JSONL fields/order differ from declared requests')
    records = old['records']
    require(len(records) == 930, 'expected exactly 465 records per mode')
    verified_rows = []
    for mode_index, mode in enumerate(MODES):
        for index, request in enumerate(requests):
            row = records[mode_index * 465 + index]
            identity = {'mode': mode, 'case_id': request['id'], 'round': request['round'],
                        'warmup': request['warmup']}
            require(same({key: row[key] for key in identity}, identity),
                    'record identity/stable order differs')
            if mode_index == 0:
                response = responses[index]
                require(response['case_id'] == request['id'] and
                        type(row['process_row']) is int and row['process_row'] == index and
                        same(row['elapsed_s'], response['elapsed_s']),
                        'response order/index/timing differs')
                if index == 4:
                    require(same(response, {'case_id': 'G42', 'elapsed_s': 5.0000352,
                                            'error': 'query_budget_exceeded'}),
                            'original warmup failure diagnostic changed')
                else:
                    require(set(response) == {'case_id', 'elapsed_s', 'value'},
                            'unexpected reused response fields/error')
                success = ('value' in response and same(response['value'], expected[request['id']])
                           and finite_elapsed(response['elapsed_s'], 5))
            else:
                rec = row['rust']
                value = decode(process_checks(rec, commands(binary, database, request),
                                              15, evidence))
                require(same(row['elapsed_s'], rec['elapsed_s']), 'CLI record timing differs')
                success = prior.usable(rec, value) and same(value, expected[request['id']])
            require(type(row['success']) is bool and row['success'] == success,
                    'recorded success differs from independent full JSON comparison')
            require(success or (mode_index == 0 and index == 4),
                    'unexpected formal/warmup value or timing failure')
            verified_rows.append({**row, 'success': bool(success)})
    outcome = policy.evaluate(verified_rows, list(IDS), samples=30)
    require(outcome['status'] == 'PASS' and outcome['structure_errors'] == [] and
            outcome['formal_counts'] == {'attempted': 900, 'success': 900, 'failed': 0} and
            outcome['warmup_counts'] == {'attempted': 30, 'success': 29, 'failed': 1},
            'formal-only policy evaluation differs')
    summary = [{key: value for key, value in row.items() if key != 'failed'}
               for row in outcome['summary']]
    require(same(summary, old['summary']) and len(summary) == 30,
            'old nearest-rank summary differs from recomputed formal samples')
    require(old['status'] == 'FAIL' and not all(row['success'] for row in verified_rows),
            'original overall FAIL must be retained')
    outcome.pop('records')
    outcome['warmup_failure'] = {'record': records[4], 'response': responses[4],
                                 'stdout': process['stdout'], 'original_status': old['status']}
    return outcome


def recompute():
    evidence = Evidence()
    old_binding = evidence.binding(OLD)
    policy_binding = evidence.binding(POLICY)
    old = decode(evidence.read(OLD)[0])
    require(old['source_commit'] == RUNTIME and old['phase'] == 'performance' and
            old['snapshot_scope'] == 'FULLSNAPSHOT' and old['source_external_cwd'] is True,
            'wrong original runtime/performance receipt')
    gold, p2 = frozen_inputs(old, evidence)
    evidence.walk(old, old['database'])
    artifacts = old['artifacts']
    require(artifacts['status'] == 'PASS' and artifacts['source_commit'] == RUNTIME,
            'old runtime artifact provenance differs')
    for field, path in (('binary', BINARY), ('reused_binary', REUSED)):
        require(absolute(artifacts[field]['path']) == absolute(path), 'wrong runtime binary')
    requests, expected, expected_bindings = workload(gold, p2, evidence)
    outcome = verify_records(old, requests, expected, evidence,
                             artifacts['binary']['path'], artifacts['reused_binary']['path'],
                             old['database']['path'])
    dependencies = [Path(__file__), Path(policy.__file__), Path(prior.__file__),
                    Path(prior.parity.__file__), ROOT / 'tools/p3_evidence.py',
                    ROOT / 'tools/p3_accept_resolver.py', ROOT / 'tools/p3_resolver_oracle.py']
    return {**outcome, 'old_receipt': old_binding, 'policy': policy_binding,
            'performance_rerun': 'NO', 'original_status': old['status'], 'retries': 0,
            'source_commit': RUNTIME, 'database': old['database'],
            'database_verification': 'frozen binding comparison only; no open/read/hash/SQL',
            'frozen_gold': evidence.binding(prior.GOLD), 'frozen_P2': evidence.binding(prior.P2),
            'expected_bindings': expected_bindings,
            'verifier_bindings': [evidence.binding(path) for path in dependencies],
            'evidence_checks': {'unique_files_verified': len(evidence.cache),
                                'all_non_database_references_verified': True,
                                'lint_original_restoration': sorted(evidence.restored),
                                'input_JSONL_rows': 465, 'response_JSONL_rows': 465,
                                'CLI_processes': 465, 'formal_full_values_compared': 900,
                                'old_summary_rows_compared': 30},
            'protocol': {'inner_s': 5, 'cli_outer_s': 15, 'reused_batch_outer_s': 600,
                         'warmups': 'diagnostic only; excluded from formal acceptance/percentiles',
                         'percentile': 'nearest rank on successful formal samples',
                         'cache': 'not claimed cold', 'rss': 'NOT_RUN'}}


def main():
    if OUT.exists() or OUT.is_symlink():
        raise FileExistsError(OUT)
    receipt = recompute()
    save(OUT, receipt)  # Exclusive creation also rejects a concurrent verifier's output.
    print(json.dumps({key: receipt[key] for key in
                      ('status', 'formal_counts', 'warmup_counts', 'performance_rerun')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
