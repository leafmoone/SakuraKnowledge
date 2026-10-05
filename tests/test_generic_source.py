import json
import sqlite3
from pathlib import Path

import pytest

from tools.normalized_source import build_normalized, inspect, normalize, safe_id, validate

RAW = Path(__file__).resolve().parents[1] / 'examples/source_pack/raw_demo.json'
ADAPTER = 'examples.source_pack.demo_adapter:DemoAdapter'


@pytest.mark.parametrize('value', ['future', 'demo-wiki', 'a.b_c-1', 'X' * 128])
def test_unknown_safe_ids(value):
    assert safe_id(value) == value


@pytest.mark.parametrize('value', ['', '.', '..', '../x', 'a/b', 'a\\b', '中文', 'a b', 'X' * 129])
def test_unsafe_ids(value):
    with pytest.raises(ValueError):
        safe_id(value)


def fixture_pack(tmp_path):
    bundle = tmp_path / 'normalized'
    normalize(RAW, ADAPTER, bundle, 'future-example')
    output = tmp_path / 'pack'
    build_normalized(bundle, output)
    return bundle, output


def test_full_build_without_mother(tmp_path, monkeypatch):
    real = sqlite3.connect
    opened = []
    def guarded(path, *args, **kwargs):
        opened.append(str(path))
        assert str(tmp_path).replace('\\', '/') in str(path).replace('\\', '/').replace('file:///', '')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', guarded)
    _, output = fixture_pack(tmp_path)
    result = validate(output)
    assert result['validation'] == 'PASS'
    assert result['counts']['entries'] == 4 and result['counts']['search_fts'] == 4
    assert result['pack_id'] != result['source_ids'][0]
    assert opened


def test_create_new_only(tmp_path):
    bundle, output = fixture_pack(tmp_path)
    with pytest.raises(FileExistsError):
        build_normalized(bundle, output)


