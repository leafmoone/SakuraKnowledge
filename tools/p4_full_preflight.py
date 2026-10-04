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
import tempfile
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path

from tools import p4_chunks as chunks
from tools import p4_corpus as corpus
from tools import p4_exact_pilot as exact
from tools import p4_rust_pilot as pilot

ROOT = Path(os.path.abspath(__file__)).parents[1]
FULL_CONTRACT = ROOT / 'configs/p4-full-semantic-v1.json'
CURRENT_ASSETS = ROOT / 'configs/p4-current-assets.json'
CONFIG = FULL_CONTRACT
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
    'build': {'output_policy': 'create_new', 'inputs': 'readonly',
              'build_entry': False},
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


def validate_contract(value, *, expected_expansion_search=128):
    require(type(expected_expansion_search) is int and expected_expansion_search in (128, 2048),
            'explicit supported expected width required')
    expected = json.loads(json.dumps(DECLARATIONS))
    expected['ann']['expansion_search'] = expected_expansion_search
    require(value.get('schema') == 'p4-full-semantic-contract-v1' and
            value.get('object_type') == 'canonical_contract' and
            chunks.canonical(value.get('snapshot')) == chunks.canonical(SNAPSHOT) and
            chunks.canonical(value.get('declarative_contract')) == chunks.canonical(expected), 'FULL contract mismatch')
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
def validate_snapshot(config, root=ROOT, report=None):
    validate_contract(config)
    report = {} if report is None else report

    def observe(path, label, observations):
        observed = observations.setdefault(label, {})
        errors = []
        try:
            stat = path.stat()
            observed.update(identity={'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                                      'dev': stat.st_dev, 'ino': stat.st_ino}, atime_ns=stat.st_atime_ns)
        except (OSError, ValueError) as error:
            observed['stat_error'] = repr(error)
            errors.append(error)
            report.setdefault('observation_errors', []).append(repr(error))
        try:
            observed['sidecars'] = corpus.sidecars(path)
        except (OSError, ValueError) as error:
            observed['sidecars_error'] = repr(error)
            errors.append(error)
            report.setdefault('observation_errors', []).append(repr(error))
        try:
            observed['sha256'] = corpus.sha256_file(path)
        except (OSError, ValueError) as error:
            observed['hash_error'] = repr(error)
            errors.append(error)
            report.setdefault('observation_errors', []).append(repr(error))
        if errors:
            raise errors[0]
        return observed

    with product_guard(root):
        path = contained(SNAPSHOT['path'], root)
        observations = report.setdefault('snapshot_observations', {})
        try:
            observe(path, 'before', observations)
            require(observations['before']['identity']['size'] == SNAPSHOT['size'] and
                    observations['before']['sha256'] == SNAPSHOT['sha256'], 'snapshot binding mismatch')
            with readonly(path) as conn:
                require(scalar(conn, "SELECT value FROM build_meta WHERE key='index_episodes'")
                        == 'false', 'index_episodes policy must be false')
                yield conn
        except Exception as error:
            report.setdefault('original_error', getattr(error, 'audit', {}).get('original_error', repr(error)))
            if hasattr(error, 'audit'):
                report['audit'] = error.audit
            error.phase_receipt = report
            raise
        finally:
            try:
                observe(path, 'after', observations)
                before, after = observations['before'], observations['after']
                observations['checks'] = {'stable_identity': after['identity'] == before['identity'],
                    'sidecars': after['sidecars'] == before['sidecars'],
                    'whole_hash': after['sha256'] == before['sha256'] == SNAPSHOT['sha256']}
                require(all(observations['checks'].values()), 'snapshot changed')
            except Exception as error:
                report.update(status='FAIL', count_complete=False, guard_error=repr(error))
                error.phase_receipt = report
                raise


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


def current_asset_spec(root=ROOT):
    """Load the current, byte-verified model asset contract (never a historical job)."""
    path = contained('configs/p4-current-assets.json', root)
    value = exact.load(path)
    require(value.get('schema') == 'product_asset_spec_v1', 'current asset spec schema mismatch')
    model = value.get('model', {})
    require({'repository', 'revision', 'assetdirectory', 'contract',
             'obtained_inventory', 'inventory_sha256'} <= set(model),
            'current model asset contract incomplete')
    require(model['repository'] == 'BAAI/bge-m3' and re.fullmatch('[0-9a-f]{40}', model['revision']),
            'current model identity mismatch')
    require(isinstance(model['obtained_inventory'], list) and model['obtained_inventory'],
            'current obtained inventory required')
    return value


def preliminary_model(job):
    # Compatibility adapter for callers that still provide a job: assets are authoritative.
    spec = current_asset_spec()
    model = spec['model']
    directory = contained(model['assetdirectory'])
    check_tree(directory)
    required = {record['path']: record for record in model['obtained_inventory']}
    verify_bindings(required, set(required), directory)
    return model


def lookup_document(conn, reference):
    """Bounded ID lookup, using exactly the FULL census eligibility relation."""
    require(type(reference.get('fts_rowid')) is int and reference['fts_rowid'] > 0,
            'reviewed FTS rowid required; old receipts cannot resume')
    sql = f'''SELECT {corpus.FIELDS} FROM search_fts f
        CROSS JOIN documents d ON d.id=f.document_id
        CROSS JOIN entries e ON e.id=d.entry_id
        WHERE f.rowid=? AND d.id=? AND f.entry_id=e.id AND f.text=d.search_text AND {corpus.TRUST}'''
    with closing(conn.execute('SELECT source_id,metadata FROM sources ORDER BY source_id')) as cur:
        sources = {row[0]: json.loads(row[1]) for row in cur}
    with closing(conn.execute(sql, (reference['fts_rowid'], reference['document_id']))) as cur:
        rows = cur.fetchmany(2)
    require(len(rows) == 1, 'selected document missing/ambiguous')
    doc = corpus.project(rows[0], sources)
    require(hashlib.sha256(chunks.document_text(doc).encode('utf-8')).hexdigest() ==
            reference['document_text_sha256'], 'selected document text changed')
    return doc


def documents(conn):
    require(scalar(conn, "SELECT value FROM build_meta WHERE key='index_episodes'") == 'false',
            'index_episodes policy must be false')
    with closing(conn.execute('SELECT source_id,metadata FROM sources ORDER BY source_id')) as cur:
        sources = {row[0]: json.loads(row[1]) for row in cur}
    sql = f'''SELECT {corpus.FIELDS},f.rowid AS fts_rowid FROM search_fts f
        CROSS JOIN documents d ON d.id=f.document_id
        CROSS JOIN entries e ON e.id=d.entry_id
        WHERE f.entry_id=e.id AND f.text=d.search_text AND {corpus.TRUST} ORDER BY d.id'''
    previous = None
    with closing(conn.execute(sql)) as cursor:
        for row in cursor:
            values = dict(row)
            rowid = values.pop('fts_rowid')
            doc = {**corpus.project(values, sources), 'fts_rowid': rowid}
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
    metadata.update(temporary_created=True, temporary_directory=directory.name, audit_started=True,
                    count_complete=False, cleanup_status='NOT_VERIFIED')
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
        failure = ValueError('global duplicate chunk ID')
        failure.audit = metadata
        raise failure from error
    except sqlite3.Error as error:
        if getattr(error, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL or \
                'database or disk is full' in str(error).lower():
            raise AuditDiskBlocked('BLOCKED_AUDIT_DISK: SQLITE_FULL', metadata) from error
        error.audit = metadata
        raise
    except Exception as error:
        error.audit = metadata
        raise
    finally:
        import sys

        original = sys.exc_info()[1]
        if original is not None:
            original.audit = metadata
            metadata.setdefault('original_error', repr(original))
        errors = []
        metadata.update(connection_close_attempted=conn is not None, connection_closed=False,
                        cleanup_attempted=False, cleanup_status='NOT_VERIFIED')
        try:
            if conn is not None:
                conn.close()
                metadata['connection_closed'] = True
        except Exception as error:  # noqa: BLE001 -- every close failure must allow independent cleanup
            metadata['close_error'] = repr(error)
            errors.append(error)
        try:
            metadata['cleanup_attempted'] = True
            directory.cleanup()
            metadata['temporary_removed'] = not Path(directory.name).exists()
            require(metadata['temporary_removed'], 'audit temporary directory cleanup failed')
        except Exception as error:  # noqa: BLE001 -- retain arbitrary finalizer failures alongside original
            metadata['cleanup_error'] = repr(error)
            errors.append(error)
        if not errors and (conn is None or metadata['connection_closed']) and metadata['temporary_removed']:
            metadata['cleanup_status'] = 'VERIFIED'
        if errors:
            if original is not None:
                # Re-raise the pending original unchanged; finally diagnostics share its audit object.
                metadata['finalization_failed'] = True
            else:
                failure = ValueError('audit finalization failed: ' + '; '.join(repr(error) for error in errors))
                failure.audit = metadata
                raise failure from errors[0]


def count_documents(stream, tokenizer, inventory_sha, *, root=ROOT,
                    max_audit_bytes=AUDIT_CAP_BYTES, audit_batch_size=AUDIT_BATCH_SIZE,
                    max_document_text_bytes=DOCUMENT_CAP_BYTES, pilot_document_ids=None):
    """Exact disk-backed count; retain bounded references during this single stream."""
    positive_integer(max_document_text_bytes, 'max_document_text_bytes')
    counts, totals = Counter(), Counter()
    digest = hashlib.sha256()
    previous, position, maximum, document_peak = None, 0, 0, 0
    audit, batch = {}, []
    sample_heap, sample_refs, full_only_refs = [], {}, []
    pilot_ids = None if pilot_document_ids is None else set(pilot_document_ids)
    require(pilot_ids is None or len(pilot_ids) == 50000, 'complete pilot document exclusion required')
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
            if pilot_ids is not None:
                score = corpus.rank(doc, 'p4-full-preflight-512-v1')
                corpus.retain(sample_heap, 512, score, did)
                retained = {-item[1] for item in sample_heap}
                sample_refs = {key: value for key, value in sample_refs.items() if key in retained}
                if did in retained:
                    sample_refs[did] = {'document_id': did, 'fts_rowid': doc['fts_rowid'], 'rank': str(score),
                        'document_text_sha256': hashlib.sha256(chunks.document_text(doc).encode('utf-8')).hexdigest()}
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
                if pilot_ids is not None and did not in pilot_ids and len(full_only_refs) < 512:
                    full_only_refs.append({'document_id': did, 'fts_rowid': doc['fts_rowid'], 'chunk_index': index,
                        'chunk_id': row['chunk_id'], 'chunk_sha256': exact.canonical_hash(row),
                        'token_ids_sha256': exact.canonical_hash(list(
                            tokenizer.encode(row['text'], add_special_tokens=False).ids)),
                        'document_text_sha256': hashlib.sha256(chunks.document_text(doc).encode('utf-8')).hexdigest()})
                digest.update(chunks.canonical({**row, 'position': position}) + b'\n')
                position += 1
        flush()
    audit['count_complete'] = True
    require(position > 0, 'empty census')
    require(pilot_ids is None or (len(sample_refs) == 512 and len(full_only_refs) == 512),
            'BLOCKED_RESOURCE: bounded smoke references insufficient; no fallback scan')
    return {'sample_documents': sorted(sample_refs.values(), key=lambda ref: ref['document_id']),
            'full_only_chunk_references': full_only_refs,
            'pilot_document_ids_sha256': None if pilot_ids is None else exact.canonical_hash(sorted(pilot_ids)),
            'documents': sum(counts.values()), 'strata': dict(counts),
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
                         ((i, row['chunk_id'], row['document_id'], row['chunk_index'],
                           chunks.canonical(row), chunks.canonical(list(
                               tokenizer.encode(row['text'], add_special_tokens=False).ids)), row['text'])
                          for i, row in enumerate(sample))).close()
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
    if staging is not None:
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
    if staging is None:
        staging = minimums
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
    if staging is None:
        staging = minimums
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
    """Current model and runtime resources; no historical execution authority."""
    spec = current_asset_spec()
    model = dict(spec['model'])
    model['asset_directory'] = model['assetdirectory']
    model['obtained_receipt'] = {'files': model['obtained_inventory']}
    contract_path = contained(model['contract']['path'])
    exact.bound(contract_path, model['contract']['file_sha256'])
    native = exact.load(contract_path)
    require(native == model['contract']['reviewed'], 'current model contract mismatch')
    contract = encoder_contract(model, native)
    directory = contained(model['asset_directory'])
    files = model['obtained_inventory']
    require(len({r['path'] for r in files}) == len(files), 'duplicate model assets')
    records = {}
    def add(path, ref):
        path = controlled_path(path) if path.is_relative_to(ROOT) else record_path(ref, ROOT, kind='ort_dll')
        name = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
        if name in records:
            require(records[name] == {'size': ref['size'], 'sha256': ref['sha256']}, 'conflicting asset bindings')
            return
        require(path.stat().st_size == ref['size'], 'current asset size mismatch')
        exact.bound(path, ref['sha256'])
        records[name] = {'size': ref['size'], 'sha256': ref['sha256']}
    for ref in files:
        add(directory / ref['path'], ref)
    records[model['contract']['path']] = {'size': contract_path.stat().st_size, 'sha256': model['contract']['file_sha256']}
    export = contained(spec['export_manifest']['path'])
    add(export, spec['export_manifest'])
    artifacts = pilot.export_artifacts(export.parent, ROOT, verified=add)
    tokenizer = directory / 'tokenizer.json'
    artifacts['tokenizer'] = {'path': tokenizer.relative_to(ROOT).as_posix(), **records[tokenizer.relative_to(ROOT).as_posix()]}
    artifacts['ort_dll'] = spec['ort_dll']
    for kind, refs in artifacts.items():
        for ref in refs if kind == 'external_data' else [refs]:
            path = Path(ref['path']) if Path(ref['path']).is_absolute() else ROOT / ref['path']
            if str(ref['path']) not in records:
                add(path, ref)
    tokenizer_inventory = {'repository': model['repository'], 'revision': model['revision'],
        'contract': native, 'tokenizer_json_sha256': records[tokenizer.relative_to(ROOT).as_posix()]['sha256'],
        'model_config_sha256': exact.sha(contained('configs/p4-chunk-model-b.json')), 'library': 'tokenizers',
        'library_version': '0.22.2', 'offset_unit': 'unicode_characters',
        'add_special_tokens': False, 'truncation': False, 'padding': False}
    return {'bindings': records, 'model': model, 'contract': contract,
        'manifest': {'tokenizer_inventory_sha256': exact.canonical_hash(tokenizer_inventory)},
        'job': {'threads': 8, 'batch_size': 8}, 'pack': {'artifacts': artifacts},
        'asset_root': ROOT, 'inventory_sha256': exact.canonical_hash(records)}


def validate_count_receipt(receipt, config):
    """Validate complete count semantics after external receipt/capture authentication."""
    validate_contract(config)
    require(receipt.get('schema') == 'p4-full-reviewed-count-v2' and
            receipt.get('status') == 'COUNT_COMPLETE' and receipt.get('count_complete') is True,
            'complete reviewed count required; partial cannot resume')
    require(receipt.get('canonical_config_sha256') == exact.sha(CONFIG) and receipt.get('snapshot') == config['snapshot'], 'count input bindings mismatch')
    count = receipt.get('count', {})
    require(count.get('count_complete') is True and count.get('FULL_DOCUMENT_COUNT') == 1295638 and
            count.get('documents') == 1295638 and count.get('strata') == STRATA and
            type(count.get('actual_chunks')) is int and count['actual_chunks'] >= 1295638 and
            count.get('FULL_EXACT_CHUNK_COUNT') == count['actual_chunks'], 'count census/count mismatch')
    for key in ('EMPTY_DOCUMENTS', 'DUPLICATE_DOCUMENTS', 'DUPLICATE_CHUNK_IDS'):
        require(type(count.get(key)) is int and count[key] == 0, 'count empty/duplicate failure')
    require(type(count.get('MAX_CHUNK_TOKENS')) is int and 0 < count['MAX_CHUNK_TOKENS'] <= 384 and
            count.get('max_chunk_tokens') == count['MAX_CHUNK_TOKENS'] and
            count.get('attempts') == 0 and receipt.get('attempts') == 0 and
            count.get('audit', {}).get('temporary_removed') is True, 'count policy/cleanup failure')
    require(len(count.get('sample_documents', [])) == 512 and
            len(count.get('full_only_chunk_references', [])) == 512,
            'bounded sample references required')
    chunks.valid_hash(count.get('streaming_sha256'))
    chunks.valid_hash(count.get('pilot_document_ids_sha256'))
    for key in ('empty_token_document_count', 'duplicate_document_count', 'duplicate_chunk_identity_count'):
        require(type(count.get(key)) is int and count[key] == 0, 'underlying count failure')
    for key in ('chunk_token_count', 'canonical_token_count'):
        require(type(count.get(key)) is int and count[key] >= count['documents'], 'invalid token statistics')
    positive_integer(count.get('max_document_text_bytes'), 'document cap')
    audit = count['audit']
    positive_integer(audit.get('batch_size'), 'audit batch')
    require(audit['batch_size'] <= 1024, 'invalid audit batch')
    positive_integer(audit.get('audit_cap_bytes'), 'audit cap')
    require(type(audit.get('audit_peak_bytes')) is int and
            0 <= audit['audit_peak_bytes'] <= audit['audit_cap_bytes'], 'invalid audit peak')
    refs = count['sample_documents']
    dids = [ref.get('document_id') for ref in refs]
    require(all(type(did) is int and did > 0 for did in dids) and
            dids == sorted(set(dids)), 'unique ordered sample document IDs required')
    for ref in refs + count['full_only_chunk_references']:
        require(type(ref.get('fts_rowid')) is int and ref['fts_rowid'] > 0, 'reviewed FTS rowid required')
    for ref in refs:
        require(isinstance(ref.get('rank'), str) and ref['rank'].isdigit(), 'invalid sample rank')
        chunks.valid_hash(ref.get('document_text_sha256'))
    only = count['full_only_chunk_references']
    pairs = [(ref.get('document_id'), ref.get('chunk_index')) for ref in only]
    require(all(type(did) is int and did > 0 and type(index) is int and index >= 0
                for did, index in pairs) and pairs == sorted(set(pairs)), 'unique ordered chunk references required')
    require(len({ref.get('chunk_id') for ref in only}) == 512, 'unique chunk identities required')
    for ref in only:
        for key in ('chunk_id', 'chunk_sha256', 'token_ids_sha256', 'document_text_sha256'):
            chunks.valid_hash(ref.get(key))
    return count






def count_preflight(config, *, root=ROOT,
                    max_audit_bytes=AUDIT_CAP_BYTES, audit_batch_size=AUDIT_BATCH_SIZE,
                    max_document_text_bytes=DOCUMENT_CAP_BYTES):
    """Explicit read-only count using current product assets, without history gates."""
    validate_contract(config)
    verified = inventory()
    raw, _ = exact.frozen_tokenizers(contained(verified['model']['asset_directory']))
    with validate_snapshot(config, root) as conn:
        return census_and_chunk_count(conn, raw,
            verified['manifest']['tokenizer_inventory_sha256'], config, root=root,
            max_audit_bytes=max_audit_bytes, audit_batch_size=audit_batch_size,
            max_document_text_bytes=max_document_text_bytes)


def selected_projection(conn, raw, inventory_sha, count, *, max_document_text_bytes):
    """Only bounded ID lookups; no documents() stream or recount."""
    projected, full_only = [], []
    selected_bytes = 0
    for ref in count['sample_documents']:
        doc = lookup_document(conn, ref)
        require(str(corpus.rank(doc, 'p4-full-preflight-512-v1')) == ref['rank'], 'sample rank changed')
        first = project(doc, raw, inventory_sha, max_document_text_bytes=max_document_text_bytes)
        second = project(doc, raw, inventory_sha, max_document_text_bytes=max_document_text_bytes)
        require(first == second and first, 'selected chunker nondeterministic')
        for row in first:
            tokens = list(raw.encode(row['text'], add_special_tokens=False).ids)
            require(tokens == list(raw.encode(row['text'], add_special_tokens=False).ids) and
                    len(tokens) == row['token_count'], 'selected token IDs nondeterministic')
            projected.append({**row, 'token_ids': tokens, 'position': len(projected)})
            selected_bytes += len(chunks.canonical(projected[-1]))
            require(selected_bytes <= 64 * 1024**2,
                    'BLOCKED_RESOURCE: selected projection exceeds bounded receipt allocation')
    for ref in count['full_only_chunk_references']:
        doc = lookup_document(conn, ref)
        rows = project(doc, raw, inventory_sha, max_document_text_bytes=max_document_text_bytes)
        require(0 <= ref['chunk_index'] < len(rows), 'selected chunk missing')
        row = rows[ref['chunk_index']]
        require(row['chunk_id'] == ref['chunk_id'] and exact.canonical_hash(row) == ref['chunk_sha256'] and
                exact.canonical_hash(list(raw.encode(row['text'], add_special_tokens=False).ids)) ==
                ref['token_ids_sha256'], 'selected FULL-only chunk changed')
        selected_bytes += len(chunks.canonical(row))
        require(selected_bytes <= 64 * 1024**2, 'BLOCKED_RESOURCE: selected samples exceed receipt cap')
        full_only.append(row)
    require(len(full_only) == 512, '512 FULL-only chunks required')
    return projected, full_only








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
    observations = {}
    for label, values in (('approved_pilot', old), ('actual_pilot', new), ('actual_full_only', full)):
        observations[label] = {'shape': list(values.shape), 'dtype': str(values.dtype),
            'finite_all': bool(np.isfinite(values).all()),
            'maximum_l2_norm_error': float(np.max(np.abs(np.linalg.norm(values, axis=1) - 1))),
            'array_sha256': hashlib.sha256(values.tobytes(order='C')).hexdigest()}
    return {'pilot_rows': 128, 'full_only_rows': 512, 'maximum_absolute_error': error,
            'minimum_cosine': float(np.min(cos)), 'observations': observations}




def preflight(config, *, root=ROOT, report=None):
    """Read-only current asset validation for the ordinary builder."""
    validate_contract(config)
    result = {} if report is None else report
    result['inventory'] = inventory()
    result['status'] = 'READY_FOR_NORMAL_BUILD'
    return result
