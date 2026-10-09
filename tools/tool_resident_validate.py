"""Capture a real native resident's continuous requests, failures and natural EOF.

No model/index builds, retry, process restart, or synthetic replacement for native queries.
Oversize and fatal-I/O injection are separately tested by small native fixtures.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024


def request_sequence(modular):
    def entry(request, expected_id, status):
        return {'input': request, 'expected_case_id': expected_id, 'expected_status': status}

    cases = [
        entry({'case_id': 'q1', 'query': 'blue hair', 'limit': 5}, 'q1', 'PASS'),
        entry({'case_id': 'q2', 'query': 'blue hair', 'limit': 'bad'}, 'q2', 'FAIL'),
        entry({'case_id': 'q3', 'query': 'Hatsune Miku', 'limit': 5}, 'q3', 'PASS'),
        entry('{"case_id":"not-reliably-json","query":', None, 'FAIL'),
        entry({'query': 'blue hair'}, None, 'FAIL'),
        entry({'case_id': 7, 'query': 'blue hair'}, None, 'FAIL'),
        entry(['not', 'an', 'object'], None, 'FAIL'),
        entry({'case_id': 'bad-query', 'query': False}, 'bad-query', 'FAIL'),
        entry({'case_id': 'long-query', 'query': '日' * 4097}, 'long-query', 'FAIL'),
        entry({'case_id': 'zero-limit', 'query': 'blue hair', 'limit': 0}, 'zero-limit', 'FAIL'),
        entry({'case_id': 'large-limit', 'query': 'blue hair', 'limit': 101}, 'large-limit', 'FAIL'),
        entry({'case_id': 'bad-kind', 'query': 'blue hair', 'kind': 'not-a-kind'}, 'bad-kind', 'FAIL'),
        entry({'case_id': 'bad-namespace', 'query': 'blue hair', 'namespace': ''}, 'bad-namespace', 'FAIL'),
        entry({'case_id': 'unknown-option', 'query': 'blue hair', 'limti': 5}, 'unknown-option', 'FAIL'),
        entry({'case_id': 'empty-source', 'query': 'blue hair', 'source': ''}, 'empty-source', 'FAIL'),
    ]
    if modular:
        cases.extend([
            entry({'case_id': 'missing-pack', 'query': 'blue hair',
                   'source': 'not-installed-for-tool-smoke'}, 'missing-pack', 'FAIL'),
            entry({'case_id': 'bad-source-member', 'query': 'blue hair',
                   'source': ['danbooru', '']}, 'bad-source-member', 'FAIL'),
        ])
    cases.append(entry({'case_id': ' 結尾-验证😀 ', 'query': '初音ミク', 'limit': 5}, ' 結尾-验证😀 ', 'PASS'))
    return cases


def write_new_json(path, data):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run(executable, output, config=None, database=None, manifest=None):
    executable, output = Path(executable).resolve(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    modular = config is not None
    argv = [str(executable)]
    if modular:
        argv.extend(['--config', str(Path(config).resolve())])
    else:
        argv.extend([str(Path(database).resolve()), str(Path(manifest).resolve())])
    cases = request_sequence(modular)
    lines = [case['input'] if isinstance(case['input'], str) else
             json.dumps(case['input'], ensure_ascii=False, separators=(',', ':')) for case in cases]
    input_bytes = ('\n'.join(lines) + '\n').encode('utf-8')
    with (output / 'requests.jsonl').open('xb') as stream:
        stream.write(input_bytes)
    report = {'schema': 'sakura-tool-resident-recovery-native-v1', 'status': 'FAIL',
              'mode': 'modular' if modular else 'monolithic', 'command': argv,
              'input_lines': len(lines), 'processes_started': 1, 'automatic_retries': 0,
              'wire_limit_bytes': MAX_BYTES, 'cases': [],
              'oversize_and_fatal_injection_scope': 'separate small native/loop fixture evidence required'}
    started = time.perf_counter()
    environment = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    try:
        process = subprocess.run(argv, input=input_bytes, capture_output=True,
                                 timeout=180, env=environment, check=False)
        for name in ('stdout', 'stderr'):
            with (output / (name + '.raw')).open('xb') as stream:
                stream.write(getattr(process, name))
        raw_lines = process.stdout.splitlines(keepends=True)
        if any(not line.endswith(b'\n') or len(line) > MAX_BYTES for line in raw_lines):
            raise ValueError('resident sent an incomplete or oversized protocol line')
        responses = [json.loads(line.decode('utf-8')) for line in raw_lines]
        opened = [record for record in responses if record.get('event') == 'opened']
        business = [record for record in responses if record.get('event') != 'opened']
        report.update(exit=process.returncode, stdout_bytes=len(process.stdout),
                      stderr_bytes=len(process.stderr), opened_events=len(opened),
                      business_responses=len(business), opened=opened,
                      wall_ms=(time.perf_counter() - started) * 1000)
        if process.returncode != 0 or len(opened) != 1 or len(business) != len(cases):
            raise ValueError('resident exited early/restarted/missed or duplicated responses')
        for expected, actual in zip(cases, business, strict=True):
            row = {'expected_case_id': expected['expected_case_id'], 'case_id': actual.get('case_id'),
                   'status': actual.get('status'), 'expected_status': expected['expected_status'],
                   'error': actual.get('error'), 'retries': actual.get('retries'),
                   'timings_ms': actual.get('timings_ms', {})}
            row['PASS'] = (row['case_id'] == row['expected_case_id']
                           and row['status'] == row['expected_status']
                           and (row['status'] == 'PASS' or row['retries'] == 0))
            if actual.get('status') == 'FAIL':
                row['PASS'] &= (isinstance(actual.get('error'), str) and bool(actual['error'])
                                and isinstance(actual.get('message'), str))
            elif actual.get('timings_ms', {}).get('total', 5001) > 5000:
                row['PASS'] = False
            report['cases'].append(row)
        pass_responses = [record for record in business if record.get('status') == 'PASS']
        session_count = opened[0].get('open_timings_ms', {}).get('model_sessions')
        encoding_counts = [record.get('timings_ms', {}).get('process_query_encodings')
                           for record in pass_responses]
        query_counts = [record.get('timings_ms', {}).get('query_encodings') for record in pass_responses]
        report['encoding_evidence'] = {'model_sessions': session_count,
                                       'valid_request_encodings': query_counts,
                                       'process_query_encodings': encoding_counts}
        report['single_session_and_encoding_pass'] = (
            session_count == 1 and encoding_counts == list(range(1, len(pass_responses) + 1))
            and all(count == 1 for count in query_counts))
        report['status'] = ('PASS' if all(row['PASS'] for row in report['cases'])
                            and report['single_session_and_encoding_pass'] else 'FAIL')
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        if isinstance(error, subprocess.TimeoutExpired):
            for name in ('stdout', 'stderr'):
                data = getattr(error, name)
                if isinstance(data, bytes):
                    with (output / (name + '.timeout.raw')).open('xb') as stream:
                        stream.write(data)
    finally:
        write_new_json(output / 'summary.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--config')
    parser.add_argument('--database')
    parser.add_argument('--manifest')
    args = parser.parse_args()
    if bool(args.config) == bool(args.database or args.manifest):
        parser.error('choose --config OR both --database and --manifest')
    if not args.config and not (args.database and args.manifest):
        parser.error('--database and --manifest are both required for monolithic mode')
    report = run(args.executable, args.output, args.config, args.database, args.manifest)
    print(json.dumps({'status': report['status'], 'mode': report['mode'], 'exit': report.get('exit'),
                      'responses': report.get('business_responses'),
                      'encoding_evidence': report.get('encoding_evidence'),
                      'error': report.get('error')}, ensure_ascii=True))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
