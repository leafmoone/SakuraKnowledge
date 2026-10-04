"""Ordinary production entrypoint wiring without heavyweight asset execution."""
from contextlib import nullcontext

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
        return work()
    monkeypatch.setattr(build, 'lifecycle', lifecycle)
    assert build.execute(output=tmp_path / 'new-product') == {'fixture_product_contract': True}
    assert calls == ['build_stream', 'manifest', 'validate_full_manifest']
    assert not (tmp_path / 'new-product').exists()
