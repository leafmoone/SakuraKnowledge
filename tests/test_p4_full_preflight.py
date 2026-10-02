import copy
import hashlib
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools import p4_full_preflight as full


def contract():
    return json.loads(full.CONFIG.read_text(encoding='utf-8'))


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
    return {'document_id': did, 'entry_id': did, 'entry_key': {
        'kind': 'subject', 'namespace': 'bangumi.subject', 'value': str(did)},
        'source_family': 'bangumi', 'source_id': 'source', 'evidence_id': 'evidence',
        'title': '', 'original': text}


def staging():
    return dict.fromkeys(full.STAGING_KEYS, 10 ** 12)


def test_contract_required_and_exact():
    value = contract()
    assert full.validate_contract(value)['corpus']['documents'] == 1295638
    for section in value['declarative_contract']:
        altered = copy.deepcopy(value)
        del altered['declarative_contract'][section]
        with pytest.raises(ValueError, match='contract mismatch'):
            full.validate_contract(altered)
    altered = copy.deepcopy(value)
    altered['declarative_contract']['corpus']['index_episodes'] = 0
    with pytest.raises(ValueError):
        full.validate_contract(altered)


def test_contract_independent_of_mutable_config(tmp_path, monkeypatch):
    altered = contract()
    altered['declarative_contract']['encoder']['dimension'] = 1
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(altered))
    monkeypatch.setattr(full, 'CONFIG', path)
    with pytest.raises(ValueError, match='contract mismatch'):
        full.validate_contract(altered)


def test_canonical_config_missing_mismatch_mutation_and_exception(canonical_root):
    path = canonical_root / 'configs/p4-full-semantic-v1.json'
    before = path.read_bytes()
    with full.config_guard(contract(), canonical_root) as binding:
        assert binding['sha256'] == hashlib.sha256(before).hexdigest()
        assert binding['size'] == len(before)
    with pytest.raises(ValueError, match='changed'), full.config_guard(contract(), canonical_root):
        path.write_bytes(before + b' ')
        raise RuntimeError('original error')
    path.write_bytes(before)
    with pytest.raises(RuntimeError, match='original'), full.config_guard(contract(), canonical_root):
        raise RuntimeError('original')
    path.write_text('{}')
    with pytest.raises(ValueError, match='contract mismatch'):
        full.preflight(contract(), root=canonical_root)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        full.preflight(contract(), root=canonical_root)


def test_product_guard_checks_after_failure(tmp_path):
    with pytest.raises(ValueError, match='product root'), full.product_guard(tmp_path):
        (tmp_path / 'build/p4-full-semantic-v1').mkdir(parents=True)
    with pytest.raises(ValueError):
        full.assert_no_product(tmp_path)


def test_lock_and_attempt_guard(tmp_path):
    directory = tmp_path / 'build'
    directory.mkdir()
    (directory / 'p4-full-semantic-v1-attempt.json').touch()
    with pytest.raises(ValueError, match='lock/attempt'):
        full.assert_no_product(tmp_path)


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


def test_orchestration_not_run_does_not_load(monkeypatch, canonical_root):
    def forbidden(*args, **kwargs):
        pytest.fail('real inventory/count/model/git operation was invoked')

    for name in ('inventory', 'source_inventory', 'census_and_chunk_count'):
        monkeypatch.setattr(full, name, forbidden)
    monkeypatch.setattr(full.exact, 'LocalEncoder', forbidden)
    for kwargs in ({}, {'authorized': True}, {'fixed_head': full.REFERENCE_HEAD}):
        result = full.preflight(contract(), root=canonical_root, **kwargs)
        assert result['status'] == 'NOT_RUN'
        assert result['attempt'] == 0 and result['output_created'] is False
        assert result['inventory_verified'] is False and result['builder_authorized'] is False
        assert result['count_complete'] is False
    with pytest.raises(ValueError, match='bool'):
        full.preflight(contract(), authorized=1, root=canonical_root)
    with pytest.raises(ValueError, match='fixed HEAD'):
        full.preflight(contract(), authorized=True, fixed_head='nonce', root=canonical_root)


