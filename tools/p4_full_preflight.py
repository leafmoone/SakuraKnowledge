from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path

from tools import p4_chunks as chunks
from tools import p4_corpus as corpus
from tools import p4_exact_pilot as exact
from tools import p4_rust_pilot as pilot

ROOT = Path(os.path.abspath(__file__)).parents[1]
CONFIG = ROOT / 'configs/p4-full-semantic-v1.json'
IMPLEMENTATION = 'clean_room_reimplementation_after_untracked_source_loss'
REFERENCE_HEAD = '471829644b32eecc10aa30d9d3b71979500a3117'
AUDIT_CAP_BYTES = 1024 ** 3
DOCUMENT_CAP_BYTES = 16 * 1024 ** 2
AUDIT_BATCH_SIZE = 1024
AUDIT_CACHE_KIB = 16384
SOURCE_PATHS = (
    'tools/p4_full_preflight.py', 'tests/test_p4_full_preflight.py',
    'configs/p4-full-semantic-v1.json', 'docs/p4-full-preflight-recovery.md',
    'tools/p4_chunks.py', 'tools/p4_corpus.py', 'tools/p4_exact_pilot.py',
    'tools/p4_rust_pilot.py', 'rust/src/semantic.rs', 'rust/src/bin/semantic_pilot.rs',
    'rust/src/bin/semantic_dependency_probe.rs', 'rust/src/lib.rs', 'rust/src/main.rs',
    'rust/Cargo.toml', 'rust/Cargo.lock',
)
SNAPSHOT = {'path': 'build/p3-full-authorized-retry1/knowledge.sqlite',
            'size': 21718736896,
            'sha256': '61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9'}
STRATA = {'bangumi.subject': 690068, 'bangumi.character': 221960,
          'bangumi.person': 102338, 'danbooru.wiki': 281272}
DECLARATIONS = {
    'corpus': {'documents': 1295638, 'strata': STRATA, 'moegirl': 0,
               'local_tag': 0, 'index_episodes': False},
    'encoder': {'repository': 'BAAI/bge-m3', 'revision': pilot.REVISION,
                'pooling': 'cls', 'normalize': True, 'dtype': 'float32',
                'dimension': 1024, 'query_prefix': '', 'passage_prefix': '',
                'max_sequence_tokens': 512},
    'chunk': {'version': 'paragraph-model-tokenizer-v1', 'max_tokens': 384,
              'overlap': 64, 'order': 'document_id,chunk_index ascending'},
    'ann': {'library': 'usearch', 'version': '2.26.2', 'metric': 'cos', 'dtype': 'f32',
            'connectivity': 16, 'expansion_add': 256, 'expansion_search': 128,
            'chunk_depth': 512, 'entry_depth': 100},
    'hybrid': {'bm25_document_depth': 100, 'rrf_k': 60, 'pins': 'trusted_exact_alias',
               'ties': 'kind,namespace,value'},
    'runtime': {'lexical_mode': 'full_snapshot_fts', 'ort_version': '1.24.1',
                'intra_threads': 8, 'inter_threads': 1, 'sequential': True,
                'provider': 'CPUExecutionProvider'},
    'build': {'max_attempts': 1, 'output_policy': 'create_new', 'inputs': 'readonly',
              'build_entry': False},
}
REFERENCE_SOURCES = ['committed Rust pilot 471829644b32eecc10aa30d9d3b71979500a3117',
                     'approved FULL requirements', 'approved P3 snapshot',
                     'committed pilot tokenizer/chunk/ANN/runtime']
REFERENCES = ['tools/p4_rust_pilot.py', 'tools/p4_chunks.py',
              'configs/p4-trusted-text-v1.json', 'docs/p4-full-preflight-recovery.md',
              'docs/p3-full-coverage-contract.md']
