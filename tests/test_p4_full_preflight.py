import copy
import hashlib
import json
import os
import sqlite3
import subprocess
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools import p4_full_preflight as full


def contract():
    return json.loads((full.ROOT / 'configs/p4-full-semantic-v1.json').read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def controlled_root(tmp_path, monkeypatch):
    original = full.count_documents

    def count(*args, **kwargs):
        kwargs.setdefault('root', tmp_path)
        return original(*args, **kwargs)

    monkeypatch.setattr(full, 'count_documents', count)
    return tmp_path


@pytest.fixture
def canonical_root(tmp_path):
    directory = tmp_path / 'configs'
    directory.mkdir()
    (directory / 'p4-full-semantic-v1.json').write_text(json.dumps(contract()), encoding='utf-8')
    return tmp_path


class CharacterTokenizer:
    truncation = None
    padding = None

    def encode(self, text, *, add_special_tokens=False):
        return SimpleNamespace(ids=[ord(char) for char in text] +
                               ([1, 2] if add_special_tokens else []),
                               offsets=[(i, i + 1) for i in range(len(text))])


def document(did, text='x' * 900):
    return {'document_id': did, 'fts_rowid': did, 'entry_id': did, 'entry_key': {
        'kind': 'subject', 'namespace': 'bangumi.subject', 'value': str(did)},
        'source_family': 'bangumi', 'source_id': 'source', 'evidence_id': 'evidence',
        'title': '', 'original': text}


def staging():
    return dict.fromkeys(full.STAGING_KEYS, 10 ** 12)


def test_contract_requires_exact_declarative_fields_and_strict_types(monkeypatch):
    value = contract()
    assert full.validate_contract(value)['corpus']['documents'] == 1295638
    assert 'max_attempts' not in value['declarative_contract']['build']
    for key, bad_value in [('output_policy', 'overwrite'), ('inputs', 'readwrite')]:
        altered = copy.deepcopy(value)
        altered['declarative_contract']['build'][key] = bad_value
        with pytest.raises(ValueError, match='contract mismatch'):
            full.validate_contract(altered)
    for section in value['declarative_contract']:
        altered = copy.deepcopy(value)
        del altered['declarative_contract'][section]
        with pytest.raises(ValueError, match='contract mismatch'):
            full.validate_contract(altered)
    altered = copy.deepcopy(value)
    altered['declarative_contract']['corpus']['documents'] = True
    with pytest.raises(ValueError, match='contract mismatch'):
        full.validate_contract(altered)
    altered = copy.deepcopy(value)
    altered['declarative_contract']['runtime']['sequential'] = 1
    with pytest.raises(ValueError, match='contract mismatch'):
        full.validate_contract(altered)
    # Contract validation is bound to the product declaration, not CONFIG's mutable path.
    monkeypatch.setattr(full, 'CONFIG', Path('/tmp/does-not-authorize-contract.json'))
    altered = copy.deepcopy(value)
    altered['declarative_contract']['encoder']['dimension'] = 1
    with pytest.raises(ValueError, match='contract mismatch'):
        full.validate_contract(altered)


def test_readonly_closes_even_on_error(tmp_path):
    path = tmp_path / 'fixture.sqlite'
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('CREATE TABLE fixture (id INTEGER)').close()
        conn.commit()
    with pytest.raises(RuntimeError), full.readonly(path) as conn:
        assert full.scalar(conn, 'SELECT count(*) FROM fixture') == 0
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('INSERT INTO fixture VALUES (1)')
        raise RuntimeError('fixture')
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute('SELECT 1')
    path.unlink()


def test_disk_uses_actual_count_and_schema_inflation(tmp_path, monkeypatch):
    mapping = tmp_path / 'pilot.sqlite'
    mapping.write_bytes(b'x' * 52664)
    budget = full.disk_budget(100, mapping, 10, raw_header_bytes=128, staging=staging())
    assert budget['raw_bytes'] == 409728
    assert budget['mapping_bytes'] == 1250
    assert budget['temporary_bytes'] == sum(staging().values()) + full.AUDIT_CAP_BYTES
    assert budget['peak_bytes'] == sum(budget[key] for key in
                                     ('raw_bytes', 'ann_bytes', 'mapping_bytes', 'temporary_bytes'))
    assert budget['required_free_bytes'] >= budget['peak_bytes'] * 1.25
    assert budget['staging_minimums']['vectors'] == budget['raw_bytes']
    assert budget['staging_minimums']['ann_construction'] == 2 * budget['ann_bytes']
    assert budget['staging_minimums']['mapping'] == budget['mapping_bytes']
    assert budget['staging_minimums']['final_ann'] == budget['ann_bytes']
    assert budget['staging_minimums']['receipts'] == 1024 ** 2
    for key, minimum in budget['staging_minimums'].items():
        with pytest.raises(ValueError, match=f'staging {key} below derived minimum'):
            full.disk_budget(100, mapping, 10, raw_header_bytes=128,
                             staging={**staging(), key: minimum - 1})
    with pytest.raises(ValueError, match='receipts below'):
        full.disk_budget(100, mapping, 10, raw_header_bytes=128,
                         staging={**staging(), 'receipts': 1024 ** 2}, report_bytes=1)
    monkeypatch.setattr(full.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    result = full.disk_capacity(budget, tmp_path)
    assert result['status'] == 'BLOCKED_DISK' and result['attempt'] == 0
    for invalid in (True, 0, -1):
        with pytest.raises(ValueError):
            full.disk_budget(invalid, mapping, 10, raw_header_bytes=128, staging=staging())
    for invalid in ({}, {**staging(), 'receipts': 0}, {**staging(), 'nonce': 1}):
        with pytest.raises(ValueError, match='staging'):
            full.disk_budget(100, mapping, 10, raw_header_bytes=128, staging=invalid)


def test_embedding_smoke_memory_parity():
    rows = np.zeros((128, 1024), dtype=np.float32)
    rows[:, 0] = 1

    def encode(texts):
        vectors = np.zeros((len(texts), 1024), dtype=np.float32)
        vectors[:, 0] = 1
        return vectors

    result = full.embedding_smoke(['pilot'] * 128, rows, [{'text': 'full'}] * 512, encode)
    assert result['maximum_absolute_error'] == 0
    rows[:, 0] = .5
    with pytest.raises(ValueError, match='normalization'):
        full.embedding_smoke(['pilot'] * 128, rows, [{'text': 'full'}] * 512, encode)
    rows[:, 0] = 1
    with pytest.raises(ValueError, match='shape'):
        full.embedding_smoke(['pilot'] * 128, rows.astype(np.float64),
                             [{'text': 'full'}] * 512, encode)


def test_mapping_inflation_is_measured_sqlite_pages():
    sample = full.project(document(1), CharacterTokenizer(), 'a' * 64)
    measured = full.measure_mapping_sample(sample, CharacterTokenizer())
    assert measured['actual_sqlite_bytes'] == measured['page_count'] * measured['page_size']
    assert measured['bytes_per_chunk'] >= measured['actual_sqlite_bytes'] / len(sample)
    assert measured['bytes_per_chunk'] >= measured['serialized_bytes'] / len(sample)
    assert 'not a formal' in measured['limitation']
    with pytest.raises(ValueError, match='nonempty'):
        full.measure_mapping_sample([], CharacterTokenizer())


def test_global_collision_across_batches_and_documents(monkeypatch, tmp_path):
    original = full.project

    def collision(*args, **kwargs):
        rows = original(*args, **kwargs)
        for row in rows:
            row['chunk_id'] = 'f' * 64
        return rows

    monkeypatch.setattr(full, 'project', collision)
    monkeypatch.setattr(full.chunks, 'digest', lambda _: 'f' * 64)
    with pytest.raises(ValueError, match='global duplicate'):
        full.count_documents(iter([document(1, 'x'), document(2, 'x')]),
                             CharacterTokenizer(), 'a' * 64, audit_batch_size=1)
    assert not list((tmp_path / 'build/p4-preflight-audit-temporary').iterdir())


def test_streaming_count_actual_chunk_statistics(tmp_path):
    result = full.count_documents(iter([document(1), document(2)]), CharacterTokenizer(), 'a' * 64)
    assert result['documents'] == 2 and result['actual_chunks'] == 6
    assert result['max_chunk_tokens'] <= 384
    assert result['oversized_paragraph_split_count'] == 4
    assert result['canonical_token_count'] == 1804
    assert result['chunk_token_count'] > result['canonical_token_count']
    assert result['duplicate_chunk_identity_count'] == 0
    assert len(result['streaming_sha256']) == 64
    assert result['count_complete'] is True
    audit = result['audit']
    assert audit['temporary_created'] and audit['temporary_removed']
    assert audit['temporary_parent_created']
    assert audit['cache_size_kib'] == -16384 and audit['batch_size'] == 1024
    assert 0 < audit['audit_peak_bytes'] < audit['audit_cap_bytes']
    assert not Path(audit['temporary_directory']).exists()
    assert Path(audit['temporary_parent']) == tmp_path / 'build/p4-preflight-audit-temporary'
    full.assert_no_product(tmp_path)


@pytest.mark.parametrize('failure', ['success', 'exception', 'diskfull'])
def test_audit_handles_closed_before_immediate_cleanup(tmp_path, monkeypatch, failure):
    real_cleanup = full.tempfile.TemporaryDirectory.cleanup
    metadata = {}
    held = []

    def cleanup(directory):
        if held:
            with pytest.raises(sqlite3.ProgrammingError):
                held[0].execute('SELECT 1')
        real_cleanup(directory)
        assert not Path(directory.name).exists()

    monkeypatch.setattr(full.tempfile.TemporaryDirectory, 'cleanup', cleanup)

    def run():
        with full.chunk_audit(tmp_path, full.AUDIT_CAP_BYTES, 1, metadata) as (conn, check):
            held.append(conn)
            with closing(conn.execute("INSERT INTO audit_ids VALUES ('a')")):
                pass
            check()
            if failure == 'exception':
                raise RuntimeError('synthetic failure')
            if failure == 'diskfull':
                error = sqlite3.OperationalError('database or disk is full')
                error.sqlite_errorcode = sqlite3.SQLITE_FULL
                raise error

    if failure == 'success':
        run()
    elif failure == 'exception':
        with pytest.raises(RuntimeError, match='synthetic'):
            run()
    else:
        with pytest.raises(full.AuditDiskBlocked) as blocked:
            run()
        assert blocked.value.status == 'BLOCKED_AUDIT_DISK'
        assert blocked.value.count_complete is False
    assert metadata['temporary_removed']


def test_audit_free_gate_before_stream_or_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(full.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))

    def forbidden():
        pytest.fail('stream scanned with insufficient audit reservation')
        yield

    with pytest.raises(full.AuditDiskBlocked):
        full.count_documents(forbidden(), CharacterTokenizer(), 'a' * 64)
    assert not (tmp_path / 'build').exists()


def test_audit_per_batch_disk_gate_and_hard_cap(tmp_path, monkeypatch):
    metadata = {}
    with pytest.raises(full.AuditDiskBlocked), full.chunk_audit(
            tmp_path, full.AUDIT_CAP_BYTES, 1, metadata) as (conn, check):
        assert full.scalar(conn, 'PRAGMA cache_size') == -16384
        assert full.scalar(conn, 'PRAGMA temp_store') == 1
        assert full.scalar(conn, 'PRAGMA journal_mode') == 'delete'
        assert full.scalar(conn, 'PRAGMA max_page_count') == full.AUDIT_CAP_BYTES // 4096
        assert 'WITHOUT ROWID' in full.scalar(conn, "SELECT sql FROM sqlite_master WHERE name='audit_ids'")
        monkeypatch.setattr(full.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
        check()
    assert metadata['temporary_removed']
    monkeypatch.undo()
    with pytest.raises(full.AuditDiskBlocked) as blocked:
        full.count_documents([document(i, 'x') for i in range(1, 1025)], CharacterTokenizer(),
                             'a' * 64, root=tmp_path, max_audit_bytes=8192, audit_batch_size=1)
    assert blocked.value.count_complete is False
    assert blocked.value.audit['temporary_removed']


@pytest.mark.parametrize('kwargs', [
    {'max_audit_bytes': 0}, {'max_audit_bytes': True}, {'audit_batch_size': 1025},
    {'audit_batch_size': 0}, {'max_document_text_bytes': 0},
])
def test_resource_parameters_fail_before_count(kwargs, tmp_path):
    with pytest.raises(ValueError):
        full.count_documents([], CharacterTokenizer(), 'a' * 64, **kwargs)
    assert not (tmp_path / 'build').exists()


def test_document_utf8_bound_rejects_before_encode(monkeypatch):
    tokenizer = CharacterTokenizer()
    monkeypatch.setattr(tokenizer, 'encode', lambda *a, **k: pytest.fail('oversized text encoded'))
    doc = document(1, '\u754c' * 5)
    assert full.document_bound(doc, 100) == len(full.chunks.document_text(doc).encode('utf-8'))
    with pytest.raises(ValueError, match='before tokenizer encode'):
        full.count_documents([doc], tokenizer, 'a' * 64, max_document_text_bytes=2)
    with pytest.raises(ValueError, match='before tokenizer encode'):
        full.project(doc, tokenizer, 'a' * 64, max_document_text_bytes=2)


@pytest.mark.parametrize('docs,match', [
    ([document(1), document(1)], 'duplicate'),
    ([document(2), document(1)], 'unordered'),
    ([document(True)], 'document ID'),
    ([], 'empty census'),
])
def test_count_rejects_duplicate_order_bool_empty(docs, match):
    with pytest.raises(ValueError, match=match):
        full.count_documents(iter(docs), CharacterTokenizer(), 'a' * 64)


def test_count_empty_and_stratum(monkeypatch):
    tokenizer = CharacterTokenizer()
    monkeypatch.setattr(tokenizer, 'encode', lambda *a, **k: SimpleNamespace(ids=[], offsets=[]))
    with pytest.raises(ValueError, match='empty'):
        full.count_documents([document(1, '')], tokenizer, 'a' * 64)
    doc = document(1)
    doc['source_family'] = 'local_tag'
    with pytest.raises(ValueError, match='stratum'):
        full.count_documents([doc], CharacterTokenizer(), 'a' * 64)


def test_tokenizer_injection_and_chunk_nonce_rejected(monkeypatch):
    tokenizer = CharacterTokenizer()
    tokenizer.truncation = {'max_length': 1}
    with pytest.raises(ValueError, match='truncation'):
        full.count_documents([document(1)], tokenizer, 'a' * 64)
    real = full.project

    def corrupt(*args, **kwargs):
        rows = real(*args, **kwargs)
        rows[0]['chunk_id'] = 'nonce'
        return rows

    monkeypatch.setattr(full, 'project', corrupt)
    with pytest.raises(ValueError, match='chunk ID'):
        full.count_documents([document(1)], CharacterTokenizer(), 'a' * 64)


def test_inventory_complete_hash_and_path_escape(tmp_path):
    path = tmp_path / 'asset'
    path.write_bytes(b'asset')
    spec = {'size': 5, 'sha256': full.chunks.digest(b'asset')}
    assert full.verify_bindings({'asset': spec}, {'asset'}, tmp_path) == {'asset': spec}
    for bindings in ({}, {'asset': spec, 'extra': spec}):
        with pytest.raises(ValueError, match='complete'):
            full.verify_bindings(bindings, {'asset'}, tmp_path)
    with pytest.raises(ValueError, match='escape'):
        full.verify_bindings({'../asset': spec}, {'../asset'}, tmp_path)
    with pytest.raises(ValueError, match='mismatch'):
        full.verify_bindings({'asset': {**spec, 'sha256': 'b' * 64}}, {'asset'}, tmp_path)


@pytest.mark.parametrize('change', ['atime', 'mtime', 'size', 'ino', 'dev', 'hash', 'sidecars', 'dual'])
def test_snapshot_observations_always_hash_and_preserve_failures(tmp_path, monkeypatch, change):
    path = tmp_path / 'snapshot'
    path.write_bytes(b'x')
    monkeypatch.setattr(full, 'validate_contract', lambda *args: None)
    monkeypatch.setattr(full, 'contained', lambda *args: path)
    monkeypatch.setattr(full, 'SNAPSHOT', {'path': 'snapshot', 'size': 1, 'sha256': 'a' * 64})
    stat = {'st_size': 1, 'st_mtime_ns': 2, 'st_dev': 3, 'st_ino': 4, 'st_atime_ns': 5}
    real_stat = Path.stat
    def fake_stat(self, *args, **kwargs):
        return SimpleNamespace(**stat) if self == path else real_stat(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', fake_stat)
    hashes = []
    monkeypatch.setattr(full.corpus, 'sha256_file', lambda *args: hashes.append(1) or (
        'b' * 64 if change == 'hash' and len(hashes) == 2 else 'a' * 64))
    sidecars = {}
    monkeypatch.setattr(full.corpus, 'sidecars', lambda *args: dict(sidecars))
    @contextmanager
    def reader(*args):
        yield None
    monkeypatch.setattr(full, 'readonly', reader)
    monkeypatch.setattr(full, 'scalar', lambda *args: 'false')
    report = {}
    def execute():
        with full.validate_snapshot({}, tmp_path, report):
            if change in ('atime', 'mtime', 'size', 'ino', 'dev'):
                stat[{'atime': 'st_atime_ns', 'mtime': 'st_mtime_ns', 'size': 'st_size',
                      'ino': 'st_ino', 'dev': 'st_dev'}[change]] += 1
            if change in ('sidecars', 'dual'):
                sidecars['-wal'] = {'size': 0}
            if change == 'dual':
                raise TypeError('original projection error')
    if change == 'atime':
        execute()
        assert all(report['snapshot_observations']['checks'].values())
    else:
        with pytest.raises(ValueError, match='snapshot changed'):
            execute()
        assert report['guard_error'] and report['status'] == 'FAIL'
    assert len(hashes) == 2
    if change == 'dual':
        assert 'original projection error' in report['original_error']


def test_sqlite_row_documents_and_lookup_actual_join_plan(monkeypatch):
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE build_meta(key TEXT,value TEXT);
            INSERT INTO build_meta VALUES('index_episodes','false');
            CREATE TABLE sources(source_id TEXT,metadata TEXT);
            INSERT INTO sources VALUES('source','{"source_family":"bangumi"}');
            CREATE TABLE entries(id INTEGER PRIMARY KEY,kind TEXT,namespace TEXT,value TEXT,conflicted INTEGER);
            INSERT INTO entries VALUES(1,'subject','bangumi.subject','1',0);
            CREATE TABLE documents(id INTEGER PRIMARY KEY,entry_id INTEGER,title TEXT,original TEXT,
                language TEXT,status TEXT,source_id TEXT,evidence_id TEXT,search_text TEXT);
            INSERT INTO documents VALUES(1,1,'','short','ja','source_backed','source','evidence','short');
            CREATE TABLE entry_evidence(entry_id INTEGER,status TEXT);
            INSERT INTO entry_evidence VALUES(1,'source_backed');
            CREATE VIRTUAL TABLE search_fts USING fts5(document_id UNINDEXED,entry_id UNINDEXED,text);
            INSERT INTO search_fts(rowid,document_id,entry_id,text) VALUES(73,1,1,'short');
        ''')
        monkeypatch.setattr(full.corpus, 'family', lambda *args: 'bangumi')
        rows = list(full.documents(conn))
        assert rows[0]['fts_rowid'] == 73 and rows[0]['entry_key']['namespace'] == 'bangumi.subject'
        ref = {'document_id': 1, 'fts_rowid': 73, 'document_text_sha256': hashlib.sha256(
            full.chunks.document_text(rows[0]).encode('utf-8')).hexdigest()}
        assert full.lookup_document(conn, ref)['document_id'] == 1
        sql = f'''SELECT {full.corpus.FIELDS} FROM search_fts f
            CROSS JOIN documents d ON d.id=f.document_id CROSS JOIN entries e ON e.id=d.entry_id
            WHERE f.rowid=? AND d.id=? AND f.entry_id=e.id AND f.text=d.search_text AND {full.corpus.TRUST}'''
        plan = conn.execute('EXPLAIN QUERY PLAN ' + sql, (73, 1)).fetchall()
        assert any('VIRTUAL TABLE INDEX' in row[3] and '=' in row[3] for row in plan)


@pytest.mark.parametrize('stream_fail,close_fail,cleanup_fail', [
    (False, False, False), (True, True, False), (True, False, True),
    (True, True, True), (False, True, True)])
def test_audit_independent_finalizers_preserve_original_error(tmp_path, monkeypatch,
                                                              stream_fail, close_fail, cleanup_fail):
    real_connect = sqlite3.connect
    real_directory = full.tempfile.TemporaryDirectory
    calls = []
    class Connection:
        def __init__(self, *args, **kwargs):
            self.connection = real_connect(*args, **kwargs)
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def close(self):
            calls.append('close')
            self.connection.close()
            if close_fail:
                raise OSError('injected close failure')
    class Directory:
        def __init__(self, *args, **kwargs):
            self.directory = real_directory(*args, **kwargs)
            self.name = self.directory.name
        def cleanup(self):
            calls.append('cleanup')
            self.directory.cleanup()
            if cleanup_fail:
                raise OSError('injected cleanup failure')
    monkeypatch.setattr(full.sqlite3, 'connect', Connection)
    monkeypatch.setattr(full.tempfile, 'TemporaryDirectory', Directory)
    audit = {}
    def execute():
        with full.chunk_audit(tmp_path, full.AUDIT_CAP_BYTES, 1024, audit):
            if stream_fail:
                raise TypeError('original stream failure')
    if stream_fail or close_fail or cleanup_fail:
        with pytest.raises((TypeError, ValueError)) as failure:
            execute()
        assert failure.value.audit is audit
    else:
        execute()
    assert calls == ['close', 'cleanup']
    assert audit['audit_started'] and audit['cleanup_attempted']
    assert audit['connection_closed'] is (not close_fail)
    assert audit['cleanup_status'] == ('NOT_VERIFIED' if close_fail or cleanup_fail else 'VERIFIED')
    assert ('close_error' in audit) is close_fail and ('cleanup_error' in audit) is cleanup_fail
    if stream_fail:
        assert 'original stream failure' in audit['original_error']


def test_failed_stream_audit_metadata_is_immediate(tmp_path):
    def stream():
        raise TypeError('stream projection failure')
        yield
    with pytest.raises(TypeError) as failure:
        full.count_documents(stream(), CharacterTokenizer(), 'a' * 64, root=tmp_path)
    audit = failure.value.audit
    assert audit['audit_started'] and audit['temporary_removed']
    assert audit['cleanup_status'] == 'VERIFIED'
    assert not Path(audit['temporary_directory']).exists()


def test_fts_reference_is_rowid_constrained_not_unindexed_scan():
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.execute('CREATE VIRTUAL TABLE search_fts USING fts5(document_id UNINDEXED,entry_id UNINDEXED,text)')
        conn.execute('INSERT INTO search_fts(rowid,document_id,entry_id,text) VALUES(73,5,9,?)', ('bound',))
        plan = conn.execute('EXPLAIN QUERY PLAN SELECT document_id,entry_id,text FROM search_fts WHERE rowid=?',
                            (73,)).fetchall()
        assert any('VIRTUAL TABLE INDEX' in row[3] and '= ' not in row[3] and '=' in row[3] for row in plan)
        assert conn.execute('SELECT document_id,entry_id,text FROM search_fts WHERE rowid=?', (73,)).fetchone() == (5, 9, 'bound')
    with pytest.raises(ValueError, match='FTS rowid required'):
        full.lookup_document(None, {'document_id': 5})


def test_count_retains_two_bounded_samples_in_single_stream(tmp_path):
    pilot_ids = set(range(-49999, 1))
    seen = []

    def stream():
        for did in range(1, 514):
            seen.append(did)
            yield document(did, 'short')

    result = full.count_documents(stream(), CharacterTokenizer(), 'a' * 64,
                                 root=tmp_path, pilot_document_ids=pilot_ids)
    assert result['documents'] == 513 and len(seen) == 513
    assert len(result['sample_documents']) == len(result['full_only_chunk_references']) == 512
    assert result['count_complete'] and result['audit']['temporary_removed']


def test_selected_projection_never_streams_or_recounts(tmp_path, monkeypatch):
    docs = {i: document(i, 'short') for i in range(1, 513)}
    result = full.count_documents(iter(docs.values()), CharacterTokenizer(), 'a' * 64,
        root=tmp_path, pilot_document_ids=set(range(-49999, 1)))
    monkeypatch.setattr(full, 'lookup_document', lambda conn, ref: copy.deepcopy(docs[ref['document_id']]))
    monkeypatch.setattr(full, 'documents', lambda *args: pytest.fail('second FULL stream'))
    monkeypatch.setattr(full, 'count_documents', lambda *args: pytest.fail('second count'))
    sample, only = full.selected_projection(None, CharacterTokenizer(), 'a' * 64, result,
                                           max_document_text_bytes=full.DOCUMENT_CAP_BYTES)
    assert len(sample) == len(only) == 512
    assert [row['position'] for row in sample] == list(range(512))
    result['full_only_chunk_references'][0]['chunk_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='changed'):
        full.selected_projection(None, CharacterTokenizer(), 'a' * 64, result,
                                 max_document_text_bytes=full.DOCUMENT_CAP_BYTES)




@pytest.fixture
def contained_link(tmp_path):
    target = tmp_path / 'real'
    target.mkdir()
    link = tmp_path / 'alias'
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                capture_output=True, check=False)
        if result.returncode:
            pytest.skip('Windows junction capability unavailable')
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f'directory symlink capability unavailable: {error}')
    yield target, link
    if os.name == 'nt':
        link.rmdir()
    else:
        link.unlink()


def test_contained_raw_parent_and_snapshot_reject_link_before_hash(tmp_path, contained_link, monkeypatch):
    target, link = contained_link
    (target / 'asset').write_bytes(b'asset')
    (tmp_path / 'asset').write_bytes(b'asset')
    monkeypatch.setattr(full, 'ROOT', tmp_path)
    assert full.contained('real/../asset') == tmp_path / 'asset'
    for name, root in [('alias/asset', tmp_path), ('alias/../asset', tmp_path),
                       ('asset', link), ('asset', link / 'child')]:
        with pytest.raises(ValueError, match='symlink/reparse/junction'):
            full.contained(name, root)

    (target / 'knowledge.sqlite').write_bytes(b'fixture')
    monkeypatch.setattr(full, 'SNAPSHOT', {**full.SNAPSHOT, 'path': 'alias/knowledge.sqlite',
                                           'size': 7, 'sha256': 'a' * 64})
    monkeypatch.setattr(full, 'validate_contract', lambda _: None)
    monkeypatch.setattr(full.corpus, 'sha256_file', lambda _: pytest.fail('hash before path check'))
    with (pytest.raises(ValueError, match='symlink/reparse/junction'),
          full.validate_snapshot({'snapshot': dict(full.SNAPSHOT)}, tmp_path)):
        pytest.fail('unsafe snapshot accepted')