def test_staging_invalid_before_expensive_work(monkeypatch, canonical_root):
    monkeypatch.setattr(full, 'ROOT', canonical_root)

    def forbidden(*args, **kwargs):
        pytest.fail('expensive work or git ran with invalid staging')

    monkeypatch.setattr(full, 'inventory', forbidden)
    monkeypatch.setattr(full, 'source_inventory', forbidden)
    for invalid in ({}, None, {**staging(), 'vectors': 0}, {**staging(), 'mapping': True}):
        with pytest.raises(ValueError, match='staging'):
            full.preflight(contract(), authorized=True, fixed_head='a' * 40,
                           staging=invalid, root=canonical_root)


def test_source_failure_before_inventory(monkeypatch, canonical_root):
    monkeypatch.setattr(full, 'ROOT', canonical_root)

    def reject(*args):
        raise ValueError('fixed source implementation mismatch')

    monkeypatch.setattr(full, 'source_inventory', reject)
    monkeypatch.setattr(full, 'inventory', lambda: pytest.fail('unbound inventory invoked'))
    with pytest.raises(ValueError, match='fixed source'):
        full.preflight(contract(), authorized=True, fixed_head='a' * 40,
                       staging=staging(), root=canonical_root)


def test_positive_undersized_staging_rejected_before_inventory_and_count(monkeypatch, canonical_root):
    path = canonical_root / full.pilot.ann.INPUTS['mapping']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'fixture')
    monkeypatch.setattr(full, 'ROOT', canonical_root.resolve())
    monkeypatch.setitem(full.pilot.ANN_INPUT_HASHES, 'mapping', full.exact.sha(path))
    full.assert_no_product(canonical_root)
    monkeypatch.setattr(full, 'source_inventory', lambda *args: {'source_inventory_sha256': 'fixed'})
    monkeypatch.setattr(full.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10**15))
    monkeypatch.setattr(full, 'inventory', lambda: pytest.fail('inventory ran before initial stage gate'))
    monkeypatch.setattr(full, 'census_and_chunk_count', lambda *args: pytest.fail('FULL count ran'))
    with pytest.raises(ValueError, match='initial staging'):
        full.preflight(contract(), authorized=True, fixed_head='a' * 40,
                       staging=dict.fromkeys(full.STAGING_KEYS, 1), root=canonical_root)
    full.assert_no_product(canonical_root)
    assert not (canonical_root / 'build/p4-preflight-audit-temporary').exists()


def test_source_guard_checks_on_failure(monkeypatch, tmp_path):
    states = iter([{'source_inventory_sha256': 'a'}, {'source_inventory_sha256': 'b'}])
    monkeypatch.setattr(full, 'source_inventory', lambda *args: next(states))
    with pytest.raises(ValueError, match='source changed'), full.source_guard('a' * 40, tmp_path, {}):
        raise RuntimeError('operation failed')


def test_source_inventory_path_aware_hash_and_remote(monkeypatch, tmp_path):
    monkeypatch.setattr(full, 'SOURCE_PATHS', ('tools/p4_full_preflight.py',))
    path = tmp_path / 'tools/p4_full_preflight.py'
    path.parent.mkdir()
    path.write_bytes(b'fixture\r\n')
    calls = []
    modified = False
    cached_dirty = False
    index_dirty = False
    policy_dirty = False

    def git(command, **kwargs):
        calls.append(command)
        args = command[1:]
        head = 'a' * 40
        if args == ['rev-parse', 'HEAD'] or args == ['rev-parse', 'origin/dev']:
            return head + '\n'
        if args == ['branch', '--show-current']:
            return 'dev\n'
        if args[0] == 'ls-remote':
            return head + '\trefs/heads/dev\n'
        if args[0] in ('ls-tree', 'ls-files'):
            assert '-z' in args
            return b'tools/p4_full_preflight.py\x00'
        if args[0] == 'diff':
            assert '-z' in args and '--no-renames' in args
            if '--' in args and policy_dirty:
                assert ':(glob)rust/src/**' in args
                assert ':(glob)tools/p4_*.py' in args
                return b'tools/p4_index_only.py\x00'
            return b'tools/p4_full_preflight.py\x00' if '--cached' in args and cached_dirty else b''
        if args == ['rev-parse', ':tools/p4_full_preflight.py']:
            return ('changed' if index_dirty else 'blob') + '\n'
        if args[0] == 'show':
            return b'fixture\n'
        if args == ['hash-object', '--stdin']:
            return b'blob\n'
        if args[0] == 'hash-object':
            assert '--path=tools/p4_full_preflight.py' in args
            return ('changed' if modified else 'blob') + '\n'
        return 'blob\n'

    monkeypatch.setattr(full.subprocess, 'check_output', git)
    result = full.source_inventory('a' * 40, tmp_path)
    assert result['fixed_code_sha'] == result['remote_dev'] == 'a' * 40
    assert any('ls-remote' in call for call in calls)
    assert result['source_inventory']['tools/p4_full_preflight.py']['index_git_blob'] == 'blob'
    policy_dirty = True
    with pytest.raises(ValueError, match='tracked source/index dirty'):
        full.source_inventory('a' * 40, tmp_path)
    policy_dirty = False
    cached_dirty = True
    with pytest.raises(ValueError, match='tracked source/index dirty'):
        full.source_inventory('a' * 40, tmp_path)
    cached_dirty = False
    index_dirty = True
    with pytest.raises(ValueError, match='source implementation mismatch'):
        full.source_inventory('a' * 40, tmp_path)
    index_dirty = False
    modified = True
    with pytest.raises(ValueError, match='source implementation mismatch'):
        full.source_inventory('a' * 40, tmp_path)
    modified = False
    (path.parent / 'p4_untracked.py').write_text('unexpected')

    with pytest.raises(ValueError, match='related source absent from fixed tree'):
        full.source_inventory('a' * 40, tmp_path)


