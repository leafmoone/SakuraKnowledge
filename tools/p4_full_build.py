"""Explicit future FULL executor; implementation is not execution authorization."""
import argparse
import hashlib
import heapq
import json
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
OUTPUT = 'build/p4-full-semantic-v1'
AUTH_SCHEMA = 'p4-full-build-authorization-v1'
RETRY_SCHEMA = 'p4-full-build-retry-authorization-v1'
RETRY_OUTPUT = 'build/p4-full-semantic-v1-retry1'
FAILURE_CLASS = 'HARNESS_AUTHORITY_DOMAIN_MISMATCH'
POLICY_EXCEPTION = 'EXPLICIT_ATTEMPT2_AFTER_VERIFIED_HARNESS_DEFECT'
ATTEMPT1_RESULT_SHA = 'd5c7c1b0bc900af1f547c544e8fd95309e1a9395'
ATTEMPT1_IMPLEMENTATION_SHA = '3eeda16b4f1c99b01430979819e5c079243d1f08'
ATTEMPT1_BINDINGS = {
    'authorization': {'path': 'build/p4-full-build-authorization-3eeda16b.json', 'size': 12988,
        'sha256': '9571003d333444e19b9974b0ce28b0e2cd4694ed6cadbe3293e1f2967fcb99c7'},
    'attempt1_lock': {'path': 'build/p4-full-semantic-v1.attempt1.lock', 'size': 30372,
        'sha256': '955b9a2e424579ff9363e942824b1911ff015db3e173c4f86b962fad40ef0220'},
    'execution_receipt': {'path': 'build/p4-full-semantic-v1/execution-receipt.json', 'size': 107066,
        'sha256': '34bf78970a3f269d9f2f1fd362458111e159c9e1df06319a7180353b38128d4a'},
    'command_receipt': {'path': 'reports/P4/full-semantic-build-command.json', 'size': 7335,
        'sha256': '69fa69d3c1e4e7dee95f3317034385fd72dd2567db3287ed880fe3b7598ef71b'},
    'handoff': {'path': 'reports/P4/full-semantic-build-handoff.json', 'size': 1140,
        'sha256': '3ab30ecacf4eb3a3af6498906578db0ddfb2ed5d623035183220a2b53e3692eb'}}
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


def authorize(path, expected_sha256, *, fixed_head, root):
    require(path is not None and expected_sha256 is not None,
            'future explicit FULL authorization and independently reviewed SHA256 required')
    full.chunks.valid_hash(expected_sha256)
    require(isinstance(fixed_head, str) and len(fixed_head) == 40 and
            all(c in '0123456789abcdef' for c in fixed_head), 'fixed HEAD required')
    path = full.contained(path, root)
    require(full.exact.sha(path) == expected_sha256, 'authorization hash mismatch')
    value = read_json(path)
    require(isinstance(value, dict) and set(value) == {'schema', 'operation', 'fixed_code_sha',
            'preflight_producer_sha', 'preflight_evidence_sha', 'reviewed_source_bindings',
            'output', 'max_attempts', 'count_review', 'disk_review', 'smoke_review', 'executor_bindings'},
            'exact future authorization fields required')
    require(value['schema'] == AUTH_SCHEMA and value['operation'] == 'execute_full' and
            value['fixed_code_sha'] == fixed_head and value['output'] == OUTPUT and
            type(value['max_attempts']) is int and value['max_attempts'] == 1, 'future authorization policy mismatch')
    authenticate_executor_bindings(value, fixed_head=fixed_head, root=root)
    return value


def authenticate_executor_bindings(value, *, fixed_head, root):
    for field in ('preflight_producer_sha', 'preflight_evidence_sha'):
        sha = value[field]
        require(isinstance(sha, str) and len(sha) == 40 and all(c in '0123456789abcdef' for c in sha),
                'future authorization policy mismatch')
    require(isinstance(value['reviewed_source_bindings'], dict) and
            set(value['reviewed_source_bindings']) == {'count', 'disk', 'smoke'},
            'reviewed preflight source bindings required')
    for digest in value['reviewed_source_bindings'].values():
        full.chunks.valid_hash(digest)
    require(isinstance(value['executor_bindings'], dict) and set(value['executor_bindings']) ==
            EXECUTOR_PATHS, 'executor source closure required')
    for name, digest in value['executor_bindings'].items():
        full.chunks.valid_hash(digest)
        require(full.exact.sha(full.contained(name, root)) == digest, 'executor source changed')
        current = subprocess.check_output(['git', 'hash-object', '--path=' + name, name], cwd=root, text=True).strip()
        approved = subprocess.check_output(['git', 'rev-parse', fixed_head + ':' + name], cwd=root, text=True).strip()
        require(current == approved, 'executor does not match fixed Git source')
    return value


