"""Independent freeze and formal retry1 acceptance, only after normal publication.

Both independent freezes must PASS before any Rust acceptance. No build, network,
staging inspection, warmup, repair or retry is performed. Unknown historical P2
summary differences fail closed. Each child has a 15s host deadline and runtime
operations retain their 5s budget. Raw bytes are retained once by content hash.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))

import check_parity as parity
from p3_evidence import save, store, verify
from p3_resolver_oracle import result as oracle
from parity_policy import classify, summarize
from parity_repair_expected import CASES

SOURCE = '9dfa610640eca1e32b6da89f78f3d4aff6062adf'
REPORTS = ROOT / 'reports/P3'
# Relative references are consumed by the existing evidence/binding tools.
RAW = Path('reports/P3/raw')
DB = ROOT / 'build/p3-full-authorized-retry1/knowledge.sqlite'
OLD_GOLD = REPORTS / 'review-cf807-real-gold.json'
GOLD = REPORTS / 'full-retry1-real-gold.json'
P2 = REPORTS / 'full-retry1-P2-frozen-expected.json'
CONTRACT = ROOT / 'docs/p3-full-coverage-contract.md'
POLICY = {'outer_timeout_s': 15, 'inner_budget_s': 5, 'retries': 0,
          'warmup_rounds': 0, 'failure_action': 'STOP; no retry/refreeze/relabel'}
BINDINGS = [OLD_GOLD, CONTRACT, Path(__file__),
            ROOT / 'tools/p3_resolver_oracle.py', ROOT / 'tools/check_parity.py',
            ROOT / 'tools/parity_policy.py', ROOT / 'tools/parity_cases.py',
            ROOT / 'tools/parity_repair_expected.py']
ERROR_MODES = ('error', 'cli', 'runtime_error')


def load(path):
    return json.loads(Path(path).read_bytes().decode('utf-8', errors='strict'))


def raw_json(value):
    return store(json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                            allow_nan=False).encode('utf-8'), root=RAW)


def frozen_value(ref):
    return json.loads(verify(ref).decode('utf-8', errors='strict'))


def binding(path):
    path = Path(path)
    return {'path': str(path), 'sha256': parity.sha256(path), 'bytes': path.stat().st_size}


def check_binding(ref):
    if binding(ref['path']) != ref:
        raise ValueError('changed frozen input: ' + ref['path'])


def published(db):
    db = Path(db).resolve()
    if db != DB.resolve() or not db.is_file():
        raise ValueError('only the normally published retry1 knowledge.sqlite is authorized')
    if any(Path(str(db) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('published database has live SQLite sidecars; STOP')
    return db


def connect(db):
    conn = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


def capture(argv):
    """Use parity's decoder, but persist bytes once, not base64/text/value copies."""
    start = time.perf_counter()
    try:
        rec = parity.capture(argv, timeout_s=15)
    except Exception as exc:  # noqa: BLE001 - retain any case failure in the evidence receipt
        rec = {'argv': argv, 'exit': None, 'elapsed_s': time.perf_counter() - start,
               'outer_timeout': False, 'timeout': False, 'attempted': 1,
               'succeeded': 0, 'other_error': 1,
               'exception': {'type': type(exc).__name__, 'message': str(exc)}}
        for stream in ('stdout', 'stderr'):
            rec[stream + '_base64'] = ''
    value = rec.pop('value', None)
    for stream in ('stdout', 'stderr'):
        data = base64.b64decode(rec.pop(stream + '_base64'), validate=True)
        rec.pop(stream, None)
        rec.pop(stream + '_sha256', None)
        rec.pop(stream + '_bytes', None)
        rec[stream] = store(data, root=RAW)
    rec.update(outer_timeout_s=15, inner_budget_s=5)
    return rec, value


def usable(rec, value):
    warnings = value.get('warnings', []) if isinstance(value, dict) else None
    return (rec['exit'] == 0 and not rec.get('timeout') and not rec.get('outer_timeout') and
            not rec.get('exception') and not rec.get('decode_error') and
            rec['stderr']['bytes'] == 0 and isinstance(value, dict) and
            isinstance(warnings, list) and not any(w in warnings for w in
                    ('response_budget_truncated', 'search_document_scan_limit')))


def entry_key(row):
    return {k: row[k] for k in ('kind', 'namespace', 'value')}


