"""The authorized DLL is a read-only exception, not a repository escape hatch."""
from pathlib import Path

import pytest

from tools import p4_rust_pilot as pilot


@pytest.fixture
def external_dll(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    dll = tmp_path / 'external' / 'onnxruntime.dll'
    dll.parent.mkdir()
    dll.write_bytes(b'pinned DLL')
    monkeypatch.setattr(pilot, 'ROOT', root)
    monkeypatch.setattr(pilot, 'EXTERNAL_ORT_DLL', dll)
    monkeypatch.setattr(pilot, 'DLL_SIZE', dll.stat().st_size)
    monkeypatch.setattr(pilot, 'DLL_SHA', pilot.sha(dll))
    return root, dll


def test_production_dll_authorization_is_exact():
    assert pilot.EXTERNAL_ORT_DLL.as_posix() == (
        'C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/'
        'Lib/site-packages/onnxruntime/capi/onnxruntime.dll')
    assert pilot.DLL_SIZE == 15355936
    assert pilot.DLL_SHA == '4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847'


def test_external_binding_roundtrip_never_uses_cross_drive_relpath(external_dll, monkeypatch):
    root, dll = external_dll
    before = dll.read_bytes()
    def cross_drive(*args):
        raise ValueError('path is on another drive')
    monkeypatch.setattr(pilot.os.path, 'relpath', cross_drive)
    record = pilot.binding(dll, root, ort_dll=True)
    assert record == {'path': dll.as_posix(), 'size': pilot.DLL_SIZE, 'sha256': pilot.DLL_SHA}
    assert pilot.verify_binding(record, root, ort_dll=True) == dll
    assert dll.read_bytes() == before
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.local(dll)
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.binding(dll, root)
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.verify_binding(record, root)


@pytest.mark.parametrize('replacement', [b'wrong size', b'changed!!!'])
def test_external_dll_independent_pins_reject_self_consistent_tampering(external_dll, replacement):
    root, dll = external_dll
    dll.write_bytes(replacement)
    record = {'path': dll.as_posix(), 'size': dll.stat().st_size, 'sha256': pilot.sha(dll)}
    with pytest.raises(ValueError, match='unpinned ORT DLL'):
        pilot.binding(dll, root, ort_dll=True)
    with pytest.raises(ValueError, match='unpinned ORT DLL'):
        pilot.verify_binding(record, root, ort_dll=True)


def test_other_external_file_rejected_even_with_identical_pins(external_dll):
    root, dll = external_dll
    other = dll.with_name('other.dll')
    other.write_bytes(dll.read_bytes())
    record = {'path': other.as_posix(), 'size': pilot.DLL_SIZE, 'sha256': pilot.DLL_SHA}
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.binding(other, root, ort_dll=True)
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.verify_binding(record, root, ort_dll=True)
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.binding(Path('../external/onnxruntime.dll'), root, ort_dll=True)


def test_pack_verification_exception_only_for_ort_role(external_dll):
    root, dll = external_dll
    artifact = root / 'artifact'
    artifact.write_bytes(b'local')
    local_record = pilot.binding(artifact, root)
    dll_record = pilot.binding(dll, root, ort_dll=True)
    pack = {'schema': 'p4-rust-semantic-pack-v1', 'contract': pilot.fixed_contract(),
            'snapshot': local_record, 'export_manifest': local_record,
            'artifacts': {'ort_dll': dll_record, 'model': local_record,
                          'external_data': [local_record]}, 'approved_receipts': {}}
    manifest = root / 'manifest.json'
    pilot.save_new(manifest, pack)
    assert dll in pilot.pack_bindings(manifest)[1]
    pack['artifacts']['model'] = dll_record
    # Use a distinct manifest to preserve create-new semantics.
    bad_manifest = root / 'bad-manifest.json'
    pilot.save_new(bad_manifest, pack)
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.pack_bindings(bad_manifest)


def test_job_uses_pack_assets_without_historical_source_closure(external_dll, monkeypatch):
    root, dll = external_dll
    calls = []
    monkeypatch.setattr(pilot, 'pack_bindings', lambda manifest: (
        calls.append(manifest) or {'snapshot': {'identity': 'snapshot'}}, [dll]))
    (root / 'binary').write_bytes(b'local')
    job = pilot.create_job('binary', output='job.json')
    assert 'frozen_sha256' not in job and 'code_sha' not in job
    pilot.validate_job(job)
    assert calls == [pilot.PACK, pilot.PACK]