def attempt1_history_binding():
    return {'result_sha': ATTEMPT1_RESULT_SHA, 'implementation_sha': ATTEMPT1_IMPLEMENTATION_SHA,
            **{k: dict(v) for k, v in ATTEMPT1_BINDINGS.items()}, 'completed_documents': 0,
            'completed_chunks': 0, 'completed_embeddings': 0, 'completed_ann': 0,
            'snapshot_after_hash_status': 'UNCHANGED'}


def validate_retry_history_and_no_retry_product(*, root, check_new=True):
    old = full.contained(OUTPUT, root)
    require(old.is_dir(), 'Attempt1 output missing')
    require(not (old / 'manifest.json').exists(), 'Attempt1 manifest must be absent')
    require({p.name for p in old.iterdir()} == {'execution-receipt.json'},
            'unexpected Attempt1 product')
    for key, ref in ATTEMPT1_BINDINGS.items():
        path = full.contained(ref['path'], root)
        require(path.is_file() and path.stat().st_size == ref['size'] and
                full.exact.sha(path) == ref['sha256'], 'Attempt1 history mismatch: ' + key)
    receipt = read_json(full.contained(ATTEMPT1_BINDINGS['execution_receipt']['path'], root))
    require(receipt.get('status') == 'FAIL' and type(receipt.get('attempts')) is int and
            receipt['attempts'] == 1 and receipt.get('phase') == 'reservation' and
            receipt.get('snapshot_after_hash_status') == 'UNCHANGED', 'Attempt1 receipt state mismatch')
    for key in ('completed_documents', 'completed_chunks', 'completed_embeddings', 'completed_ann'):
        require(type(receipt.get(key)) is int and receipt[key] == 0, 'Attempt1 completed counts mismatch')
    if check_new:
        output = full.controlled_path(RETRY_OUTPUT, root, strict=False)
        full.check_components(output)
        require(not output.exists(), 'Attempt2 output already exists')
        require(not attempt_lock(output, 2).exists(), 'Attempt2 already reserved; no attempt3')
    return attempt1_history_binding()


def validate_retry_policy(value, fixed_head):
    require(isinstance(value, dict) and set(value) == {'schema', 'operation', 'fixed_code_sha',
        'attempt_number', 'max_total_attempts', 'retry_of', 'failure_class', 'preflight_producer_sha',
        'preflight_evidence_sha', 'reviewed_source_bindings', 'output', 'previous_output',
        'count_review', 'disk_review', 'smoke_review', 'executor_bindings'}, 'exact retry fields required')
    require(value['schema'] == RETRY_SCHEMA and value['operation'] == 'execute_full_retry' and
            value['fixed_code_sha'] == fixed_head and value['output'] == RETRY_OUTPUT and
            value['previous_output'] == OUTPUT and value['failure_class'] == FAILURE_CLASS and
            type(value['attempt_number']) is int and value['attempt_number'] == 2 and
            type(value['max_total_attempts']) is int and value['max_total_attempts'] == 2,
            'explicit Attempt2 retry policy mismatch')
    require(full.chunks.canonical(value['retry_of']) == full.chunks.canonical(attempt1_history_binding()),
            'retry history binding mismatch')


def authorize_retry(path, expected_sha256, *, fixed_head, root, check_sources=True):
    require(path is not None and expected_sha256 is not None, 'explicit retry authorization required')
    full.chunks.valid_hash(expected_sha256)
    require(isinstance(fixed_head, str) and len(fixed_head) == 40 and
            all(c in '0123456789abcdef' for c in fixed_head), 'fixed HEAD required')
    path = full.contained(path, root)
    require(full.exact.sha(path) == expected_sha256, 'retry authorization hash mismatch')
    value = read_json(path)
    validate_retry_policy(value, fixed_head)
    if check_sources:
        authenticate_executor_bindings(value, fixed_head=fixed_head, root=root)
    return value


def authenticate_acceptance_repair(producer_bytes, record, root, auth):
    # Exact reviewed before/after Git bytes pin the three approved edit regions.
    name = 'tools/p4_full_acceptance.py'
    require(hashlib.sha256(producer_bytes).hexdigest() ==
            '21583b2b2a38afee54bddccbdbbbbdf7f369dff23cc2946495d62d602e721c8c',
            'unapproved acceptance repair producer')
    require(isinstance(auth, dict) and set(auth.get('executor_bindings', {})) == EXECUTOR_PATHS,
            'executor source closure required')
    require(full.exact.sha(full.contained(name, root)) == auth['executor_bindings'][name],
            'acceptance repair checkout mismatch')
    current = subprocess.check_output(['git', 'hash-object', '--path=' + name, name], cwd=root, text=True).strip()
    fixed = subprocess.check_output(['git', 'rev-parse', auth['fixed_code_sha'] + ':' + name], cwd=root, text=True).strip()
    require(current == fixed == record['git_blob'], 'acceptance repair fixed source mismatch')
    shown = subprocess.check_output(['git', 'show', fixed], cwd=root)
    require(hashlib.sha256(shown).hexdigest() ==
            '1210800f6e56f8ff91f07fbcb5577ff5720f085bfba35341bba6ee88b90e42a0',
            'unapproved acceptance repair diff')


