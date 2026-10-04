"""Ordinary production entrypoint wiring without heavyweight asset execution."""
import copy
import json
import sqlite3
from contextlib import nullcontext

import pytest

from tools import p4_full_acceptance as acceptance
from tools import p4_full_build as build
from tools import p4_full_preflight as full


def test_execute_connects_real_builder_and_manifest(tmp_path, monkeypatch):
    snapshot = tmp_path / 'snapshot.sqlite'
    snapshot.write_bytes(b'fixture')
    ref = build.binding(snapshot, tmp_path)
    config = {'snapshot': ref, 'declarative_contract': full.DECLARATIONS}
    verified = {'model': {'asset_directory': 'model'}, 'contract': {}, 'bindings': {},
                'manifest': {'tokenizer_inventory_sha256': 'a' * 64},
                'job': {'threads': 8, 'batch_size': 8}}
    calls = []
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build, 'binding', lambda path, root: ref)
    monkeypatch.setattr(build, 'read_json', lambda path: config)
    monkeypatch.setattr(full, 'validate_contract', lambda value: full.DECLARATIONS)
    monkeypatch.setattr(full, 'inventory', lambda: verified)
    monkeypatch.setattr(full, 'contained', lambda name: tmp_path / name)
    monkeypatch.setattr(full.exact, 'frozen_tokenizers', lambda path: (object(), None))
    monkeypatch.setattr(full, 'readonly', lambda path: nullcontext(object()))
    monkeypatch.setattr(full, 'census_and_chunk_count', lambda *a: {'actual_chunks': 3})
    monkeypatch.setattr(full, 'documents', lambda conn: (x for x in []))
    monkeypatch.setattr(acceptance, '_inventory_guard', lambda refs: nullcontext())
    monkeypatch.setattr(build, 'synthetic_run', lambda *a, **k: (_ for _ in ()).throw(AssertionError('fixture substitution')))
    def stream(*args, **kwargs):
        calls.append('build_stream')
        assert args[6] == full.DECLARATIONS and args[7]['actual_chunks'] == 3
        assert kwargs['batch_size'] == 8 and isinstance(kwargs['reference'], build.FreshCPUReference)
        return {'chunks': 3}
    monkeypatch.setattr(build, 'build_stream', stream)
    def manifest(*args):
        calls.append('manifest')
        assert args[0] is config and args[1] is verified and args[3] == 3
        return {'fixture_product_contract': True}
    monkeypatch.setattr(build, 'manifest', manifest)
    monkeypatch.setattr(acceptance, 'validate_full_manifest', lambda *a, **k: calls.append('validate_full_manifest'))
    def lifecycle(output, report, work, **kwargs):
        assert kwargs['snapshot'] == snapshot
        assert report['activation']['snapshot'] == ref
        return work()
    monkeypatch.setattr(build, 'lifecycle', lifecycle)
    assert build.execute(output=tmp_path / 'new-product') == {'fixture_product_contract': True}
    assert calls == ['build_stream', 'manifest', 'validate_full_manifest']
    assert not (tmp_path / 'new-product').exists()


def test_real_configuration_paths_are_distinct():
    contract = build.read_json(full.FULL_CONTRACT)
    assert full.validate_contract(contract) == full.DECLARATIONS
    assert full.CONFIG == full.FULL_CONTRACT and full.CURRENT_ASSETS != full.FULL_CONTRACT
    assert full.current_asset_spec()['schema'] == 'product_asset_spec_v1'
    with pytest.raises(ValueError, match='FULL contract'):
        full.validate_contract(build.read_json(full.CURRENT_ASSETS))


def test_real_lifecycle_snapshot_baseline_and_terminal_failure_release_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    snapshot = tmp_path / 'snapshot.sqlite'
    snapshot.write_bytes(b'original')
    output = tmp_path / 'candidate'
    report = build.new_report()
    report['activation'] = {'snapshot': build.binding(snapshot, tmp_path)}
    def work():
        snapshot.write_bytes(b'changed!')
        raise RuntimeError('first failure')
    with pytest.raises(RuntimeError, match='first failure') as caught:
        build.lifecycle(output, report, work, snapshot=snapshot)
    assert report['snapshot_after_hash_status'] == 'CHANGED'
    assert report['error_message'] == 'first failure'
    assert report['terminal_error_message'] == 'terminal snapshot changed'
    assert caught.value.__cause__ is not None
    assert report['lock_released'] and not build.attempt_lock(output).exists()
    assert (output / 'execution-receipt.json').is_file()


