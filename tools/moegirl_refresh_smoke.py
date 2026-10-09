"""Frozen source-only/no-model smoke; retain raw stdout/stderr and honest rankings."""
import argparse
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

from tools.modular_semantic_validate import closure
from tools.p4_rust_pilot import MAX_BYTES, Driver


def run(root, gold, output):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cases = json.loads(Path(gold).read_bytes())['cases']
    if (root / 'model').exists():
        raise ValueError('source-only smoke requires model directory absent')
    db = root / 'packs/moegirl/knowledge.sqlite'
    conn = sqlite3.connect(db.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    rows = []
    report = {'status': 'FAIL', 'cases': rows, 'model_directory_absent': True,
              'metrics_scope': 'PARTIAL', 'positive_recall10': None, 'positive_recall100': None,
              'command_attempts': []}
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    try:
        with (output / 'resident.stderr').open('wb') as stderr, (output / 'resident.jsonl').open('xb') as raw:
            child = Driver([str(root / 'bin/semantic_pilot.exe'), '--config', str(root / 'sknow-config.json')], stderr)
            report['opened'], _ = child.receive(60)
            try:
                for case in cases:
                    started = time.perf_counter()
                    response, size = child.request(case)
                    wall = (time.perf_counter() - started) * 1000
                    raw.write(child.last_raw); raw.flush()
                    if response['status'] != 'PASS':
                        rows.append({'case_id': case['case_id'], 'record_state': case['record_state'], 'wall_ms': wall,
                                     'response_bytes': size, 'original_response_bytes': response.get('response_bytes'),
                                     'error': response.get('error'), 'target_lexical_rank100': None, 'source_closure': 'NOT_RUN'})
                        continue
                    closure(response, {'moegirl': conn})
                    if response['timings_ms']['query_encodings'] != 0 or response['dense_hits'] or wall > 5000 or size > MAX_BYTES:
                        raise ValueError('no-model runtime/closure/protocol failure')
                    target = case['entry_key']
                    ranking = [r.get('entry', r.get('entry_key')) for r in response['lexical_hits']]
                    rank = ranking.index(target) + 1 if target in ranking else None
                    count = conn.execute('SELECT count(*) FROM documents d JOIN entries e ON e.id=d.entry_id WHERE e.kind=? AND e.namespace=? AND e.value=?', (target['kind'], target['namespace'], target['value'])).fetchone()[0]
                    if (count > 0) != (case['record_state'] == 'template_present'):
                        raise ValueError('frozen positive/negative per-record document invariant')
                    commands = [('lookup', [case['raw_title'], '--kind', 'character', '--namespace', 'moegirl.character', '--key'])]
                    if case['record_state'] == 'template_present':
                        commands.append(('search', [case['query'], '--kind', 'character', '--namespace', 'moegirl.character', '--limit', '10']))
                    command_results = []
                    for command, args in commands:
                        argv = [str(root / 'bin/sknow-rs.exe'), '--config', str(root / 'sknow-config.json'), command, *args]
                        command_started = time.perf_counter()
                        process = subprocess.run(argv, capture_output=True, env=env, timeout=10, check=False)
                        name = case['case_id'] + '-' + command
                        (output / (name + '.stdout')).write_bytes(process.stdout)
                        (output / (name + '.stderr')).write_bytes(process.stderr)
                        attempt = {'case_id': case['case_id'], 'argv': argv, 'exit': process.returncode,
                                   'wall_ms': (time.perf_counter() - command_started) * 1000,
                                   'stdout_bytes': len(process.stdout), 'stderr_bytes': len(process.stderr)}
                        report['command_attempts'].append(attempt)
                        if process.returncode:
                            attempt['error_response'] = json.loads(process.stderr) if process.stderr else None
                            raise ValueError('source CLI returned failure; raw stderr retained')
                        actual = json.loads(process.stdout)
                        if command == 'lookup' and actual['status'] != 'found':
                            raise ValueError('source historical identity lookup lost')
                        command_results.append({'command': argv, 'exit': process.returncode, 'status': actual.get('status')})
                    rows.append({'case_id': case['case_id'], 'record_state': case['record_state'], 'wall_ms': wall, 'response_bytes': size,
                                 'target_lexical_rank100': rank, 'record_document_count': count, 'query_encodings': 0, 'source_closure': 'PASS', 'commands': command_results,
                                 'top_level_field_bytes': {k: len(json.dumps(v, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) for k, v in response.items()}})
                report['status'] = 'PASS' if all('error' not in r for r in rows) else 'FAIL'
            finally:
                report['shutdown'] = child.close()
    except (ValueError, KeyError, RuntimeError, OSError, sqlite3.Error) as error:
        report['error'] = repr(error)
        report['failed_case_id'] = case['case_id'] if 'case' in locals() else None
    finally:
        conn.close()
    report['evaluated_positive_count'] = sum(r['record_state'] == 'template_present' and r['source_closure'] == 'PASS' for r in rows)
    if report['status'] == 'PASS' and len(rows) == len(cases):
        report['metrics_scope'] = 'COMPLETE_FROZEN_SMALL_SOURCE_SUITE'
        positives = [r for r in rows if r['record_state'] == 'template_present']
        report['positive_recall10'] = sum(r['target_lexical_rank100'] is not None and r['target_lexical_rank100'] <= 10 for r in positives) / len(positives) if positives else None
        report['positive_recall100'] = sum(r['target_lexical_rank100'] is not None for r in positives) / len(positives) if positives else None
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'cases': len(rows), 'positive_recall10': report['positive_recall10'], 'positive_recall100': report['positive_recall100'], 'error': report.get('error')}))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--gold', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if run(args.root, args.gold, args.output)['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
