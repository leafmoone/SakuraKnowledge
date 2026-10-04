"""Supported ordinary P4 builder lifecycle."""
import argparse
import hashlib
import heapq
import json
import math
import os
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter
from contextlib import closing
from pathlib import Path

from tools import p4_full_acceptance as acceptance
from tools import p4_full_preflight as full

ROOT = full.ROOT
OUTPUT = 'build/p4-current-semantic-v1'
ASSET_SPEC = 'configs/p4-current-assets.json'
EXECUTOR_ORIGIN = 'clean_room_full_build_executor_v1'
require = full.require
PRODUCTS = ('chunks.sqlite', 'corpus.jsonl', 'vectors.npy', 'vectors.usearch',
            'sample.json', 'manifest.json', 'execution-receipt.json')
TRANSIENTS = ('chunks.sqlite-journal', 'chunks.sqlite-wal', 'chunks.sqlite-shm')
EXECUTOR_PATHS = {'tools/p4_full_build.py', 'tests/test_p4_full_build.py',
                  'docs/p4-full-semantic-v1.md', 'docs/STAGE_STATUS.md', 'rust/src/semantic.rs',
                  'tools/p4_full_acceptance.py', 'tests/test_p4_full_acceptance.py'}
APPROVED_RUST_HARNESS_SHA256 = '8a5306d202fe4a7ee87a14d5cf05407a7b28ed18951ecf5a55c18566af876a78'