def identities(conn, query, *, kind=None, namespace=None, exact=False):
    """Indexed value and alias lookups; no LIMIT until AFTER complete identities."""
    ids = {r['id']: dict(r) for r in conn.execute(
        'SELECT * FROM entries INDEXED BY entry_value WHERE value=?', (query,))}
    if not exact:
        for r in conn.execute(
                "SELECT e.* FROM aliases a INDEXED BY alias_exact JOIN entries e ON e.id=a.entry_id "
                "WHERE a.text=? AND a.status='source_backed'", (query,)):
            ids[r['id']] = dict(r)
    output = []
    for row in ids.values():
        if (row['conflicted'] or (kind is not None and row['kind'] != kind) or
                (namespace is not None and row['namespace'] != namespace)):
            continue
        proofs = [dict(r) for r in conn.execute(
            "SELECT source_id,evidence_id,status FROM entry_evidence INDEXED BY entry_evidence_entry "
            "WHERE entry_id=? AND status='source_backed' ORDER BY source_id,evidence_id", (row['id'],))]
        if not proofs:
            continue
        aliases = [] if exact else [dict(r) for r in conn.execute(
            "SELECT text,source_id,evidence_id,status FROM aliases INDEXED BY alias_entry "
            "WHERE entry_id=? AND text=? AND status='source_backed' ORDER BY source_id,evidence_id",
            (row['id'], query))]
        output.append({'entry_id': row['id'], 'entry_key': entry_key(row),
                       'identity_evidence': proofs, 'matching_alias_evidence': aliases})
    return sorted(output, key=lambda r: tuple(r['entry_key'][k] for k in ('kind', 'namespace', 'value')))


def source_checks(value, expected):
    problems = []
    if not isinstance(value, dict):
        return [{'kind': 'missing_source_value'}]
    for key in ('status', 'tag_key', 'source_key', 'matched_by', 'canonical_status',
                'candidates_truncated', 'unresolved_reasons'):
        if key in expected and value.get(key) != expected[key]:
            problems.append({'kind': 'source_assertion', 'field': key,
                             'want': expected[key], 'got': value.get(key)})
    if 'candidates' in expected:
        got = [c.get('entry_key', c.get('tag_key')) for c in value.get('candidates', [])]
        if got != expected['candidates']:
            problems.append({'kind': 'source_candidates', 'want': expected['candidates'], 'got': got})
    if expected.get('description') and not value.get('descriptions'):
        problems.append({'kind': 'source_description_missing'})
    if expected.get('descriptions_empty') and value.get('descriptions') != []:
        problems.append({'kind': 'source_description_not_empty'})
    for assertion in expected.get('evidence_assertions', []):
        if not any(all(ref.get(k) == v for k, v in assertion.items())
                   for ref in value.get('evidence_chain', [])):
            problems.append({'kind': 'source_proof_missing', 'assertion': assertion})
    return problems


def entity_expectation(conn, case):
    expected = copy.deepcopy(case['expected'])
    if expected['status'] not in ('entity_found_tag_unmapped', 'entity_ambiguous'):
        return expected, None
    matches = identities(conn, case['query'], **{k: case[k] for k in ('kind', 'namespace', 'exact') if k in case})
    if not matches:
        raise ValueError(case['id'] + ': original source identity disappeared')
    keys = [m['entry_key'] for m in matches]
    if any(k not in keys for k in expected.get('candidates', [])):
        raise ValueError(case['id'] + ': historical candidate disappeared')
    for match in matches:
        if conn.execute("SELECT 1 FROM links INDEXED BY link_src WHERE src=? AND relation='entity_tag' "
                        "AND verification_status='verified' LIMIT 1", (match['entry_id'],)).fetchone():
            raise ValueError(case['id'] + ': unexpected verified entity mapping')
    limit = case.get('limit', 20)
    expected.update(tag_key=None, descriptions_empty=True, canonical_status='unknown')
    if len(keys) > 1:
        expected.update(status='entity_ambiguous', source_key=None,
                        candidates=keys[:limit], candidates_truncated=len(keys) > limit)
    else:
        if case['expected']['status'] == 'entity_ambiguous':
            raise ValueError(case['id'] + ': unsafe identity contraction')
        expected.update(status='entity_found_tag_unmapped', source_key=keys[0],
                        candidates=[], candidates_truncated=False)
    return expected, {'rule': 'complete source-indexed typed identity expansion only',
                       'contract_anchor': 'lines 8-13,40-48', 'original_expected': case['expected'],
                       'full_identity_count': len(keys), 'complete_identities': matches,
                       'added_keys': [k for k in keys if k not in case['expected'].get('candidates', [])]}