def authenticate_rust_harness(producer_bytes, record, root, auth):
    name = 'rust/src/semantic.rs'
    require(isinstance(auth, dict) and isinstance(auth.get('executor_bindings'), dict) and
            set(auth['executor_bindings']) == EXECUTOR_PATHS, 'executor source closure required')
    require(full.exact.sha(full.contained(name, root)) == auth['executor_bindings'][name],
            'executor source changed')
    blob = subprocess.check_output(['git', 'hash-object', '--path=' + name, name], cwd=root, text=True).strip()
    approved = subprocess.check_output(['git', 'rev-parse', auth['fixed_code_sha'] + ':' + name],
                                       cwd=root, text=True).strip()
    require(blob == approved == record['git_blob'], 'executor does not match fixed Git source')
    shown = subprocess.check_output(['git', 'show', approved], cwd=root)
    start = b'    #[test]\n    fn builder_synthetic_reader_interop() {'
    end = b'    #[test]\n    fn full_paths_controlled_assets_receipt_exception_and_aliases() {'
    module = b'#[cfg(test)]\nmod tests {\n'
    require(shown.count(start) == shown.count(end) == shown.count(module) == 1,
            'unapproved Rust test harness')
    first, last = shown.index(start), shown.index(end)
    require(shown.index(module) < first < last and module in producer_bytes,
            'unapproved Rust test harness')
    require(hashlib.sha256(shown[first:last]).hexdigest() == APPROVED_RUST_HARNESS_SHA256,
            'unapproved Rust test harness')
    require(shown[:first] + shown[last:] == producer_bytes,
            'shared preflight Rust implementation changed')


def authenticate_preflight_source(receipt, producer, expected, current, root, *, auth=None):
    """Authenticate historical inventory without claiming that producer is today's HEAD."""
    records = receipt.get('source_inventory')
    require(isinstance(records, dict) and records and
            full.exact.canonical_hash(records) == expected == receipt.get('source_inventory_sha256'),
            'reviewed preflight source inventory mismatch')
    families = (('rust/src/', '.rs'), ('rust/Cargo.', ''), ('configs/p4-', '.json'),
                ('tools/p4_', '.py'), ('docs/p4-', '.md'), ('tests/test_p4_', '.py'))
    metadata = {'rust/build.rs', 'Cargo.toml', 'Cargo.lock', 'build.rs', '.gitattributes',
                '.gitmodules', '.cargo/config', '.cargo/config.toml', 'rust/.cargo/config',
                'rust/.cargo/config.toml', 'rust-toolchain', 'rust-toolchain.toml',
                'rust/rust-toolchain', 'rust/rust-toolchain.toml', 'pyproject.toml'}
    tree = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '-z', producer], cwd=root)
    names = {name.decode('utf-8') for name in tree.split(b'\0') if name}
    expected_names = set(full.SOURCE_PATHS) | {name for name in names if name in metadata or any(
        name.startswith(prefix) and name.endswith(suffix) for prefix, suffix in families)}
    require(set(records) == expected_names, 'historical source closure mismatch')
    for name, record in records.items():
        require(isinstance(record, dict) and set(record) == {'git_blob', 'index_git_blob', 'size',
                'sha256', 'checkout_size', 'checkout_sha256', 'checkout_git_filtered_blob'},
                'historical source record mismatch')
        blob = subprocess.check_output(['git', 'rev-parse', producer + ':' + name], cwd=root, text=True).strip()
        shown = subprocess.check_output(['git', 'show', producer + ':' + name], cwd=root)
        require(record['git_blob'] == record['index_git_blob'] == record['checkout_git_filtered_blob'] == blob and
                type(record['size']) is int and record['size'] == len(shown) and
                record['sha256'] == hashlib.sha256(shown).hexdigest(), 'historical producer blob mismatch')
        full.chunks.valid_hash(record['checkout_sha256'])
        require(type(record['checkout_size']) is int and record['checkout_size'] >= 0,
                'historical checkout size mismatch')
        require(name in current, 'shared preflight implementation changed')
        if name == 'tools/p4_full_acceptance.py' and current[name]['git_blob'] != blob:
            authenticate_acceptance_repair(shown, current[name], root, auth)
        elif name == 'rust/src/semantic.rs' and current[name]['git_blob'] != blob:
            authenticate_rust_harness(shown, current[name], root, auth)
        else:
            require(name in EXECUTOR_PATHS or current[name]['git_blob'] == blob,
                    'shared preflight implementation changed')
    additions = set(current) - set(records)
    require(all(name in EXECUTOR_PATHS or name.startswith('docs/') and name.endswith('.md') or
                name.startswith('tests/') and name.endswith('.py') for name in additions),
            'unreviewed implementation added')


