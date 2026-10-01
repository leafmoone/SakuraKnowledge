"""Read-only FULL protection diagnostics; never rerun or promote historical S02.

compare() is a pure contract for future validators: pass independently measured
FULL byte bindings and sidecar metadata on both sides of a protected operation.
Only SHM mtime is diagnostic. SHM content, WAL metadata and every other field
remain strict. CLI modes perform byte/evidence checks only, never SQL or queries.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

import p3_close_validate as helpers
from p3_evidence import verify
from p3_final_artifacts import REPORTS, ROOT, binding, check_binding, create_new, verify_artifacts
from p3_retry1_sidecar_audit import TARGET, validate_metadata, verify_snapshot

FULL_BYTES = 21718736896
FULL_SHA256 = '61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9'
ARTIFACT_SOURCE = 'e19d2278f26c12cba28eaff82a6eed2f0cda62cb'
VALIDATOR_COMMIT = '922192e52cc7f2001f9ed243e1edcd31ae4adc41'
VALIDATOR_BLOB = 'c6fa624c60cf2cd8e216876ba8600c7d004655c9'
PROTECTION_MESSAGE = 'database sidecars changed during phase'


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _full(ref):
    if (not isinstance(ref, dict) or set(ref) != {'path', 'bytes', 'sha256'} or
            not isinstance(ref['path'], str) or not ref['path'] or
            Path(ref['path']) != TARGET or
            type(ref['bytes']) is not int or ref['bytes'] != FULL_BYTES or
            ref['sha256'] != FULL_SHA256):
        raise ValueError('missing exact fixed FULL path/size/SHA evidence; STOP')


def _sidecars(state):
    if not isinstance(state, dict) or set(state) != {'-wal', '-shm', '-journal'}:
        raise ValueError('missing or unknown sidecar evidence; STOP')
    for suffix, row in state.items():
        if not isinstance(row, dict) or type(row.get('exists')) is not bool:
            raise ValueError('missing exact sidecar existence evidence; STOP')
        fields = {'exists'}
        if row['exists']:
            fields |= {'bytes', 'mtime_ns'}
            if suffix == '-shm':
                fields |= {'sha256', 'header_copies_equal', 'version', 'initialized', 'mx_frame'}
            if (type(row.get('bytes')) is not int or row['bytes'] < 0 or
                    type(row.get('mtime_ns')) is not int or row['mtime_ns'] < 0):
                raise ValueError('missing exact sidecar size/mtime evidence; STOP')
        if set(row) != fields:
            raise ValueError('missing or unknown sidecar metadata fields; STOP')
        if (suffix == '-shm' and row['exists'] and
                (not _sha(row['sha256']) or type(row['header_copies_equal']) is not bool or
                 any(type(row[k]) is not int for k in ('version', 'initialized', 'mx_frame')))):
            raise ValueError('missing exact SHM hash/header evidence; STOP')
    # Reuse the frozen known-header, empty-WAL, absent-journal safety contract.
    validate_metadata(state)


def compare(before, after, db_before, db_after):
    """Return PASS with SHM-mtime diagnostics, or raise ValueError (STOP).

    No I/O, mutation, fallback hash, or implied historical protection proof.
    Callers must supply actual whole-byte hash receipts, not size-only stats.
    """
    _full(db_before)
    _full(db_after)
    if db_before != db_after:
        raise ValueError('FULL byte binding/identity changed; STOP')
    _sidecars(before)
    _sidecars(after)
    strict = []
    for state in (before, after):
        strict.append({suffix: {k: v for k, v in row.items()
                               if not (suffix == '-shm' and k == 'mtime_ns')}
                       for suffix, row in state.items()})
    if strict[0] != strict[1]:
        raise ValueError('sidecar content or strict metadata changed; STOP')
    diagnostics = []
    if before['-shm'].get('mtime_ns') != after['-shm'].get('mtime_ns'):
        diagnostics.append({'sidecar': '-shm', 'field': 'mtime_ns',
                            'before': before['-shm']['mtime_ns'],
                            'after': after['-shm']['mtime_ns'],
                            'meaning': 'mutable coordination metadata; content SHA unchanged'})
    return {'status': 'PASS', 'database': dict(db_after), 'diagnostics': diagnostics,
            'excluded_invariant_fields': ['-shm.mtime_ns'], 'SHM_content_SHA_strict': True}


def _load(path):
    return json.loads(Path(path).read_bytes().decode('utf-8', errors='strict'))


def _inputs():
    gold, p2, ref = helpers.validate_inputs()
    _full(ref)
    return gold, p2, ref


def _artifacts():
    path = REPORTS / 'final-artifacts-retry1.json'
    ref = binding(path)
    report = _load(path)
    if report.get('source_commit') != ARTIFACT_SOURCE or report.get('attempt') != 'retry1':
        raise ValueError('not fixed retry1 artifact source')
    verify_artifacts(report)
    check_binding(ref)
    return report, ref


def readonly_baseline():
    """Hash only FULL now; old P2/partial historical receipts are not rehashed."""
    started = time.time_ns()
    artifacts, artifact_ref = _artifacts()
    _, _, expected = _inputs()
    frozen = {'gold': binding(helpers.prior.GOLD), 'P2': binding(helpers.prior.P2)}
    _, gate = verify_snapshot(Path(expected['path']), expected)
    result = compare(gate['sidecars_before'], gate['sidecars_after'], expected, gate['database'])
    verify_artifacts(artifacts)
    check_binding(artifact_ref)
    for ref in frozen.values():
        check_binding(ref)
    return {**result, 'kind': 'current read-only FULL protection baseline',
            'started_ns': started, 'finished_ns': time.time_ns(),
            'readonly_gate': gate, 'artifacts': artifact_ref, 'frozen_inputs': frozen,
            'whole_FULL_hash_verified_now': True, 'historical_protection_PASS': False,
            'SQL_queries': 0, 'query_rerun': 'NO', 'write_probes': 0,
            'process_inspection_status': 'existing verify_snapshot process gate passed',
            'limitations': gate['limitations'] + [
                'Existing process gate records status, not raw process enumeration bytes',
                'This baseline is now, not saved metadata from the original S02 after-check']}


def validator_source():
    """Bind the implementation that ran, not a potentially different current file."""
    argv = ['git', 'show', VALIDATOR_COMMIT + ':tools/p3_final_validate.py']
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=30, check=False)
    if proc.returncode != 0 or proc.stderr:
        raise ValueError('cannot obtain fixed historical validator git blob')
    data = proc.stdout
    oid = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()
    if oid != VALIDATOR_BLOB:
        raise ValueError('historical validator git blob mismatch')
    return data, {'commit': VALIDATOR_COMMIT, 'path': 'tools/p3_final_validate.py',
                  'git_blob_oid': oid, 'bytes': len(data),
                  'sha256': hashlib.sha256(data).hexdigest(),
                  'command': argv, 'exit': proc.returncode,
                  'stdout_utf8': data.decode('utf-8', errors='strict'),
                  'stderr_utf8': proc.stderr.decode('utf-8', errors='strict')}


def review_s02(receipt, case, plan, stdout, stderr, profile_bytes, source):
    """Read-only review of verified bytes, never a historical protection compare."""
    if (receipt.get('phase') != 'S02' or receipt.get('status') != 'FAIL' or
            receipt.get('protection_exception') != {'type': 'ValueError',
                                                   'message': PROTECTION_MESSAGE} or
            'exception' in receipt or 'readonly_gate_after' in receipt):
        raise ValueError('not the original S02 protection-only FAIL without saved after receipt')
    for field in ('source_commit', 'artifacts', 'frozen_gold', 'frozen_P2', 'database',
                  'performance_prerequisite'):
        if receipt[field] != plan[field]:
            raise ValueError('original S02/runplan binding differs: ' + field)
    _full(receipt['database'])
    gate = receipt['readonly_gate_before']
    compare(gate['sidecars_before'], gate['sidecars_after'], gate['database'], receipt['database'])
    if (case['case_id'] != 'S02' or receipt.get('retries') != 0 or
            plan.get('S02_profile_invocations') != 1 or plan.get('retries') != 0):
        raise ValueError('not a single frozen S02 invocation')
    rec = receipt['rust']
    argv = helpers.commands(Path(plan['artifacts']['binary']['path']),
                            Path(receipt['database']['path']), case)
    profile = json.loads(profile_bytes.decode('utf-8', errors='strict'))
    if (rec.get('argv') != argv or rec.get('attempted') != 1 or rec.get('succeeded') != 1 or
            rec.get('exit') != 0 or rec.get('timeout') is not False or
            rec.get('outer_timeout') is not False or stderr != b'' or
            json.loads(stdout.decode('utf-8', errors='strict')) !=
            helpers.prior.frozen_value(case['expected_json']) or
            profile != receipt['profile'] or profile.get('query_invocations') != 1 or
            profile.get('query_succeeded') is not True or profile.get('query_error') is not None or
            profile.get('profile', {}).get('fts_skipped_kind_not_indexed') is not True):
        raise ValueError('recorded S02 query/full frozen JSON/profile contract failed')
    env = {'SKNOW_SEARCH_PROFILE_OUT': plan['S02_profile_sink']}
    if (receipt.get('profile_environment') != env or
            rec.get('environment', {}).get('SKNOW_SEARCH_PROFILE_OUT') != plan['S02_profile_sink']):
        raise ValueError('profile not bound to the same recorded invocation')
    oid = hashlib.sha1(b'blob ' + str(len(source)).encode('ascii') + b'\0' + source).hexdigest()
    if oid != VALIDATOR_BLOB:
        raise ValueError('not exact historical validator source')
    block = ("            check_binding(binding_ref)\n"
             "            after = metadata(db)\n"
             "            validate_metadata(after)\n"
             "            if after != gate['sidecars_after']:\n"
             "                raise ValueError('database sidecars changed during phase')\n")
    if block not in source.decode('utf-8', errors='strict'):
        raise ValueError('historical FULL after-check control flow not established')
    if receipt.get('source_git', {}).get('validation_source_commit') != VALIDATOR_COMMIT:
        raise ValueError('recorded validation source differs from reviewed git blob')
    return {'status': 'QUERY_PASS_PROTECTION_FAIL', 'original_status': 'FAIL',
            'original_protection_exception': receipt['protection_exception'],
            'query_rerun': 'NO', 'SQL_queries': 0, 'historical_protection_PASS': False,
            'original_exact_after_metadata': 'NOT_SAVED',
            'historical_FULL_after_evidence':
                'control-flow check_binding returned before comparison exception; '
                'original exact after metadata NOT_SAVED',
            'SHM_mtime_only_historical_cause': 'NOT_PROVEN',
            'limitations': ['No saved original after-sidecars or FULL after-hash receipt',
                            'A current baseline cannot retroactively PASS original protection']}


def independent_review():
    started = time.time_ns()
    original_path = REPORTS / 'final-S02.json'
    original_ref = binding(original_path)
    receipt = _load(original_path)
    plan_path = REPORTS / 'final-runplan.json'
    check_binding(receipt['runplan'])
    if Path(receipt['runplan']['path']).resolve() != plan_path.resolve():
        raise ValueError('wrong original runplan path')
    plan = _load(plan_path)
    artifacts, artifact_ref = _artifacts()
    if receipt['artifacts'] != artifacts:
        raise ValueError('original artifact bindings differ from fixed retry1 artifacts')
    _, p2, db_ref = _inputs()
    if receipt['database'] != db_ref:
        raise ValueError('original FULL reference differs from frozen input')
    for field, path in (('frozen_gold', helpers.prior.GOLD), ('frozen_P2', helpers.prior.P2)):
        if Path(receipt[field]['path']).resolve() != Path(path).resolve():
            raise ValueError('wrong original frozen input path')
        check_binding(receipt[field])
    cases = [row for row in p2['cases'] if row['case_id'] == 'S02']
    if len(cases) != 1:
        raise ValueError('not exactly one frozen S02 case')
    source, source_ref = validator_source()
    refs = {field: receipt['rust'][field] for field in ('stdout', 'stderr')}
    refs['profile_raw'] = receipt['profile_raw']
    data = {field: verify(ref) for field, ref in refs.items()}
    result = review_s02(receipt, cases[0], plan, data['stdout'], data['stderr'],
                        data['profile_raw'], source)
    check_binding(original_ref)
    check_binding(receipt['runplan'])
    check_binding(artifact_ref)
    return {**result, 'started_ns': started, 'finished_ns': time.time_ns(),
            'original_receipt': original_ref, 'runplan': receipt['runplan'],
            'artifacts': artifact_ref, 'raw_evidence': refs,
            'frozen_S02_expected_JSON': cases[0]['expected_json'], 'validator_source': source_ref,
            'current_baseline_is_separate': 'final-protection-baseline.json'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('baseline', 'review', 'workflow'))
    args = parser.parse_args(argv)
    jobs = [('baseline', 'final-protection-baseline', readonly_baseline),
            ('review', 'final-S02-independent-review', independent_review)]
    jobs = [job for job in jobs if args.mode in (job[0], 'workflow')]
    # Check all outputs before doing any work; interrupted reservations block retry.
    for _, name, _ in jobs:
        for suffix in ('.json', '-start.json'):
            path = REPORTS / (name + suffix)
            if path.exists() or path.is_symlink():
                raise FileExistsError(path)
    for _, name, operation in jobs:
        started = time.time_ns()
        create_new(REPORTS / (name + '-start.json'), {'started_ns': started, 'query_rerun': 'NO'})
        try:
            result = operation()
        except Exception as exc:  # noqa: BLE001 - preserve failed once-only diagnostic reservations
            result = {'status': 'FAIL', 'started_ns': started, 'finished_ns': time.time_ns(),
                      'exception': {'type': type(exc).__name__, 'message': str(exc)},
                      'query_rerun': 'NO', 'historical_protection_PASS': False}
        create_new(REPORTS / (name + '.json'), result)
        if result['status'] == 'FAIL':
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