@pytest.mark.parametrize('field,value', [('count', 999), ('sha256', 'a' * 64), ('path', '../raw')])
def test_bundle_binding_rejects(tmp_path, field, value):
    bundle = tmp_path / 'normalized'
    normalize(RAW, ADAPTER, bundle, 'future-example')
    m = json.loads((bundle / 'manifest.json').read_bytes())
    m['records'][field] = value
    (bundle / 'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):
        build_normalized(bundle, tmp_path / 'output')


@pytest.mark.parametrize('field,value', [('requires_model', 'other-model'), ('capabilities', ['structured']), ('namespaces', ['fake']), ('source_ids', ['fake']), ('trusted_fts_documents', 0)])
def test_actual_pack_validation_rejects(tmp_path, field, value):
    _, output = fixture_pack(tmp_path)
    m = json.loads((output / 'manifest.json').read_bytes())
    m[field] = value
    (output / 'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):
        validate(output)


def test_inspection_candidate_stays_candidate(tmp_path):
    _, output = fixture_pack(tmp_path)
    assert inspect(output)['requires_model'] is None
    c = sqlite3.connect(output / 'knowledge.sqlite')
    try:
        assert c.execute("SELECT count(*) FROM links WHERE verification_status='candidate'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM documents WHERE status='generated_from_evidence'").fetchone()[0] == 1
    finally:
        c.close()


def _replace_bundle_records(bundle, records, sources=None):
    from tools.source_pack import binding

    path = bundle / 'records.jsonl'
    path.write_text(''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    manifest['records'] = {**binding(path), 'count': len(records)}
    if sources is not None:
        manifest['sources'] = sources
    (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


def _rebind_artifact(pack, role):
    from tools.source_pack import binding

    manifest = json.loads((pack / 'manifest.json').read_bytes())
    item = manifest['artifacts'][role]
    manifest['artifacts'][role] = {**item, **binding(pack / item['path'])}
    (pack / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


def _multisource_bundle(tmp_path):
    bundle, _ = fixture_pack(tmp_path)
    records = []
    sources = []
    for owner in ('owner-a', 'owner-b'):
        sources.append({'source_id': owner, 'provider': 'demo', 'repo': 'local://' + owner,
                        'dataset_role': 'fixture', 'asset_name': 'records.jsonl',
                        'importer_version': 'test-1'})
        records.append({'source_id': owner,
                        'key': {'kind': 'subject', 'namespace': 'demo.subject', 'value': owner},
                        'status': 'source_backed', 'evidence_id': owner + ':identity',
                        'documents': [{'title': owner, 'original': 'Tiny source owned document.',
                                       'status': 'source_backed', 'evidence_id': owner + ':text'}]})
    records.append({'record_type': 'link', 'source_id': 'owner-a',
                    'src': records[0]['key'], 'dst': records[1]['key'],
                    'relation': 'related_to', 'verification_status': 'candidate',
                    'method': 'fixture_crosspack', 'evidence_id': 'owner-a:relation'})
    _replace_bundle_records(bundle, records, sources)
    return bundle, records


def test_real_multisource_build_preserves_record_ownership(tmp_path):
    from contextlib import closing

    bundle, _ = _multisource_bundle(tmp_path)
    output = tmp_path / 'multisource'
    build_normalized(bundle, output)
    result = validate(output)
    assert result['validation'] == 'PASS'
    assert set(result['source_ids']) == {'owner-a', 'owner-b'}
    assert result['counts']['entries'] == result['counts']['documents'] == 2
    assert result['counts']['search_fts'] == 2
    with closing(sqlite3.connect(output / 'knowledge.sqlite')) as conn:
        assert conn.execute('SELECT source_id FROM sources ORDER BY source_id').fetchall() == [
            ('owner-a',), ('owner-b',)]
        assert conn.execute('SELECT e.value,d.source_id,d.evidence_id,v.source_id,v.evidence_id '
                            'FROM documents d JOIN entries e ON e.id=d.entry_id '
                            'JOIN entry_evidence v ON v.entry_id=e.id ORDER BY e.value').fetchall() == [
            ('owner-a', 'owner-a', 'owner-a:text', 'owner-a', 'owner-a:identity'),
            ('owner-b', 'owner-b', 'owner-b:text', 'owner-b', 'owner-b:identity')]


@pytest.mark.parametrize('owner', ['foreign-owner', None])
def test_multisource_foreign_or_missing_owner_rejected(tmp_path, owner):
    bundle, records = _multisource_bundle(tmp_path)
    if owner is None:
        records[0].pop('source_id')
    else:
        records[0]['source_id'] = owner
    _replace_bundle_records(bundle, records)
    with pytest.raises(ValueError, match='normalized record source ownership missing'):
        build_normalized(bundle, tmp_path / 'rejected')
    assert not (tmp_path / 'rejected').exists()


@pytest.mark.parametrize('corruption', ['orphan-fts', 'membership'])
def test_rehashed_lexical_corruption_rejected(tmp_path, corruption):
    from contextlib import closing

    _, output = fixture_pack(tmp_path)
    assert validate(output)['validation'] == 'PASS'
    if corruption == 'orphan-fts':
        with closing(sqlite3.connect(output / 'knowledge.sqlite')) as conn:
            conn.execute('UPDATE search_fts SET document_id=999999 WHERE rowid='
                         '(SELECT min(rowid) FROM search_fts)')
            conn.commit()
        _rebind_artifact(output, 'snapshot')
        manifest = json.loads((output / 'manifest.json').read_bytes())
        with closing(sqlite3.connect(output / 'lexical-membership.sqlite')) as conn:
            conn.execute('UPDATE members SET document_id=999999 WHERE fts_rowid='
                         '(SELECT min(fts_rowid) FROM members)')
            conn.execute("UPDATE meta SET value=? WHERE key='snapshot_sha256'",
                         (manifest['artifacts']['snapshot']['sha256'],))
            conn.execute("UPDATE meta SET value=? WHERE key='snapshot_size'",
                         (str(manifest['artifacts']['snapshot']['size']),))
            conn.commit()
        expected = 'FTS trust closure'
    else:
        with closing(sqlite3.connect(output / 'lexical-membership.sqlite')) as conn:
            conn.execute('UPDATE members SET document_id=999999 WHERE fts_rowid='
                         '(SELECT min(fts_rowid) FROM members)')
            conn.commit()
        expected = 'membership closure'
    _rebind_artifact(output, 'lexical_membership')
    with pytest.raises(ValueError, match=expected):
        validate(output)


def test_generated_only_entry_has_no_trusted_fts(tmp_path):
    from contextlib import closing

    bundle, _ = fixture_pack(tmp_path)
    records = [{'key': {'kind': 'subject', 'namespace': 'demo.subject', 'value': 'generated-only'},
                'evidence_id': 'generated:identity',
                'documents': [{'title': 'Generated only', 'original': 'Not identity evidence.',
                               'status': 'generated_from_evidence', 'evidence_id': 'generated:text'}]}]
    _replace_bundle_records(bundle, records)
    output = tmp_path / 'generated'
    build_normalized(bundle, output)
    result = validate(output)
    assert result['validation'] == 'PASS'
    assert result['counts']['entries'] == result['counts']['documents'] == 1
    assert result['counts']['search_fts'] == 0
    with closing(sqlite3.connect(output / 'knowledge.sqlite')) as conn:
        assert conn.execute('SELECT status FROM entry_evidence').fetchall() == [('no_reference',)]
        assert conn.execute("SELECT count(*) FROM entry_evidence WHERE status='source_backed'").fetchone()[0] == 0
    with closing(sqlite3.connect(output / 'lexical-membership.sqlite')) as conn:
        assert conn.execute('SELECT count(*) FROM members').fetchone()[0] == 0


def test_crosspack_endpoint_retains_identity_not_foreign_proof(tmp_path):
    from contextlib import closing

    from tools.source_pack import build_database

    bundle, _ = _multisource_bundle(tmp_path)
    output = tmp_path / 'multisource'
    build_normalized(bundle, output)
    selected = tmp_path / 'selected.sqlite'
    build_database(output / 'knowledge.sqlite', selected, ['owner-a'])
    with closing(sqlite3.connect(selected)) as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('SELECT source_id FROM sources').fetchall() == [('owner-a',)]
        assert conn.execute('SELECT value,type,locator FROM entries ORDER BY value').fetchall() == [
            ('owner-a', 'subject', None), ('owner-b', None, None)]
        endpoint = conn.execute("SELECT id FROM entries WHERE value='owner-b'").fetchone()[0]
        for table in ('entry_evidence', 'documents', 'aliases'):
            assert conn.execute('SELECT count(*) FROM ' + table + ' WHERE entry_id=?',
                                (endpoint,)).fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM search_fts WHERE entry_id=?', (endpoint,)).fetchone()[0] == 0
        assert conn.execute('SELECT dst,source_id,verification_status FROM links').fetchall() == [
            (endpoint, 'owner-a', 'candidate')]


def _stub_model(tmp_path):
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'manifest.json').write_text(json.dumps({
        'schema': 'synthetic-test-model',
        'revision': '5617a9f61b028005a4858fdac845db406aefb181'}), encoding='utf-8')
    (model / 'tokenizer.json').write_text('{}', encoding='utf-8')
    return model


@pytest.fixture
def native_semantic_pack(tmp_path):
    import re
    from types import SimpleNamespace

    import numpy as np

    from tools.generic_semantic import prepare

    native = Path(__file__).resolve().parents[1] / 'build/p4-usearch-native-fix/rust-target/release/examples'
    builder, inspector = native / 'build_i8.exe', native / 'inspect_i8.exe'
    if not builder.is_file() or not inspector.is_file():
        pytest.skip('native build_i8/inspect_i8 executables absent: ' + str(native))

    class TinyTokenizer:
        def encode(self, text, *, add_special_tokens=False):
            offsets = [match.span() for match in re.finditer(r'\S+', text)]
            ids = list(range(1, len(offsets) + 1))
            if add_special_tokens:
                ids = [0, *ids, 0]
                offsets = [(0, 0), *offsets, (0, 0)]
            return SimpleNamespace(ids=ids, offsets=offsets)

    calls = []
    def unit_encoder(texts):
        calls.append(list(texts))
        vectors = np.zeros((len(texts), 1024), dtype=np.float32)
        vectors[np.arange(len(texts)), np.arange(len(texts))] = 1
        return vectors

    _, pack = fixture_pack(tmp_path)
    output = tmp_path / 'semantic'
    result = prepare(pack, _stub_model(tmp_path), output, builder,
                     encoder=unit_encoder, tokenizer=TinyTokenizer())
    assert len(calls) == 1 and len(calls[0]) == result['rows'] == 4
    return output, inspector, result


def test_native_tiny_semantic_prepare_and_explicit_inspection(native_semantic_pack):
    from contextlib import closing

    output, inspector, result = native_semantic_pack
    assert result['rows'] == 4
    assert isinstance(result['native_build'], dict)
    with pytest.raises(ValueError, match='semantic validation requires explicit'):
        validate(output)
    verified = validate(output, index_inspector=inspector)
    assert verified['validation'] == 'PASS'
    assert verified['capabilities'] == ['structured', 'lexical', 'semantic']
    assert verified['requires_model'] == 'bge-m3'
    with closing(sqlite3.connect(output / 'mapping.sqlite')) as conn:
        assert conn.execute('SELECT position,original_position FROM chunks ORDER BY position').fetchall() == [
            (i, i) for i in range(4)]
    manifest = json.loads((output / 'manifest.json').read_bytes())
    assert manifest['text_projection']['synthetic_test_encoder'] is True


def test_native_semantic_rehashed_mapping_evidence_rejected(native_semantic_pack):
    from contextlib import closing

    output, inspector, _ = native_semantic_pack
    assert validate(output, index_inspector=inspector)['validation'] == 'PASS'
    with closing(sqlite3.connect(output / 'mapping.sqlite')) as conn:
        conn.execute("UPDATE chunks SET evidence_id='foreign:evidence' WHERE position=0")
        conn.commit()
    _rebind_artifact(output, 'mapping')
    with pytest.raises(ValueError, match='semantic mapping proof closure'):
        validate(output, index_inspector=inspector)


@pytest.mark.parametrize('bad_contract', ['revision', 'schema'])
def test_production_semantic_unsupported_model_rejected_without_download(tmp_path, monkeypatch, bad_contract):
    import socket

    from tools.generic_semantic import prepare

    def forbidden_network(*args, **kwargs):
        pytest.fail('unsupported production model attempted network access')

    monkeypatch.setattr(socket, 'socket', forbidden_network)
    monkeypatch.setattr(socket, 'create_connection', forbidden_network)
    _, pack = fixture_pack(tmp_path)
    model = _stub_model(tmp_path)
    if bad_contract == 'revision':
        manifest = json.loads((model / 'manifest.json').read_bytes())
        manifest['revision'] = 'unsupported'
        (model / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    expected = 'unsupported frozen model revision' if bad_contract == 'revision' else 'unsupported_model_contract'
    output = tmp_path / 'rejected-semantic'
    with pytest.raises(ValueError, match=expected):
        prepare(pack, model, output, tmp_path / 'must-not-run.exe')
    assert not output.exists()