def reviewed_preflight(auth, config, verified, report, root):
    producer, evidence = auth['preflight_producer_sha'], auth['preflight_evidence_sha']
    receipts = {}
    for name in ('count', 'disk', 'smoke'):
        review = auth[name + '_review']
        receipt = full.load_reviewed_receipt(fixed_head=producer, root=root, **review)
        authenticate_preflight_source(receipt, producer, auth['reviewed_source_bindings'][name],
                                      report['source_inventory'], root, auth=auth)
        # Raw captures are externally authenticated; unchanged receipts are Git-published evidence.
        file = full.contained(review['path'], root)
        relative = file.relative_to(Path(root).resolve()).as_posix()
        shown = subprocess.check_output(['git', 'show', evidence + ':' + relative], cwd=root)
        require(hashlib.sha256(shown).hexdigest() == review['expected_sha256'],
                'reviewed preflight evidence Git binding mismatch')
        require(receipt.get('inventory_sha256') == verified['inventory_sha256'],
                'reviewed phase inventory mismatch')
        receipts[name] = receipt
    receipt = receipts['count']
    count = full.validate_count_receipt(receipt, config, fixed_head=producer,
        source_binding=auth['reviewed_source_bindings']['count'], inventory_binding=verified['inventory_sha256'])
    pilot_ids, _, _, _, _ = full.pilot_inputs(verified)
    require(count['pilot_document_ids_sha256'] == full.exact.canonical_hash(sorted(pilot_ids)) and
            all(ref['document_id'] not in pilot_ids for ref in count['full_only_chunk_references']),
            'reviewed count pilot exclusion mismatch')
    require(receipt.get('tokenizer_inventory_sha256') == verified['manifest']['tokenizer_inventory_sha256'],
            'count tokenizer binding mismatch')
    report['preflight_provenance'] = {'producer_sha': producer, 'evidence_sha': evidence,
                                    'reviewed_source_bindings': auth['reviewed_source_bindings']}
    return count, receipts['disk'], receipts['smoke']


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
    require(type(attempt_number) is int and attempt_number in (1, 2), 'no attempt3')
    return output.with_name(output.name + f'.attempt{attempt_number}.lock')


