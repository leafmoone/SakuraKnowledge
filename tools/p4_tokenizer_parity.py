"""Full frozen-pilot tokenizer parity, without model loading or embedding."""
import argparse
import importlib.metadata
import time

from tools import p4_exact_pilot as pilot


def scan(raw, wrapper, chunks, cases, contract, expected_count):
    count = maximum = 0
    for row in chunks:
        _, counts = pilot.checked_tokens(
            raw, wrapper, [row['text']], contract['passage_prefix'],
            contract['max_sequence_tokens'])
        pilot.require(counts == [row['inference_token_count']],
                      f'chunk token count mismatch at row {count}')
        maximum = max(maximum, counts[0])
        count += 1
    pilot.require(count == expected_count, 'chunk count mismatch')
    queries = []
    for case in cases:
        _, counts = pilot.checked_tokens(
            raw, wrapper, [case['query']], contract['query_prefix'],
            contract['max_sequence_tokens'])
        queries.append({'case_id': case['case_id'], 'inference_token_count': counts[0]})
    return {'chunk_count': count, 'max_passage_tokens': maximum,
            'query_count': len(queries), 'queries': queries}


def run(job_path, output):
    # Reserve receipt before work: never overwrite prior failure or success.
    with output.open('x', encoding='utf-8') as receipt:
        import json

        started = time.perf_counter()
        result = {'schema': 'p4-tokenizer-parity-v1', 'status': 'FAIL',
                  'model_loaded': False, 'embedding_executed': False}
        try:
            job_hash = pilot.sha(job_path)
            job = pilot.load(job_path)
            auth_hash = pilot.sha(pilot.local(job['authorization']))
            model, contract, manifest, cases = pilot.prepare(job)
            result.update({'job_sha256': job_hash, 'authorization_sha256': auth_hash,
                           'model': job['model'], 'repository': model['repository'],
                           'revision': model['revision'],
                           'provenance': pilot.provenance(job, model, manifest)})
            raw, wrapper = pilot.frozen_tokenizers(pilot.local(model['asset_directory']))
            result['versions'] = {name: importlib.metadata.version(name)
                                  for name in ('transformers', 'tokenizers')}
            result['scan'] = scan(raw, wrapper, pilot.rows(pilot.local(job['chunks'])),
                                  cases, contract, manifest['chunk_count'])
            pilot.require(pilot.prepare(job) == (model, contract, manifest, cases),
                          'frozen input changed during scan')
            pilot.bound(job_path, job_hash)
            pilot.bound(pilot.local(job['authorization']), auth_hash)
            result['status'] = 'PASS'
        except Exception as exc:  # noqa: BLE001 -- retain failure receipt and return nonzero
            result['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        result['elapsed_seconds'] = time.perf_counter() - started
        json.dump(result, receipt, ensure_ascii=False, sort_keys=True, allow_nan=False)
        receipt.write('\n')
    return 0 if result['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    return run(pilot.local(args.job), pilot.local(args.output))


if __name__ == '__main__':
    raise SystemExit(main())