def source_inventory(conn):
    return [{'source_id': r['source_id'], 'metadata': json.loads(r['metadata'])}
            for r in conn.execute('SELECT source_id,metadata FROM sources ORDER BY source_id')]


def native_categories():
    acquisition = load(REPORTS / 'native-acquisition.json')
    record = next(r for r in acquisition['records'] if r['role'] == 'tags_and_wiki')
    path = ROOT / record['raw_path']
    if parity.sha256(path) != record['sha256']:
        raise ValueError('native raw source mutated')
    return {r['name']: r['category'] for r in load(path)}, binding(path)


def base_report(db, kind):
    refs = [binding(p) for p in BINDINGS]
    database = binding(db)
    return {'kind': kind, 'status': 'STOP', 'policy': POLICY, 'db': database,
            'database': database, 'source_commit': SOURCE, 'bindings': refs,
            'source_proof': list(refs), 'frozen_before_runtime': True,
            'cases': [], 'created_ns': time.time_ns(), 'problems': []}


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, report)
    return binding(path)


def before_freeze():
    for phase in ('gold', 'P2'):
        if (REPORTS / ('full-retry1-' + phase + '-accept-start.json')).exists():
            raise ValueError('Rust acceptance already started; no refreeze')
    for name in ('real-acceptance', 'P2-compatibility'):
        if (REPORTS / ('full-retry1-' + name + '.json')).exists():
            raise ValueError('formal acceptance already exists; no refreeze')


def gold_row(case):
    # Existing performance/artifact tools consume query/options at the top level.
    inputs = {k: copy.deepcopy(v) for k, v in case.items() if k != 'expected'}
    return {**inputs, 'input': inputs, 'original_expected': copy.deepcopy(case['expected']),
            'problems': []}


def freeze_gold(db):
    before_freeze()
    if GOLD.exists():
        raise FileExistsError(GOLD)
    report = base_report(db, 'independent full55 source assertions plus frozen oracle')
    old = load(OLD_GOLD)
    if len(old['cases']) != 55 or len({c['id'] for c in old['cases']}) != 55:
        raise ValueError('historical gold must have exactly 55 unique IDs')
    categories, native_ref = native_categories()
    report.update(native_raw=native_ref, limitations=old['limitations'])
    report['source_proof'].append(native_ref)
    conn = connect(db)
    try:
        report['source_inventory'] = raw_json(source_inventory(conn))
        report['source_proof'].append(report['source_inventory'])
        for case in old['cases']:
            row = gold_row(case)
            try:
                expected, delta = entity_expectation(conn, case)
                row.update(expected=expected, source_delta=delta)
                if expected.get('tag_key'):
                    name = expected['tag_key']['value']
                    if name not in categories:
                        raise ValueError('native target absent from raw source')
                    row['native_category'] = categories[name]
                    if case.get('category') is not None and case['category'] != categories[name]:
                        raise ValueError('resolved target conflicts with raw native category')
                cmd = [sys.executable, str(Path(__file__).resolve()), '--oracle-child',
                       str(db), json.dumps(row['input'], ensure_ascii=True)]
                rec, value = capture(cmd)
                row['oracle_process'] = rec
                if not usable(rec, value):
                    row['problems'].append({'kind': 'oracle_process_failed'})
                else:
                    row['oracle_json'] = rec['stdout']
                    row['problems'].extend(source_checks(value, expected))
                    if case.get('category') is not None:
                        row['category_source_anchor'] = native_ref
            except Exception as exc:  # noqa: BLE001 - retain any case failure in the evidence receipt
                row['problems'].append({'kind': type(exc).__name__, 'message': str(exc)})
            row['passed'] = not row['problems']
            report['cases'].append(row)
        report['status'] = 'PASS' if all(c['passed'] for c in report['cases']) else 'STOP'
    finally:
        conn.close()
    write_report(GOLD, report)
    return report['status'] == 'PASS'


