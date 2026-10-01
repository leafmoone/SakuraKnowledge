import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p3_final_artifacts as artifacts
import p3_final_fixture as fixture


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('pure fixture verification must not execute processes or open SQLite')

    monkeypatch.setattr(artifacts.subprocess, 'run', forbidden)
    monkeypatch.setattr(artifacts.subprocess, 'check_output', forbidden)
    monkeypatch.setattr(artifacts.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(fixture, 'run', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(artifacts, 'ROOT', tmp_path)
    monkeypatch.setattr(fixture, 'ROOT', tmp_path)
    real_check_binding = fixture.check_binding

    def check_temporary_binding(ref):
        assert Path(ref['path']).resolve().is_relative_to(tmp_path.resolve())
        real_check_binding(ref)

    monkeypatch.setattr(fixture, 'check_binding', check_temporary_binding)

    def put(name, data):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return artifacts.binding(path)

    directory = tmp_path / 'dist/final'
    target = directory / 'source/rust/target'
    art = {
        'source_commit': 'a' * 40, 'directory': str(directory),
        'source': str(directory / 'source'),
        'environment': {'CARGO_TARGET_DIR': str(target)},
        'binary': put('dist/final/source/rust/target/release/sknow.exe', b'delivery binary'),
        'wheel': put('dist/final/wheel/synthetic.whl', b'delivery wheel')}
    put('dist/final/source/rust/Cargo.toml', b'[package]\nname = "synthetic"\n')
    artifact_ref = put('reports/P3/final-artifacts-retry1.json', json.dumps(art).encode())
    delivery = {name: art[name] for name in ('binary', 'wheel')}
    receipt = {
        'status': 'PASS', 'source_commit': art['source_commit'], 'artifacts': artifact_ref,
        'before': copy.deepcopy(delivery), 'after': copy.deepcopy(delivery),
        'delivery_artifacts_unchanged': True, 'retries': 0, 'FULL_queries': 0,
        'benchmark_build_or_execution': False, 'runtime_or_delivery_rebuild_requested': False,
        'original_pytest_FAIL': 'reports/P3/final-check-pytest.json',
        'source_bindings': {
            'example': put('dist/final/source/rust/examples/text_probe.rs', b'fn main() {}\n'),
            'runtime': put('dist/final/source/rust/src/lib.rs', b'pub fn synthetic() {}\n')},
        'probe': put('dist/final/source/rust/target/release/examples/text_probe.exe', b'probe'),
        'process': {
            'argv': ['cargo', 'build', '--manifest-path', str(directory / 'source/rust/Cargo.toml'),
                     '--locked', '--release', '--example', 'text_probe'],
            'exit': 0, 'environment': copy.deepcopy(art['environment']),
            'child_cargo_target_explicit': True, 'target_inside_Knowledge_and_archive': True}}
    return art, receipt, artifact_ref


def test_valid_fixture_is_pure_and_preserves_delivery_and_sources(synthetic, tmp_path):
    art, receipt, artifact_ref = synthetic
    before = copy.deepcopy(synthetic)
    paths = [Path(ref['path']) for ref in
             (*receipt['before'].values(), *receipt['source_bindings'].values(), receipt['probe'],
              artifact_ref)]
    original_bytes = {path: path.read_bytes() for path in paths}
    assert fixture.verify_fixture(art, receipt, artifact_ref) is None
    assert synthetic == before
    assert {path: path.read_bytes() for path in paths} == original_bytes
    assert not (tmp_path / 'reports/P3/final-text-probe-prerequisite-start.json').exists()


@pytest.mark.parametrize('field,value', [('path', 'different'), ('bytes', 0), ('sha256', '0' * 64)])
def test_artifact_receipt_reference_must_match_exactly(synthetic, tmp_path, field, value):
    art, receipt, artifact_ref = synthetic
    wrong_ref = copy.deepcopy(artifact_ref)
    wrong_ref[field] = str(tmp_path / value) if field == 'path' else value
    with pytest.raises(ValueError, match='fixture provenance'):
        fixture.verify_fixture(art, receipt, wrong_ref)


@pytest.mark.parametrize('side', ['before', 'after'])
@pytest.mark.parametrize('name', ['binary', 'wheel'])
def test_before_and_after_must_equal_delivery_bindings(synthetic, side, name):
    art, receipt, artifact_ref = synthetic
    receipt[side][name]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='fixture provenance'):
        fixture.verify_fixture(art, receipt, artifact_ref)


@pytest.mark.parametrize('name', ['binary', 'wheel', 'probe', 'example', 'runtime'])
def test_current_bytes_must_still_match_receipt(synthetic, name):
    art, receipt, artifact_ref = synthetic
    ref = (art[name] if name in ('binary', 'wheel') else receipt['probe'] if name == 'probe'
           else receipt['source_bindings'][name])
    Path(ref['path']).write_bytes(b'changed current bytes')
    with pytest.raises(ValueError, match='artifact bytes/identity changed'):
        fixture.verify_fixture(art, receipt, artifact_ref)


@pytest.mark.parametrize('change', ['unlocked', 'wrong-order', 'runtime-build', 'benchmark',
                                  'other-manifest', 'target-override'])
def test_only_exact_locked_release_text_probe_build_is_accepted(synthetic, tmp_path, change):
    art, receipt, artifact_ref = synthetic
    argv = receipt['process']['argv']
    if change == 'unlocked':
        argv.remove('--locked')
    elif change == 'wrong-order':
        argv[4:6] = ['--release', '--locked']
    elif change == 'runtime-build':
        del argv[-2:]
    elif change == 'benchmark':
        argv[-2:] = ['--example', 'benchmark']
    elif change == 'other-manifest':
        argv[3] = str(tmp_path / 'other/Cargo.toml')
    else:
        argv.extend(['--target-dir', str(tmp_path / 'other-target')])
    with pytest.raises(ValueError, match='exact compile contract'):
        fixture.verify_fixture(art, receipt, artifact_ref)


@pytest.mark.parametrize('exit_code', [1, None])
def test_unsuccessful_compile_is_rejected(synthetic, exit_code):
    art, receipt, artifact_ref = synthetic
    receipt['process']['exit'] = exit_code
    with pytest.raises(ValueError, match='exact compile contract'):
        fixture.verify_fixture(art, receipt, artifact_ref)


@pytest.mark.parametrize('name', ['binary', 'wheel', 'probe', 'example', 'runtime'])
def test_missing_bound_file_is_rejected(synthetic, name):
    art, receipt, artifact_ref = synthetic
    ref = (art[name] if name in ('binary', 'wheel') else receipt['probe'] if name == 'probe'
           else receipt['source_bindings'][name])
    Path(ref['path']).unlink()
    with pytest.raises(FileNotFoundError):
        fixture.verify_fixture(art, receipt, artifact_ref)


def test_probe_must_be_in_delivery_binary_parent_examples(synthetic, tmp_path):
    art, receipt, artifact_ref = synthetic
    external_probe = tmp_path / 'external/examples/text_probe.exe'
    external_probe.parent.mkdir(parents=True)
    external_probe.write_bytes(b'probe')
    receipt['probe'] = artifacts.binding(external_probe)
    with pytest.raises(ValueError, match='exact compile contract'):
        fixture.verify_fixture(art, receipt, artifact_ref)


@pytest.mark.parametrize('name', ['example', 'runtime'])
def test_sources_must_be_in_archived_source_even_when_bytes_match(synthetic, tmp_path, name):
    art, receipt, artifact_ref = synthetic
    external_source = tmp_path / ('external-' + name + '.rs')
    external_source.write_bytes(Path(receipt['source_bindings'][name]['path']).read_bytes())
    receipt['source_bindings'][name] = artifacts.binding(external_source)
    with pytest.raises(ValueError, match='source escaped archive'):
        fixture.verify_fixture(art, receipt, artifact_ref)


@pytest.mark.parametrize('change', ['outside', 'other-inside', 'unverified', 'retry'])
def test_target_must_match_verified_artifact_target_without_retries(synthetic, tmp_path, change):
    art, receipt, artifact_ref = synthetic
    proc = receipt['process']
    if change == 'outside':
        proc['environment']['CARGO_TARGET_DIR'] = str(tmp_path / 'external-target')
    elif change == 'other-inside':
        proc['environment']['CARGO_TARGET_DIR'] = str(Path(art['directory']) / 'other-target')
    elif change == 'unverified':
        proc['child_cargo_target_explicit'] = False
    else:
        proc['retries'] = 1
    with pytest.raises(ValueError, match='exact compile contract'):
        fixture.verify_fixture(art, receipt, artifact_ref)


@pytest.mark.parametrize('field,value', [
    ('status', 'FAIL'), ('source_commit', 'b' * 40), ('retries', 1), ('FULL_queries', 1),
    ('delivery_artifacts_unchanged', False), ('benchmark_build_or_execution', True),
    ('runtime_or_delivery_rebuild_requested', True),
])
def test_fixture_cannot_claim_queries_rebuilds_retries_or_changed_delivery(synthetic, field, value):
    art, receipt, artifact_ref = synthetic
    receipt[field] = value
    with pytest.raises(ValueError, match='fixture provenance'):
        fixture.verify_fixture(art, receipt, artifact_ref)
