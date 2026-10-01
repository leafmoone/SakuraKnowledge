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


def test_freeze_and_check_preserve_absolute_dll_and_reject_other_external(external_dll, monkeypatch):
    root, dll = external_dll
    monkeypatch.setattr(pilot, 'pack_bindings', lambda manifest: (
        {'snapshot': {'identity': 'snapshot'}}, [dll]))
    monkeypatch.setattr(pilot, 'approved_receipts', lambda: None)
    monkeypatch.setattr(pilot, 'load', lambda path: {})
    monkeypatch.setattr(pilot.ann.selection, 'BINDINGS', {})
    monkeypatch.setattr(pilot.subprocess, 'check_output', lambda *args, **kwargs: 'commit\n')
    names = [pilot.ann.selection.JOB, pilot.ann.selection.CONFIG, pilot.ann.selection.SOURCE,
             pilot.ann.RETRY_CONFIG, pilot.ann.INPUTS['queries'], pilot.ann.INPUTS['ranks'],
             f'{pilot.ann.RETRY_RAW}/{pilot.SELECTED}.json',
             'rust/Cargo.toml', 'rust/Cargo.lock', 'binary']
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'local')
    job = pilot.freeze_job('binary', output='job.json')
    assert job['frozen_sha256'][dll.as_posix()] == pilot.DLL_SHA
    assert 'binary' in job['frozen_sha256']
    pilot.check_frozen(job)
    other = dll.with_name('other.dll')
    other.write_bytes(dll.read_bytes())
    job['frozen_sha256'][other.as_posix()] = pilot.DLL_SHA
    with pytest.raises(ValueError, match='escapes repository'):
        pilot.check_frozen(job)
    del job['frozen_sha256'][other.as_posix()]
    dll.write_bytes(b'changed!!!')
    job['frozen_sha256'][dll.as_posix()] = pilot.sha(dll)
    with pytest.raises(ValueError, match='unpinned ORT DLL'):
        pilot.check_frozen(job)