def p2_case_data(case):
    cid, op, args, expect, mode = case
    return {'case_id': cid, 'op': op, 'args': args, 'historical_expect': expect, 'mode': mode}


def p2_data_deltas(conn, op, args, value, expect):
    """Fail closed: summary differences require field-specific SQL proof."""
    differences = parity.check_expect(value, expect)
    if not differences:
        return {'status': 'HISTORICAL_SUMMARY_UNCHANGED', 'differences': [], 'anchors': []}
    anchors, allowed = [], set()
    if op == 'inspect':
        meta = dict(conn.execute("SELECT key,value FROM build_meta WHERE key IN ('snapshot','p3_resolver_version')"))
        if meta.get('p3_resolver_version') == '1':
            facts = {'snapshot': meta.get('snapshot'),
                     'page_count': conn.execute('PRAGMA page_count').fetchone()[0],
                     'freelist_count': conn.execute('PRAGMA freelist_count').fetchone()[0]}
            allowed.update(k for k, v in facts.items() if value.get(k) == v)
            anchors.append({'kind': 'capability/new snapshot physical counts', 'facts': facts,
                            'contract_anchor': 'lines 32-34'})
    else:
        query = value.get('parsed_subject', args.get('query', args.get('value')))
        matches = identities(conn, query, kind=args.get('kind'), namespace=args.get('namespace'),
                             exact=op in ('lookup_key', 'related')) if isinstance(query, str) else []
        native = [m for m in matches if m['entry_key']['namespace'] == 'danbooru.tag']
        actual = [c.get('entry_key') for c in value.get('candidates', [])]
        native_actual = [k for k in actual if isinstance(k, dict) and k.get('namespace') == 'danbooru.tag']
        if native and all(k in [m['entry_key'] for m in native] for k in native_actual):
            n = len(actual)
            old_n = expect.get('n_candidates')
            if (op in ('lookup', 'lookup_key', 'ask') and old_n is not None and
                    n == old_n + len(native_actual) and len(native_actual) > 0):
                allowed.add('n_candidates')
                old_status, status = expect.get('status'), value.get('status')
                if ((old_status in ('found', 'not_found') and status == 'ambiguous' and n > 1) or
                    (old_status in ('entity_found_tag_unmapped', 'unknown') and
                     status == 'entity_ambiguous' and n > 1)):
                    allowed.add('status')
                if n > 1 and value.get('entry_key') is None and value.get('matched_by') is None:
                    allowed.update(('entry_key', 'matched_by'))
                if actual and actual[0] in native_actual:
                    allowed.update(('first_candidate_key', 'first_candidate_matched_by'))
                anchors.append({'kind': 'additional typed native identities', 'complete_matches': matches,
                                'native_candidates': native_actual, 'contract_anchor': 'lines 35-39'})
        key = value.get('entry_key')
        if key and 'n_relations' in expect:
            selected = [m for m in matches if m['entry_key'] == key]
            if len(selected) == 1:
                links = [dict(r) for r in conn.execute(
                    "SELECT l.source_id,l.evidence_id,l.payload,e.kind,e.namespace,e.value "
                    "FROM links l INDEXED BY link_src JOIN entries e ON e.id=l.dst "
                    "WHERE l.src=? AND l.relation='wiki_tag' AND l.verification_status IN ('native','verified') "
                    "AND e.namespace='danbooru.tag' ORDER BY l.id", (selected[0]['entry_id'],))]
                new_links = [r for r in value.get('relations', []) if r.get('relation') == 'wiki_tag']
                if links and len(value.get('relations', [])) == expect['n_relations'] + len(new_links) and new_links:
                    allowed.add('n_relations')
                    anchors.append({'kind': 'explicit nativeWiki association', 'links': links,
                                    'contract_anchor': 'lines 37-39'})
    unexplained = [d for d in differences if d.get('path') not in allowed]
    return {'status': 'UNEXPLAINED_FAIL' if unexplained else 'PREDECLARED_DATA_DIFFERENCE',
            'differences': differences, 'unexplained': unexplained, 'anchors': anchors}