PINNED_JOBS = {
    'configs/p4-rust-pilot-v1.json':
        '53ee8132288252713b5ccdcd36acfa6f4aee455e95e552eafca0676a91e0cf14',
    'configs/p4-pilot-job-b.json':
        '6e4e975e9a0e068156e841069535a7db935a8db233034c1e870191050e98f18f',
}
STAGING_KEYS = {'vectors', 'ann_construction', 'mapping', 'final_ann', 'receipts'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def positive_integer(value, name):
    require(type(value) is int and value > 0, f'explicit positive {name} required')


def validate_staging(staging):
    require(isinstance(staging, dict) and set(staging) == STAGING_KEYS and
            all(type(v) is int and v > 0 for v in staging.values()),
            'explicit nonzero staging budgets required')


def validate_contract(value):
    expected = {'schema': 'p4-full-semantic-contract-v1', 'object_type': 'canonical_contract',
                'implementation_origin': IMPLEMENTATION, 'reference_sources': REFERENCE_SOURCES,
                'implementation': IMPLEMENTATION,
                'recovered_original_source': False, 'references': REFERENCES,
                'preservation_inventory_sha256':
                    '26d7f147be8aca7d715f35d839f3758dd247eae9a573a7e3e3b0057c564879e1',
                'snapshot': SNAPSHOT, 'declarative_contract': DECLARATIONS}
    require(chunks.canonical(value) == chunks.canonical(expected), 'FULL contract mismatch')
    return value['declarative_contract']


def assert_no_product(root=ROOT):
    root = Path(root)
    require(not os.path.lexists(root / 'build/p4-full-semantic-v1'),
            'FULL product root must be absent')
    for directory in (root / 'build', root / 'reports/P4'):
        if directory.exists():
            for path in directory.glob('*p4-full*'):
                require(not any(word in path.name.lower() for word in ('lock', 'attempt')),
                        'FULL lock/attempt exists')


@contextmanager
def product_guard(root=ROOT):
    assert_no_product(root)
    try:
        yield
    finally:
        assert_no_product(root)


@contextmanager
def config_guard(config, root=ROOT):
    path = contained('configs/p4-full-semantic-v1.json', root)
    before = path.read_bytes()
    validate_contract(json.loads(before))
    require(chunks.canonical(json.loads(before)) == chunks.canonical(config),
            'canonical config differs from passed contract')
    binding = {'path': 'configs/p4-full-semantic-v1.json', 'size': len(before),
               'sha256': hashlib.sha256(before).hexdigest()}
    try:
        yield binding
    finally:
        current = contained('configs/p4-full-semantic-v1.json', root)
        require(current == path and current.read_bytes() == before,
                'canonical config changed during preflight')


def scalar(conn, sql, parameters=()):
    with closing(conn.execute(sql, parameters)) as cursor:
        row = cursor.fetchone()
        require(row is not None, 'required SQLite metadata missing')
        return row[0]


@contextmanager
def readonly(path):
    check_components(path)
    path = Path(path).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        conn.row_factory = sqlite3.Row
        for sql in ('PRAGMA query_only=ON', 'PRAGMA temp_store=MEMORY'):
            with closing(conn.execute(sql)):
                pass
        yield conn
    finally:
        conn.close()


@contextmanager
def validate_snapshot(config, root=ROOT):
    validate_contract(config)
    with product_guard(root):
        path = contained(SNAPSHOT['path'], root)
        before = path.stat()
        sidecars = corpus.sidecars(path)
        require(before.st_size == SNAPSHOT['size'] and
                corpus.sha256_file(path) == SNAPSHOT['sha256'], 'snapshot binding mismatch')
        try:
            with readonly(path) as conn:
                require(scalar(conn, "SELECT value FROM build_meta WHERE key='index_episodes'")
                        == 'false', 'index_episodes policy must be false')
                yield conn
        finally:
            require(path.stat() == before and corpus.sidecars(path) == sidecars and
                    corpus.sha256_file(path) == SNAPSHOT['sha256'], 'snapshot changed')


def check_components(path):
    """Inspect the raw walk, including components traversed before a '..'."""
    path = Path(path)
    if not path.is_absolute():
        path = Path.cwd() / path
    current = Path(path.anchor)
    for part in (None, *path.parts[1:]):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        junction = getattr(current, 'is_junction', None)
        require(not stat.S_ISLNK(info.st_mode) and
                not (getattr(info, 'st_file_attributes', 0) & 0x400) and
                not (junction is not None and junction()),
                f'inventory path escape: symlink/reparse/junction component: {current}')
    return path


def controlled_path(path, root=None, *, strict=True):
    root = Path(ROOT if root is None else root)
    check_components(root)
    raw = Path(path)
    if not raw.is_absolute():
        raw = root / raw
    check_components(raw)
    resolved_root = root.resolve(strict=True)
    require(Path(os.path.abspath(raw)).is_relative_to(resolved_root), 'inventory path escape')
    resolved = raw.resolve(strict=strict)
    require(resolved.is_relative_to(resolved_root), 'inventory path escape')
    return resolved


def contained(name, root=None):
    require(not Path(name).is_absolute(), 'inventory path escape')
    return controlled_path(name, root)


def record_path(record, directory, *, kind=None):
    raw = Path(directory) / record['path']
    if kind == 'ort_dll' and Path(record['path']).is_absolute():
        check_components(ROOT)
        check_components(raw)
        require(raw == pilot.EXTERNAL_ORT_DLL and raw.resolve(strict=True) == raw and
                record['size'] == pilot.DLL_SIZE and record['sha256'] == pilot.DLL_SHA,
                'unapproved external ORT DLL')
        require(raw.is_file() and raw.stat().st_size == pilot.DLL_SIZE and
                exact.sha(raw) == pilot.DLL_SHA, 'unpinned ORT DLL')
        return raw
    return controlled_path(raw)


def check_tree(directory):
    directory = controlled_path(directory)
    for path in directory.rglob('*'):
        check_components(path)
    return directory


def preliminary_pack(pack_path):
    pack_path = controlled_path(pack_path)
    pack = exact.load(pack_path)
    for record in (pack['snapshot'], pack['export_manifest']):
        record_path(record, pack_path.parent)
    for kind, value in pack['artifacts'].items():
        for record in value if kind == 'external_data' else [value]:
            record_path(record, pack_path.parent, kind=kind)
    for record in pack['approved_receipts'].values():
        record_path(record, ROOT)
    return pack


def preliminary_export(export):
    export = controlled_path(export)
    manifest = exact.load(export)
    check_tree(export.parent)
    for record in manifest['files']:
        path = record_path(record, export.parent)
        require(path.is_relative_to(export.parent), 'external tensor escapes export')


def preliminary_model(job):
    for key in ('summary', 'chunks', 'chunks_manifest', 'corpus', 'gold', 'authorization'):
        contained(job[key])
    for key in ('index', 'output'):
        controlled_path(job[key], strict=False)
    summary = exact.load(contained(job['summary']))
    model = summary['models'][job['model']]
    contained(model['contract']['path'])
    directory = contained(model['asset_directory'])
    check_tree(directory)
    for record in model['obtained_receipt']['files']:
        path = record_path(record, directory)
        require(path.is_relative_to(directory), 'asset path escape')
    return model


def documents(conn):
    require(scalar(conn, "SELECT value FROM build_meta WHERE key='index_episodes'") == 'false',
            'index_episodes policy must be false')
    with closing(conn.execute('SELECT source_id,metadata FROM sources ORDER BY source_id')) as cur:
        sources = {row[0]: json.loads(row[1]) for row in cur}
    sql = f'''SELECT {corpus.FIELDS} FROM documents d
        JOIN entries e ON e.id=d.entry_id WHERE {corpus.TRUST}
        AND EXISTS (SELECT 1 FROM search_fts f WHERE f.document_id=d.id
                    AND f.entry_id=e.id AND f.text=d.search_text) ORDER BY d.id'''
    previous = None
    with closing(conn.execute(sql)) as cursor:
        for row in cursor:
            doc = corpus.project(row, sources)
            did = doc['document_id']
            require(type(did) is int and (previous is None or did > previous),
                    'duplicate or unordered document ID')
            previous = did
            yield doc


def document_bound(document, cap):
    positive_integer(cap, 'max_document_text_bytes')
    text = chunks.document_text(document)
    # Reject invalid Unicode and measure exact UTF-8 without another document-sized allocation.
    size = 0
    for char in text:
        code = ord(char)
        require(not 0xD800 <= code <= 0xDFFF, 'invalid UTF-8 document text')
        size += 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4
        require(size <= cap, 'BLOCKED_RESOURCE: document UTF-8 text exceeds configured bound before tokenizer encode')
    return size


def project(document, tokenizer, tokenizer_inventory_sha256, statistics=None, *,
            max_document_text_bytes=DOCUMENT_CAP_BYTES):
    document_bound(document, max_document_text_bytes)
    require(getattr(tokenizer, 'truncation', None) is None and
            getattr(tokenizer, 'padding', None) is None, 'tokenizer truncation/padding enabled')
    return chunks.project_document(document, tokenizer,
                                   base_snapshot_sha256=SNAPSHOT['sha256'],
                                   tokenizer_inventory_sha256=tokenizer_inventory_sha256,
                                   passage_prefix='', max_sequence_tokens=512,
                                   statistics=statistics)


class AuditDiskBlocked(RuntimeError):
    def __init__(self, message, audit=None):
        super().__init__(message)
        self.audit = audit if audit is not None else {}
        self.status = 'BLOCKED_AUDIT_DISK'
        self.count_complete = False


def audit_capacity(root, max_audit_bytes):
    positive_integer(max_audit_bytes, 'max_audit_bytes')
    free = shutil.disk_usage(Path(root).resolve(strict=True)).free
    if free < math.ceil(max_audit_bytes * 1.25):
        raise AuditDiskBlocked('BLOCKED_AUDIT_DISK: insufficient audit reservation')
    return free


@contextmanager
def chunk_audit(root, max_audit_bytes, batch_size, metadata):
    positive_integer(batch_size, 'audit_batch_size')
    require(batch_size <= 1024, 'audit batch exceeds 1024')
    audit_capacity(root, max_audit_bytes)
    root = Path(root).resolve(strict=True)
    parent = root / 'build/p4-preflight-audit-temporary'
    for path in (root / 'build', parent):
        require(not path.is_symlink() and path.resolve().is_relative_to(root),
                'audit temporary parent escape')
        require(not (getattr(path.lstat(), 'st_file_attributes', 0) & 0x400) if path.exists()
                else True, 'audit reparse point forbidden')
    created_parent = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    metadata.update(audit_cap_bytes=max_audit_bytes, audit_peak_bytes=0,
                    temporary_parent=str(parent), temporary_parent_created=created_parent,
                    temporary_created=False, temporary_removed=False,
                    batch_size=batch_size, cache_size_kib=-AUDIT_CACHE_KIB,
                    temp_store='FILE', journal_mode='DELETE')
    directory = tempfile.TemporaryDirectory(prefix='chunk-ids-', dir=parent)
    path = Path(directory.name) / 'audit.sqlite'
    conn = None
    metadata.update(temporary_created=True, temporary_directory=directory.name)
    try:
        conn = sqlite3.connect(path)
        for sql in ('PRAGMA cache_size=-16384', 'PRAGMA temp_store=FILE',
                    'PRAGMA journal_mode=DELETE'):
            with closing(conn.execute(sql)):
                pass
        page_size = scalar(conn, 'PRAGMA page_size')
        limit = max_audit_bytes // page_size
        if limit < 2:
            raise AuditDiskBlocked('BLOCKED_AUDIT_DISK: audit cap too small', metadata)
        require(scalar(conn, f'PRAGMA max_page_count={limit}') == limit, 'audit hard cap failed')
        metadata.update(page_size=page_size, max_page_count=limit)
        with closing(conn.execute('CREATE TABLE audit_ids (chunk_id TEXT PRIMARY KEY) WITHOUT ROWID')):
            pass
        conn.commit()

        def check():
            allocated = scalar(conn, 'PRAGMA page_count') * page_size
            journal = Path(str(path) + '-journal')
            used = allocated + (journal.stat().st_size if journal.exists() else 0)
            metadata['audit_peak_bytes'] = max(metadata['audit_peak_bytes'], used)
            free = shutil.disk_usage(parent).free
            if used >= max_audit_bytes or free < max_audit_bytes - used:
                raise AuditDiskBlocked('BLOCKED_AUDIT_DISK: audit disk hard cap/free space', metadata)

        check()
        yield conn, check
    except sqlite3.IntegrityError as error:
        raise ValueError('global duplicate chunk ID') from error
    except sqlite3.Error as error:
        if getattr(error, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL or \
                'database or disk is full' in str(error).lower():
            raise AuditDiskBlocked('BLOCKED_AUDIT_DISK: SQLITE_FULL', metadata) from error
        raise
    finally:
        if conn is not None:
            conn.close()
        directory.cleanup()
        metadata['temporary_removed'] = not Path(directory.name).exists()
        require(metadata['temporary_removed'], 'audit temporary directory cleanup failed')


def count_documents(stream, tokenizer, inventory_sha, *, root=ROOT,
                    max_audit_bytes=AUDIT_CAP_BYTES, audit_batch_size=AUDIT_BATCH_SIZE,
                    max_document_text_bytes=DOCUMENT_CAP_BYTES):
    """Exact disk-backed global uniqueness; never an assumed token/chunk bound."""
    positive_integer(max_document_text_bytes, 'max_document_text_bytes')
    counts, totals = Counter(), Counter()
    digest = hashlib.sha256()
    previous, position, maximum, document_peak = None, 0, 0, 0
    audit, batch = {}, []
    with product_guard(root), chunk_audit(root, max_audit_bytes, audit_batch_size, audit) as (db, check):
        def flush():
            if batch:
                with closing(db.executemany('INSERT INTO audit_ids VALUES (?)', batch)):
                    pass
                check()  # Include the rollback journal before DELETE-mode commit.
                db.commit()
                check()
                batch.clear()

        for doc in stream:
            document_peak = max(document_peak, document_bound(doc, max_document_text_bytes))
            did = doc['document_id']
            require(type(did) is int and (previous is None or did > previous),
                    'duplicate or unordered document ID')
            previous = did
            namespace = doc['entry_key']['namespace']
            expected = {'bangumi.subject': ('bangumi', 'subject'),
                        'bangumi.character': ('bangumi', 'character'),
                        'bangumi.person': ('bangumi', 'person'),
                        'danbooru.wiki': ('danbooru', 'page')}
            require(namespace in expected and
                    (doc['source_family'], doc['entry_key']['kind']) == expected[namespace],
                    'unexpected eligible stratum')
            counts[namespace] += 1
            stats = {}
            rows = project(doc, tokenizer, inventory_sha, stats,
                           max_document_text_bytes=max_document_text_bytes)
            require(rows and stats['empty_token_document_count'] == 0, 'empty token document')
            totals.update(stats)
            for index, row in enumerate(rows):
                require(row['document_id'] == did and row['chunk_index'] == index,
                        'chunk order/identity mismatch')
                identity = {key: row[key] for key in
                            ('version', 'base_snapshot_sha256', 'tokenizer_inventory_sha256',
                             'document_id', 'chunk_index', 'canonical_token_start',
                             'canonical_token_end', 'text_sha256')}
                require(row['chunk_id'] == chunks.digest(chunks.canonical(identity)), 'chunk ID mismatch')
                batch.append((row['chunk_id'],))
                if len(batch) == audit_batch_size:
                    flush()
                require(0 < row['token_count'] <= 384, 'chunk token budget')
                maximum = max(maximum, row['token_count'])
                digest.update(chunks.canonical({**row, 'position': position}) + b'\n')
                position += 1
        flush()
    require(position > 0, 'empty census')
    return {'documents': sum(counts.values()), 'strata': dict(counts),
            'actual_chunks': position, **dict(totals), 'max_chunk_tokens': maximum,
            'duplicate_document_count': 0, 'duplicate_chunk_identity_count': 0,
            'chunk_id_collision_policy': 'Exact SQLite UNIQUE(chunk_id) WITHOUT ROWID',
            'audit': audit, 'count_complete': True,
            'max_document_text_bytes': max_document_text_bytes,
            'actual_max_document_text_bytes': document_peak,
            'moegirl': 0, 'local_tag': 0, 'index_episodes': False,
            'order': 'document_id,chunk_index ascending', 'streaming_sha256': digest.hexdigest()}


def census_and_chunk_count(conn, tokenizer, tokenizer_inventory_sha256, contract, **resources):
    validate_contract(contract)
    with closing(documents(conn)) as stream:
        result = count_documents(stream, tokenizer, tokenizer_inventory_sha256, **resources)
    require(result['strata'] == STRATA and result['documents'] == 1295638, 'FULL census mismatch')
    return {'schema': 'p4-full-phase9-count-v1', **result,
            'FULL_DOCUMENT_COUNT': result['documents'], 'FULL_EXACT_CHUNK_COUNT': result['actual_chunks'],
            'EMPTY_DOCUMENTS': result.get('empty_token_document_count', 0),
            'DUPLICATE_DOCUMENTS': result['duplicate_document_count'],
            'DUPLICATE_CHUNK_IDS': result['duplicate_chunk_identity_count'],
            'OVERSIZED_PARAGRAPH_SPLITS': result.get('oversized_paragraph_split_count', 0),
            'TOTAL_TOKENS': result.get('canonical_token_count', 0),
            'MAX_CHUNK_TOKENS': result['max_chunk_tokens'], 'attempts': 0}


def deterministic_smoke(conn, tokenizer, inventory_sha, pilot_document_ids, *,
                        max_document_text_bytes=DOCUMENT_CAP_BYTES):
    pilot_ids = set(pilot_document_ids)
    require(len(pilot_ids) == 50000, 'complete pilot document exclusion required')
    with closing(documents(conn)) as stream:
        sample = heapq.nsmallest(512, stream,
                                key=lambda doc: corpus.rank(doc, 'p4-full-preflight-512-v1'))
    require(len(sample) == 512, '512 smoke documents required')
    projected = []
    for doc in sorted(sample, key=lambda item: item['document_id']):
        first = project(doc, tokenizer, inventory_sha,
                        max_document_text_bytes=max_document_text_bytes)
        second = project(doc, tokenizer, inventory_sha,
                         max_document_text_bytes=max_document_text_bytes)
        require(first and first == second, 'nondeterministic/empty chunker')
        for row, repeated in zip(first, second, strict=True):
            ids = list(tokenizer.encode(row['text'], add_special_tokens=False).ids)
            again = list(tokenizer.encode(repeated['text'], add_special_tokens=False).ids)
            require(ids == again and len(ids) == row['token_count'], 'nondeterministic token IDs')
            projected.append({**row, 'token_ids': ids, 'position': len(projected)})
    full_only = []
    with closing(documents(conn)) as stream:
        for doc in stream:
            if doc['document_id'] not in pilot_ids:
                full_only.extend(project(doc, tokenizer, inventory_sha,
                                         max_document_text_bytes=max_document_text_bytes)
                                 [:512 - len(full_only)])
                if len(full_only) == 512:
                    break
    require(len(full_only) == 512, '512 FULL-only chunks required')
    return projected, full_only


def measure_mapping_sample(sample, tokenizer):
    require(sample, 'nonempty mapping sample required')
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.execute('CREATE TABLE audit_mapping (position INTEGER PRIMARY KEY, '
                     'chunk_id TEXT UNIQUE, document_id INTEGER, chunk_index INTEGER, '
                     'metadata BLOB NOT NULL, token_ids BLOB NOT NULL, text TEXT NOT NULL)').close()
        conn.execute('CREATE INDEX audit_document ON audit_mapping(document_id)').close()
        conn.executemany('INSERT INTO audit_mapping VALUES (?,?,?,?,?,?,?)',
                         [(i, row['chunk_id'], row['document_id'], row['chunk_index'],
                           chunks.canonical(row), chunks.canonical(list(
                               tokenizer.encode(row['text'], add_special_tokens=False).ids)), row['text'])
                          for i, row in enumerate(sample)]).close()
        pages, page_size = scalar(conn, 'PRAGMA page_count'), scalar(conn, 'PRAGMA page_size')
    serialized_bytes = sum(len(chunks.canonical(row)) for row in sample)
    return {'rows': len(sample), 'page_count': pages, 'page_size': page_size,
            'actual_sqlite_bytes': pages * page_size, 'serialized_bytes': serialized_bytes,
            'bytes_per_chunk': max(pages * page_size, serialized_bytes) / len(sample),
            'schema': 'expanded position/chunk_id/document_id/chunk_index/metadata/token_ids/text',
            'database': ':memory: audit only; explicit finally-close',
            'limitation': 'Measured actual sample plus 25%; not a formal future size bound'}


def initial_stage_gate(staging, root, max_audit_bytes):
    """Necessary lower bound only: each required nonempty document emits >=1 chunk.

    This never substitutes for exact-count, measured-header or expanded-schema gates.
    No model inventory, tokenizer load or FULL scan occurs here.
    """
    validate_staging(staging)
    positive_integer(max_audit_bytes, 'max_audit_bytes')
    n = DECLARATIONS['corpus']['documents']
    raw = n * 4096 + 1  # Strictly positive header lower bound; actual header checked later.
    ann = math.ceil(n * (223537008 / 52664) * 1.1)
    mapping_path = contained(pilot.ann.INPUTS['mapping'], root)
    exact.bound(mapping_path, pilot.ANN_INPUT_HASHES['mapping'])
    mapping_size = mapping_path.stat().st_size
    require(mapping_size > 0, 'initial approved pilot mapping bytes required')
    mapping = math.ceil(n * mapping_size / 52664 * 1.25)
    minimums = {'vectors': raw, 'ann_construction': 2 * ann, 'mapping': mapping,
                'final_ann': ann, 'receipts': 1024 ** 2}
    for name, minimum in minimums.items():
        require(staging[name] >= minimum, f'initial staging {name} below necessary minimum {minimum}')
    peak = raw + ann + mapping + sum(staging.values()) + max_audit_bytes
    free = shutil.disk_usage(Path(root).resolve(strict=True)).free
    required = math.ceil(peak * 1.25)
    require(free >= required, 'BLOCKED_DISK: initial minimum reservation insufficient')
    return {'document_chunk_lower_bound': n, 'not_exact_chunk_count': True,
            'raw_header_lower_bound_bytes': 1, 'pilot_mapping_bytes': mapping_size,
            'minimums': minimums, 'peak_lower_bound_bytes': peak, 'required_free_bytes': required,
            'free_bytes': free, 'audit_cap_bytes': max_audit_bytes,
            'existing_assets_accounting': 'Referenced existing model/runtime bytes are not copied; '
            'complete bound inventory and actual header/schema/count gates remain mandatory'}


def disk_budget(actual_chunks, pilot_mapping, schema_sample_bytes_per_chunk, *,
                raw_header_bytes, staging, max_audit_bytes=AUDIT_CAP_BYTES, report_bytes=0):
    positive_integer(actual_chunks, 'actual chunk count')
    positive_integer(raw_header_bytes, 'measured raw header')
    positive_integer(max_audit_bytes, 'max_audit_bytes')
    require(type(report_bytes) is int and report_bytes >= 0, 'invalid serialized report bytes')
    require(math.isfinite(schema_sample_bytes_per_chunk) and schema_sample_bytes_per_chunk > 0,
            'actual schema sample required')
    validate_staging(staging)
    mapping_bytes = Path(pilot_mapping).stat().st_size
    require(mapping_bytes > 0, 'actual pilot mapping required')
    raw = actual_chunks * 4096 + raw_header_bytes
    ann = math.ceil(actual_chunks * (223537008 / 52664) * 1.1)
    mapping = math.ceil(actual_chunks * max(mapping_bytes / 52664 * 1.25,
                                            schema_sample_bytes_per_chunk * 1.25))
    minimums = {'vectors': raw, 'ann_construction': 2 * ann, 'mapping': mapping,
                'final_ann': ann, 'receipts': 1024 ** 2 + report_bytes}
    for name, minimum in minimums.items():
        require(staging[name] >= minimum, f'staging {name} below derived minimum {minimum}')
    temporary = sum(staging.values()) + max_audit_bytes
    peak = raw + ann + mapping + temporary
    return {'actual_chunks': actual_chunks, 'raw_bytes': raw, 'raw_header_bytes': raw_header_bytes,
            'ann_bytes': ann, 'mapping_bytes': mapping, 'pilot_mapping_bytes': mapping_bytes,
            'schema_sample_bytes_per_chunk': schema_sample_bytes_per_chunk,
            'staging': staging, 'staging_minimums': minimums, 'audit_cap_bytes': max_audit_bytes,
            'temporary_bytes': temporary, 'peak_bytes': peak,
            'accounting': 'Conservative sum of product, staging and audit cap, despite audit removal '
                          'before build; existing inventory references are not additional copies',
            'formulas': {'raw': 'N*4096+actual NPY header',
                         'ann': 'ceil(N*223537008/52664*1.1)',
                         'mapping': 'ceil(N*max(pilot bytes/52664, measured sample bytes/chunk)*1.25)'},
            'required_free_bytes': math.ceil(peak * 1.25)}


def disk_capacity(budget, root=ROOT):
    free = shutil.disk_usage(Path(root).resolve(strict=True)).free
    return {**budget, 'free_bytes': free, 'FREE_DISK_BYTES': free,
            'EST_VECTOR_BYTES': budget['raw_bytes'], 'EST_ANN_BYTES': budget['ann_bytes'],
            'EST_MAPPING_BYTES': budget['mapping_bytes'], 'EST_TEMP_BYTES': budget['temporary_bytes'],
            'EST_PEAK_BYTES': budget['peak_bytes'], 'REQUIRED_WITH_1_25_SAFETY': budget['required_free_bytes'],
            'drive': str(Path(root).resolve().anchor),
            'status': 'PASS' if free >= budget['required_free_bytes'] else 'BLOCKED_DISK', 'attempt': 0}


def verify_bindings(bindings, required, root=ROOT):
    require(bindings and set(bindings) == set(required), 'complete required inventory set required')
    result = {}
    for name, spec in bindings.items():
        chunks.valid_hash(spec['sha256'])
        positive_integer(spec['size'], 'inventory size')
        path = contained(name, root)
        require(path.is_file() and path.stat().st_size == spec['size'] and
                corpus.sha256_file(path) == spec['sha256'], f'inventory mismatch: {name}')
        result[name] = dict(spec)
    return result


def encoder_contract(model, contract):
    require(model['repository'] == 'BAAI/bge-m3' and model['revision'] == pilot.REVISION,
            'wrong encoder identity')
    for key in ('dimension', 'pooling', 'normalize', 'query_prefix', 'passage_prefix'):
        require(chunks.canonical(contract[key]) == chunks.canonical(DECLARATIONS['encoder'][key]),
                'encoder contract')
    require(type(contract['max_sequence_tokens']) is int and
            contract['max_sequence_tokens'] == 8192, 'pinned native token capacity')
    return {**contract, 'max_sequence_tokens': 512}


def inventory():
    for name, digest in PINNED_JOBS.items():
        exact.bound(contained(name), digest)
    frozen = exact.load(contained('configs/p4-rust-pilot-v1.json'))['frozen_sha256']
    pack_path = contained(pilot.PACK)
    exact.bound(pack_path, frozen[pilot.PACK])
    preliminary_pack(pack_path)
    pack, paths = pilot.pack_bindings(pilot.PACK)
    require(pack['artifacts']['ort_dll']['sha256'] == pilot.DLL_SHA and
            pack['artifacts']['ort_dll']['size'] == pilot.DLL_SIZE, 'unpinned ORT DLL')
    require(pack['artifacts']['mapping']['sha256'] == pilot.ANN_INPUT_HASHES['mapping'],
            'unapproved pilot mapping')
    require(set(pack['artifacts']) == {'model', 'external_data', 'tokenizer', 'ort_dll',
                                     'index', 'mapping', 'corpus', 'lexical'}, 'pack inventory set')
    for name in (*pilot.RECEIPTS.values(), *pilot.ann.INPUTS.values()):
        contained(name)
    pilot.approved_receipts()
    export = contained('build/p4/bge-onnx-v2/manifest.json')
    exact.bound(export, pilot.EXPORT_MANIFEST_SHA)
    preliminary_export(export)
    exported = pilot.export_artifacts(export.parent, pack_path.parent)
    require(all(exported[key] == pack['artifacts'][key] for key in exported),
            'pack/export closure mismatch')
    job = exact.load(contained('configs/p4-pilot-job-b.json'))
    preliminary_model(job)
    environment = {name: os.environ.get(name) for name in
                   ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')}
    try:
        model, contract, manifest, _ = exact.prepare(job)
    finally:
        for name, value in environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    contract = encoder_contract(model, contract)
    require(manifest['base_snapshot_sha256'] == SNAPSHOT['sha256'] and
            manifest['chunk_count'] == 52664, 'pilot chunk binding')
    directory = contained(model['asset_directory'])
    names = [record['path'] for record in model['obtained_receipt']['files']]
    require(len(names) == len(set(names)), 'duplicate model inventory')
    paths += [controlled_path(directory / name) for name in names]
    paths += [contained(model['contract']['path'])]
    paths += [contained(job[key]) for key in
              ('summary', 'chunks', 'chunks_manifest', 'corpus', 'gold', 'authorization')]
    paths += [contained(pilot.ann.INPUTS[key]) for key in pilot.ann.INPUTS]
    records = {}
    for path in set(paths):
        if path == pilot.EXTERNAL_ORT_DLL:
            record_path(pack['artifacts']['ort_dll'], pack_path.parent, kind='ort_dll')
        else:
            path = controlled_path(path)
        name = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
        records[name] = {'size': path.stat().st_size, 'sha256': exact.sha(path)}
        if name in frozen:
            require(records[name]['sha256'] == frozen[name], 'pinned inventory mismatch')
    return {'bindings': records, 'model': model, 'contract': contract,
            'manifest': manifest, 'job': job, 'pack': pack,
            'inventory_sha256': exact.canonical_hash(records)}


def source_inventory(fixed_head, root=ROOT):
    """Bind source to reviewed Git blobs with Git's path-aware CRLF filters."""
    require(re.fullmatch('[0-9a-f]{40}', fixed_head or '') is not None, 'fixed HEAD required')

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()

    require(git('rev-parse', 'HEAD') == fixed_head, 'fixed HEAD mismatch')
    require(git('branch', '--show-current') == 'dev', 'clean dev branch required')
    require(git('rev-parse', 'origin/dev') == fixed_head, 'origin/dev mismatch')
    remote = git('ls-remote', '--exit-code', 'origin', 'refs/heads/dev').split()
    require(len(remote) == 2 and remote == [fixed_head, 'refs/heads/dev'], 'remote dev mismatch')
    # Prefix/suffix policy is independent of Git and filesystem enumeration.
    families = (('rust/src/', '.rs'), ('rust/Cargo.', ''),
                ('configs/p4-', '.json'), ('tools/p4_', '.py'),
                ('docs/p4-', '.md'), ('tests/test_p4_', '.py'))
    metadata = {'rust/build.rs', 'Cargo.toml', 'Cargo.lock', 'build.rs',
                '.gitattributes', '.gitmodules', '.cargo/config', '.cargo/config.toml',
                'rust/.cargo/config', 'rust/.cargo/config.toml',
                'rust-toolchain', 'rust-toolchain.toml',
                'rust/rust-toolchain', 'rust/rust-toolchain.toml', 'pyproject.toml'}

    def related(name):
        return name in SOURCE_PATHS or name in metadata or any(
            name.startswith(prefix) and name.endswith(suffix) for prefix, suffix in families)

    def names(*args):
        data = subprocess.check_output(['git', *args], cwd=root)
        return [name.decode('utf-8', errors='strict') for name in data.split(b'\0') if name]

    fixed_names = set(names('ls-tree', '-r', '--name-only', '-z', fixed_head))
    index_names = set(names('ls-files', '-z'))
    paths = set(SOURCE_PATHS) | {name for name in fixed_names | index_names if related(name)}
    # No rename pairing: both the old and new names remain independently visible.
    for cached in ((), ('--cached',)):
        changed = names('diff', *cached, '--name-only', '-z', '--no-renames', fixed_head)
        require(not any(related(name) for name in changed),
                'related tracked source/index dirty')
    # Independently audit the entire policy, not only paths enumerated above.
    policy = (':(glob)rust/src/**', ':(glob)rust/Cargo.*',
              ':(glob)configs/p4-*.json', ':(glob)configs/p4-*/**/*.json',
              ':(glob)tools/p4_*.py', ':(glob)tools/p4_*/**/*.py',
              ':(glob)docs/p4-*.md', ':(glob)docs/p4-*/**/*.md',
              ':(glob)tests/test_p4_*.py', ':(glob)tests/test_p4_*/**/*.py')
    require(not names('diff', '--cached', '--name-only', '-z', '--no-renames',
                      fixed_head, '--', *policy,
                      *(f':(literal){name}' for name in sorted(metadata | set(SOURCE_PATHS)))),
            'related tracked source/index dirty')
    for directory in ('rust/src', 'configs', 'tools', 'docs', 'tests'):
        base = Path(root) / directory
        if base.exists():
            paths.update(path.relative_to(root).as_posix() for path in base.rglob('*')
                         if related(path.relative_to(root).as_posix()) and
                         (path.is_file() or path.is_symlink()))
    paths.update(path.relative_to(root).as_posix() for path in (Path(root) / 'rust').glob('Cargo.*'))
    paths.update(name for name in metadata if os.path.lexists(Path(root) / name))
    require(paths <= fixed_names,
            'related source absent from fixed tree: ' + ', '.join(sorted(paths - fixed_names)))
    records = {}
    for name in sorted(paths):
        contained(name, root)
        blob = git('rev-parse', f'{fixed_head}:{name}')
        shown = subprocess.check_output(['git', 'show', f'{fixed_head}:{name}'], cwd=root)
        shown_blob = subprocess.check_output(['git', 'hash-object', '--stdin'], cwd=root,
                                             input=shown).decode().strip()
        index = git('rev-parse', f':{name}')
        current = git('hash-object', f'--path={name}', name)
        require(blob == shown_blob == index == current, f'fixed source implementation mismatch: {name}')
        checkout = (Path(root) / name).read_bytes()
        records[name] = {'git_blob': blob, 'index_git_blob': index, 'size': len(shown),
                         'sha256': hashlib.sha256(shown).hexdigest(),
                         'checkout_size': len(checkout),
                         'checkout_sha256': hashlib.sha256(checkout).hexdigest(),
                         'checkout_git_filtered_blob': current}
    return {'fixed_code_sha': fixed_head, 'HEAD': fixed_head, 'origin_dev': fixed_head,
            'remote_dev': remote[0], 'source_inventory': records,
            'source_inventory_sha256': exact.canonical_hash(records),
            'dirt_policy': 'Unrelated dirt allowed; related tracked/untracked source must match fixed blobs'}


@contextmanager
def source_guard(fixed_head, root, report):
    before = source_inventory(fixed_head, root)
    report.update(before)
    try:
        yield
    finally:
        require(source_inventory(fixed_head, root) == before, 'fixed source changed during preflight')


def embedding_smoke(pilot_texts, pilot_vectors, full_only_chunks, encode):
    import numpy as np

    require(len(pilot_texts) == len(pilot_vectors) == 128, '128 pilot chunks required')
    require(len(full_only_chunks) == 512, '512 FULL-only chunks required')
    old, new = np.asarray(pilot_vectors), np.asarray(encode(pilot_texts))
    full = np.asarray(encode([chunk['text'] for chunk in full_only_chunks]))
    for values, rows in ((old, 128), (new, 128), (full, 512)):
        require(values.dtype == np.float32 and values.shape == (rows, 1024) and
                np.isfinite(values).all(), 'FP32 embedding shape/finite mismatch')
        require(float(np.max(np.abs(np.linalg.norm(values, axis=1) - 1))) <= 1e-5,
                'embedding normalization mismatch')
    error = float(np.max(np.abs(old - new)))
    cos = np.sum(old * new, axis=1) / (np.linalg.norm(old, axis=1) * np.linalg.norm(new, axis=1))
    require(error <= 1e-4 and float(np.min(cos)) >= .99999, 'pilot embedding parity failed')
    return {'pilot_rows': 128, 'full_only_rows': 512, 'maximum_absolute_error': error,
            'minimum_cosine': float(np.min(cos))}


def pilot_inputs(verified):
    import numpy as np

    job = verified['job']
    mapping = contained(pilot.ann.INPUTS['mapping'])
    with readonly(mapping) as conn:
        require(scalar(conn, 'SELECT count(*) FROM chunks') == 52664, 'pilot mapping count')
        with closing(conn.execute('SELECT metadata FROM chunks ORDER BY position')) as cur:
            ids = {json.loads(row[0])['document_id'] for row in cur}
        require(len(ids) == 50000, 'pilot document count')
        schema = set(json.loads(scalar(conn, 'SELECT metadata FROM chunks WHERE position=0')))
    texts, selected = [], []
    with closing(exact.rows(contained(job['chunks']))) as stream:
        for row in stream:
            texts.append(row['text'])
            selected.append(row)
            if len(texts) == 128:
                break
    with contained(pilot.ann.INPUTS['vectors']).open('rb') as stream:
        version = np.lib.format.read_magic(stream)
        require(version in ((1, 0), (2, 0)), 'unsupported approved vector container')
        reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                  else np.lib.format.read_array_header_2_0)
        shape, fortran, dtype = reader(stream)
        require(shape == (52664, 1024) and not fortran and dtype == np.dtype('<f4'),
                'approved vector header mismatch')
        header = stream.tell()
        vectors = np.frombuffer(stream.read(128 * 4096), dtype=dtype).reshape(128, 1024)
    verified['pilot_smoke_binding'] = {
        'vector_reference': verified['bindings'][pilot.ann.INPUTS['vectors']],
        'chunk_reference': verified['bindings'][job['chunks']],
        'selected_chunks_sha256': exact.canonical_hash(selected),
        'selected_chunk_ids': [row['chunk_id'] for row in selected],
        'order': 'approved first 128 positions ascending',
    }
    return ids, texts, vectors, header, schema


def preflight(config, *, authorized=False, fixed_head='NOT_FIXED_YET', staging=None, root=ROOT,
              max_audit_bytes=AUDIT_CAP_BYTES, audit_batch_size=AUDIT_BATCH_SIZE,
              max_document_text_bytes=DOCUMENT_CAP_BYTES):
    """Reviewed preflight only: no builder entry, product, attempt or authorization."""
    report = {'schema': 'p4-full-phase12-preflight-v1', 'status': 'NOT_RUN',
              'implementation_origin': IMPLEMENTATION, 'recovered_original_source': False,
              'reference_sources': REFERENCE_SOURCES,
              'fixed_head': fixed_head, 'fixed_code_sha': fixed_head,
              'component_policy': 'Raw ROOT, ancestors and input walks checked before resolve; '
                                  'no symlink/junction/reparse; only pinned ORT external exception',
              'snapshot_bound': False, 'inventory_verified': False, 'count_complete': False,
              'snapshot': dict(SNAPSHOT), 'declarative_contract': DECLARATIONS,
              'builder_authorized': False, 'full_output_created': False, 'full_mapping_created': False,
              'full_vectors_created': False, 'full_ann_created': False,
              'output_created': False, 'attempt': 0, 'attempts': 0}
    with product_guard(root), config_guard(config, root) as config_binding:
        report['canonical_config_binding'] = config_binding
        require(type(authorized) is bool, 'explicit authorization bool required')
        if not authorized or fixed_head == 'NOT_FIXED_YET':
            return report
        require(re.fullmatch('[0-9a-f]{40}', fixed_head or '') is not None, 'fixed HEAD required')
        require(Path(root).resolve() == ROOT, 'real preflight repository root required')
        validate_staging(staging)
        positive_integer(max_document_text_bytes, 'max_document_text_bytes')
        positive_integer(audit_batch_size, 'audit_batch_size')
        require(audit_batch_size <= 1024, 'audit batch exceeds 1024')
        with source_guard(fixed_head, root, report):
            def operation(function, *args, **kwargs):
                with product_guard(root):
                    return function(*args, **kwargs)

            try:
                audit_capacity(root, max_audit_bytes)
                report['initial_stage_gate'] = operation(initial_stage_gate, staging, root, max_audit_bytes)
                verified = operation(inventory)
                report.update(inventory_verified=True, inventory_sha256=verified['inventory_sha256'])
                ids, texts, vectors, header, schema = operation(pilot_inputs, verified)
                raw, _ = operation(exact.frozen_tokenizers, contained(verified['model']['asset_directory']))
                with validate_snapshot(config, root) as conn:
                    count = operation(census_and_chunk_count, conn, raw,
                                      verified['manifest']['tokenizer_inventory_sha256'], config,
                                      root=root, max_audit_bytes=max_audit_bytes,
                                      audit_batch_size=audit_batch_size,
                                      max_document_text_bytes=max_document_text_bytes)
                    sample, full_only = operation(deterministic_smoke, conn, raw,
                                                 verified['manifest']['tokenizer_inventory_sha256'], ids,
                                                 max_document_text_bytes=max_document_text_bytes)
            except AuditDiskBlocked as error:
                report.update(status=error.status, count_complete=False, audit=error.audit,
                              blocked_reason=str(error))
                return report
            except ValueError as error:
                if str(error).startswith('BLOCKED_RESOURCE:'):
                    report.update(status='BLOCKED_RESOURCE', count_complete=False,
                                  blocked_reason=str(error), census_reduced=False,
                                  documents_skipped=0, text_truncated=False)
                    return report
                raise
            report.update(snapshot_bound=True, phase9=count, count_complete=True,
                          pilot_document_count=len(ids),
                          pilot_document_ids_sha256=exact.canonical_hash(sorted(ids)),
                          smoke_document_count=512, smoke_chunks_sha256=exact.canonical_hash(sample),
                          smoke_token_ids_sha256=exact.canonical_hash([row['token_ids'] for row in sample]),
                          smoke_token_ids_count=sum(len(row['token_ids']) for row in sample),
                          smoke_boundary_ids_sha256=exact.canonical_hash([
                              {key: row[key] for key in ('chunk_id', 'document_id', 'chunk_index',
                                                        'canonical_token_start', 'canonical_token_end',
                                                        'position')} for row in sample]),
                          pilot_smoke_binding=verified['pilot_smoke_binding'],
                          full_only_document_ids=sorted({row['document_id'] for row in full_only}))
            require(schema and all(schema <= set(row) for row in sample), 'mapping schema projection')
            measurement = operation(measure_mapping_sample, sample, raw)
            report['mapping_sample_measurement'] = measurement
            report['referenced_asset_bytes'] = sum(r['size'] for r in verified['bindings'].values())
            report['additional_asset_copy_bytes'] = 0
            report['model_tokenizer_ONNX_inventory'] = verified['bindings']
            report['ANN_contract'] = DECLARATIONS['ann']
            report['DLL_binding'] = verified['pack']['artifacts']['ort_dll']
            budget = operation(disk_budget, count['actual_chunks'],
                               contained(pilot.ann.INPUTS['mapping']), measurement['bytes_per_chunk'],
                               raw_header_bytes=header, staging=staging, max_audit_bytes=max_audit_bytes,
                               report_bytes=len(chunks.canonical(report)))
            report['disk'] = operation(disk_capacity, budget, root)
            report['disk']['actual_audit_peak_bytes'] = count['audit']['audit_peak_bytes']
            model_directory = contained(verified['model']['asset_directory'])
            model_runtime_names = {name for name in verified['bindings'] if
                                   (Path(ROOT / name).resolve().is_relative_to(model_directory) or
                                    name.endswith(('.onnx', '.onnx_data', '.dll', '.data')))}
            report['disk']['EST_MODEL_RUNTIME_BYTES'] = sum(
                verified['bindings'][name]['size'] for name in model_runtime_names)
            report['disk']['model_runtime_accounting'] = 'Referenced existing bytes; additional copies zero'
            if report['disk']['status'] != 'PASS':
                report['status'] = 'BLOCKED_DISK'
                return report
            require(verified['contract']['max_sequence_tokens'] == 512 and
                    verified['contract']['query_prefix'] == verified['contract']['passage_prefix'] == '',
                    'actual encoder sequence/prefix contract')
            encoder = operation(exact.LocalEncoder, verified['model'], verified['contract'],
                                'cuda', verified['job']['threads'])
            require(encoder.contract == verified['contract'], 'actual LocalEncoder contract mismatch')
            batch_size = verified['job']['batch_size']
            positive_integer(batch_size, 'encoder batch size')

            def encode(values):
                import numpy as np

                batches = []
                for start in range(0, len(values), batch_size):
                    result, _ = operation(encoder.encode, values[start:start + batch_size])
                    batches.append(result)
                return np.concatenate(batches)

            report['embedding'] = operation(embedding_smoke, texts, vectors, full_only, encode)
            torch = encoder.torch
            require(torch.cuda.device_count() > 0 and encoder.info['actual_device'].startswith('cuda'),
                    'actual GPU required')
            report['encoder'] = {**encoder.info, 'class': 'tools.p4_exact_pilot.LocalEncoder',
                                 'max_sequence_tokens': 512, 'passage_prefix': '', 'query_prefix': '',
                                 'batch_size': batch_size, 'gpu_count': torch.cuda.device_count(),
                                 'gpu_name': torch.cuda.get_device_name(torch.cuda.current_device())}
            after = operation(inventory)
            require(after['bindings'] == verified['bindings'], 'inventory changed during preflight')
            report.update(status='READY_FOR_BUILD_REVIEW', STOP_STATE='WAITING_REVIEW', gates='PASS')
            report['phase18_receipt'] = {key: report[key] for key in
                                         ('HEAD', 'origin_dev', 'remote_dev', 'fixed_code_sha',
                                          'source_inventory_sha256')}
            # Recheck the actual final receipt, not just its earlier partial representation.
            final_budget = operation(disk_budget, count['actual_chunks'],
                                     contained(pilot.ann.INPUTS['mapping']), measurement['bytes_per_chunk'],
                                     raw_header_bytes=header, staging=staging,
                                     max_audit_bytes=max_audit_bytes,
                                     report_bytes=len(chunks.canonical(report)))
            require(report['disk']['free_bytes'] >= final_budget['required_free_bytes'],
                    'final receipt disk budget exceeded')
            return report
