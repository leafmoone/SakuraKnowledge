import json
import sqlite3

import pytest

from sakura_knowledge.adapters import MOEGIRL_FILES
from sakura_knowledge.moegirl_refresh import (
    MAPPING_FILES,
    MoegirlRefreshAdapter,
    category_observations,
)
from tools.normalized_source import build_normalized, normalize, validate
from tools.source_pack import binding


def frozen_fixture(tmp_path, duplicate_category=False, unresolved_mapping=False):
    root = tmp_path / 'frozen'
    (root / 'moegirl').mkdir(parents=True)
    (root / 'bangumi').mkdir()
    values = {name: {} for name in MOEGIRL_FILES}
    values.update(char_index=['Mira', 'Empty', 'Gone', 'Skip'], subject_index=['Harbor'],
                  extra_processed={'Mira': {'\u522b\u540d': ['Historical Alias']}}, char2attr={'Mira': ['old-attribute']})
    if duplicate_category:
        values['subject_index'].append('Harbor')
    values['extra_info'] = {'Mira': ['{{Info|name=Mira|hair=blue}}', '{{Info|extra=second template}}'], 'Empty': []}
    values['extra_info.outcomes'] = {'Gone': {'status': 'missing'}, 'Skip': {'status': 'skipped_by_user'}}
    values['extra_info.missing'] = []
    tree = {'pages': [], 'subcategories': [{'name': 'Harbor', 'pages': [{'name': 'Mira', 'url': '/Mira'}], 'subcategories': []}]}
    values.update(attrs=tree, subjects=tree)
    for name, obj in values.items():
        (root / 'moegirl' / (name + '.json')).write_text(json.dumps(obj), encoding='utf-8')
    mapping = {'bgm2moegirl': {'1': ['Mira']}, 'moegirl2bgm': {'Mira': ['1']}, 'bgm_info': {}, 'bgm_redirects_full': {}}
    for name, obj in mapping.items():
        (root / 'bangumi' / (name + '.json')).write_text(json.dumps(obj), encoding='utf-8')
    legacy = {}
    for group, directory, files in [('moegirl', 'moegirl', MOEGIRL_FILES), ('mapping', 'bangumi', MAPPING_FILES)]:
        inventory = [{**binding(root / directory / (f + '.json')), 'path': directory + '/' + f + '.json'} for f in files]
        legacy[group] = {'source': {'source_id': group + '-historical', 'local_sha256': 'a' * 64,
                                   'repo': 'https://example.invalid/frozen-source', 'provider': 'moegirl', 'asset_name': group},
                         'owned_inventory': inventory}
    if unresolved_mapping:
        legacy['mapping']['historical_missing_endpoint_lines'] = [1]
    (root / 'refresh-context.json').write_text(json.dumps({'schema': 'moegirl-refresh-context-v1', 'legacy': legacy}), encoding='utf-8')
    return root


def test_actual_multi_source_normalize_builder(tmp_path):
    frozen = frozen_fixture(tmp_path)
    bundle, pack = tmp_path / 'bundle', tmp_path / 'pack'
    manifest = normalize(frozen, 'sakura_knowledge.moegirl_refresh:MoegirlRefreshAdapter', bundle, 'moegirl')
    assert len(manifest['sources']) == 3
    assert len(manifest['input_inventory']) == 19
    result = build_normalized(bundle, pack)
    assert result['validation'] == 'PASS' and result['counts']['documents'] == result['counts']['search_fts'] == 2
    c = sqlite3.connect(pack / 'knowledge.sqlite')
    try:
        assert c.execute("SELECT count(*) FROM links WHERE verification_status='candidate'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM links WHERE relation='character_of'").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM entry_evidence v JOIN entries e ON e.id=v.entry_id WHERE e.namespace='bangumi.character' AND v.status='source_backed'").fetchone()[0] == 0
        alias = c.execute("SELECT evidence_id,source_id FROM aliases WHERE text='Historical Alias'").fetchone()
        assert alias == ('moegirl-historical:' + 'a' * 64 + ':line:1', 'moegirl-historical')
        current = c.execute("SELECT status,payload FROM entry_evidence WHERE source_id LIKE 'moegirl-local-%'").fetchall()
        states = {json.loads(p)['raw']['current_template_state']: status for status, p in current}
        assert states == {'template_present': 'source_backed', 'empty_template_list': 'no_reference', 'missing': 'no_reference', 'skipped_by_user': 'no_reference'}
        sources = {s: json.loads(m) for s, m in c.execute('SELECT source_id,metadata FROM sources')}
        assert all(len(s['input_file_inventory']) == 19 for s in sources.values())
        assert len(sources['mapping-historical']['owned_input_inventory']) == 4
    finally:
        c.close()
    assert validate(pack)['validation'] == 'PASS'
    from tools.moegirl_refresh_validate import verify
    assert verify(pack, frozen)['documents'] == 2