def freeze_p2(db):
    before_freeze()
    if P2.exists():
        raise FileExistsError(P2)
    report = base_report(db, 'independent Python P2 full values; historical inputs unchanged')
    parity.DB = db
    conn = connect(db)
    try:
        report['source_inventory'] = raw_json(source_inventory(conn))
        report['source_proof'].append(report['source_inventory'])
        values = sum(c[4] not in ERROR_MODES for c in CASES)
        if len(CASES) != 151 or values != 135:
            raise ValueError('immutable P2 denominators must be 135 values + 16 errors')
        for case in CASES:
            row = p2_case_data(case)
            row['problems'] = []
            if row['mode'] in ERROR_MODES:
                row.update(passed=True, expectation_origin='historical exact error contract')
            else:
                rec, value = capture(parity.python_cmd(row['op'], row['args']))
                row.update(python=rec, expectation_origin='independent Python before any Rust process')
                if not usable(rec, value):
                    row['problems'].append({'kind': 'python_freeze_failed'})
                else:
                    row['expected_json'] = rec['stdout']
                    try:
                        row['historical_behavior'] = p2_data_deltas(conn, row['op'], row['args'], value,
                                                                   row['historical_expect'])
                        if row['historical_behavior']['status'] == 'UNEXPLAINED_FAIL':
                            row['problems'].append({'kind': 'non_predeclared_data_difference'})
                    except Exception as exc:  # noqa: BLE001 - retain any case failure in the evidence receipt
                        row['problems'].append({'kind': type(exc).__name__, 'message': str(exc)})
                row['passed'] = not row['problems']
            report['cases'].append(row)
        report.update(value_denominator=135, error_denominator=16)
        report['status'] = 'PASS' if all(c['passed'] for c in report['cases']) else 'STOP'
    finally:
        conn.close()
    write_report(P2, report)
    return report['status'] == 'PASS'


def gold_command(binary, db, case):
    cmd = [str(binary), 'resolve-tag', str(db), case['query']]
    for name in ('kind', 'namespace', 'category', 'limit'):
        if case.get(name) is not None:
            cmd.extend(['--' + name, str(case[name])])
    if case.get('exact'):
        cmd.append('--key')
    return cmd + ['--target-namespace', 'danbooru.tag']


def validate_frozen(report, count, db):
    if (report['status'] != 'PASS' or report['frozen_before_runtime'] is not True or
            report['source_commit'] != SOURCE):
        raise ValueError('frozen expectation STOP or wrong source')
    check_binding(report['db'])
    if Path(report['db']['path']).resolve() != Path(db).resolve() or report['database'] != report['db']:
        raise ValueError('frozen DB path mismatch')
    for ref in report['bindings'] + report['source_proof']:
        check_binding(ref)
    cases = report['cases']
    ids = [c.get('id', c.get('case_id')) for c in cases]
    if len(cases) != count or len(set(ids)) != count or None in ids:
        raise ValueError('incomplete frozen cases')
    for case in cases:
        if case.get('passed') is not True or case.get('problems'):
            raise ValueError('failed frozen case')
        if count == 55:
            ref = case['oracle_json']
        elif case['mode'] not in ERROR_MODES:
            ref = case['expected_json']
        else:
            if not case['historical_expect']:
                raise ValueError('missing historical error contract')
            continue
        if not isinstance(frozen_value(ref), dict):
            raise TypeError('invalid frozen full JSON')


def acceptance_gate(db, binary, phase):
    for path, count in ((GOLD, 55), (P2, 151)):
        validate_frozen(load(path), count, db)
    p2 = load(P2)
    if [p2_case_data(c) for c in CASES] != [
            {k: r[k] for k in ('case_id', 'op', 'args', 'historical_expect', 'mode')} for r in p2['cases']]:
        raise ValueError('historical P2 case inputs changed')
    gold = load(GOLD)
    if [{**r['input'], 'expected': r['original_expected']} for r in gold['cases']] != load(OLD_GOLD)['cases']:
        raise ValueError('historical 55 case inputs or expectations changed')
    if any(any(r.get(k) != v for k, v in r['input'].items()) for r in gold['cases']):
        raise ValueError('gold top-level query/options differ from frozen input')
    marker = REPORTS / ('full-retry1-' + phase + '-accept-start.json')
    proof = {'kind': 'all independent expectations frozen before Rust acceptance', 'created_ns': time.time_ns(),
             'gold': binding(GOLD), 'P2': binding(P2), 'db': binding(db),
             'binary': binding(binary), 'policy': POLICY}
    if max(gold['created_ns'], p2['created_ns']) >= proof['created_ns']:
        raise ValueError('freeze does not precede acceptance')
    proof['frozen_marker_raw'] = raw_json(proof)
    write_report(marker, proof)
    return proof