@pytest.mark.parametrize('deleted', ['tools/p4_deleted.py', 'rust/src/unicode16.rs',
                                     'rust/src/nested/dependency.rs',
                                     'tools/p4_line\nbreak.py'])
def test_source_inventory_rejects_deleted_wildcard_source(monkeypatch, tmp_path, deleted):
    monkeypatch.setattr(full, 'SOURCE_PATHS', ())

    def git(command, **kwargs):
        args = command[1:]
        head = 'a' * 40
        if args == ['branch', '--show-current']:
            return 'dev\n'
        if args[0] == 'ls-remote':
            return head + '\trefs/heads/dev\n'
        if args[0] in ('ls-tree', 'ls-files'):
            return (deleted + '\x00').encode()
        if args[0] == 'diff':
            assert '-z' in args and '--no-renames' in args
            return (deleted + '\x00').encode()
        return head + '\n'

    monkeypatch.setattr(full.subprocess, 'check_output', git)
    with pytest.raises(ValueError, match='tracked source/index dirty'):
        full.source_inventory('a' * 40, tmp_path)


@pytest.fixture
def source_repo(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    root.mkdir()

    def git(*args):
        return subprocess.check_output(
            ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
             '-c', 'core.autocrlf=false', *args], cwd=root)

    git('init', '--initial-branch=dev')
    git('init', '--bare', str(tmp_path / 'origin.git'))
    (root / 'tools').mkdir()
    (root / 'tools/p4_approved.py').write_bytes(b'fixture\n')
    (root / '.gitattributes').write_bytes(b'*.py text eol=crlf\n')
    git('add', '--', '.gitattributes', 'tools/p4_approved.py')
    git('commit', '-m', 'temporary source fixture')
    git('remote', 'add', 'origin', str(tmp_path / 'origin.git'))
    git('push', 'origin', 'dev')
    head = git('rev-parse', 'HEAD').decode().strip()
    monkeypatch.setattr(full, 'SOURCE_PATHS', ('tools/p4_approved.py',))
    return root, head, git


def test_source_inventory_real_git_crlf_and_readonly(source_repo):
    root, head, git = source_repo
    (root / 'tools/p4_approved.py').write_bytes(b'fixture\r\n')
    (root / 'unrelated.txt').write_text('allowed')
    git('add', '--', 'unrelated.txt')
    before = (root / '.git/index').read_bytes()
    result = full.source_inventory(head, root)
    record = result['source_inventory']['tools/p4_approved.py']
    assert result['HEAD'] == result['origin_dev'] == result['remote_dev'] == head
    assert record['git_blob'] == record['index_git_blob'] == record['checkout_git_filtered_blob']
    assert record['size'] == len(b'fixture\n')
    assert record['checkout_size'] == len(b'fixture\r\n')
    assert (root / '.git/index').read_bytes() == before


