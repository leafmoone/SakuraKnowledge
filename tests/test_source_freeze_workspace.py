import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from examples.source_pack.multi_adapter import MultiAdapter
from tools import generic_semantic
from tools.normalized_source import build_normalized, normalize, validate
from tools.source_inventory import capture, validate_inventory

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = 'examples.source_pack.multi_adapter:MultiAdapter'


def raw_copy(tmp_path):
    raw = tmp_path / 'raw'
    shutil.copytree(ROOT / 'examples/source_pack/raw_multi', raw)
    return raw


def test_complete_reads_and_raw_removed_build(tmp_path, monkeypatch):
    raw = raw_copy(tmp_path)
    reads = []
    original = Path.read_bytes
    def tracked(path):
        if path.is_relative_to(raw):
            reads.append(path.relative_to(raw).as_posix())
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', tracked)
    bundle = tmp_path / 'bundle'
    manifest = normalize(raw, ADAPTER, bundle, 'demo-multi')
    declared = {i['path'] for i in manifest['input_inventory']}
    assert len(declared) == 4 and set(reads) == declared
    assert sum(i['size'] for i in manifest['input_inventory']) > 0
    shutil.rmtree(raw)
    result = build_normalized(bundle, tmp_path / 'pack')
    assert result['validation'] == 'PASS' and result['counts']['entries'] == 4


@pytest.mark.parametrize('phase', ['source_metadata', 'inspect', 'iter_records'])
@pytest.mark.parametrize('mutation', ['same_size', 'delete', 'add_declared'])
def test_all_adapter_reads_are_bracketed(tmp_path, monkeypatch, phase, mutation):
    raw = raw_copy(tmp_path)
    original = getattr(MultiAdapter, phase)
    changed = []
    def mutate():
        if changed:
            return
        changed.append(True)
        if mutation == 'same_size':
            p = raw / 'subjects.json'
            p.write_bytes(p.read_bytes().replace(b'Crystal', b'Kristal'))
        elif mutation == 'delete':
            (raw / 'subjects.json').unlink()
        else:
            (raw / 'extra.json').write_text('{}')
    def hooked(self, path):
        result = original(self, path)
        if phase == 'iter_records':
            result = list(result)
        mutate()
        return iter(result) if phase == 'iter_records' else result
    monkeypatch.setattr(MultiAdapter, phase, hooked)
    inventory = MultiAdapter.input_inventory
    if mutation == 'add_declared':
        monkeypatch.setattr(MultiAdapter, 'input_inventory', lambda self, path: inventory(self, path) + ([{'path': 'extra.json'}] if changed else []))
    bundle = tmp_path / 'bundle'
    with pytest.raises((ValueError, FileNotFoundError)):
        normalize(raw, ADAPTER, bundle, 'demo-multi')
    assert not (bundle / 'manifest.json').exists()


@pytest.mark.parametrize('path', ['../bad', '/absolute', 'a\\b', './bad', 'a//b', 'C:/raw'])
def test_unsafe_inventory_paths(path):
    with pytest.raises(ValueError):
        validate_inventory([{'path': path, 'size': 1, 'sha256': 'a' * 64}])


def test_duplicate_and_directory_inventory_rejected(tmp_path):
    raw = raw_copy(tmp_path)
    class Bad:
        def input_inventory(self, path):
            return [{'path': 'subjects.json'}, {'path': 'subjects.json'}]
    with pytest.raises(ValueError, match='duplicate'):
        capture(Bad(), raw)
    class Directory:
        def input_inventory(self, path):
            return [{'path': 'folder'}]
    (raw / 'folder').mkdir()
    with pytest.raises(ValueError, match='regular'):
        capture(Directory(), raw)


def test_symlink_inventory_rejected(tmp_path):
    raw = raw_copy(tmp_path)
    try:
        (raw / 'linked.json').symlink_to(raw / 'subjects.json')
    except OSError as exc:
        pytest.skip('symlink privilege unavailable: ' + str(exc))
    class Linked:
        def input_inventory(self, path):
            return [{'path': 'linked.json'}]
    with pytest.raises(ValueError, match='symlink'):
        capture(Linked(), raw)