def compare_gold(rec, value, row):
    problems = []
    if not usable(rec, value):
        problems.append({'kind': 'rust_process_failed'})
    else:
        problems.extend(parity.diff(frozen_value(row['oracle_json']), value))
        problems.extend(source_checks(value, row['expected']))
    wrong = (isinstance(value, dict) and value.get('status') == 'resolved' and
             (row['expected']['status'] != 'resolved' or value.get('tag_key') != row['expected'].get('tag_key')))
    return {'passed': not problems, 'problems': problems, 'wrong_resolved': bool(wrong),
            'actual_status': value.get('status') if isinstance(value, dict) else None}


def as_parity(rec, value):
    out = {k: v for k, v in rec.items() if k not in ('stdout', 'stderr')}
    if value is not None:
        out['value'] = value
    return out


def compare_p2(rec, value, row):
    mode, expect = row['mode'], row['historical_expect']
    rs = as_parity(rec, value)
    if mode not in ('cli', 'runtime_error'):
        if mode == 'error':
            py = {'exit': 2, 'error': {'message': expect['error']}, 'timeout': False}
            result = classify(py, rs, mode, expect, parity.diff, parity.check_expect)
        else:
            py = {'exit': 0, 'value': frozen_value(row['expected_json']), 'timeout': False}
            result = classify(py, rs, 'value', {}, parity.diff, parity.check_expect)
        if rec.get('decode_error') or rec.get('exception') or rec['stdout']['bytes'] and mode == 'error':
            result.update(status='EXPECTED_ERROR_FAIL' if mode == 'error' else 'MISMATCH', passed=False)
            result['problems'].append({'kind': 'invalid_process_stream'})
        if mode != 'error' and rec['stderr']['bytes']:
            result.update(status='MISMATCH', passed=False)
            result['problems'].append({'kind': 'stderr_not_empty'})
    else:
        problems = []
        error = rec.get('error')
        if rec.get('timeout') or rec['exit'] != expect['exit_rs']:
            problems.append({'kind': 'exit_or_timeout', 'side': 'rs'})
        if rec['stdout']['bytes']:
            problems.append({'kind': 'stdout_not_empty', 'side': 'rs'})
        if not isinstance(error, dict) or 'error' not in error or rec.get('decode_error') or rec.get('exception'):
            problems.append({'kind': 'invalid_error_json', 'side': 'rs'})
        else:
            for field in ('error', 'message'):
                name = 'stderr_rs_' + field
                if name in expect and error.get(field) != expect[name]:
                    problems.append({'kind': name, 'want': expect[name], 'got': error.get(field)})
        result = {'passed': not problems, 'problems': problems, 'semantic_compared': False,
                  'error_contract_verified': not problems,
                  'status': 'EXPECTED_ERROR_FAIL' if problems else 'EXPECTED_ERROR_PASS'}
    result['historical_behavior_problems'] = parity.check_expect(value, expect) if isinstance(value, dict) else []
    for problem in result['problems']:
        if 'actual' in problem and isinstance(problem['actual'], dict):
            problem['actual'] = {'exit': rec['exit'], 'stdout': rec['stdout'], 'stderr': rec['stderr']}
    return result