def test_historical_duplicate_and_unresolved_are_preserved(tmp_path):
    frozen = frozen_fixture(tmp_path, duplicate_category=True, unresolved_mapping=True)
    records = list(MoegirlRefreshAdapter().iter_records(frozen))
    historical = [r for r in records if r['source_id'] == 'moegirl-historical']
    assert len(historical) == 5
    assert sum(r['key']['value'] == 'Harbor' for r in historical) == 1
    mappings = [r for r in records if r['source_id'] == 'mapping-historical']
    assert len(mappings) == 1 and mappings[0]['record_type'] == 'unresolved'
    assert mappings[0]['reason'] == 'missing_endpoint'
    assert not any(r.get('key', {}).get('namespace') == 'bangumi.character' for r in records)
    bundle, pack = tmp_path / 'bundle', tmp_path / 'pack'
    manifest = normalize(frozen, 'sakura_knowledge.moegirl_refresh:MoegirlRefreshAdapter', bundle, 'moegirl')
    assert manifest['expected_unresolved'] == {'mapping-historical': {'missing_endpoint': 1}}
    assert build_normalized(bundle, pack)['counts']['links'] == 0
    with sqlite3.connect(pack / 'knowledge.sqlite') as conn:
        assert conn.execute('SELECT unresolved FROM source_counts WHERE source_id=?', ('mapping-historical',)).fetchone() == (1,)


@pytest.mark.parametrize('declaration', [{}, {'mapping-historical': {'missing_endpoint': 2}}, {'unowned': {'missing_endpoint': 1}}, {'mapping-historical': {'missing_endpoint': True}}])
def test_unresolved_declaration_mismatch_fails_before_build(tmp_path, declaration):
    frozen = frozen_fixture(tmp_path, unresolved_mapping=True)
    bundle, pack = tmp_path / 'bundle', tmp_path / 'pack'
    manifest = normalize(frozen, 'sakura_knowledge.moegirl_refresh:MoegirlRefreshAdapter', bundle, 'moegirl')
    manifest['expected_unresolved'] = declaration
    (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='unresolved'):
        build_normalized(bundle, pack)
    assert not pack.exists()


def test_current_raw_changes_new_id_without_mutating_history(tmp_path):
    frozen = frozen_fixture(tmp_path)
    adapter = MoegirlRefreshAdapter()
    before = adapter.source_metadata(frozen)
    raw = frozen / 'moegirl/extra_info.json'
    data = json.loads(raw.read_bytes())
    data['Mira'][0] += ' '
    raw.write_text(json.dumps(data))
    after = adapter.source_metadata(frozen)
    assert [x['source_id'] for x in before[:2]] == [x['source_id'] for x in after[:2]]
    assert before[-1]['source_id'] != after[-1]['source_id']


def test_changed_historical_bytes_cannot_reuse_id(tmp_path):
    frozen = frozen_fixture(tmp_path)
    (frozen / 'moegirl/char_index.json').write_text('["other"]')
    with pytest.raises(ValueError, match='legacy source bytes changed'):
        MoegirlRefreshAdapter().inspect(frozen)


def test_unindexed_raw_title_fails_closed(tmp_path):
    frozen = frozen_fixture(tmp_path)
    path = frozen / 'moegirl/extra_info.json'
    data = json.loads(path.read_bytes()); data['Unbacked'] = ['{{Info|name=new}}']
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='closure'):
        MoegirlRefreshAdapter().inspect(frozen)


@pytest.mark.parametrize('field,value', [('method', 'invented'), ('raw_locator', 'wrong'), ('raw_title', 'Other'), ('trusted_text_sha256', '0' * 64), ('identity_index_locator', 'moegirl/char_index.json#/-4')])
def test_independent_proof_tamper_rejects(tmp_path, field, value):
    from tools.moegirl_refresh_validate import verify
    frozen = frozen_fixture(tmp_path)
    bundle, pack = tmp_path / 'bundle', tmp_path / 'pack'
    normalize(frozen, 'sakura_knowledge.moegirl_refresh:MoegirlRefreshAdapter', bundle, 'moegirl')
    build_normalized(bundle, pack)
    c = sqlite3.connect(pack / 'knowledge.sqlite')
    try:
        did, payload = c.execute('SELECT id,payload FROM documents LIMIT 1').fetchone()
        obj = json.loads(payload); obj['text_provenance'][field] = value
        c.execute('UPDATE documents SET payload=? WHERE id=?', (json.dumps(obj), did)); c.commit()
    finally:
        c.close()
    with pytest.raises(ValueError):
        verify(pack, frozen)


@pytest.mark.parametrize('file', ['attrs', 'subjects', 'extra_info.outcomes'])
def test_independent_category_state_owned_binding_tamper(tmp_path, file):
    from tools.moegirl_refresh_validate import verify
    frozen = frozen_fixture(tmp_path)
    bundle, pack = tmp_path / 'bundle', tmp_path / 'pack'
    normalize(frozen, 'sakura_knowledge.moegirl_refresh:MoegirlRefreshAdapter', bundle, 'moegirl')
    build_normalized(bundle, pack)
    with sqlite3.connect(pack / 'knowledge.sqlite') as conn:
        sid, raw = conn.execute("SELECT source_id,metadata FROM sources WHERE source_id LIKE 'moegirl-local-%'").fetchone()
        metadata = json.loads(raw)
        next(item for item in metadata['owned_input_inventory'] if item['path'] == 'moegirl/' + file + '.json')['sha256'] = '0' * 64
        conn.execute('UPDATE sources SET metadata=? WHERE source_id=?', (json.dumps(metadata), sid))
    with pytest.raises(ValueError, match='source-owned'):
        verify(pack, frozen)


def test_category_is_observation_not_work():
    result = category_observations({'pages': [], 'subcategories': [{'name': 'Maintenance', 'pages': [{'name': 'Mira'}], 'subcategories': []}]}, {'Mira'})
    assert result['Mira'][0]['categories'] == ['Maintenance']
    assert result['Mira'][0]['locator'] == '#/subcategories/0/pages/0'
    assert 'character_of' not in result
    with pytest.raises(TypeError):
        category_observations({'pages': None, 'subcategories': []}, {'Mira'})
