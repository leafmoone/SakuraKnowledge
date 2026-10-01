"""Offline P4 legacy preflight. Never imports a runtime or opens a database."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ROOT = 'D:/SakuraTool/SakuraKnowledge/'
RAW_ROOTS = ('reports/P3/final-raw/', 'reports/P3/close-raw/')


def binding(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def strict_json(data):
    def reject(value):
        raise ValueError('non-finite JSON: ' + value)
    return json.loads(data.decode('utf-8', errors='strict'), parse_constant=reject)


def relative_ref(path):
    path = path.replace('\\', '/').removeprefix(HISTORICAL_ROOT)
    if any(p in ('', '.', '..') for p in path.split('/')) or ':' in path:
        raise ValueError('unsafe receipt path: ' + path)
    return path


def tracked_files(root):
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'],
                            check=True, capture_output=True)
    return set(result.stdout.decode('utf-8', errors='strict').split('\0')) - {''}


def read_tracked(root, relative, tracked):
    relative = relative_ref(relative)
    if relative not in tracked:
        raise ValueError('untracked receipt: ' + relative)
    path = root / relative
    if path.resolve() != root.resolve().joinpath(relative) or not path.is_file():
        raise ValueError('non-contained or absent receipt: ' + relative)
    data = path.read_bytes()
    data.decode('utf-8', errors='strict')
    return data


def verify_raw(root, ref, tracked):
    relative = relative_ref(ref['path'])
    if not relative.startswith(RAW_ROOTS):
        raise ValueError('raw receipt outside retained allowlist: ' + relative)
    if not re.fullmatch(r'[0-9a-f]{64}\.raw', relative.rsplit('/', 1)[1]):
        raise ValueError('invalid raw filename')
    data = read_tracked(root, relative, tracked)
    if binding(data) != {k: ref[k] for k in ('bytes', 'sha256')}:
        raise ValueError('raw receipt byte mismatch: ' + relative)
    if relative.rsplit('/', 1)[1] != ref['sha256'] + '.raw':
        raise ValueError('raw filename/hash mismatch')
    return data


def byte_refs(value):
    if isinstance(value, dict):
        if {'path', 'bytes', 'sha256'} <= value.keys():
            yield value
        for child in value.values():
            yield from byte_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from byte_refs(child)


def reconstruct(value, ref):
    """Known print(json.dumps(...)) formats only; never reorder accepted keys."""
    text = json.dumps(value, ensure_ascii=True, allow_nan=False)
    attempts = []
    for newline in ('\n', '\r\n'):
        data = (text + newline).encode('utf-8', errors='strict')
        attempts.append({'newline': repr(newline), **binding(data)})
        if binding(data) == {k: ref[k] for k in ('bytes', 'sha256')}:
            return data, attempts
    return None, attempts


def unique_rows(rows, key, count):
    result = {row[key]: row for row in rows}
    if len(rows) != count or len(result) != count:
        raise ValueError('wrong case count or duplicate IDs')
    return result


def source_checks(value, expected):
    """Pure retained-source assertions, matching p3_retry1_acceptance:150-170."""
    problems = []
    for key in ('status', 'tag_key', 'source_key', 'matched_by', 'canonical_status',
                'candidates_truncated', 'unresolved_reasons'):
        if key in expected and value.get(key) != expected[key]:
            problems.append(key)
    if 'candidates' in expected:
        keys = [c.get('entry_key', c.get('tag_key')) for c in value.get('candidates', [])]
        if keys != expected['candidates']:
            problems.append('candidates')
    if expected.get('description') and not value.get('descriptions'):
        problems.append('description')
    if expected.get('descriptions_empty') and value.get('descriptions') != []:
        problems.append('descriptions_empty')
    for assertion in expected.get('evidence_assertions', []):
        if not any(all(ref.get(k) == v for k, v in assertion.items())
                   for ref in value.get('evidence_chain', [])):
            problems.append('evidence_assertion')
    return problems


def freeze(root=ROOT):
    tracked = tracked_files(root)
    manifest = {
        'schema': 'p4-legacy-baseline-freeze-v1',
        'kind': 'offline preflight, independent of pilot; NOT a regression run',
        'serialization_sources': ['tools/check_parity.py:234',
                                  'tools/p3_retry1_acceptance.py:625'],
        'limitations': [
            'Original reports/P3/raw bytes were NOT read; no fallback or external preservation reads.',
            'Only LF/CRLF historical ensure_ascii=True default-separator serialization tried in memory.',
            'Hash matches are reconstructions from accepted values, not reads of original oracle files.',
            'Reconstructed bytes are not persisted; this manifest records exact hash/size comparisons.',
            'Mismatches block original oracle recovery; retained responses are an alternative historical baseline only.',
            'Source assertions are checked against retained values; source raw proofs are not independently recovered.',
            'No database queries, runtime CLI calls, or formal regressions performed.',
        ], 'sources': {}, 'suites': {},
    }
    reconstructed = {hashlib.sha256(b'').hexdigest(): b''}
    originals = []
    for suite, count, frozen_name, key in (
        ('P2', 151, 'full-retry1-P2-frozen-expected.json', 'case_id'),
        ('gold', 55, 'full-retry1-real-gold.json', 'id'),
    ):
        docs = []
        for name in ('final-' + suite + '.json', frozen_name):
            path = 'reports/P3/' + name
            data = read_tracked(root, path, tracked)
            manifest['sources'][path] = binding(data)
            docs.append(strict_json(data))
        accepted, original = docs
        if accepted['status'] != 'PASS' or original['status'] != 'PASS':
            raise ValueError('non-PASS source')
        bound = accepted['frozen_P2' if suite == 'P2' else 'frozen_gold']
        if {k: bound[k] for k in ('bytes', 'sha256')} != manifest['sources']['reports/P3/' + frozen_name]:
            raise ValueError('accepted/frozen source binding mismatch')
        cases = unique_rows(original['cases'], key, count)
        records = unique_rows(accepted['records'], 'case_id', count)
        if cases.keys() != records.keys():
            raise ValueError('original/accepted IDs differ')
        originals.extend(byte_refs(original))
        rows = []
        verified = 0
        for cid, case in cases.items():
            rec = records[cid]
            if not rec['passed']:
                raise ValueError('non-passing accepted record ' + cid)
            for ref in byte_refs(rec):
                verify_raw(root, ref, tracked)
                verified += 1
            source = 'installed_python' if 'installed_python' in rec else 'rust'
            process = rec[source]
            if source == 'installed_python':
                argv = process['argv']
                if '-c' in argv:
                    if argv[-2] != case['op'] or strict_json(argv[-1].encode('utf-8')) != case['args']:
                        raise ValueError('installed Python arguments differ: ' + cid)
                elif argv[argv.index('sakura_knowledge.cli') + 1:] != rec['rust']['argv'][1:]:
                    raise ValueError('installed CLI arguments differ: ' + cid)
                if not rec['installed_python_passed']:
                    raise ValueError('installed Python not accepted: ' + cid)
            row = {'case_id': cid, 'original_case': case,
                   'accepted_argv': rec['rust']['argv'],
                   'alternative_historical_baseline': {
                       'origin': source, 'argv': process['argv'], 'stdout': process['stdout'],
                       'stderr': process['stderr'], 'exit': process['exit']}}
            expected_ref = case.get('expected_json' if suite == 'P2' else 'oracle_json')
            if expected_ref is None:
                row['original_recovery'] = 'not_applicable_error_contract'
            else:
                value = strict_json(verify_raw(root, process['stdout'], tracked))
                if suite == 'gold':
                    row['source_assertion_problems'] = source_checks(value, case['expected'])
                    if row['source_assertion_problems']:
                        raise ValueError('gold source assertions failed: ' + cid)
                data, attempts = reconstruct(value, expected_ref)
                row['reconstruction_attempts'] = attempts
                row['original_recovery'] = ('hash_verified_reconstruction_from_accepted_value'
                                            if data is not None else 'BLOCKED_original_oracle_hash_mismatch')
                if data is not None:
                    reconstructed[expected_ref['sha256']] = data
            rows.append(row)
        recovered = sum(r['original_recovery'].startswith('hash_verified') for r in rows)
        blocked = sum(r['original_recovery'].startswith('BLOCKED') for r in rows)
        manifest['suites'][suite] = {
            'case_count': count, 'unique_ids': len(cases),
            'verified_retained_raw_reference_occurrences': verified,
            'recoverable_original_values': recovered, 'blocked_original_values': blocked,
            'error_contract_cases': count - recovered - blocked, 'cases': rows,
        }
    inventory = []
    for ref in originals:
        path = relative_ref(ref['path'])
        if not path.startswith('reports/P3/raw/'):
            continue
        data = reconstructed.get(ref['sha256'])
        matched = data is not None and binding(data) == {k: ref[k] for k in ('bytes', 'sha256')}
        inventory.append({'original_ref': ref, 'status': (
            'hash_verified_reconstruction_not_original_read' if matched
            else 'BLOCKED_original_raw_not_recovered')})
    manifest['original_raw_reference_audit'] = inventory
    manifest['status'] = ('BLOCKED_original_oracle_recovery' if any(
        s['blocked_original_values'] for s in manifest['suites'].values())
        else 'original_value_hashes_recovered_source_proof_limitations_remain')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', action='store_true', help='create-new P4 manifest')
    args = parser.parse_args()
    manifest = freeze()
    if args.export:
        output = ROOT / 'reports/P4/legacy-baseline-freeze.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8', errors='strict', newline='\n') as stream:
            json.dump(manifest, stream, ensure_ascii=True, indent=2, allow_nan=False)
            stream.write('\n')
    print(json.dumps({k: {f: v for f, v in s.items() if f != 'cases'}
                      for k, s in manifest['suites'].items()}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