@pytest.mark.parametrize('name', [
    'tools/p4_extra.py', 'tools/p4_nested/extra.py', 'configs/p4-nested/extra.json',
    'docs/p4-nested/extra.md', 'tests/test_p4_nested/extra.py',
    'rust/src/extra.rs', 'rust/src/deep/extra.rs', 'rust/Cargo.extra',
    'rust/build.rs', 'Cargo.toml', 'build.rs', '.cargo/config.toml',
])
def test_source_inventory_real_git_index_added_missing_checkout(source_repo, name):
    root, head, git = source_repo
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'extra\n')
    git('add', '--', name)
    path.unlink()
    before = (root / '.git/index').read_bytes()
    with pytest.raises(ValueError, match='related tracked source/index dirty'):
        full.source_inventory(head, root)
    assert (root / '.git/index').read_bytes() == before


@pytest.mark.parametrize('operation', ['delete', 'rename-related', 'rename-unrelated'])
def test_source_inventory_real_git_staged_delete_and_rename(source_repo, operation):
    root, head, git = source_repo
    if operation == 'delete':
        git('rm', '--', 'tools/p4_approved.py')
    else:
        destination = 'tools/p4_renamed.py' if operation == 'rename-related' else 'unrelated.py'
        git('mv', '--', 'tools/p4_approved.py', destination)
    before = (root / '.git/index').read_bytes()
    with pytest.raises(ValueError, match='related tracked source/index dirty'):
        full.source_inventory(head, root)
    assert (root / '.git/index').read_bytes() == before


@pytest.mark.parametrize('name', ['tools/p4_nested/extra.py', 'rust/src/deep/extra.rs'])
def test_source_inventory_real_git_untracked_related(source_repo, name):
    root, head, _ = source_repo
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'extra\n')
    with pytest.raises(ValueError, match='related source absent from fixed tree'):
        full.source_inventory(head, root)


def test_deterministic_smoke_excludes_all_pilot(monkeypatch):
    docs = [document(i, 'short') for i in range(1, 1025)]

    def stream(_):
        yield from copy.deepcopy(docs)

    monkeypatch.setattr(full, 'documents', stream)
    pilot_ids = set(range(-49999, 1))
    sample, only = full.deterministic_smoke(None, CharacterTokenizer(), 'a' * 64, pilot_ids)
    assert len(sample) == len(only) == 512
    assert all(row['document_id'] not in pilot_ids for row in only)
    assert [row['position'] for row in sample] == list(range(512))
    assert all(len(row['token_ids']) == row['token_count'] for row in sample)
    with pytest.raises(ValueError, match='complete pilot'):
        full.deterministic_smoke(None, CharacterTokenizer(), 'a' * 64, {1})


def test_deterministic_smoke_rejects_token_id_mutation(monkeypatch):
    def stream(_):
        yield from [document(i, 'short') for i in range(1, 513)]

    monkeypatch.setattr(full, 'documents', stream)
    tokenizer = CharacterTokenizer()
    real = tokenizer.encode
    count = 0

    def encode(*args, **kwargs):
        nonlocal count
        result = real(*args, **kwargs)
        count += 1
        if count == 8:
            result.ids[0] += 1
        return result

    monkeypatch.setattr(tokenizer, 'encode', encode)
    with pytest.raises(ValueError, match='token IDs'):
        full.deterministic_smoke(None, tokenizer, 'a' * 64, set(range(-49999, 1)))


@pytest.fixture
def junction(tmp_path):
    links = []

    def create(name, target):
        link = tmp_path / name
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                    capture_output=True, check=False)
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            link.symlink_to(target, target_is_directory=True)
        links.append(link)
        return link

    yield create
    for link in reversed(links):
        if os.name == 'nt':
            link.rmdir()
        else:
            link.unlink()


def test_contained_raw_parent_walk_and_root_ancestors(tmp_path, junction, monkeypatch):
    target = tmp_path / 'real'
    target.mkdir()
    (target / 'asset').write_bytes(b'asset')
    (tmp_path / 'asset').write_bytes(b'asset')
    link = junction('alias', target)
    monkeypatch.setattr(full, 'ROOT', tmp_path)
    assert full.contained('real/../asset') == tmp_path / 'asset'
    for name, root in [('alias/asset', tmp_path), ('alias/../asset', tmp_path),
                       ('asset', link), ('asset', link / 'child')]:
        with pytest.raises(ValueError, match='symlink/reparse/junction'):
            full.contained(name, root)


