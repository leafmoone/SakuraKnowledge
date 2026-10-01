"""Offline exact pilot. CLI: python -m tools.p4_exact_pilot COMMAND --job JOB.json.

COMMAND: build, query, benchmark. Required job keys: model (a/b), device
(cpu/cuda), threads, batch_size, summary, summary_sha256, corpus, corpus_sha256,
chunks, chunks_manifest, chunks_manifest_sha256, gold, gold_sha256, authorization,
index, output. All paths are repository-relative and locally contained.
Optional benchmark_scope: query_embedding (default) or total_retrieve;
timeout_seconds: 1800. No sample-count override: all 120 sorted gold cases once.
Authorization: authorized=true, gold_status=FROZEN_PRE_EMBEDDING, and matching
summary_sha256, chunks_manifest_sha256, gold_sha256, corpus_sha256, chunks_sha256.
Chunks CLI model-config is a wrapper {repository, revision, contract}; contract
itself is flat and must equal the reviewed model contract, not that wrapper.
Fresh includes interpreter/imports/input and model verification/model load;
only total_retrieve loads/verifies the index. Neither mode claims disk-cold IO.
No downloads, fallback, truncation, ANN, fusion, quality tuning, or metrics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = 'FROZEN_PRE_EMBEDDING'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def local(path):
    path = Path(path)
    require(not path.is_absolute() and '..' not in path.parts, 'path must be repository-relative')
    result = (ROOT / path).resolve()
    require(result.is_relative_to(ROOT.resolve()), 'local path escape')
    return result


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True, allow_nan=False)
        f.write('\n')


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def bound(path, expected):
    require(re.fullmatch('[0-9a-f]{64}', expected or '') is not None, 'invalid SHA256')
    require(sha(path) == expected, f'SHA256 mismatch: {path}')


def prepare(job):
    """Validate frozen inputs before importing any inference dependency."""
    require(job['model'] in ('a', 'b'), 'model must be a or b')
    require(job['device'] in ('cpu', 'cuda'), 'explicit cpu/cuda device required')
    for key in ('threads', 'batch_size'):
        require(type(job[key]) is int and job[key] > 0, f'invalid {key}')
    for key in ('summary', 'corpus', 'gold', 'chunks_manifest'):
        bound(local(job[key]), job[key + '_sha256'])
    for key in ('chunks', 'authorization', 'index', 'output'):
        local(job[key])
    require('samples' not in job, 'samples override forbidden: formal run uses all 120 cases')
    require(job.get('benchmark_scope', 'query_embedding') in ('query_embedding', 'total_retrieve'),
            'invalid benchmark_scope')
    manifest = load(local(job['chunks_manifest']))
    bound(local(job['chunks']), manifest['chunks_sha256'])
    require(manifest['corpus_sha256'] == job['corpus_sha256'], 'chunk corpus mismatch')
    require(manifest['document_count'] == 50000, 'pilot must contain 50k documents')
    require(manifest['chunk_count'] > 0, 'empty chunks')
    auth = load(local(job['authorization']))
    require(auth.get('authorized') is True and auth.get('gold_status') == FROZEN,
            'parent frozen-gold authorization required')
    for key in ('gold_sha256', 'corpus_sha256', 'summary_sha256', 'chunks_manifest_sha256'):
        require(auth.get(key) == job[key], f'authorization mismatch: {key}')
    require(auth.get('chunks_sha256') == manifest['chunks_sha256'], 'authorization chunk mismatch')
    summary = load(local(job['summary']))
    require(summary['status'] == 'PASS', 'model freeze failed')
    model = summary['models'][job['model']]
    require(re.fullmatch('[0-9a-f]{40}', model['revision']) is not None, 'unpinned model')
    bound(local(model['contract']['path']), model['contract']['file_sha256'])
    contract = load(local(model['contract']['path']))
    require(contract == model['contract']['reviewed'], 'contract mismatch')
    inventory = manifest['tokenizer_inventory']
    require(canonical_hash(inventory) == manifest['tokenizer_inventory_sha256'],
            'tokenizer inventory mismatch')
    require(inventory['repository'] == model['repository'] and
            inventory['revision'] == model['revision'] and inventory['contract'] == contract,
            'chunks use another model contract')
    require(inventory['truncation'] is False and inventory['padding'] is False,
            'chunk tokenizer truncation/padding forbidden')
    files = {x['path']: x for x in model['obtained_receipt']['files']}
    require(inventory['tokenizer_json_sha256'] == files['tokenizer.json']['sha256'],
            'chunk tokenizer hash mismatch')
    for name in contract['tokenizer_files']:
        require(name in files, 'missing tokenizer asset')
    directory = local(model['asset_directory'])
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    require(actual == set(files), 'unverified or missing model asset')
    for name, record in files.items():
        path = directory / name
        require(not Path(name).is_absolute() and path.resolve().is_relative_to(directory), 'asset path escape')
        require(path.stat().st_size == record['size'], 'asset size mismatch')
        bound(path, record['sha256'])
    require(contract['pooling'] in ('mean', 'cls') and contract['normalize'] is True,
            'unsupported embedding contract')
    gold = load(local(job['gold']))
    require(gold['status'] == FROZEN, 'gold not frozen')
    require(gold['base_snapshot_sha256'] == manifest['base_snapshot_sha256'], 'snapshot mismatch')
    cases = gold['cases']
    require(len(cases) == 120, 'exactly 120 frozen gold cases required')
    require(all(isinstance(c['case_id'], str) and isinstance(c['query'], str) and
                c['query'].strip() for c in cases), 'invalid gold query')
    require(len({c['case_id'] for c in cases}) == len(cases), 'duplicate gold case')
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ[name] = str(job['threads'])
    return model, contract, manifest, sorted(cases, key=lambda c: c['case_id'])


def checked_tokens(raw, wrapper, texts, prefix, maximum):
    """Compare IDs, not lengths, both canonical passage and prefixed/special input."""
    require(raw.truncation is None and wrapper.backend_tokenizer.truncation is None,
            'tokenizer truncation enabled')
    for special, values in ((False, texts), (True, [prefix + t for t in texts])):
        encoded = wrapper(values, padding=False, truncation=False, add_special_tokens=special)
        expected = [raw.encode(t, add_special_tokens=special).ids for t in values]
        require(encoded['input_ids'] == expected, 'raw/HF tokenizer ID mismatch')
    counts = [len(ids) for ids in encoded['input_ids']]
    require(all(0 < n <= maximum for n in counts), 'actual inference token budget exceeded; truncation forbidden')
    require(raw.truncation is None and wrapper.backend_tokenizer.truncation is None,
            'tokenizer truncation enabled')
    return encoded, counts


def frozen_tokenizers(directory):
    """Load a previously verified local tokenizer without model-specific rebuilding."""
    import tokenizers
    from transformers import PreTrainedTokenizerFast

    raw = tokenizers.Tokenizer.from_file(str(directory / 'tokenizer.json'))
    raw.no_truncation()
    raw.no_padding()
    wrapper = PreTrainedTokenizerFast.from_pretrained(
        str(directory), local_files_only=True, trust_remote_code=False)
    require(wrapper.is_fast, 'fast tokenizer required')
    wrapper.backend_tokenizer.no_truncation()
    wrapper.backend_tokenizer.no_padding()
    require(json.loads(raw.to_str()) ==
            json.loads(wrapper.backend_tokenizer.to_str()),
            'frozen tokenizer backend mismatch')
    return raw, wrapper


class LocalEncoder:
    def __init__(self, model, contract, device, threads):
        import tokenizers
        import torch
        import transformers
        from transformers import AutoModel
        require(device in ('cpu', 'cuda'), 'unsupported device')
        require(device != 'cuda' or torch.cuda.is_available(), 'requested CUDA unavailable')
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(threads)
        self.torch, self.contract, self.device = torch, contract, device
        directory = local(model['asset_directory'])
        self.raw, self.tokenizer = frozen_tokenizers(directory)
        for prefix in (contract['passage_prefix'], contract['query_prefix']):
            checked_tokens(self.raw, self.tokenizer, ['hello 日本語', 'prefix: test'],
                           prefix, contract['max_sequence_tokens'])
        self.model = AutoModel.from_pretrained(
            str(directory), local_files_only=True, trust_remote_code=False,
            weights_only=True, use_safetensors=model['repository'] != 'BAAI/bge-m3',
            torch_dtype=torch.float32).to(device).eval()
        require(all(p.dtype == torch.float32 for p in self.model.parameters()), 'non-float32 weights')
        self.info = {'provider': 'huggingface/torch', 'torch': torch.__version__,
                     'transformers': transformers.__version__, 'tokenizers': tokenizers.__version__,
                     'requested_device': device, 'actual_device': str(next(self.model.parameters()).device),
                     'actual_dtype': str(next(self.model.parameters()).dtype),
                     'threads': torch.get_num_threads(), 'interop_threads': torch.get_num_interop_threads()}

    def encode(self, texts, query=False):
        torch, contract = self.torch, self.contract
        encoded, counts = checked_tokens(self.raw, self.tokenizer, texts,
            contract['query_prefix' if query else 'passage_prefix'], contract['max_sequence_tokens'])
        batch = self.tokenizer.pad(encoded, padding=True, return_tensors='pt').to(self.device)
        with torch.inference_mode():
            hidden = self.model(**batch).last_hidden_state
            if contract['pooling'] == 'mean':
                mask = batch['attention_mask'].unsqueeze(-1)
                vectors = (hidden * mask).sum(1) / mask.sum(1)
            else:
                vectors = hidden[:, 0]
            vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
        result = vectors.cpu().numpy()
        validate_vectors(result, contract['dimension'])
        return result, counts


def validate_vectors(vectors, dimension):
    import numpy as np
    require(vectors.ndim == 2 and vectors.shape[1] == dimension and vectors.dtype == np.float32,
            'vector shape/dtype mismatch')
    require(np.isfinite(vectors).all(), 'nonfinite vectors')
    require(np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5), 'vectors not normalized')


def rows(path):
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            yield json.loads(line)


def provenance(job, model, manifest):
    return {'model': job['model'], 'repository': model['repository'], 'revision': model['revision'],
            'model_inventory_sha256': model['obtained_receipt']['inventory_sha256'],
            'contract_sha256': model['contract']['file_sha256'],
            'summary_sha256': job['summary_sha256'], 'gold_sha256': job['gold_sha256'],
            'corpus_sha256': job['corpus_sha256'], 'chunks_sha256': manifest['chunks_sha256'],
            'chunks_manifest_sha256': sha(local(job['chunks_manifest'])),
            'tokenizer_inventory_sha256': manifest['tokenizer_inventory_sha256']}


class DiskMapping:
    """Read-only SQLite mapping; only one candidate block is materialized."""
    def __init__(self, path):
        self.connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        self.size = self.connection.execute('SELECT count(*) FROM chunks').fetchone()[0]

    def __len__(self):
        return self.size

    def block(self, offset, count):
        return [json.loads(r[0]) for r in self.connection.execute(
            'SELECT metadata FROM chunks WHERE position>=? AND position<? ORDER BY position',
            (offset, offset + count))]


def build(job, prepared, encoder_factory=LocalEncoder):
    import numpy as np
    start = time.perf_counter()
    model, contract, manifest, _ = prepared
    output = local(job['index'])
    output.mkdir(parents=True, exist_ok=False)
    encoder = encoder_factory(model, contract, job['device'], job['threads'])
    shape = (manifest['chunk_count'], contract['dimension'])
    vectors = np.lib.format.open_memmap(output / 'vectors.npy', mode='w+', dtype='float32', shape=shape)
    batch, offset, max_tokens = [], 0, 0
    mapping = sqlite3.connect(output / 'mapping.sqlite')
    mapping.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY, metadata TEXT NOT NULL)')
    def flush():
        nonlocal offset, max_tokens
        result, counts = encoder.encode([r['text'] for r in batch])
        validate_vectors(result, contract['dimension'])
        require(len(result) == len(batch) and offset + len(batch) <= shape[0], 'chunk count mismatch')
        require(counts == [r['inference_token_count'] for r in batch], 'chunk token count mismatch')
        vectors[offset:offset + len(batch)] = result
        mapping.executemany('INSERT INTO chunks VALUES (?, ?)',
            ((offset + i, json.dumps({k: row[k] for k in
              ('entry_key', 'chunk_id', 'document_id', 'source_id', 'evidence_id')}))
             for i, row in enumerate(batch)))
        mapping.commit()
        offset += len(batch)
        max_tokens = max(max_tokens, *counts)
        batch.clear()
    try:
        for row in rows(local(job['chunks'])):
            require(hashlib.sha256(row['text'].encode()).hexdigest() == row['text_sha256'], 'chunk text mismatch')
            require(row['tokenizer_inventory_sha256'] == manifest['tokenizer_inventory_sha256'], 'chunk inventory mismatch')
            batch.append(row)
            if len(batch) == job['batch_size']:
                flush()
        if batch:
            flush()
    finally:
        mapping.close()
    require(offset == shape[0], 'chunk count mismatch')
    vectors.flush()
    bound(local(job['chunks']), manifest['chunks_sha256'])
    elapsed = time.perf_counter() - start
    model_bytes = sum(r['size'] for r in model['obtained_receipt']['files'])
    index_bytes = sum((output / n).stat().st_size for n in ('vectors.npy', 'mapping.sqlite'))
    save(output / 'index.json', {'schema': 'p4-exact-index-v2', 'provenance': provenance(job, model, manifest),
         'shape': shape, 'dtype': 'float32', 'max_actual_tokens': max_tokens, 'encoder': encoder.info,
         'build_elapsed_seconds': elapsed, 'chunks_per_second': offset / elapsed,
         'model_asset_bytes': model_bytes, 'index_payload_bytes': index_bytes,
         'model_plus_index_payload_bytes': model_bytes + index_bytes, 'memory': rss(),
         'byte_scope': 'all verified model assets plus vectors.npy and mapping.sqlite; excludes receipt',
         'vectors_sha256': sha(output / 'vectors.npy'), 'mapping_sha256': sha(output / 'mapping.sqlite')})


def open_index(job, prepared):
    import numpy as np
    directory = local(job['index'])
    for name in ('index.json', 'vectors.npy', 'mapping.sqlite'):
        require((directory / name).resolve().is_relative_to(directory), 'index path escape')
    receipt = load(directory / 'index.json')
    require(receipt['provenance'] == provenance(job, prepared[0], prepared[2]), 'index provenance mismatch')
    for filename, field in [('vectors.npy', 'vectors_sha256'), ('mapping.sqlite', 'mapping_sha256')]:
        bound(directory / filename, receipt[field])
    vectors = np.load(directory / 'vectors.npy', mmap_mode='r', allow_pickle=False)
    mapping = DiskMapping(directory / 'mapping.sqlite')
    require(list(vectors.shape) == receipt['shape'] and len(mapping) == len(vectors), 'index size mismatch')
    for offset in range(0, len(vectors), 4096):
        validate_vectors(vectors[offset:offset + 4096], prepared[1]['dimension'])
    return vectors, mapping


def exact_rank(vectors, mapping, query, depth=100, block_size=4096):
    """Exact normalized dot; entry max; ties typed key then chunk ID; <=50k entries."""
    import numpy as np
    require(block_size > 0 and depth > 0 and len(mapping) == len(vectors), 'invalid ranking input')
    validate_vectors(query.reshape(1, -1), vectors.shape[1])
    best = {}
    for offset in range(0, len(vectors), block_size):
        scores = np.einsum('ij,j->i', vectors[offset:offset + block_size], query, optimize=False)
        require(np.isfinite(scores).all(), 'nonfinite score')
        block = mapping.block(offset, len(scores)) if isinstance(mapping, DiskMapping) else mapping[offset:offset + len(scores)]
        require(len(block) == len(scores), 'mapping positions missing')
        for row, score in zip(block, scores):
            key = tuple(row['entry_key'][k] for k in ('kind', 'namespace', 'value'))
            require(all(isinstance(v, str) and v.strip() for v in key), 'invalid typed entry')
            candidate = (float(score), row['chunk_id'], row)
            previous = best.get(key)
            if previous is None:
                require(len(best) < 50000, 'more than 50k entry metadata records')
            if previous is None or (-candidate[0], candidate[1]) < (-previous[0], previous[1]):
                best[key] = candidate
    return [{'entry': dict(zip(('kind', 'namespace', 'value'), key)), 'rank': rank,
             'score': score, **{k: str(row[k]) for k in
             ('chunk_id', 'document_id', 'source_id', 'evidence_id')}}
            for rank, (key, (score, _, row)) in enumerate(
                sorted(best.items(), key=lambda x: (-x[1][0], x[0]))[:depth], 1)]


def rss():
    import psutil
    memory = psutil.Process().memory_info()
    peak = getattr(memory, 'peak_wset', None)
    source = 'Windows peak_wset'
    if peak is None:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
        source = 'getrusage ru_maxrss'
    return {'rss_bytes': memory.rss, 'peak_rss_bytes': peak, 'peak_rss_source': source}


def retrieve(encoder, case, index=None):
    start = time.perf_counter()
    query, counts = encoder.encode([case['query']], query=True)
    result = {'embedding_ms': (time.perf_counter() - start) * 1000, 'actual_tokens': counts[0]}
    if index is not None:
        start = time.perf_counter()
        result['hits'] = exact_rank(*index, query[0])
        result['exact_search_ms'] = (time.perf_counter() - start) * 1000
    return result


def measure(action, case):
    start = time.perf_counter()
    record = {'case_id': case['case_id']}
    try:
        result = action(case)
        if result:
            record.update(result)
        record['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 - Preserve failed attempts without retry.
        record.update(status='FAIL', error=f'{type(exc).__name__}: {exc}')
    record['elapsed_ms'] = (time.perf_counter() - start) * 1000
    try:
        record.update(rss())
    except Exception as exc:  # noqa: BLE001 - Preserve memory measurement failures.
        record.update(status='FAIL', rss_error=str(exc))
    return record


def summarize(records):
    attempts = [r for r in records if r['status'] != 'NOT_RUN']
    values = sorted(r['elapsed_ms'] for r in attempts)
    def percentile(p):
        if not values:
            return None
        position = (len(values) - 1) * p
        low, high = math.floor(position), math.ceil(position)
        return values[low] + (values[high] - values[low]) * (position - low)
    return {'attempts': len(attempts), 'not_run': len(records) - len(attempts),
            'failures': sum(r['status'] != 'PASS' for r in attempts),
            'p50_ms': percentile(.50), 'p95_ms': percentile(.95),
            'percentile_policy': 'linear interpolation (n-1)*p; attempted failures included; NOT_RUN excluded',
            'peak_rss_bytes': max((r.get('peak_rss_bytes', 0) for r in attempts), default=0)}


def not_run(cases):
    return [{'case_id': c['case_id'], 'status': 'NOT_RUN'} for c in cases]


def worker(job, mode, case_id=None):
    cases = []
    try:
        prepared = prepare(job)
        cases = prepared[3]
        encoder = LocalEncoder(prepared[0], prepared[1], 'cpu', job['threads'])
        index = open_index(job, prepared) if job.get('benchmark_scope') == 'total_retrieve' else None
    except Exception as exc:  # noqa: BLE001 - Setup is never a formal attempt.
        return {'setup': {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'},
                'warmups': [], 'samples': not_run(cases), 'summary': summarize(not_run(cases))}
    def action(case):
        result = retrieve(encoder, case, index)
        result.pop('hits', None)
        return result
    if mode == 'fresh':
        case = next(c for c in cases if c['case_id'] == case_id)
        return {'setup': {'status': 'PASS'}, 'encoder': encoder.info, **measure(action, case)}
    warmups = [measure(action, c) for c in cases[:2]]
    samples = [measure(action, c) for c in cases] if all(r['status'] == 'PASS' for r in warmups) else not_run(cases)
    return {'setup': {'status': 'PASS'}, 'encoder': encoder.info, 'warmups': warmups,
            'samples': samples, 'summary': summarize(samples)}


def benchmark(job, job_path, prepared):
    require('samples' not in job, 'samples override forbidden: formal run uses all 120 cases')
    cases = prepared[3]
    require(len(cases) == 120, 'exactly 120 frozen gold cases required')
    def launch(mode, case=None):
        command = [sys.executable, '-m', 'tools.p4_exact_pilot', '_worker', '--job', str(job_path), '--mode', mode]
        if case:
            command += ['--case-id', case['case_id']]
        start = time.perf_counter()
        try:
            process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                     timeout=job.get('timeout_seconds', 1800), check=False)
            require(process.returncode == 0, process.stderr[-4000:])
            record = json.loads(process.stdout)
        except Exception as exc:  # noqa: BLE001 - Unknown worker phase is not a fabricated query attempt.
            record = {'setup': {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'},
                      'worker_phase': 'unknown; no completed attempt record'}
        record['process_elapsed_ms'] = (time.perf_counter() - start) * 1000
        if mode == 'fresh':
            if record['setup']['status'] == 'PASS':
                record['query_elapsed_ms'] = record['elapsed_ms']
                record['elapsed_ms'] = record['process_elapsed_ms']
            else:
                record['status'] = 'NOT_RUN'
            record['case_id'] = case['case_id']
        return record
    reused = launch('reused')
    if reused['setup']['status'] != 'PASS':
        reused.update(warmups=[], samples=not_run(cases), summary=summarize(not_run(cases)))
    fresh_warmups = []
    for case in cases[:2]:
        fresh_warmups.append(launch('fresh', case))
        if fresh_warmups[-1]['status'] != 'PASS':
            break
    fresh = []
    if all(r['status'] == 'PASS' for r in fresh_warmups):
        for case in cases:
            record = launch('fresh', case)
            fresh.append(record)
            if record['status'] == 'NOT_RUN':
                break
    fresh.extend(not_run(cases[len(fresh):]))
    return {'schema': 'p4-cpu-feasibility-v2', 'provenance': provenance(job, prepared[0], prepared[2]),
            'requested_device': 'cpu', 'bulk_requested_device': job['device'], 'threads': job['threads'],
            'benchmark_scope': job.get('benchmark_scope', 'query_embedding'),
            'disk_cold': False, 'retries': 0, 'reused': reused,
            'fresh': {'warmups': fresh_warmups, 'samples': fresh, 'summary': summarize(fresh)},
            'timing_scope': 'reused excludes setup; fresh includes interpreter/imports/input and model verification/model load; total_retrieve additionally verifies/loads index; embedding and exact search independently timed',
            'rss_scope': 'process lifetime high-water RSS, including setup; rss_bytes is instantaneous, not peak'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'query', 'benchmark', '_worker'))
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--mode', choices=('fresh', 'reused'))
    parser.add_argument('--case-id')
    args = parser.parse_args(argv)
    job = load(args.job)
    if args.command == '_worker':
        print(json.dumps(worker(job, args.mode, args.case_id), allow_nan=False))
        return
    prepared = prepare(job)
    if args.command == 'build':
        build(job, prepared)
    elif args.command == 'benchmark':
        save(local(job['output']), benchmark(job, args.job.resolve(), prepared))
    else:
        try:
            encoder = LocalEncoder(prepared[0], prepared[1], job['device'], job['threads'])
            index = open_index(job, prepared)
        except Exception as exc:  # noqa: BLE001 - Preserve setup failure and zero attempts.
            save(local(job['output']), {'setup': {'status': 'FAIL', 'error': str(exc)},
                 'cases': not_run(prepared[3]), 'summary': summarize(not_run(prepared[3]))})
            return
        cases = [measure(lambda c: retrieve(encoder, c, index), case) for case in prepared[3]]
        save(local(job['output']), {'schema': 'p4-exact-results-v2', 'exact_reference': True,
             'setup': {'status': 'PASS'}, 'provenance': provenance(job, prepared[0], prepared[2]),
             'encoder': encoder.info, 'depth': 100,
             'aggregation': 'maximum chunk dot score per typed entry', 'cases': cases})


if __name__ == '__main__':
    main()