def test_lifecycle_receipt_failure_releases_owned_lock_and_retains_first_error(tmp_path, monkeypatch):
    output = tmp_path / 'candidate'
    report = build.new_report()
    def work():
        raise RuntimeError('work failed')
    monkeypatch.setattr(build, 'terminal', lambda *args: (_ for _ in ()).throw(OSError('receipt failed')))
    with pytest.raises(RuntimeError, match='work failed'):
        build.lifecycle(output, report, work)
    assert report['terminal_error_message'] == 'receipt failed'
    assert report['lock_released'] and not build.attempt_lock(output).exists()


def test_existing_assets_real_small_products(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(build, 'ROOT', root)
    contract = copy.deepcopy(build.read_json(full.FULL_CONTRACT))
    spec = copy.deepcopy(full.current_asset_spec())
    def make(name, data):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return build.binding(path, root)
    snapshot = make('snapshot.sqlite', b'snapshot-fixture')
    contract['snapshot'] = snapshot
    contract['declarative_contract']['corpus']['documents'] = 1
    config = root / 'configs/p4-full-semantic-v1.json'
    make('configs/p4-full-semantic-v1.json', json.dumps(contract).encode())
    prefix = 'build/p4-full-semantic-v1-retry1/'
    pins = {'rows': 1, 'documents': 1}
    for role, name in [('index', 'vectors.usearch'), ('corpus', 'corpus.jsonl'), ('vectors', 'vectors.npy')]:
        pins[role] = make(prefix + name, ('real-fixture-' + role).encode())
    mapping = root / (prefix + 'chunks.sqlite')
    with sqlite3.connect(mapping) as conn:
        conn.executescript('CREATE TABLE chunks (id INTEGER); INSERT INTO chunks VALUES (1);')
    pins['mapping'] = build.binding(mapping, root)
    spec['existing_full_assets'] = pins
    model = spec['model']
    native = model['contract']['reviewed']
    ref = make(model['contract']['path'], json.dumps(native).encode())
    model['contract']['file_sha256'] = ref['sha256']
    token = make(model['assetdirectory'] + '/tokenizer.json', b'tiny-tokenizer')
    model['obtained_inventory'] = [{**token, 'path': 'tokenizer.json', 'git_blob_sha1': 'historical-metadata-not-authority'}]
    exported = [make('build/export/' + name, b'tiny-' + name.encode()) for name in ('model.onnx', 'weights.bin')]
    export = make('build/export/manifest.json', json.dumps({'files': [
        {**r, 'path': r['path'].split('/')[-1]} for r in exported]}).encode())
    spec['export_manifest'] = export
    spec['ort_dll'] = {**make('runtime/onnxruntime.dll', b'tiny-dll'),
                       'path': str(root / 'runtime/onnxruntime.dll')}
    make('configs/p4-current-assets.json', json.dumps(spec).encode())
    for module in (build, full, acceptance):
        monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(full, 'FULL_CONTRACT', config)
    monkeypatch.setattr(full, 'SNAPSHOT', snapshot)
    monkeypatch.setattr(full, 'DECLARATIONS', contract['declarative_contract'])
    monkeypatch.setattr(acceptance, 'CONFIG', config)
    for name in ('execute', 'build_stream', 'index_factory'):
        monkeypatch.setattr(build, name, lambda *a, **k: pytest.fail('rebuild forbidden'))
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    target = root / 'build/candidate'
    with acceptance.AcceptanceSession() as session:
        manifest = build.existing_assets(output=target, session=session)
        assert acceptance.validate_full_manifest(manifest, contract, pack_root=target, session=session) == 1
        bad = copy.deepcopy(manifest)
        replacement = make('unrelated-index', b'other-index')
        bad['artifacts']['index'] = {**replacement, 'path': '../../unrelated-index'}
        with pytest.raises(ValueError, match='role binding mismatch'):
            acceptance.validate_full_manifest(bad, contract, pack_root=target, session=session)
        escaped = copy.deepcopy(manifest)
        escaped['artifacts']['index']['path'] = '../../../../outside'
        with pytest.raises((ValueError, FileNotFoundError)):
            acceptance.validate_full_manifest(escaped, contract, pack_root=target, session=session)
        with pytest.raises(ValueError, match='already exists'):
            build.existing_assets(output=target, session=session)
    assert all(p.read_bytes() == data for p, data in before.items())
    assert list(target.iterdir()) == [target / 'manifest.json']
    assert not list(target.parent.glob('candidate.staging-*'))


def test_lifecycle_never_releases_replaced_lock(tmp_path):
    output = tmp_path / 'candidate'
    report = build.new_report()
    def work():
        lock = build.attempt_lock(output)
        lock.unlink()
        lock.write_text('{"token":"another-owner"}', encoding='utf8')
        raise RuntimeError('work failed')
    with pytest.raises(RuntimeError, match='work failed') as caught:
        build.lifecycle(output, report, work)
    assert build.attempt_lock(output).is_file()
    assert not report.get('lock_released', False)
    assert any('ownership changed' in note for note in caught.value.__notes__)