def reserve(output, report, *, attempt_number=1):
    require(type(attempt_number) is int and attempt_number in (1, 2), 'no attempt3')
    if attempt_number == 2:
        require(report.get('attempts') == 1 and report.get('attempt_reserved') is False,
                'retry requires historical1 and no current claim')
        require(output == ROOT / RETRY_OUTPUT and report.get('retry_of') == attempt1_history_binding(),
                'explicit retry history/output required')
        validate_retry_history_and_no_retry_product(root=ROOT)
    require(not output.exists(), 'output already exists; no overwrite')
    lock = attempt_lock(output, attempt_number)
    require(not lock.exists(), 'attempt already reserved; no retry')
    output.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('xb') as stream:
        report.update(attempts=attempt_number, attempt_number=attempt_number,
                      attempt_reserved=True, attempt_lock=str(lock))
        payload = {'executor_origin': EXECUTOR_ORIGIN, 'attempt': attempt_number,
                   'activation': report.get('activation', {})}
        if attempt_number == 2:
            payload.update(retry_of=report['retry_of'], fixed_code_sha=report['fixed_code_sha'],
                           authorization_sha256=report['authorization_sha256'])
        stream.write(full.chunks.canonical(payload) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
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
        metrics = {'max_component_error': 0.0, 'minimum_cosine': 1.0, 'max_norm_error': 0.0}
        with full.readonly(output / 'chunks.sqlite') as db:
            for start in range(0, len(sample['positions']), batch_size):
                check_capacity()
                positions = sample['positions'][start:start + batch_size]
                rows = [json.loads(db.execute('SELECT row_json FROM projection WHERE position=?', (p,)).fetchone()[0])
                        for p in positions]
                expected_vectors, tokens = reference.encode([row['text'] for row in rows])
                full.exact.validate_vectors(expected_vectors, dimension)
                require(expected_vectors.shape == (len(rows), dimension) and
                        tokens == [row['inference_token_count'] for row in rows], 'reference shape/tokens mismatch')
                actual = np.asarray(loaded[positions])
                norms = np.linalg.norm(actual, axis=1)
                cosine = np.sum(actual * expected_vectors, axis=1) / (norms * np.linalg.norm(expected_vectors, axis=1))
                metrics['max_component_error'] = max(metrics['max_component_error'], float(np.max(np.abs(actual - expected_vectors))))
                metrics['minimum_cosine'] = min(metrics['minimum_cosine'], float(np.min(cosine)))
                metrics['max_norm_error'] = max(metrics['max_norm_error'], float(np.max(np.abs(norms - 1))))
                require(metrics['max_component_error'] <= 1e-4 and metrics['minimum_cosine'] >= .99999 and
                        metrics['max_norm_error'] <= 1e-5, 'sample reference parity failed')
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
    pilot_root = (ROOT / full.pilot.PACK).parent
    for name in ('model', 'tokenizer', 'ort_dll', 'external_data'):
        records = verified['pack']['artifacts'][name]
        artifacts[name] = ([binding(pilot_root / record['path'], output) for record in records]
                           if name == 'external_data' else binding(pilot_root / records['path'], output))
    for name, filename in (('index', 'vectors.usearch'), ('mapping', 'chunks.sqlite'), ('corpus', 'corpus.jsonl')):
        artifacts[name] = binding(output / filename, output)
    declaration = config['declarative_contract']
    return attach_inventory({'schema': acceptance.PACK_SCHEMA, 'object_type': 'runtime_pack',
            'pack_version': 'p4-full-semantic-v1',
            'implementation_origin': full.IMPLEMENTATION, 'recovered_original_source': False,
            'canonical_contract': {'schema': config['schema'], **binding(ROOT / acceptance.CANONICAL_PATH, ROOT)},
            'declarative_contract': declaration, 'full_chunk_count': rows,
            'contract': acceptance.runtime_contract(declaration, rows),
            'snapshot': {'identity': config['snapshot']['path'], **binding(ROOT / config['snapshot']['path'], output)},
            'artifacts': artifacts}, output)


def new_report():
    return {'schema': 'p4-full-build-receipt-v1', 'status': 'FAIL', 'attempts': 0,
            'executor_origin': EXECUTOR_ORIGIN, 'implementation_origin': full.IMPLEMENTATION,
            'recovered_original_source': False, 'phase': 'activation', 'phases': [], 'input_hashes': {},
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
        if attempt_number == 1:
            reserve(output, report)
        else:
            reserve(output, report, attempt_number=attempt_number)
        value = work()
        if attempt_number == 2:
            value['build_provenance'] = retry_build_provenance(report)
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
        if report.get('attempt_reserved', report['attempts'] == 1):
            try:
                terminal(report, output, snapshot)
            except BaseException as terminal_error:
                failed(report, terminal_error, terminal_error=True)
                # Accounting survives failure of the receipt channel.
                try:
                    print(json.dumps(report, sort_keys=True), file=__import__('sys').stderr)
                except BaseException as stderr_error:  # noqa: BLE001 - broken stderr must not mask original
                    failed(report, stderr_error, terminal_error=True)
                if original is not None:
                    raise original from terminal_error
                raise
    if original is not None:
        raise original
    return report


def retry_build_provenance(report):
    return {'attempt_number': 2, 'prior_attempt_result': 'FAIL', 'prior_failure_class': FAILURE_CLASS,
            'retry_authorization_sha256': report['authorization_sha256'],
            'attempt1_execution_receipt_sha256': ATTEMPT1_BINDINGS['execution_receipt']['sha256'],
            'attempt1_result_sha': ATTEMPT1_RESULT_SHA}


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


def _execute(auth, config, fixed_head, report, authorization, authorization_sha):
    retry = auth.get('schema') == RETRY_SCHEMA
    attempt_number = 2 if retry else 1
    output = ROOT / (RETRY_OUTPUT if retry else OUTPUT)
    if not retry:
        full.assert_no_product(ROOT)
        full.check_components(output)
        require(not attempt_lock(output).exists(), 'attempt already reserved; no retry')
    # Activation guards must EXIT before claiming the sole attempt.
    with full.config_guard(config), full.source_guard(fixed_head, ROOT, report):
        if retry:
            authenticate_executor_bindings(auth, fixed_head=fixed_head, root=ROOT)
        verified = full.inventory()
        if retry:
            full.historical_job_bindings(root=ROOT)
        validate_activation_dll(verified)
        count, disk, smoke = reviewed_preflight(auth, config, verified, report, ROOT)
        for receipt in (disk, smoke):
            require(receipt.get('inventory_sha256') == verified['inventory_sha256'] and
                    receipt.get('count_receipt_sha256') == auth['count_review']['expected_sha256'],
                    'reviewed phase bindings mismatch')
        require(disk.get('schema') == 'p4-full-reviewed-disk-v1' and disk.get('status') == 'DISK_PASS' and
                disk.get('count_capture_sha256') == auth['count_review']['expected_capture_sha256'], 'reviewed disk PASS required')
        require(smoke.get('schema') == 'p4-full-phase12-preflight-v1' and
                smoke.get('status') == 'READY_FOR_BUILD_REVIEW' and smoke.get('gates') == 'PASS' and
                smoke.get('disk_receipt_sha256') == auth['disk_review']['expected_sha256'], 'reviewed smoke PASS required')

        def capacity():
            require(full.disk_capacity(disk['disk'])['status'] == 'PASS', 'BLOCKED_DISK: executor')

        capacity()
        snapshot = full.contained(config['snapshot']['path'])
        snapshot_ref = binding(snapshot, ROOT)
        require(all(snapshot_ref[k] == config['snapshot'][k] for k in ('path', 'size', 'sha256')),
                'activation snapshot size/SHA mismatch')
        import torch
        require(torch.cuda.is_available() and torch.cuda.device_count() > 0, 'GPU unavailable')
        if retry:
            validate_retry_history_and_no_retry_product(root=ROOT)
        report['activation'] = {'snapshot': snapshot_ref, 'inventory': verified['bindings'],
                                'dll': verified['pack']['artifacts']['ort_dll'], 'disk': full.disk_capacity(disk['disk']),
                                'gpu_available': True, 'authorization_sha256': authorization_sha, 'fixed_source': fixed_head,
                                'output_absent': not output.exists(), 'lock_absent': not attempt_lock(output, attempt_number).exists()}
        report['input_hashes'] = verified['bindings']
        records = [(snapshot, config['snapshot'], 'snapshot')]
        for name, record in verified['bindings'].items():
            kind = 'ort_dll' if Path(name).is_absolute() else 'input'
            records.append((Path(name) if kind == 'ort_dll' else full.contained(name), {'path': name, **record}, kind))

    def work():
        with full.config_guard(config), full.source_guard(fixed_head, ROOT, report), acceptance._inventory_guard(records):
            raw, _ = full.exact.frozen_tokenizers(full.contained(verified['model']['asset_directory']))

            def encoder(device):
                capacity()
                result = full.exact.LocalEncoder(verified['model'], verified['contract'], device, verified['job']['threads'])
                require(result.info['actual_dtype'] == 'torch.float32', 'actual FP32 required')
                if device == 'cuda':
                    require(result.info['actual_device'].startswith('cuda'), 'actual GPU required')
                    report['encoder'] = result.info
                else:
                    report['reference_encoder'] = {'path': 'independent_pinned_cpu_LocalEncoder', **result.info}
                return result

            with full.readonly(snapshot) as conn, closing(full.documents(conn)) as stream:
                report['build'] = build_stream(stream, raw, verified['manifest']['tokenizer_inventory_sha256'],
                    lambda: encoder('cuda'), lambda: index_factory(config['declarative_contract']), output,
                    config['declarative_contract'], count, batch_size=verified['job']['batch_size'],
                    check_capacity=capacity, reference=lambda: encoder('cpu'), report=report)
            phase(report, 'runtime_manifest_validation')
            value = manifest(config, verified, output, count['actual_chunks'])
            acceptance.validate_full_manifest(value, config, pack_root=output)
            capacity()
        return value

    def finalize():
        with full.config_guard(config), full.source_guard(fixed_head, ROOT, report), acceptance._inventory_guard(records):
            require(full.inventory()['bindings'] == verified['bindings'], 'executor inventory changed')
            if retry:
                authorize_retry(authorization, authorization_sha, fixed_head=fixed_head, root=ROOT)
                validate_retry_history_and_no_retry_product(root=ROOT, check_new=False)
            else:
                authorize(authorization, authorization_sha, fixed_head=fixed_head, root=ROOT)

    if retry:
        return lifecycle(output, report, work, snapshot=snapshot, finalize=finalize, attempt_number=2)
    return lifecycle(output, report, work, snapshot=snapshot, finalize=finalize)


def execute(*, authorization=None, expected_authorization_sha256=None, fixed_head='NOT_FIXED_YET'):
    report = new_report()
    report.update(fixed_code_sha=fixed_head, authorization_sha256=expected_authorization_sha256)
    try:
        auth = authorize(authorization, expected_authorization_sha256, fixed_head=fixed_head, root=ROOT)
        config = read_json(full.CONFIG)
        full.validate_contract(config)
        return _execute(auth, config, fixed_head, report, authorization, expected_authorization_sha256)
    except BaseException as error:
        failed(report, error)
        raise


def verify_fixed_current_dev(fixed_head, root):
    for ref in ('HEAD', 'origin/dev'):
        require(subprocess.check_output(['git', 'rev-parse', ref], cwd=root, text=True).strip() == fixed_head,
                'retry fixed HEAD/origin dev mismatch')


def execute_retry(*, authorization=None, expected_authorization_sha256=None, fixed_head='NOT_FIXED_YET'):
    report = new_report()
    report.update(attempts=1, attempt_reserved=False, attempt_number=2,
                  fixed_code_sha=fixed_head, authorization_sha256=expected_authorization_sha256,
                  retry_of=attempt1_history_binding(), BUILD_POLICY_EXCEPTION=POLICY_EXCEPTION)
    try:
        verify_fixed_current_dev(fixed_head, ROOT)
        auth = authorize_retry(authorization, expected_authorization_sha256, fixed_head=fixed_head,
                               root=ROOT, check_sources=False)
        validate_retry_history_and_no_retry_product(root=ROOT, check_new=False)
        config = read_json(full.CONFIG)
        full.validate_contract(config)
        return _execute(auth, config, fixed_head, report, authorization, expected_authorization_sha256)
    except BaseException as error:
        failed(report, error)
        raise


def attempt2_readiness(*, fixed_head):
    """One read-only resource probe; never authorize/reserve/project/embed/build ANN."""
    report = {'schema': 'p4-full-semantic-attempt2-readiness-v1',
              'ATTEMPT2_IMPLEMENTATION_SHA': fixed_head, 'SECOND_ATTEMPT_STARTED': 'NO',
              'SECOND_ATTEMPT_AUTHORIZED': 'NO', 'FORMAL_BUILD_ATTEMPTS_TOTAL': 1,
              'STOP_STATE': 'WAITING_REVIEW', 'status': 'FAIL', 'checks': {}}
    before = {}
    gate = 'FIXED_SOURCE'
    cancellation = None
    try:
        verify_fixed_current_dev(fixed_head, ROOT)
        report['FIXED_SOURCE'] = 'PASS'
        gate = 'ATTEMPT1_HISTORY'
        for key, ref in ATTEMPT1_BINDINGS.items():
            path = full.contained(ref['path'], ROOT)
            before[key] = {'size': path.stat().st_size, 'sha256': full.exact.sha(path)}
        report['history'] = validate_retry_history_and_no_retry_product(root=ROOT)
        report['ATTEMPT1_HISTORY'] = 'PASS'
        gate = 'CANONICAL_CONTRACT'
        config = read_json(full.CONFIG)
        full.validate_contract(config)
        report['CANONICAL_CONTRACT'] = 'PASS'
        source_report = new_report()
        gate = 'AUTHORITY_PARITY'
        with full.config_guard(config), full.source_guard(fixed_head, ROOT, source_report):
            report['historical_jobs'] = full.historical_job_bindings(root=ROOT)
            dll = acceptance._approved_dll_path()
            verified = full.inventory()
            require(validate_activation_dll(verified) == dll, 'readiness authority parity mismatch')
            report['dll'] = binding(dll, ROOT)
            report['inventory_sha256'] = verified['inventory_sha256']
            report['AUTHORITY_PARITY'] = 'PASS'
            gate = 'SNAPSHOT'
            snapshot = full.contained(config['snapshot']['path'], ROOT)
            report['snapshot'] = binding(snapshot, ROOT)
            require(all(report['snapshot'][k] == config['snapshot'][k] for k in ('path', 'size', 'sha256')),
                    'readiness snapshot mismatch')
            report['SNAPSHOT'] = 'PASS'
            gate = 'DISK'
            auth = read_json(full.contained(ATTEMPT1_BINDINGS['authorization']['path'], ROOT))
            review = auth['disk_review']
            disk_path = full.contained(review['path'], ROOT)
            require(full.exact.sha(disk_path) == review['expected_sha256'], 'readiness reviewed disk hash mismatch')
            disk = read_json(disk_path)
            report['fresh_disk'] = full.disk_capacity(disk['disk'])
            require(report['fresh_disk']['status'] == 'PASS', 'readiness fresh disk FAIL')
            report['DISK'] = 'PASS'
            gate = 'GPU'
            import torch
            report['gpu'] = {'available': torch.cuda.is_available(), 'device_count': torch.cuda.device_count()}
            require(report['gpu']['available'] and report['gpu']['device_count'] > 0, 'readiness GPU unavailable')
            report['GPU'] = 'PASS'
        gate = 'FINAL_HISTORY'
        validate_retry_history_and_no_retry_product(root=ROOT)
        report['FINAL_HISTORY'] = 'PASS'
        report.update(ATTEMPT2_OUTPUT_ABSENT='YES', ATTEMPT2_LOCK_ABSENT='YES', status='PASS')
    except BaseException as error:  # noqa: BLE001 - preserve cancellation evidence, then propagate below
        report[gate] = 'FAIL'
        report['status'] = 'FAIL'
        report['error'] = {'type': type(error).__name__, 'message': str(error), 'gate': gate}
        if not isinstance(error, Exception):
            cancellation = error
    finally:
        report['attempt1_before'] = before
        report['attempt1_after'] = {}
        report['after_errors'] = []
        for key, ref in ATTEMPT1_BINDINGS.items():
            try:
                path = full.contained(ref['path'], ROOT)
                report['attempt1_after'][key] = {'size': path.stat().st_size, 'sha256': full.exact.sha(path)}
            except BaseException as error:  # noqa: BLE001 - retain secondary error without losing first/cancellation
                report['after_errors'].append({'binding': key, 'type': type(error).__name__, 'message': str(error)})
                if not isinstance(error, Exception) and cancellation is None:
                    cancellation = error
        report['ATTEMPT1_PRESERVED'] = ('YES' if before == report['attempt1_after'] and
            len(before) == len(ATTEMPT1_BINDINGS) and not report['after_errors'] else 'NO')
        if report['ATTEMPT1_PRESERVED'] != 'YES':
            report['status'] = 'FAIL'
        for key in ('ATTEMPT1_HISTORY', 'AUTHORITY_PARITY', 'SNAPSHOT', 'DISK', 'GPU'):
            report.setdefault(key, 'NOT_RUN')
        report['ATTEMPT2_OUTPUT_ABSENT'] = 'NO' if (ROOT / RETRY_OUTPUT).exists() else 'YES'
        report['ATTEMPT2_LOCK_ABSENT'] = 'NO' if attempt_lock(ROOT / RETRY_OUTPUT, 2).exists() else 'YES'
    if cancellation is not None:
        cancellation.readiness_receipt = report
        raise cancellation
    return report


def synthetic_run(root):
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
    output, report = root / 'synthetic-pack', new_report()
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
            'synthetic': True, 'implementation_origin': full.IMPLEMENTATION, 'recovered_original_source': False,
            'canonical_contract': {'schema': config['schema'], **binding(config_path, root)},
            'snapshot': {'identity': config['snapshot']['path'], **binding(snapshot, output)},
            'contract': acceptance.runtime_contract(declaration, n),
            'declarative_contract': declaration, 'full_chunk_count': n, 'artifacts': artifacts}, output)
        # Only fixture authorities are substituted; byte/path/schema validation is real.
        with ExitStack() as stack:
            for obj, name, replacement in ((acceptance, 'ROOT', root), (acceptance, 'CONFIG', config_path),
                    (acceptance, 'validate_contract', lambda value: declaration if value == config else None),
                    (acceptance.pilot, 'DLL_SIZE', artifacts['ort_dll']['size']),
                    (acceptance.pilot, 'DLL_SHA', artifacts['ort_dll']['sha256'])):
                stack.enter_context(patch.object(obj, name, replacement))
            acceptance.validate_full_manifest(value, config, pack_root=output)
        report['manifest_validator'] = 'actual_FULL_validator_with_synthetic_authorities'
        return value

    with patch.object(__import__(__name__, fromlist=['ROOT']), 'ROOT', root):
        return lifecycle(output, report, work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ('validate', 'dry-run', 'synthetic', 'execute-full', 'execute-full-retry'):
        modes.add_argument('--' + mode, action='store_true')
    parser.add_argument('--authorization')
    parser.add_argument('--expected-authorization-sha256')
    parser.add_argument('--fixed-head', default='NOT_FIXED_YET')
    args = parser.parse_args()
    if args.execute_full_retry:
        result = execute_retry(authorization=args.authorization,
            expected_authorization_sha256=args.expected_authorization_sha256, fixed_head=args.fixed_head)
    elif args.execute_full:
        result = execute(authorization=args.authorization,
                         expected_authorization_sha256=args.expected_authorization_sha256, fixed_head=args.fixed_head)
    elif args.synthetic:
        with tempfile.TemporaryDirectory(prefix='p4-full-synthetic-') as directory:
            result = synthetic_run(Path(directory))
    else:
        config = read_json(full.CONFIG)
        full.validate_contract(config)
        result = {'status': 'SOURCE_CONFIG_VALID', 'attempts': 0, 'executor_origin': EXECUTOR_ORIGIN,
                  'source_sha256': full.exact.sha(Path(__file__)), 'config_sha256': full.exact.sha(full.CONFIG)}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