class TinyTokenizer:
    def encode(self, text, add_special_tokens=False):
        offsets = [m.span() for m in re.finditer(r'\S+', text)]
        return SimpleNamespace(ids=list(range(len(offsets))), offsets=offsets)


def semantic_inputs(tmp_path):
    raw = raw_copy(tmp_path)
    normalize(raw, ADAPTER, tmp_path / 'bundle', 'demo-multi')
    build_normalized(tmp_path / 'bundle', tmp_path / 'pack')
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'manifest.json').write_text(json.dumps({'revision': '5617a9f61b028005a4858fdac845db406aefb181'}))
    (model / 'tokenizer.json').write_text('{}')
    native = ROOT / 'build/p4-usearch-native-fix/rust-target/release/examples'
    if not (native / 'build_i8.exe').exists() or not (native / 'inspect_i8.exe').exists():
        pytest.skip('explicit native helpers missing')
    return tmp_path / 'pack', model, native


def test_publish_failure_verified_resume_never_encodes(tmp_path, monkeypatch):
    pack, model, native = semantic_inputs(tmp_path)
    calls = []
    def encoder(texts):
        calls.append(1)
        v = np.zeros((len(texts), 1024), dtype=np.float32)
        v[:, 0] = 1
        return v
    workspace, output = tmp_path / 'work', tmp_path / 'runtime'
    publish = generic_semantic._publish
    def fail(staging, output):
        raise OSError('injected publish failure')
    monkeypatch.setattr(generic_semantic, '_publish', fail)
    with pytest.raises(RuntimeError, match='workspace preserved'):
        generic_semantic.prepare(pack, model, output, native / 'build_i8.exe', encoder=encoder,
                                 tokenizer=TinyTokenizer(), workspace=workspace)
    assert calls == [1] and (workspace / 'vectors.npy').exists() and not output.exists()
    monkeypatch.setattr(generic_semantic, '_publish', publish)
    calls.clear()
    old_contract = (model / 'manifest.json').read_bytes()
    (model / 'manifest.json').write_bytes(old_contract + b' ')
    with pytest.raises(RuntimeError, match='binding mismatch'):
        generic_semantic.prepare(pack, model, output, native / 'build_i8.exe', encoder=encoder,
                                 tokenizer=TinyTokenizer(), workspace=workspace, resume_workspace=True)
    assert calls == []
    (model / 'manifest.json').write_bytes(old_contract)
    with pytest.raises(FileExistsError, match='workspace already exists'):
        generic_semantic.prepare(pack, model, output, native / 'build_i8.exe', encoder=encoder,
                                 tokenizer=TinyTokenizer(), workspace=workspace)
    old_index = (workspace / 'vectors.i8.usearch').read_bytes()
    result = generic_semantic.prepare(pack, model, output, native / 'build_i8.exe', encoder=encoder,
                                      tokenizer=TinyTokenizer(), workspace=workspace, resume_workspace=True,
                                      keep_workspace=True)
    assert calls == [] and result['workspace_kept']
    assert {p.name for p in output.iterdir()} == {'manifest.json', 'knowledge.sqlite', 'lexical-membership.sqlite', 'mapping.sqlite', 'vectors.i8.usearch'}
    assert (workspace / 'vectors.npy').exists()
    assert (output / 'vectors.i8.usearch').read_bytes() == old_index
    validate(output, native / 'inspect_i8.exe')
    (output / 'vectors.npy').write_bytes(b'not runtime')
    with pytest.raises(ValueError, match='closed set'):
        validate(output, native / 'inspect_i8.exe')


def test_collisions_rejected_before_encoding(tmp_path):
    pack, model, native = semantic_inputs(tmp_path)
    def forbidden(texts):
        raise AssertionError('encoder must not run')
    with pytest.raises(ValueError, match='collision'):
        generic_semantic.prepare(pack, model, pack / 'nested', native / 'build_i8.exe', encoder=forbidden)
    old_output = tmp_path / 'existing-runtime'
    old_output.mkdir()
    (old_output / 'manifest.json').write_text('old valid output must be preserved')
    with pytest.raises(FileExistsError):
        generic_semantic.prepare(pack, model, old_output, native / 'build_i8.exe', encoder=forbidden)
    assert (old_output / 'manifest.json').read_text() == 'old valid output must be preserved'