def read_json(path):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def save_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(full.chunks.canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def binding(path, directory):
    path = Path(path).resolve(strict=True)
    name = (os.path.relpath(path, directory).replace('\\', '/')
            if path.is_relative_to(Path(ROOT).resolve()) else path.as_posix())
    return {'path': name, 'size': path.stat().st_size, 'sha256': full.exact.sha(path)}


def validate_partial_vectors(path, *, rows, dimension=1024):
    """Read-only vector validation; no historical receipt or attempt authority."""
    import numpy as np
    vectors = np.load(path, mmap_mode='r', allow_pickle=False)
    try:
        require(vectors.shape == (rows, dimension) and vectors.dtype == np.float32,
                'vector shape/dtype mismatch')
        max_error = 0.0
        for start in range(0, rows, 1024):
            batch = vectors[start:start + 1024]
            require(np.isfinite(batch).all(), 'nonfinite vectors')
            error = float(np.max(np.abs(np.linalg.norm(batch, axis=1) - 1)))
            require(error <= 1e-5, 'vector normalization failed')
            max_error = max(max_error, error)
        return {'ROWS': rows, 'DIM': dimension, 'DTYPE': 'float32', 'FINITE': 'PASS',
                'NORMALIZATION': 'PASS', 'max_norm_error': max_error}
    finally:
        close_memmap(vectors)


def partial_parity_metrics(actual, expected, actual_tokens, expected_tokens):
    import numpy as np
    require(actual.shape == expected.shape and actual_tokens == expected_tokens, 'sample shape/token mismatch')
    require(actual.dtype == expected.dtype == np.float32 and np.isfinite(actual).all() and
            np.isfinite(expected).all(), 'sample FP32/finite mismatch')
    norms, expected_norms = np.linalg.norm(actual, axis=1), np.linalg.norm(expected, axis=1)
    require(np.all(expected_norms > 0) and np.all(norms > 0), 'sample zero norms')
    metrics = {'max_component_error': float(np.max(np.abs(actual - expected))),
        'minimum_cosine': float(np.min(np.sum(actual * expected, axis=1) / (norms * expected_norms))),
        'max_norm_error': float(max(np.max(np.abs(norms - 1)), np.max(np.abs(expected_norms - 1))))}
    require(metrics['max_component_error'] <= 1e-4 and metrics['minimum_cosine'] >= .99999 and
            metrics['max_norm_error'] <= 1e-5, 'CPU sample parity failed')
    return metrics


def partial_cpu_worker(request):
    """Fresh-process CPU parity over explicit current products, never historical authority."""
    import numpy as np
    verified = full.inventory()
    require(verified['inventory_sha256'] == request['inventory_sha256'], 'CPU model inventory mismatch')
    require(verified['manifest']['tokenizer_inventory_sha256'] == request['tokenizer_inventory_sha256'],
            'CPU tokenizer mismatch')
    encoder = full.exact.LocalEncoder(verified['model'], verified['contract'], 'cpu', 8)
    info = encoder.info
    require(info['actual_device'] == 'cpu' and info['actual_dtype'] == 'torch.float32' and
            info['threads'] == info['interop_threads'] == 8, 'CPU actual configuration mismatch')
    output = full.contained(request['product_directory'])
    positions = request['positions']
    require(positions and positions == sorted(set(positions)) and all(type(p) is int and p >= 0 for p in positions),
            'CPU positions invalid')
    vectors = np.load(output / 'vectors.npy', mmap_mode='r', allow_pickle=False)
    metrics = {'max_component_error': 0.0, 'minimum_cosine': 1.0, 'max_norm_error': 0.0}
    try:
        with full.readonly(output / 'chunks.sqlite') as db:
            for start in range(0, len(positions), 8):
                selected = positions[start:start + 8]
                rows = []
                for pos in selected:
                    row = db.execute('SELECT row_json FROM projection WHERE position=?', (pos,)).fetchone()
                    require(row is not None and pos < len(vectors), 'CPU mapping position missing')
                    rows.append(json.loads(row[0]))
                expected, tokens = encoder.encode([row['text'] for row in rows])
                values = partial_parity_metrics(np.asarray(vectors[selected]), expected,
                    [row['inference_token_count'] for row in rows], tokens)
                metrics['max_component_error'] = max(metrics['max_component_error'], values['max_component_error'])
                metrics['minimum_cosine'] = min(metrics['minimum_cosine'], values['minimum_cosine'])
                metrics['max_norm_error'] = max(metrics['max_norm_error'], values['max_norm_error'])
    finally:
        close_memmap(vectors)
    return {'schema': 'p4-cpu-parity-response-v1', 'status': 'PASS',
        'request_sha256': full.exact.canonical_hash(request), 'positions': positions,
        'sample_count': len(positions), 'process_id': os.getpid(), 'encoder': info, 'metrics': metrics}


def run_partial_cpu_worker(request):
    import sys
    command = [sys.executable, '-X', 'utf8', '-c',
        'import json,sys; from tools import p4_full_build as b; print(json.dumps(b.partial_cpu_worker(json.load(sys.stdin)),sort_keys=True))']
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    child = subprocess.run(command, input=full.chunks.canonical(request), cwd=ROOT, env=env,
                           capture_output=True, check=False)
    require(child.returncode == 0, 'fresh CPU worker failed: ' + child.stderr.decode('utf8', errors='replace'))
    response = read_json_bytes(child.stdout)
    require(response['status'] == 'PASS' and response['request_sha256'] == full.exact.canonical_hash(request) and
            response['positions'] == request['positions'] and response['sample_count'] == len(request['positions']) and
            response['process_id'] != os.getpid(), 'CPU response coverage mismatch')
    info = response['encoder']
    require(info['actual_device'] == 'cpu' and info['actual_dtype'] == 'torch.float32' and
            info['threads'] == info['interop_threads'] == 8, 'CPU response actual thread/device mismatch')
    metrics = response['metrics']
    require(all(math.isfinite(metrics[k]) for k in ('max_component_error', 'minimum_cosine', 'max_norm_error')) and
            metrics['max_component_error'] <= 1e-4 and metrics['minimum_cosine'] >= .99999 and
            metrics['max_norm_error'] <= 1e-5, 'CPU response parity failed')
    return response


def read_json_bytes(value):
    return json.loads(value, parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def index_factory(declaration):
    from importlib.metadata import version

    from usearch.index import Index
    require(version('usearch') == declaration['ann']['version'], 'USearch version mismatch')
    ann = declaration['ann']
    return Index(ndim=declaration['encoder']['dimension'], metric=ann['metric'], dtype=ann['dtype'],
                 connectivity=ann['connectivity'], expansion_add=ann['expansion_add'],
                 expansion_search=ann['expansion_search'])


def close_index(index):
    # Native views own mappings on Windows. Optional cleanup must not mask failures.
    for name in ('reset', 'close'):
        try:
            method = getattr(index, name, None)
            if callable(method):
                method()
        except Exception:  # noqa: BLE001, S110
            pass


def optional_telemetry(index):
    result = {'optional': True, 'process_rss': 'NOT_AVAILABLE'}
    for name in ('memory_usage', 'hardware_acceleration'):
        try:
            value = getattr(index, name)
            value = value() if callable(value) else value
            json.dumps(value, allow_nan=False)
            result[name] = value
        except Exception:  # noqa: BLE001
            result[name] = 'NOT_AVAILABLE'
    return result


def close_memmap(value):
    if value is not None:
        try:
            if value.flags.writeable:
                value.flush()
        finally:
            value._mmap.close()


def phase(report, name):
    report['phase'] = name
    report.setdefault('phases', []).append(name)


def attempt_lock(output, attempt_number=1):
    return output.with_name(output.name + '.build.lock')


def reserve(output, report):
    require(not output.exists(), 'output already exists; no overwrite')
    lock = attempt_lock(output)
    require(not lock.exists(), 'attempt already reserved')
    output.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('xb') as stream:
        import uuid
        info = os.fstat(stream.fileno())
        report['lock_token'] = uuid.uuid4().hex
        report.update(attempts=1, attempt_number=1, attempt_reserved=True, attempt_lock=str(lock),
                      lock_identity=[info.st_dev, info.st_ino])
        stream.write(full.chunks.canonical({'executor_origin': EXECUTOR_ORIGIN, 'token': report['lock_token']}) + b'\n')
        stream.flush(); os.fsync(stream.fileno())
    output.mkdir(exist_ok=False)


def select_sample(db, n, *, synthetic=False):
    boundary = set(range(min(100, n))) | set(range(max(0, n - 100), n))
    ranked = heapq.nsmallest(1000, (
        (hashlib.sha256(('p4-full-sample-v1:' + cid).encode()).hexdigest(), pos)
        for pos, cid in db.execute('SELECT position,chunk_id FROM chunks ORDER BY position')
        if pos not in boundary and pos < n))
    selected = sorted(boundary | {pos for _, pos in ranked})
    require(synthetic or len(selected) >= 1200, 'sample requires >=1200 unique chunks; no fallback')
    return {'positions': selected, 'first': list(range(min(100, n))),
            'last': list(range(max(0, n - 100), n)), 'hash_ranked': [p for _, p in ranked],
            'rule': 'first100,last100,boundary-excluded-sha256-ranked1000', 'synthetic': synthetic}


def verify_mapping(db, output, tokenizer, inventory_sha, count):
    """Bounded exact audit; aggregate extrema cannot prove position or join closure."""
    n = count['actual_chunks']
    for table in ('chunks', 'projection'):
        total = 0
        for total, (position,) in enumerate(db.execute(f'SELECT position FROM {table} ORDER BY position'), 1):
            require(type(position) is int and position == total - 1, 'mapping positions mismatch')
        require(total == n, 'mapping positions mismatch')
    rows = iter(db.execute('''SELECT c.position,c.chunk_id,c.document_id,c.entry_id,c.kind,c.namespace,
        c.value,c.source_id,c.evidence_id,c.text_sha256,c.token_start,c.token_end,c.metadata,p.row_json
        FROM chunks c JOIN projection p ON c.position=p.position ORDER BY c.position'''))
    total, previous, documents = 0, None, 0
    census, digest = Counter(), hashlib.sha256()
    with (output / 'corpus.jsonl').open('rb') as corpus:
        while True:
            line = corpus.readline(count['max_document_text_bytes'] * 6 + 65537)
            if not line:
                break
            require(line.endswith(b'\n'), 'corpus record exceeds bound')
            document = json.loads(line)
            require(line == full.chunks.canonical(document) + b'\n', 'corpus canonical bytes mismatch')
            did, key = document['document_id'], document['entry_key']
            require(type(did) is int and (previous is None or did > previous), 'corpus document order mismatch')
            previous = did
            documents += 1
            census[key['namespace']] += 1
            projected = full.project(document, tokenizer, inventory_sha,
                                     max_document_text_bytes=count['max_document_text_bytes'])
            require(projected, 'empty corpus projection')
            for row in projected:
                stored = next(rows, None)
                metadata = {k: row[k] for k in ('entry_key', 'chunk_id', 'document_id',
                                               'entry_id', 'source_id', 'evidence_id')}
                expected = (total, row['chunk_id'], did, row['entry_id'], key['kind'], key['namespace'],
                            key['value'], row['source_id'], row['evidence_id'], row['text_sha256'],
                            row['canonical_token_start'], row['canonical_token_end'],
                            full.chunks.canonical(metadata).decode(), full.chunks.canonical(row).decode())
                require(stored is not None and tuple(stored) == expected, 'mapping corpus/projection closure mismatch')
                digest.update(full.chunks.canonical({**row, 'position': total}) + b'\n')
                total += 1
    require(next(rows, None) is None and total == n and documents == count['documents'] and
            dict(census) == count['strata'] and digest.hexdigest() == count['streaming_sha256'],
            'mapping corpus/projection census mismatch')


def verify_keys(index, n, directory=None):
    with tempfile.TemporaryDirectory(prefix='p4-ann-key-audit-', dir=directory) as temporary:  # noqa: SIM117
        with closing(sqlite3.connect(Path(temporary) / 'keys.sqlite')) as db:
            db.executescript('PRAGMA cache_size=-16384; CREATE TABLE keys(position INTEGER PRIMARY KEY);')
            total = 0
            for key in index.keys:
                position = int(key)
                require(position == key and 0 <= position < n, 'ANN key out of range')
                try:
                    db.execute('INSERT INTO keys VALUES (?)', (position,))
                except sqlite3.IntegrityError as error:
                    raise ValueError('duplicate ANN key') from error
                total += 1
            require(total == n and len(index) == n, 'missing ANN keys')


def build_stream(stream, tokenizer, inventory_sha, encoder, index, output, declaration,
                 count, *, batch_size, check_capacity, reference=None, synthetic=False,
                 report=None, reload_factory=None):
    """Closed mapping -> preselection -> vectors -> independent parity -> ANN."""
    import numpy as np
    report = {} if report is None else report
    full.positive_integer(batch_size, 'batch size')
    require(batch_size <= 1024, 'batch size exceeds bound')
    n, dimension = count['actual_chunks'], declaration['encoder']['dimension']
    full.positive_integer(n, 'actual chunks')
    output = Path(output)
    require(not any((output / name).exists() for name in PRODUCTS), 'product exists; no overwrite')
    position, previous = 0, None
    census, digest = Counter(), hashlib.sha256()
    phase(report, 'projection_mapping')
    check_capacity()
    with closing(sqlite3.connect(output / 'chunks.sqlite')) as db, (output / 'corpus.jsonl').open('xb') as corpus:
        db.executescript('''PRAGMA journal_mode=DELETE; PRAGMA cache_size=-16384;
            CREATE TABLE chunks(position INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL UNIQUE,
                document_id INTEGER NOT NULL, entry_id INTEGER NOT NULL, kind TEXT NOT NULL,
                namespace TEXT NOT NULL, value TEXT NOT NULL, source_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL, text_sha256 TEXT NOT NULL, token_start INTEGER NOT NULL,
                token_end INTEGER NOT NULL, metadata TEXT NOT NULL);
            CREATE INDEX chunks_document_id ON chunks(document_id);
            CREATE INDEX chunks_typedkey ON chunks(kind,namespace,value);
            CREATE TABLE projection(position INTEGER PRIMARY KEY, row_json TEXT NOT NULL);''')
        expected = {'bangumi.subject': ('bangumi', 'subject'), 'bangumi.character': ('bangumi', 'character'),
                    'bangumi.person': ('bangumi', 'person'), 'danbooru.wiki': ('danbooru', 'page')}
        for document in stream:
            did, key = document['document_id'], document['entry_key']
            require(type(did) is int and (previous is None or did > previous), 'duplicate or unordered document ID')
            previous = did
            require(key['namespace'] in expected and
                    (document['source_family'], key['kind']) == expected[key['namespace']], 'unexpected eligible stratum')
            rows = full.project(document, tokenizer, inventory_sha,
                                max_document_text_bytes=count['max_document_text_bytes'])
            require(rows, 'empty token document')
            census[key['namespace']] += 1
            corpus.write(full.chunks.canonical(document) + b'\n')
            for row in rows:
                require(position < n, 'projection row count mismatch')
                metadata = {k: row[k] for k in ('entry_key', 'chunk_id', 'document_id',
                                               'entry_id', 'source_id', 'evidence_id')}
                db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (position, row['chunk_id'], did, row['entry_id'], key['kind'], key['namespace'],
                            key['value'], row['source_id'], row['evidence_id'], row['text_sha256'],
                            row['canonical_token_start'], row['canonical_token_end'],
                            full.chunks.canonical(metadata).decode()))
                db.execute('INSERT INTO projection VALUES (?,?)', (position, full.chunks.canonical(row).decode()))
                digest.update(full.chunks.canonical({**row, 'position': position}) + b'\n')
                position += 1
                report.update(completed_chunks=position, last_position=position - 1)
            report['completed_documents'] = sum(census.values())
            if position % batch_size < len(rows):
                db.commit()
                check_capacity()
        require(position == n and sum(census.values()) == count['documents'] and
                dict(census) == count['strata'], 'build census/count mismatch')
        require(digest.hexdigest() == count['streaming_sha256'], 'build projection digest mismatch')
        db.commit()
        corpus.flush()
        os.fsync(corpus.fileno())
    phase(report, 'mapping_readonly_integrity')
    with full.readonly(output / 'chunks.sqlite') as db:
        require(tuple(db.execute('PRAGMA integrity_check').fetchone()) == ('ok',), 'mapping integrity failure')
        verify_mapping(db, output, tokenizer, inventory_sha, count)
        phase(report, 'sample_preselection')
        sample = select_sample(db, n, synthetic=synthetic)
        positions = sample['positions']
        require(isinstance(positions, list) and positions and
                all(type(p) is int and 0 <= p < n for p in positions) and positions == sorted(set(positions)),
                'sample positions mismatch')
        save_new(output / 'sample.json', sample)
    phase(report, 'embedding')
    check_capacity()
    require(reference is not None, 'approved independent reference encoder required')
    encoder = encoder() if callable(encoder) else encoder
    vectors = None
    try:
        vectors = np.lib.format.open_memmap(output / 'vectors.npy', mode='w+', dtype='float32', shape=(n, dimension))
        with full.readonly(output / 'chunks.sqlite') as db:
            for start in range(0, n, batch_size):
                check_capacity()
                rows = [json.loads(item[0]) for item in db.execute(
                    'SELECT row_json FROM projection WHERE position>=? AND position<? ORDER BY position',
                    (start, start + batch_size))]
                require(len(rows) == min(batch_size, n - start), 'embedding projection positions mismatch')
                result, tokens = encoder.encode([row['text'] for row in rows])
                full.exact.validate_vectors(result, dimension)
                require(len(result) == len(rows), 'encoder row count mismatch')
                require(tokens == [row['inference_token_count'] for row in rows], 'encoder token count mismatch')
                vectors[start:start + len(rows)] = result
                report.update(completed_embeddings=start + len(rows), last_position=start + len(rows) - 1)
        vectors.flush()
    finally:
        close_memmap(vectors)
    loaded, reopened, owned_index = None, None, None
    try:
        loaded = np.load(output / 'vectors.npy', mmap_mode='r', allow_pickle=False)
        require(loaded.shape == (n, dimension) and loaded.dtype == np.float32, 'saved vector shape mismatch')
        phase(report, 'whole_vector_validation')
        for start in range(0, n, batch_size):
            check_capacity()
            full.exact.validate_vectors(loaded[start:start + batch_size], dimension)
        phase(report, 'sample_reference_parity')
        reference = reference() if callable(reference) else reference
        if hasattr(reference, 'verify_sample'):
            metrics = reference.verify_sample(output, sample['positions'])
        else:
            metrics = verify_sample_reference(loaded, output, sample, batch_size, reference, dimension, check_capacity)
        report['sample_parity'] = {'count': len(sample['positions']), **metrics}
        phase(report, 'ann_construction')
        check_capacity()
        started = time.perf_counter()
        owned_index = index() if callable(index) else index
        for start in range(0, n, batch_size):
            check_capacity()
            result = loaded[start:start + batch_size]
            owned_index.add(np.arange(start, start + len(result), dtype=np.uint64), result,
                            threads=declaration['runtime']['intra_threads'], copy=True)
            report['completed_ann'] = start + len(result)
        verify_keys(owned_index, n, output)
        owned_index.save(str(output / 'vectors.usearch'))
        report['ann_build_seconds'] = time.perf_counter() - started
        report['ann_binding'] = binding(output / 'vectors.usearch', output)
        report['telemetry'] = optional_telemetry(owned_index)
        phase(report, 'ann_readonly_reload')
        reopened = reload_factory() if reload_factory else index_factory(declaration)
        reopened.view(str(output / 'vectors.usearch'))
        verify_keys(reopened, n, output)
    finally:
        close_index(reopened)
        close_index(owned_index)
        close_memmap(loaded)
    return {'documents': sum(census.values()), 'chunks': position,
            'streaming_sha256': digest.hexdigest(), 'strata': dict(census)}


def verify_sample_reference(loaded, output, sample, batch_size, reference, dimension, check_capacity):
    import numpy as np
    metrics = {'max_component_error': 0.0, 'minimum_cosine': 1.0, 'max_norm_error': 0.0}
    with full.readonly(output / 'chunks.sqlite') as db:
        for start in range(0, len(sample['positions']), batch_size):
            check_capacity()
            positions = sample['positions'][start:start + batch_size]
            rows = [json.loads(db.execute('SELECT row_json FROM projection WHERE position=?', (p,)).fetchone()[0])
                    for p in positions]
            expected, tokens = reference.encode([row['text'] for row in rows])
            full.exact.validate_vectors(expected, dimension)
            require(expected.shape == (len(rows), dimension), 'reference shape mismatch')
            values = partial_parity_metrics(np.asarray(loaded[positions]), expected,
                                           [row['inference_token_count'] for row in rows], tokens)
            metrics['max_component_error'] = max(metrics['max_component_error'], values['max_component_error'])
            metrics['minimum_cosine'] = min(metrics['minimum_cosine'], values['minimum_cosine'])
            metrics['max_norm_error'] = max(metrics['max_norm_error'], values['max_norm_error'])
    return metrics


class FreshCPUReference:
    def __init__(self, verified):
        self.verified = verified

    def verify_sample(self, output, positions):
        request = {'product_directory': Path(output).relative_to(ROOT).as_posix(), 'positions': positions,
            'inventory_sha256': self.verified['inventory_sha256'],
            'tokenizer_inventory_sha256': self.verified['manifest']['tokenizer_inventory_sha256']}
        return run_partial_cpu_worker(request)['metrics']


def attach_inventory(value, output):
    require(set(value['artifacts']) == acceptance.ARTIFACTS, 'exact FULL artifact inventory required')
    records = []
    refs = dict(value['artifacts'])
    refs['snapshot'] = value['snapshot']
    canonical = value['canonical_contract']
    refs['canonical'] = binding(ROOT / canonical['path'], output)
    for role, values in refs.items():
        for ref in values if isinstance(values, list) else [values]:
            records.append({'path': ref['path'], 'role': 'runtime_required', 'artifact': role,
                            'bytes': ref['size'], 'sha256': ref['sha256']})
    for name in ('vectors.npy', 'sample.json'):
        ref = binding(output / name, output)
        records.append({'path': ref['path'], 'role': 'build_only', 'artifact': name,
                        'bytes': ref['size'], 'sha256': ref['sha256']})
    records.sort(key=lambda item: (item['path'], item['artifact']))
    require(len({r['path'] for r in records}) == len(records), 'duplicate inventory path')
    value['inventory'] = records
    value['inventory_sha256'] = hashlib.sha256(full.chunks.canonical(records)).hexdigest()
    value['FULL_SEMANTIC_PACK_SHA256'] = value['inventory_sha256']
    value['inventory_exclusions'] = {'manifest.json': 'self_reference',
        'execution-receipt.json': 'terminal_binding_in_receipt', 'transients': 'tempstate'}
    value['transient_existence'] = {name: (output / name).exists() for name in TRANSIENTS}
    require(not any(value['transient_existence'].values()), 'transient SQLite artifacts remain')
    return value


def manifest(config, verified, output, rows):
    artifacts = {}
    pilot_root = verified.get('asset_root', ROOT)
    for name in ('model', 'tokenizer', 'ort_dll', 'external_data'):
        records = verified['pack']['artifacts'][name]
        artifacts[name] = ([binding(pilot_root / record['path'], output) for record in records]
                           if name == 'external_data' else binding(pilot_root / records['path'], output))
    for name, filename in (('index', 'vectors.usearch'), ('mapping', 'chunks.sqlite'), ('corpus', 'corpus.jsonl')):
        artifacts[name] = binding(output / filename, output)
    declaration = config['declarative_contract']
    return attach_inventory({'schema': acceptance.PACK_SCHEMA, 'object_type': 'runtime_pack',
            'pack_version': 'p4-full-semantic-v1',
            'canonical_contract': {'schema': config['schema'], **binding(ROOT / acceptance.CANONICAL_PATH, ROOT)},
            'declarative_contract': declaration, 'full_chunk_count': rows,
            'contract': acceptance.runtime_contract(declaration, rows),
            'snapshot': {'identity': config['snapshot']['path'], **binding(ROOT / config['snapshot']['path'], output)},
            'artifacts': artifacts}, output)


def new_report():
    return {'schema': 'p4-full-build-receipt-v1', 'status': 'FAIL', 'attempts': 0,
            'executor_origin': EXECUTOR_ORIGIN,
            'phase': 'activation', 'phases': [], 'input_hashes': {},
            'completed_documents': 0, 'completed_chunks': 0, 'completed_embeddings': 0,
            'completed_ann': 0, 'last_position': None, 'retained_partial': False}


def failed(report, error, *, terminal_error=False):
    report.update(status='FAIL', retained_partial=bool(report.get('attempt_reserved', report['attempts'] == 1)))
    if terminal_error:
        report['terminal_error'] = repr(error)
        report.setdefault('finalization_errors', []).append({
            'error_type': type(error).__name__, 'error_message': str(error)})
        report['terminal_error_type'] = type(error).__name__
        report['terminal_error_message'] = str(error)
    if 'error_type' not in report:
        report.update(error_type=type(error).__name__, error_message=str(error))
    error.build_receipt = report


def terminal(report, output, snapshot=None):
    report['artifact_existence'] = {name: (output / name).exists() for name in PRODUCTS + TRANSIENTS}
    report['snapshot_after_hash_status'] = 'NOT_APPLICABLE'
    error = None
    if snapshot is not None:
        try:
            ref = binding(snapshot, ROOT)
            report['snapshot_after'] = ref
            report['snapshot_after_hash_status'] = ('UNCHANGED' if ref == report['activation']['snapshot'] else 'CHANGED')
            if report['snapshot_after_hash_status'] == 'CHANGED':
                error = ValueError('terminal snapshot changed')
        except BaseException as hash_error:  # noqa: BLE001 - publish FAIL, then re-raise original below
            report['snapshot_after_hash_status'] = 'HASH_FAILED'
            report['snapshot_after_error'] = repr(hash_error)
            error = hash_error
    if error is not None:
        failed(report, error, terminal_error=True)
    report['retained_partial'] = bool(report.get('attempt_reserved', report['attempts'] == 1)) and report['status'] == 'FAIL'
    if report.get('attempt_reserved', report['attempts'] == 1):
        target = (output / 'execution-receipt.json' if output.is_dir() else
                  output.with_name(output.name + '.execution-receipt.json'))
        report['receipt_binding'] = {'path': target.name, 'role': 'build_only',
                                   'digest_exclusion': 'self_reference; bind externally after terminal write'}
        report['tempstate'] = {name: (output / name).exists() for name in TRANSIENTS}
        report['artifact_existence']['execution-receipt.json'] = output.is_dir()
        report['receipt_publication'] = {
            'method': 'fsynced_stage_then_exclusive_hard_link',
            'directory_durability': 'NOT_GUARANTEED; directory fsync unavailable on some platforms'}
        stage = target.with_name(target.name + '.' + os.urandom(16).hex() + '.staging')
        publication = dict(report)
        if report['status'] == 'BUILD_COMPLETE_WAITING_REVIEW':
            publication.update(phase='complete', phases=[*report['phases'], 'complete'])
        linked = False
        try:
            # Final names never expose unflushed success bytes. Hard links are
            # atomic create-new on Windows and POSIX; never replace a receipt.
            save_new(stage, publication)
            os.link(stage, target)
            linked = True
            stage.unlink()
            report.update(publication)
        except BaseException as write_error:
            failed(report, write_error, terminal_error=True)
            # Cancellation can arrive after link creation but before return.
            if not linked:
                try:
                    linked = target.exists() and stage.exists() and target.samefile(stage)
                except BaseException as ownership_error:  # noqa: BLE001 - retain secondary accounting without masking original
                    failed(report, ownership_error, terminal_error=True)
            for path in ([target] if linked else []) + [stage]:
                try:
                    path.unlink(missing_ok=True)
                except BaseException as cleanup_error:  # noqa: BLE001 - retain secondary accounting without masking original
                    failed(report, cleanup_error, terminal_error=True)
                    try:
                        with path.open('wb') as stream:
                            stream.write(full.chunks.canonical(report) + b'\n')
                            stream.flush()
                    except BaseException as scrub_error:  # noqa: BLE001 - retain secondary accounting without masking original
                        failed(report, scrub_error, terminal_error=True)
            # Retain FAIL evidence even when durability itself is unavailable.
            try:
                save_new(target, report)
            except BaseException as accounting_error:  # noqa: BLE001 - retain secondary accounting without masking original
                failed(report, accounting_error, terminal_error=True)
            report['artifact_existence']['execution-receipt.json'] = target.exists() and output.is_dir()
            if error is not None:
                report['snapshot_terminal_error'] = repr(error)
            raise
    if error is not None:
        raise error


def lifecycle(output, report, work, *, snapshot=None, finalize=lambda: None, attempt_number=1):
    original = None
    try:
        phase(report, 'reservation')
        reserve(output, report)
        value = work()
        phase(report, 'final_input_guards')
        finalize()
        phase(report, 'manifest_publication')
        save_new(output / 'manifest.json', value)
        report.update(status='BUILD_COMPLETE_WAITING_REVIEW', manifest_sha256=full.exact.sha(output / 'manifest.json'))
    except BaseException as error:
        original = error
        failed(report, error)
        raise  # Finally persists accounting for every BaseException subtype.
    finally:
        terminal_failure = None
        try:
            if report.get('attempt_reserved', report['attempts'] == 1):
                try:
                    terminal(report, output, snapshot)
                except BaseException as terminal_error:  # noqa: BLE001 - release owned lock even on cancellation
                    terminal_failure = terminal_error
                    failed(report, terminal_error, terminal_error=True)
                    try:
                        print(json.dumps(report, sort_keys=True), file=__import__('sys').stderr)
                    except BaseException as stderr_error:  # noqa: BLE001 - broken stderr must not mask first error
                        failed(report, stderr_error, terminal_error=True)
        finally:
            if report.get('attempt_reserved'):
                lock = report.get('attempt_lock')
                try:
                    if lock:
                        path = Path(lock)
                        info = path.lstat()
                        require([info.st_dev, info.st_ino] == report['lock_identity'] and
                                read_json(path).get('token') == report['lock_token'], 'build lock ownership changed')
                        path.unlink()
                        report['lock_released'] = True
                except (OSError, ValueError) as cleanup_error:
                    primary = original or terminal_failure
                    if primary is None:
                        raise
                    primary.add_note(f'lock cleanup failed: {cleanup_error!r}')
        if terminal_failure is not None:
            if original is not None:
                raise original from terminal_failure
            raise terminal_failure
    if original is not None:
        raise original
    return report


def validate_activation_dll(verified):
    record = verified['pack']['artifacts']['ort_dll']
    path = acceptance._approved_dll_path()
    expected = Path(record['path'])
    if not expected.is_absolute():
        expected = ROOT / full.pilot.PACK
        expected = expected.parent / record['path']
    require(path == expected.resolve(strict=True), 'activation external ORT DLL path mismatch')
    require((record['size'], record['sha256']) == (full.pilot.DLL_SIZE, full.pilot.DLL_SHA),
            'activation external ORT DLL binding mismatch')
    acceptance._verify_file(path, record)
    return path


def execute(*, output=None):
    """Run the real builder from current assets and measured product inputs."""
    config = read_json(full.CONFIG)
    full.validate_contract(config)
    target = Path(output) if output else ROOT / OUTPUT
    full.check_components(target)
    require(not target.exists(), 'output already exists')
    report = new_report()
    verified = full.inventory()
    snapshot = full.contained(config['snapshot']['path'])
    snapshot_ref = binding(snapshot, ROOT)
    require(all(snapshot_ref[k] == config['snapshot'][k] for k in ('path', 'size', 'sha256')),
            'snapshot content mismatch')
    report['activation'] = {'snapshot': dict(snapshot_ref)}
    raw, _ = full.exact.frozen_tokenizers(full.contained(verified['model']['asset_directory']))
    with full.readonly(snapshot) as conn:
        count = full.census_and_chunk_count(conn, raw, verified['manifest']['tokenizer_inventory_sha256'], config)
    # Conservative schema-independent reserve; checked again before each batch.
    required = count['actual_chunks'] * (4096 + 3 * 5000 + 8192) * 2
    def capacity():
        import shutil
        require(shutil.disk_usage(ROOT).free >= required, 'BLOCKED_DISK: builder reserve')
    capacity()
    records = [(snapshot, config['snapshot'], 'snapshot')]
    records += [(Path(n) if Path(n).is_absolute() else ROOT / n, {'path': n, **r},
                 'ort_dll' if Path(n).is_absolute() else 'input') for n, r in verified['bindings'].items()]
    def encoder(device):
        capacity()
        result = full.exact.LocalEncoder(verified['model'], verified['contract'], device, verified['job']['threads'])
        require(result.info['actual_dtype'] == 'torch.float32', 'actual FP32 required')
        if device == 'cuda':
            require(result.info['actual_device'].startswith('cuda'), 'actual GPU required')
        return result
    def work():
        with acceptance._inventory_guard(records), full.readonly(snapshot) as conn, closing(full.documents(conn)) as stream:
            report['build'] = build_stream(stream, raw, verified['manifest']['tokenizer_inventory_sha256'],
                lambda: encoder('cuda'), lambda: index_factory(config['declarative_contract']), target,
                config['declarative_contract'], count, batch_size=verified['job']['batch_size'],
                check_capacity=capacity, reference=FreshCPUReference(verified), report=report)
            value = manifest(config, verified, target, count['actual_chunks'])
            acceptance.validate_full_manifest(value, config, pack_root=target)
            return value
    return lifecycle(target, report, work, snapshot=snapshot)


def synthetic_run(root, output=None):
    """Synthetic authorities, real FULL validator; never actual FULL acceptance."""
    import copy
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import patch

    import numpy as np

    class Tokenizer:
        truncation = padding = None

        def encode(self, text, *, add_special_tokens=False):
            spans = [(i, i + 1) for i, char in enumerate(text) if not char.isspace()]
            return SimpleNamespace(ids=[1] * (len(spans) + (2 if add_special_tokens else 0)), offsets=spans)

    class Encoder:
        def encode(self, texts):
            vectors = np.zeros((len(texts), 4), dtype=np.float32)
            vectors[:, 0] = 1
            return vectors, [len(Tokenizer().encode(t, add_special_tokens=True).ids) for t in texts]

    class Index:
        def __init__(self):
            self.keys = []

        def __len__(self):
            return len(self.keys)

        def add(self, keys, vectors, **kwargs):
            self.keys.extend(int(k) for k in keys)

        def save(self, path):
            save_new(path, self.keys)

        def view(self, path):
            self.keys = read_json(path)

    root = Path(root).resolve()
    declaration = copy.deepcopy(full.DECLARATIONS)
    declaration['encoder']['dimension'] = 4
    docs = [{'document_id': i, 'entry_id': i, 'entry_key': {'kind': 'subject',
             'namespace': 'bangumi.subject', 'value': str(i)}, 'source_family': 'bangumi',
             'source_id': 'synthetic', 'evidence_id': str(i), 'title': f'doc {i}',
             'original': 'x' * (450 if i == 20 else 10)} for i in range(1, 21)]
    digest, n = hashlib.sha256(), 0
    for doc in docs:
        for row in full.project(doc, Tokenizer(), 'a' * 64):
            digest.update(full.chunks.canonical({**row, 'position': n}) + b'\n')
            n += 1
    count = {'actual_chunks': n, 'documents': 20, 'strata': {'bangumi.subject': 20},
             'streaming_sha256': digest.hexdigest(), 'max_document_text_bytes': 10000}
    output, report = (Path(output), new_report()) if output is not None else (root / 'synthetic-pack', new_report())
    report['synthetic'] = True
    report['activation'] = {'output_absent': not output.exists(), 'lock_absent': not attempt_lock(output).exists(),
                            'gpu_available': 'SYNTHETIC', 'inventory': {}, 'fixed_source': 'SYNTHETIC'}

    def work():
        report['build'] = build_stream(iter(docs), Tokenizer(), 'a' * 64, Encoder(), Index(), output,
            declaration, count, batch_size=3, check_capacity=lambda: None, reference=Encoder(),
            synthetic=True, report=report, reload_factory=Index)
        phase(report, 'runtime_manifest_validation')
        artifacts = {}
        for name in ('model', 'tokenizer', 'ort_dll', 'external_data'):
            path = root / name
            with path.open('xb') as file:
                file.write(('synthetic ' + name).encode())
            ref = binding(path, output)
            artifacts[name] = [ref] if name == 'external_data' else ref
        snapshot = root / 'snapshot.sqlite'
        with snapshot.open('xb') as file:
            file.write(b'synthetic snapshot')
        config = {'schema': 'p4-full-semantic-contract-v1', 'declarative_contract': declaration,
                  'snapshot': binding(snapshot, root)}
        config_path = root / acceptance.CANONICAL_PATH
        config_path.parent.mkdir()
        save_new(config_path, config)
        for name, filename in (('index', 'vectors.usearch'), ('mapping', 'chunks.sqlite'), ('corpus', 'corpus.jsonl')):
            artifacts[name] = binding(output / filename, output)
        value = attach_inventory({'schema': acceptance.PACK_SCHEMA, 'object_type': 'runtime_pack',
            'synthetic': True,
            'canonical_contract': {'schema': config['schema'], **binding(config_path, root)},
            'snapshot': {'identity': config['snapshot']['path'], **binding(snapshot, output)},
            'contract': acceptance.runtime_contract(declaration, n),
            'declarative_contract': declaration, 'full_chunk_count': n, 'artifacts': artifacts}, output)
        # Only fixture authorities are substituted; byte/path/schema validation is real.
        with ExitStack() as stack:
            for obj, name, replacement in ((acceptance, 'ROOT', root), (acceptance, 'CONFIG', config_path),
                    (acceptance, 'validate_contract', lambda value: declaration if value == config else None),
                    (acceptance, 'approved_full_dll', lambda: {'path': str(root / 'ort_dll'),
                        'size': artifacts['ort_dll']['size'], 'sha256': artifacts['ort_dll']['sha256']})):
                stack.enter_context(patch.object(obj, name, replacement))
            acceptance.validate_full_manifest(value, config, pack_root=output)
        report['manifest_validator'] = 'actual_FULL_validator_with_synthetic_authorities'
        return value

    with patch.object(__import__(__name__, fromlist=['ROOT']), 'ROOT', root):
        return lifecycle(output, report, work)


def existing_assets(*, output, session=None):
    """Publish a small candidate referencing pinned immutable products; never rebuild."""
    config = read_json(full.FULL_CONTRACT)
    declaration = full.validate_contract(config)
    spec = full.current_asset_spec(ROOT)
    pins = spec['existing_full_assets']
    require(set(pins) == {'rows', 'documents', 'index', 'mapping', 'corpus', 'vectors'},
            'exact existing FULL product roles required')
    require(type(pins['rows']) is int and pins['rows'] > 0 and
            pins['documents'] == declaration['corpus']['documents'], 'existing FULL census mismatch')
    target = full.controlled_path(ROOT / output, ROOT, strict=False)
    full.check_components(target)
    require(not target.exists(), 'candidate output already exists')
    target.parent.mkdir(parents=True, exist_ok=True)
    # The final destination is the relative-reference base even while staging.
    def relative(record):
        path = full.contained(record['path'], ROOT)
        return {'path': Path(os.path.relpath(path, target)).as_posix(),
                'size': record['size'], 'sha256': record['sha256']}
    export = full.contained(spec['export_manifest']['path'], ROOT)
    exported = read_json(export)['files']
    require(len({r['path'] for r in exported}) == len(exported), 'duplicate export paths')
    records = []
    model = spec['model']
    native = read_json(full.contained(model['contract']['path'], ROOT))
    require(full.chunks.canonical(native) == full.chunks.canonical(model['contract']['reviewed']),
            'current model contract mismatch')
    full.encoder_contract(model, native)
    for rec in model['obtained_inventory']:
        raw = Path(rec['path'])
        require(not raw.is_absolute() and '..' not in raw.parts, 'model asset path escape')
        ref = {'path': model['assetdirectory'] + '/' + raw.as_posix(),
               'size': rec['size'], 'sha256': rec['sha256']}
        records.append((full.contained(ref['path'], ROOT), ref, 'input'))
    model_contract = full.contained(model['contract']['path'], ROOT)
    records.append((model_contract, {'path': model['contract']['path'], 'size': model_contract.stat().st_size,
                                   'sha256': model['contract']['file_sha256']}, 'input'))
    artifacts = {}
    for record in exported:
        raw = Path(record['path'])
        require(not raw.is_absolute() and '..' not in raw.parts, 'export path escape')
        path = full.controlled_path(export.parent / raw, ROOT)
        rec = {**record, 'path': path.relative_to(ROOT).as_posix()}
        records.append((path, rec, 'input'))
        if raw.as_posix() == 'model.onnx':
            artifacts['model'] = relative(rec)
        elif raw.as_posix() != 'passage-sample.json':
            artifacts.setdefault('external_data', []).append(relative(rec))
    require(artifacts.get('model') and artifacts.get('external_data'), 'complete ONNX resources required')
    for role in ('index', 'mapping', 'corpus', 'vectors'):
        rec = pins[role]
        require(rec['path'] == 'build/p4-full-semantic-v1-retry1/' +
                {'index': 'vectors.usearch', 'mapping': 'chunks.sqlite', 'corpus': 'corpus.jsonl',
                 'vectors': 'vectors.npy'}[role], 'existing product role/path mismatch')
        records.append((full.contained(rec['path'], ROOT), rec, role))
        if role != 'vectors':
            artifacts[role] = relative(rec)
    tokenizer = next(r for r in spec['model']['obtained_inventory'] if r['path'] == 'tokenizer.json')
    tokenizer = {'path': spec['model']['assetdirectory'] + '/tokenizer.json',
                 'size': tokenizer['size'], 'sha256': tokenizer['sha256']}
    artifacts['tokenizer'] = relative(tokenizer)
    artifacts['ort_dll'] = dict(spec['ort_dll'])
    records.extend([(export, spec['export_manifest'], 'input'),
                    (full.contained(tokenizer['path'], ROOT), tokenizer, 'tokenizer')])
    snapshot = config['snapshot']
    canonical = binding(full.FULL_CONTRACT, ROOT)
    value = {'schema': acceptance.PACK_SCHEMA, 'object_type': 'runtime_pack',
        'pack_version': 'p4-full-existing-assets-v1', 'full_chunk_count': pins['rows'],
        'canonical_contract': {'schema': config['schema'], **canonical},
        'declarative_contract': declaration, 'contract': acceptance.runtime_contract(declaration, pins['rows']),
        'snapshot': {'identity': snapshot['path'], **relative(snapshot)}, 'artifacts': artifacts}
    owned = session is None
    session = session or acceptance.AcceptanceSession()
    stage = None
    try:
        with session.guard(records):
            with full.readonly(full.contained(pins['mapping']['path'], ROOT)) as db:
                require(db.execute('SELECT count(*) FROM chunks').fetchone()[0] == pins['rows'],
                        'mapping row census mismatch')
            stage = Path(tempfile.mkdtemp(prefix=target.name + '.staging-', dir=target.parent))
            # Staging is a sibling: controlled ../ references resolve identically.
            save_new(stage / 'manifest.json', value)
            acceptance.validate_full_manifest(value, config, pack_root=stage, session=session)
            require(not target.exists(), 'candidate output already exists')
            stage.rename(target)
            stage = None
        return value
    finally:
        if stage is not None:
            import shutil
            shutil.rmtree(stage)
        if owned:
            session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='readiness receipt destination (default: stdout)')
    parser.add_argument('--execute', action='store_true', help='run the supported ordinary builder lifecycle')
    parser.add_argument('--synthetic', action='store_true', help='run the supported synthetic lifecycle')
    parser.add_argument('--existing-assets', action='store_true', help='validate and reference existing FULL assets without rebuilding')
    args = parser.parse_args()
    if sum((args.execute, args.synthetic, args.existing_assets)) > 1:
        parser.error('execution modes are mutually exclusive')
    if args.existing_assets:
        if not args.output:
            parser.error('--existing-assets requires a new --output directory')
        result = existing_assets(output=args.output)
    elif args.execute:
        result = execute(output=args.output)
    elif args.synthetic:
        with tempfile.TemporaryDirectory(prefix='p4-full-synthetic-') as directory:
            result = synthetic_run(Path(directory))
    else:
        config = read_json(full.CONFIG)
        full.validate_contract(config)
        result = {'status': 'READY_FOR_NORMAL_BUILD', 'attempts': 0,
                  'executor_origin': EXECUTOR_ORIGIN,
                  'source_sha256': full.exact.sha(Path(__file__)),
                  'config_sha256': full.exact.sha(full.CONFIG)}
    if args.output and not (args.execute or args.existing_assets):
        save_new(args.output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
