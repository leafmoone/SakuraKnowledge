"""Read-only native Top-K capture, source-qualified proof checks and baseline comparison.

This is a small interface acceptance suite, not a replacement for retrieval-quality gold.
Cold process/model startup is recorded separately from the returned query timing.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
CASES = (
    ('tag-wiki', 'blue_hair'),
    ('moegirl', '初音'),
    ('danbooru', 'blue hair'),
    ('danbooru,bangumi', 'blue hair'),
    ('all', 'blue hair'),
)


def typed_key(record):
    if not isinstance(record, dict):
        return None
    key = record.get('entry', record.get('entry_key', record.get('tag_key', record)))
    if not isinstance(key, dict):
        return None
    values = tuple(key.get(name) for name in ('kind', 'namespace', 'value'))
    return values if all(isinstance(value, str) for value in values) else None


def owners(record, installed):
    value = record.get('source_packs', record.get('source_pack', []))
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or any(name not in installed for name in value):
        raise ValueError('missing or invalid source-qualified record owner')
    return value


def proof_scope(response, connections):
    """Check only returned rows; never scan/hash a source database or change trust."""
    allowed = set()
    for record in [*response.get('candidates', []), *response.get('trusted_pins', [])]:
        key = typed_key(record)
        if key is None:
            raise ValueError('candidate/pin lacks a typed identity')
        for pack in owners(record, connections):
            allowed.add((pack, key))
    violations, document_keys, used_sources = [], set(), set()
    document_bindings, proven_keys, published_sources = {}, set(), set()
    for document in response.get('documents', []):
        key = typed_key(document)
        for pack in owners(document, connections):
            locator = (pack, str(document['document_id']))
            if locator in document_keys:
                violations.append({'error': 'duplicate_pack_document', 'locator': locator})
            document_keys.add(locator)
            if (pack, key) not in allowed:
                violations.append({'error': 'document_outside_topk_or_pin', 'locator': locator, 'key': key})
            row = connections[pack].execute(
                'SELECT e.kind,e.namespace,e.value,d.source_id,d.evidence_id,d.status,'
                'd.original,d.payload,d.entry_id FROM documents d '
                'JOIN entries e ON e.id=d.entry_id WHERE d.id=?',
                (int(document['document_id']),),
            ).fetchone()
            if (not row or tuple(row[:3]) != key
                    or row[3:6] != (document['source_id'], document['evidence_id'], document['status'])
                    or row[5] not in ('source_backed', 'generated_from_evidence')
                    or row[6] != document['original']):
                raise ValueError('document typed identity/source/evidence/status/body binding failed')
            identity = connections[pack].execute(
                "SELECT 1 FROM entries e JOIN entry_evidence v ON v.entry_id=e.id "
                "JOIN sources s ON s.source_id=v.source_id WHERE e.id=? "
                "AND e.conflicted=0 AND v.status='source_backed' LIMIT 1", (row[8],),
            ).fetchone()
            if not identity:
                raise ValueError('document does not retain source-backed identity')
            provenance = json.loads(row[7]).get('text_provenance')
            if pack in ('moegirl', 'tag-wiki'):
                if not isinstance(provenance, dict):
                    raise ValueError('text provenance absent from source document')
                if provenance.get('trusted_text_sha256') != hashlib.sha256(row[6].encode('utf-8')).hexdigest():
                    raise ValueError('trusted document text digest mismatch')
                if document.get('text_provenance') != provenance:
                    raise ValueError('public text provenance differs from source payload')
            used_sources.add((pack, row[3]))
            document_bindings[locator] = (row[3], row[4])
            proven_keys.add((pack, key))
            for field in ('citations', 'evidence'):
                if not any(str(record.get('document_id')) == locator[1]
                           and record.get('source_id') == row[3] and record.get('evidence_id') == row[4]
                           and pack in owners(record, connections) for record in response.get(field, [])):
                    raise ValueError('document proof dependency missing')
    # Independent identity proofs may survive without a document (e.g. exact pins).
    for field in ('evidence', 'citations'):
        for record in response.get(field, []):
            sid, eid = record.get('source_id'), record.get('evidence_id')
            if not isinstance(sid, str) or not isinstance(eid, str):
                raise TypeError('proof lacks source/evidence identifiers')
            for pack in owners(record, connections):
                used_sources.add((pack, sid))
                did = record.get('document_id')
                if did is not None:
                    if (pack, str(did)) not in document_keys:
                        violations.append({'error': 'proof_without_public_document', 'field': field,
                                           'pack': pack, 'document_id': str(did)})
                    elif document_bindings[(pack, str(did))] != (sid, eid):
                        raise ValueError('proof refers to a document with different source/evidence binding')
                    continue
                supported = False
                for allowed_pack, key in allowed:
                    if allowed_pack != pack:
                        continue
                    entry = connections[pack].execute(
                        'SELECT id FROM entries WHERE kind=? AND namespace=? AND value=?', key,
                    ).fetchone()
                    if entry is None:
                        continue
                    matches_identity = bool(connections[pack].execute(
                        "SELECT 1 FROM entry_evidence WHERE entry_id=? AND source_id=? "
                        "AND evidence_id=? AND status='source_backed' UNION ALL "
                        "SELECT 1 FROM aliases WHERE entry_id=? AND source_id=? "
                        "AND evidence_id=? AND status='source_backed' LIMIT 1",
                        (entry[0], sid, eid, entry[0], sid, eid),
                    ).fetchone())
                    supported |= matches_identity
                    if matches_identity:
                        proven_keys.add((pack, key))
                if not supported:
                    violations.append({'error': 'identity_proof_outside_topk_or_pin',
                                       'field': field, 'pack': pack, 'source_id': sid, 'evidence_id': eid})
    for source in response.get('sources', []):
        for pack in owners(source, connections):
            sid = source.get('source_id')
            published_sources.add((pack, sid))
            if not connections[pack].execute('SELECT 1 FROM sources WHERE source_id=?', (sid,)).fetchone():
                raise ValueError('returned source does not exist in owning pack')
            if (pack, sid) not in used_sources:
                violations.append({'error': 'orphan_source', 'pack': pack, 'source_id': sid})
    for pack, key in sorted(allowed - proven_keys):
        violations.append({'error': 'selected_key_or_pin_has_no_public_proof', 'pack': pack, 'key': key})
    for pack, sid in sorted(used_sources - published_sources):
        violations.append({'error': 'required_source_missing', 'pack': pack, 'source_id': sid})
    return {'status': 'PASS' if not violations else 'FAIL', 'violations': violations,
            'source_qualified_documents': len(document_keys), 'allowed_typed_key_origins': len(allowed)}


def candidate_ranking(response):
    return [{'entry': list(typed_key(candidate)) if typed_key(candidate) is not None else None,
             'rank': candidate.get('hybrid_rank'),
             'source_packs': candidate.get('source_packs'),
             'ranking_fields': {name: candidate[name] for name in
                                ('rrf_score', 'score', 'global_semantic_rank', 'best_distance', 'backend_ranks')
                                if name in candidate}}
            for candidate in response.get('candidates', [])]


def save_new(path, content):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(content, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def capture(executable, config, output, phase, baseline=None):
    executable, config, output = Path(executable).resolve(), Path(config).resolve(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    config_data = json.loads(config.read_bytes())
    packroot = config.parent / config_data['packs_directory']
    connections = {path.parent.name: sqlite3.connect(
        (path.parent / 'knowledge.sqlite').resolve().as_uri() + '?mode=ro&immutable=1', uri=True,
    ) for path in packroot.glob('*/manifest.json')}
    before = json.loads(Path(baseline).read_bytes()) if baseline else None
    before_cases = {row['case_id']: row for row in before['cases']} if before else {}
    report = {'schema': 'sakura-tool-topk-native-v1', 'phase': phase, 'status': 'FAIL',
              'executable': str(executable), 'config': str(config), 'cases': [],
              'quality_scope': 'NOT_RUN: interface smoke, not full120 or quality retuning',
              'assets_rebuilt': False, 'wire_limit_bytes': MAX_BYTES}
    try:
        for source, query in CASES:
            for topk in (1, 5):
                case_id = source.replace(',', '+') + '-top' + str(topk)
                argv = [str(executable), '--config', str(config), 'retrieve', query, '--topk', str(topk)]
                if source != 'all':
                    argv.extend(['--source', source])
                started = time.perf_counter()
                process = subprocess.run(argv, capture_output=True, env=environment, timeout=90, check=False)
                wall_ms = (time.perf_counter() - started) * 1000
                for channel in ('stdout', 'stderr'):
                    with (output / (case_id + '.' + channel)).open('xb') as stream:
                        stream.write(getattr(process, channel))
                row = {'case_id': case_id, 'command': argv, 'query': query, 'topk': topk,
                       'exit': process.returncode, 'cold_wall_ms': wall_ms,
                       'stdout_bytes': len(process.stdout), 'stderr_bytes': len(process.stderr), 'status': 'FAIL'}
                report['cases'].append(row)
                if process.returncode:
                    row['limitation'] = 'native command failed; raw stdout/stderr retained'
                    continue
                response = json.loads(process.stdout.decode('utf-8'))
                row.update(response_status=response.get('status'),
                           candidates=candidate_ranking(response),
                           document_count=len(response.get('documents', [])),
                           source_count=len(response.get('sources', [])),
                           evidence_count=len(response.get('evidence', [])),
                           citation_count=len(response.get('citations', [])),
                           query_timings_ms=response.get('timings_ms', {}),
                           proof_scope=proof_scope(response, connections))
                row['runtime_pass'] = (response.get('status') == 'PASS'
                                       and process.stdout.endswith(b'\n')
                                       and len(process.stdout.splitlines()) == 1
                                       and len(process.stdout) <= MAX_BYTES
                                       and len(response.get('candidates', [])) <= topk
                                       and response.get('timings_ms', {}).get('total', 5001) <= 5000)
                if before is not None:
                    prior = before_cases[case_id]
                    row['ranking_unchanged'] = prior.get('candidates') == row['candidates']
                    row['before_document_count'] = prior.get('document_count')
                    row['before_stdout_bytes'] = prior['stdout_bytes']
                    row['before_query_timings_ms'] = prior.get('query_timings_ms')
                row['status'] = ('PASS' if row['runtime_pass']
                                 and (phase == 'before' or row['proof_scope']['status'] == 'PASS')
                                 and row.get('ranking_unchanged', True) else 'FAIL')
        passed = all(row['status'] == 'PASS' for row in report['cases'])
        report['status'] = ('BASELINE_CAPTURED' if phase == 'before' else 'PASS') if passed else 'FAIL'
    except (ValueError, TypeError, KeyError, sqlite3.Error, OSError, subprocess.SubprocessError) as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        for connection in connections.values():
            connection.close()
        save_new(output / 'summary.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    parser.add_argument('--baseline')
    args = parser.parse_args()
    if args.phase == 'after' and not args.baseline:
        parser.error('--baseline is required for after')
    report = capture(args.executable, args.config, args.output, args.phase, args.baseline)
    print(json.dumps({'status': report['status'], 'cases': len(report['cases']),
                      'scope_failures': sum(row.get('proof_scope', {}).get('status') == 'FAIL'
                                            for row in report['cases']),
                      'error': report.get('error')}, ensure_ascii=True))
    if report['status'] not in ('PASS', 'BASELINE_CAPTURED'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