def accept(db, binary, phase):
    path = REPORTS / ('full-retry1-real-acceptance.json' if phase == 'gold' else
                      'full-retry1-P2-compatibility.json')
    if path.exists():
        raise FileExistsError(path)
    marker = acceptance_gate(db, binary, phase)
    frozen_path = GOLD if phase == 'gold' else P2
    frozen = load(frozen_path)
    report = {'kind': 'formal ' + phase + ' acceptance', 'policy': POLICY, 'retries': 0,
              'source_commit': SOURCE, 'database': marker['db'],
              'frozen_expected': binding(frozen_path),
              'freeze_before_accept': marker, 'records': []}
    parity.DB = db
    for row in frozen['cases']:
        if phase == 'gold':
            cmd = gold_command(binary, db, row['input'])
        elif row['mode'] in ('cli', 'runtime_error'):
            cmd = [str(binary)] + [str(db) if a == 'DB' else
                   str(db.parent / 'missing-parity-input.sqlite') if a == 'DB_MISSING' else a
                   for a in row['args']['argv_rs']]
        else:
            cmd = [str(binary)] + parity.rust_argv(row['op'], row['args'])
        rec, value = capture(cmd)
        record = {'case_id': row.get('id', row.get('case_id')), 'rust': rec}
        try:
            record.update(compare_gold(rec, value, row) if phase == 'gold' else compare_p2(rec, value, row))
        except Exception as exc:  # noqa: BLE001 - retain any case failure in the evidence receipt
            record.update(passed=False, status='FAIL', problems=[{'kind': type(exc).__name__, 'message': str(exc)}])
        if phase == 'gold':
            record['historical_behavior_problems'] = source_checks(value, row['original_expected'])
            record['source_delta'] = row['source_delta']
        else:
            record['frozen_historical_behavior'] = row.get('historical_behavior')
        report['records'].append(record)
    report['preservation_problems'] = []
    for ref in (marker['gold'], marker['P2'], marker['db'], marker['binary']):
        try:
            check_binding(ref)
        except Exception as exc:  # noqa: BLE001 - retain any case failure in the evidence receipt
            report['preservation_problems'].append(str(exc))
    passed = sum(r['passed'] for r in report['records'])
    report.update(attempted=len(report['records']), passed=passed,
                  wrong_resolved=sum(r.get('wrong_resolved', False) for r in report['records']))
    if phase == 'P2':
        report['summary'] = summarize(report['records'], 151)
        report['summary']['old_data_identical_claimed'] = False
    else:
        report.update(positive_denominator=sum(r['expected']['status'] == 'resolved' for r in frozen['cases']),
                      nonresolved_denominator=sum(r['expected']['status'] != 'resolved' for r in frozen['cases']))
    report['status'] = ('PASS' if passed == (55 if phase == 'gold' else 151) and
                        report['wrong_resolved'] == 0 and not report['preservation_problems'] else 'FAIL')
    write_report(path, report)
    return report['status'] == 'PASS'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--freeze', metavar='DB', type=Path)
    modes.add_argument('--accept-gold', nargs=2, metavar=('BIN', 'DB'), type=Path)
    modes.add_argument('--accept-P2', nargs=2, metavar=('BIN', 'DB'), type=Path)
    parser.add_argument('--phase', choices=('gold', 'P2', 'all'), default='all')
    args = parser.parse_args()
    if args.freeze:
        db = published(args.freeze)
        results = []
        for phase, runner, path in (('gold', freeze_gold, GOLD), ('P2', freeze_p2, P2)):
            if args.phase not in ('all', phase):
                continue
            if path.exists():
                raise FileExistsError(path)
            try:
                results.append(runner(db))
            except Exception as exc:  # noqa: BLE001 - retain any case failure in the evidence receipt
                if not path.exists():
                    write_report(path, {'status': 'STOP', 'policy': POLICY, 'cases': [],
                                        'problems': [{'kind': type(exc).__name__, 'message': str(exc)}]})
                results.append(False)
        good = all(results)
    else:
        binary, db = args.accept_gold or args.accept_P2
        db = published(db)
        phase = 'gold' if args.accept_gold else 'P2'
        try:
            good = accept(db, binary.resolve(), phase)
        except Exception as exc:  # noqa: BLE001 - retain any case failure in the evidence receipt
            failure = REPORTS / ('full-retry1-' + phase + '-accept-STOP.json')
            if not failure.exists():
                write_report(failure, {'status': 'STOP', 'policy': POLICY, 'records': [],
                                       'problems': [{'kind': type(exc).__name__, 'message': str(exc)}]})
            good = False
    print(json.dumps({'status': 'PASS' if good else 'STOP', 'policy': POLICY}))
    return 0 if good else 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--oracle-child':
        try:
            case = json.loads(sys.argv[3])
            value = oracle(Path(sys.argv[2]), case['query'], **{
                k: case[k] for k in ('category', 'kind', 'namespace', 'exact', 'limit') if k in case})
            print(json.dumps(value, ensure_ascii=True, allow_nan=False))
        except Exception as exc:
            print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}, ensure_ascii=True), file=sys.stderr)
            raise SystemExit(2) from exc
    else:
        raise SystemExit(main())
