import errno
import json
import sqlite3
from pathlib import Path

import pytest

from tools import portable_pack as pack
from tools.portable_pack import assemble, binding


def test_binding_hashes_actual_bytes_and_relative_path(tmp_path):
    path = tmp_path / 'space file'
    path.write_bytes(b'abc')
    assert binding(path, tmp_path) == {'path': 'space file', 'size': 3, 'sha256': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}
    with pytest.raises(ValueError):
        binding(path, tmp_path / 'other')


@pytest.fixture
def tiny(tmp_path):
    repo, output, index, native = [tmp_path / name for name in ('repo', 'output', 'external/index.i8', 'native')]

    def put(path, data=b'tiny'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    oldroot = repo / pack.OLD_ROOT
    artifacts = {}
    for role, name in [('model', 'model.onnx'), ('tokenizer', 'tokenizer.json'), ('ort_dll', 'onnxruntime.dll')]:
        put(oldroot / name)
        artifacts[role] = {'path': name}
    put(oldroot / 'model.onnx.data')
    artifacts['external_data'] = [{'path': 'model.onnx.data'}]
    manifest = {'artifacts': artifacts, 'contract': {'ann': {'dtype': 'f32'}, 'ann_storage': 'f32'},
                'declarative_contract': {'ann': {'dtype': 'f32'}}, 'canonical_contract': {},
                'lexical_membership': {'version': 'p4-full-membership-v1', 'rows': 1}}
    put(oldroot / 'manifest.json', json.dumps(manifest).encode())
    put(repo / 'configs/p4-full-semantic-v1.json', b'{"snapshot":{"path":"source.sqlite"}}')
    with sqlite3.connect(oldroot / 'lexical-membership.sqlite') as connection:
        connection.executescript('CREATE TABLE members(fts_rowid INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL, document_id INTEGER NOT NULL); CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL); INSERT INTO members VALUES(1,2,3);')
        connection.executemany('INSERT INTO meta VALUES(?,?)', [('version', 'p4-full-membership-v1'), ('rows', '1'), ('snapshot_sha256', 'old'), ('snapshot_size', '0')])
    for name in ['sknow-rs.exe', 'semantic_pilot.exe']:
        put(repo / 'build/p4-usearch-native-fix/rust-target/release' / name)
    for name in ['scripts/sknow.ps1', 'README.md', 'vendor/usearch-2.26.2/LICENSE', 'docs/licenses/BGE-LICENSE', 'docs/licenses/ONNXRuntime-LICENSE',
                 'build/p3-full-authorized-retry1/knowledge.sqlite', 'build/p4-full-semantic-v1-retry1/chunks.sqlite',
                 'build/p4-full-semantic-v1-retry1/vectors.npy', 'build/p4-usearch-native-fix/rust-target/release/examples/build_i8.exe']:
        put(repo / name)
    for name in ['bin/libstdc++-6.dll', 'bin/libgcc_s_seh-1.dll', 'bin/libwinpthread-1.dll',
                 'share/licenses/gcc-libs/COPYING3', 'share/licenses/gcc-libs/COPYING.RUNTIME', 'share/licenses/gcc-libs/COPYING.LIB', 'share/licenses/libwinpthread/COPYING']:
        put(native / name)
    put(output / 'knowledge.sqlite', b'database')
    put(output / 'chunks.sqlite', b'mapping')
    put(index, b'I8 product')
    return repo, output, index, native


def test_tiny_real_assembly_manifest_last_and_closed_inventory(tiny, monkeypatch):
    repo, output, index, native = tiny
    order = []
    publish = pack._publish

    def observe(source, destination):
        if destination.name == 'manifest.json':
            assert (output / 'inventory.json').is_file()
            inventory = json.loads((output / 'inventory.json').read_text())
            assert all((output / name).is_file() for name in inventory if name != 'manifest.json')
        else:
            assert not (output / 'manifest.json').exists()
        order.append(destination.relative_to(output).as_posix())
        publish(source, destination)

    monkeypatch.setattr(pack, '_publish', observe)
    result = assemble(repo, output, index, native)
    assert order[-2:] == ['inventory.json', 'manifest.json']
    assert index.read_bytes() == b'I8 product'
    assert (output / 'vectors.i8.usearch').read_bytes() == index.read_bytes()
    assert not (output / '.assemble-stage').exists()
    inventory = json.loads((output / 'inventory.json').read_text())
    manifest = json.loads((output / 'manifest.json').read_text())
    pack.validate_pack(output, manifest, {**inventory, 'inventory.json': binding(output / 'inventory.json', output)}, set(inventory) | {'inventory.json'})
    assert result['files'] == 25
    assert result['files'] == len(inventory) + 1
    assert manifest['artifacts']['external_data'][0]['path'] == 'model/model.onnx.data'
    assert (repo / pack.OLD_ROOT / 'lexical-membership.sqlite').read_bytes() != (output / 'lexical-membership.sqlite').read_bytes()


def test_midcopy_failure_preserves_prerequisites_and_index_then_retry(tiny, monkeypatch):
    repo, output, index, native = tiny
    originals = {path: path.read_bytes() for path in [index, output / 'knowledge.sqlite', output / 'chunks.sqlite']}
    copyfile = pack.shutil.copyfile

    def fail(source, destination):
        if Path(destination).name == 'tokenizer.json':
            Path(destination).write_bytes(b'partial')
            raise OSError('mid-copy')
        return copyfile(source, destination)

    with monkeypatch.context() as scoped:
        scoped.setattr(pack.shutil, 'copyfile', fail)
        with pytest.raises(OSError, match='mid-copy'):
            assemble(repo, output, index, native)
    assert {path: path.read_bytes() for path in originals} == originals
    assert {p.name for p in output.iterdir()} == pack.PREREQUISITES
    assemble(repo, output, index, native)
    assert (output / 'manifest.json').exists()


def test_partial_publish_failure_rolls_back_owned_files_and_retries(tiny, monkeypatch):
    repo, output, index, native = tiny
    publish = pack._publish

    def fail(source, destination):
        if destination.name == 'inventory.json':
            destination.write_bytes(b'concurrent owner')
            raise FileExistsError(destination)
        publish(source, destination)

    with monkeypatch.context() as scoped:
        scoped.setattr(pack, '_publish', fail)
        with pytest.raises(FileExistsError):
            assemble(repo, output, index, native)
    assert (output / 'inventory.json').read_bytes() == b'concurrent owner'
    assert not (output / 'manifest.json').exists()
    assert not (output / 'vectors.i8.usearch').exists()
    assert index.read_bytes() == b'I8 product'
    (output / 'inventory.json').unlink()
    assemble(repo, output, index, native)


def test_valid_existing_manifest_refused_before_any_inputs(tiny, monkeypatch):
    repo, output, index, native = tiny
    assemble(repo, output, index, native)
    original = (output / 'manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        assemble(Path('missing-repo'), output, Path('never-read'), Path('missing-native'))
    assert (output / 'manifest.json').read_bytes() == original


@pytest.mark.parametrize('collision', ['bin/model.onnx', 'bin/onnxruntime.dll', 'inventory.json', 'unrelated.txt', '.assemble-stage'])
def test_output_collision_before_hash(tiny, monkeypatch, collision):
    repo, output, index, native = tiny
    path = output / collision
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'preserve')
    monkeypatch.setattr(pack, 'binding', lambda *args: pytest.fail('hashed before preflight'))
    with pytest.raises(FileExistsError):
        assemble(repo, output, index, native)
    assert path.read_bytes() == b'preserve'


@pytest.mark.parametrize('missing', ['share/licenses/gcc-libs/COPYING3', 'bin/libgcc_s_seh-1.dll'])
def test_all_sources_preflight_before_hash(tiny, monkeypatch, missing):
    repo, output, index, native = tiny
    (native / missing).unlink()
    monkeypatch.setattr(pack, 'binding', lambda *args: pytest.fail('hashed before preflight'))
    with pytest.raises(FileNotFoundError):
        assemble(repo, output, index, native)
    assert not (output / '.assemble-stage').exists()


def test_cross_volume_supplied_index_never_renamed(tiny, monkeypatch):
    repo, output, index, native = tiny

    def no_rename(*args, **kwargs):
        raise OSError(errno.EXDEV, 'simulated cross-volume')

    monkeypatch.setattr(Path, 'rename', no_rename)
    monkeypatch.setattr(pack.os, 'rename', no_rename)
    monkeypatch.setattr(pack.os, 'replace', no_rename)
    assemble(repo, output, index, native)
    assert index.is_file()


def _prepare(tiny, monkeypatch):
    import sys
    repo, output, index, native = tiny
    for path in output.iterdir():
        path.unlink()
    output.rmdir()
    index.unlink()
    index.parent.rmdir()
    monkeypatch.setattr(sys, 'argv', ['portable_pack', '--repository', str(repo), '--output', str(output), '--index', str(index), '--native-root', str(native), '--prepare'])
    return repo, output, index, native


@pytest.mark.parametrize('collision', ['index', 'output', 'missing-license', 'missing-builder', 'missing-npy', 'index-parent-file'])
def test_prepare_preflight_before_exports(tiny, monkeypatch, collision):
    from tools import portable_export
    repo, output, index, native = _prepare(tiny, monkeypatch)
    if collision == 'index':
        index.parent.mkdir()
        index.write_bytes(b'preserve')
    elif collision == 'output':
        output.mkdir()
    elif collision == 'missing-license':
        (native / 'share/licenses/libwinpthread/COPYING').unlink()
    elif collision == 'missing-builder':
        (repo / 'build/p4-usearch-native-fix/rust-target/release/examples/build_i8.exe').unlink()
    elif collision == 'missing-npy':
        (repo / 'build/p4-full-semantic-v1-retry1/vectors.npy').unlink()
    else:
        index.parent.write_bytes(b'not a directory')
    monkeypatch.setattr(portable_export, 'export_db', lambda *args: pytest.fail('export before preflight'))
    monkeypatch.setattr(pack.subprocess, 'run', lambda *args, **kwargs: pytest.fail('build before preflight'))
    with pytest.raises((FileExistsError, FileNotFoundError)):
        pack.main()
    assert not (output / 'knowledge.sqlite').exists()


def test_prepare_real_assembly_only_expensive_steps_mocked(tiny, monkeypatch):
    from tools import portable_export
    _repo, output, index, _native = _prepare(tiny, monkeypatch)
    calls = []

    def export(source, destination):
        assert index.parent.is_dir()
        assert not index.exists()
        destination.write_bytes(b'exported')
        calls.append(destination.name)

    def build(command, check):
        assert check
        assert not index.exists()
        index.write_bytes(b'built I8')
        calls.append('build')

    monkeypatch.setattr(portable_export, 'export_db', export)
    monkeypatch.setattr(portable_export, 'export_mapping', export)
    monkeypatch.setattr(pack.subprocess, 'run', build)
    pack.main()
    assert calls == ['knowledge.sqlite', 'chunks.sqlite', 'build']
    assert index.read_bytes() == b'built I8'
    assert (output / 'manifest.json').is_file()


def test_bad_membership_never_publishes(tiny):
    repo, output, index, native = tiny
    with sqlite3.connect(repo / pack.OLD_ROOT / 'lexical-membership.sqlite') as connection:
        connection.execute("UPDATE meta SET value='2' WHERE key='rows'")
    with pytest.raises(ValueError, match='membership binding'):
        assemble(repo, output, index, native)
    assert not (output / 'manifest.json').exists()
    assert not (output / '.assemble-stage').exists()