def test_snapshot_junction_before_hash_and_config_before_load(tmp_path, junction, monkeypatch):
    config = contract()
    target = tmp_path / 'real'
    target.mkdir()
    (target / 'knowledge.sqlite').write_bytes(b'fixture')
    link = junction('alias', target)
    monkeypatch.setattr(full, 'ROOT', tmp_path)
    monkeypatch.setattr(full, 'SNAPSHOT', {**full.SNAPSHOT, 'path': 'alias/knowledge.sqlite'})
    monkeypatch.setattr(full, 'validate_contract', lambda _: None)
    monkeypatch.setattr(full.corpus, 'sha256_file', lambda _: pytest.fail('hash before path check'))
    monkeypatch.setattr(full.exact, 'LocalEncoder', lambda *a: pytest.fail('model loaded'))
    with pytest.raises(ValueError, match='symlink/reparse/junction'), full.validate_snapshot(config, tmp_path):
        pytest.fail('snapshot accepted')
    with pytest.raises(ValueError, match='symlink/reparse/junction'), full.config_guard(config, link):
        pytest.fail('config accepted')


@pytest.mark.parametrize('closure', ['pack', 'export', 'model'])
def test_inventory_preliminary_record_junction_before_helpers(tmp_path, junction, monkeypatch, closure):
    monkeypatch.setattr(full, 'ROOT', tmp_path)
    target = tmp_path / 'assets'
    target.mkdir()
    (target / 'tokenizer.json').write_bytes(b'fixture')
    junction('alias', target)
    record = {'path': 'alias/tokenizer.json', 'size': 7, 'sha256': 'a' * 64}
    monkeypatch.setattr(full.exact, 'LocalEncoder', lambda *a: pytest.fail('model loaded'))
    monkeypatch.setattr(full.pilot, 'pack_bindings', lambda *a: pytest.fail('pack helper loaded'))
    monkeypatch.setattr(full.pilot, 'export_artifacts', lambda *a: pytest.fail('export helper loaded'))
    monkeypatch.setattr(full.exact, 'prepare', lambda *a: pytest.fail('prepare loaded'))
    manifest = tmp_path / 'manifest.json'
    if closure == 'pack':
        manifest.write_text(json.dumps({'snapshot': record, 'export_manifest': record,
                                       'artifacts': {}, 'approved_receipts': {}}))
        operation = lambda: full.preliminary_pack(manifest)
    elif closure == 'export':
        manifest.write_text(json.dumps({'files': [record]}))
        operation = lambda: full.preliminary_export(manifest)
    else:
        (tmp_path / 'contract.json').write_text('{}')
        model = {'asset_directory': '.', 'contract': {'path': 'contract.json'},
                 'obtained_receipt': {'files': [record]}}
        manifest.write_text(json.dumps({'models': {'b': model}}))
        job = dict.fromkeys(('summary', 'chunks', 'chunks_manifest', 'corpus', 'gold',
                             'authorization', 'index', 'output'), 'manifest.json')
        job['model'] = 'b'
        operation = lambda: full.preliminary_model(job)
    with pytest.raises(ValueError, match='symlink/reparse/junction'):
        operation()


def test_external_exception_is_kind_path_size_hash_specific(tmp_path, monkeypatch):
    monkeypatch.setattr(full, 'ROOT', tmp_path)
    external = tmp_path.parent / (tmp_path.name + '-ort.dll')
    external.write_bytes(b'fixture')
    monkeypatch.setattr(full.pilot, 'EXTERNAL_ORT_DLL', external)
    monkeypatch.setattr(full.pilot, 'DLL_SIZE', 7)
    monkeypatch.setattr(full.pilot, 'DLL_SHA', full.exact.sha(external))
    record = {'path': str(external), 'size': 7, 'sha256': full.pilot.DLL_SHA}
    try:
        assert full.record_path(record, tmp_path, kind='ort_dll') == external
        with pytest.raises(ValueError, match='escape'):
            full.record_path(record, tmp_path, kind='model')
        for field, value in [('size', 8), ('sha256', 'b' * 64)]:
            with pytest.raises(ValueError, match='unapproved external'):
                full.record_path({**record, field: value}, tmp_path, kind='ort_dll')
    finally:
        external.unlink()
