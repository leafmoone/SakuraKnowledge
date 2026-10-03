import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools import p4_full_acceptance as acceptance
from tools import p4_full_build as build
from tools import p4_full_preflight as full


class Tokenizer:
    truncation = padding = None

    def encode(self, text, *, add_special_tokens=False):
        spans = [(i, i + 1) for i, char in enumerate(text) if not char.isspace()]
        return SimpleNamespace(ids=[1] * (len(spans) + (2 if add_special_tokens else 0)), offsets=spans)


class Encoder:
    fault = None

    def encode(self, texts):
        result = np.zeros((len(texts), 4), dtype=np.float32)
        result[:, 0] = 1
        counts = [len(Tokenizer().encode(text, add_special_tokens=True).ids) for text in texts]
        if self.fault == 'nonfinite':
            result[0, 0] = np.nan
        elif self.fault == 'norm':
            result[0, 0] = 2
        elif self.fault == 'dtype':
            result = result.astype(np.float64)
        elif self.fault == 'shape':
            result = result[:, :2]
        elif self.fault == 'tokens':
            counts[0] += 1
        elif self.fault == 'encode':
            raise RuntimeError('synthetic encoder failure')
        elif self.fault == 'parity':
            result[:, 0], result[:, 1] = 0, 1
        return result, counts


class Index:
    def __init__(self):
        self.keys = []
        self.fault = None
        self.closed = False

    def __len__(self):
        return len(self.keys)

    def add(self, keys, vectors, **kwargs):
        if self.fault == 'add':
            raise RuntimeError('synthetic ANN add failure')
        self.keys.extend(int(key) for key in keys)
        if self.fault == 'duplicate':
            self.keys[-1] = self.keys[0]
        elif self.fault == 'missing':
            self.keys.pop()

    def save(self, path):
        if self.fault == 'save':
            raise RuntimeError('synthetic ANN save failure')
        build.save_new(path, self.keys)

    def view(self, path):
        self.keys = build.read_json(path)
        if self.fault == 'reload':
            self.keys.pop()

    def reset(self):
        self.closed = True


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    declaration = copy.deepcopy(full.DECLARATIONS)
    declaration['encoder']['dimension'] = 4
    documents = [{'document_id': i, 'entry_id': i, 'entry_key': {'kind': 'subject',
                  'namespace': 'bangumi.subject', 'value': str(i)}, 'source_family': 'bangumi',
                  'source_id': 'synthetic', 'evidence_id': str(i), 'title': f'doc {i}',
                  'original': 'x' * (450 if i == 20 else 10)} for i in range(1, 21)]
    digest, n = hashlib.sha256(), 0
    for doc in documents:
        for row in full.project(doc, Tokenizer(), 'a' * 64):
            digest.update(full.chunks.canonical({**row, 'position': n}) + b'\n')
            n += 1
    count = {'actual_chunks': n, 'documents': 20, 'strata': {'bangumi.subject': 20},
             'streaming_sha256': digest.hexdigest(), 'max_document_text_bytes': 10000}
    monkeypatch.setattr(build, 'index_factory', lambda declaration: Index())
    return documents, declaration, count, tmp_path / 'synthetic'


def run(fixture, encoder=None, index=None, capacity=lambda: None, reference=None, finalize=lambda: None):
    documents, declaration, count, output = fixture
    report = build.new_report()
    report['activation'] = {'output_absent': True, 'lock_absent': True}

    def work():
        report['build'] = build.build_stream(iter(documents), Tokenizer(), 'a' * 64,
            Encoder() if encoder is None else encoder, Index() if index is None else index,
            output, declaration, count, batch_size=3, check_capacity=capacity,
            reference=Encoder() if reference is None else reference, synthetic=True, report=report)
        build.phase(report, 'runtime_manifest_validation')
        artifacts = {}
        for name in ('model', 'tokenizer', 'ort_dll', 'external_data'):
            path = output.parent / name
            path.write_bytes(('synthetic ' + name).encode())
            ref = build.binding(path, output)
            artifacts[name] = [ref] if name == 'external_data' else ref
        for name, filename in (('index', 'vectors.usearch'), ('mapping', 'chunks.sqlite'), ('corpus', 'corpus.jsonl')):
            artifacts[name] = build.binding(output / filename, output)
        snapshot = output.parent / 'snapshot.sqlite'
        snapshot.write_bytes(b'synthetic snapshot')
        canonical = output.parent / acceptance.CANONICAL_PATH
        canonical.parent.mkdir(exist_ok=True)
        canonical.write_bytes(b'{}')
        return build.attach_inventory({'artifacts': artifacts,
            'snapshot': build.binding(snapshot, output),
            'canonical_contract': build.binding(canonical, output.parent)}, output)

    return build.lifecycle(output, report, work, finalize=finalize)


def test_missing_authorization_precedes_every_side_effect(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(full, 'inventory', lambda: pytest.fail('inventory before authorization'))
    with pytest.raises(ValueError, match='future explicit FULL authorization') as error:
        build.execute()
    assert error.value.build_receipt['attempts'] == 0
    assert error.value.build_receipt['phase'] == 'activation'
    assert error.value.build_receipt['status'] == 'FAIL'
    assert list(tmp_path.iterdir()) == []


def test_config_failure_attaches_activation_report(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build, 'authorize', lambda *args, **kwargs: {})
    monkeypatch.setattr(full, 'CONFIG', tmp_path / 'absent.json')
    monkeypatch.setattr(full, 'inventory', lambda: pytest.fail('inventory before config'))
    with pytest.raises(FileNotFoundError) as error:
        build.execute()
    assert error.value.build_receipt['attempts'] == 0
    assert error.value.build_receipt['phase'] == 'activation'
    assert list(tmp_path.iterdir()) == []


def test_hash_mismatch_precedes_parse(tmp_path):
    (tmp_path / 'auth.json').write_bytes(b'invalid JSON')
    with pytest.raises(ValueError, match='authorization hash'):
        build.authorize('auth.json', '0' * 64, fixed_head='b' * 40, root=tmp_path)


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a":NaN}'])
def test_strict_json(tmp_path, raw):
    path = tmp_path / 'bad.json'
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        build.read_json(path)


@pytest.mark.parametrize('fault', ['nonfinite', 'norm', 'dtype', 'shape', 'tokens', 'encode', 'add', 'save',
                                  'count', 'digest', 'census', 'duplicate_document', 'empty', 'stratum', 'disk',
                                  'missing', 'duplicate', 'parity', 'final_guard'])
def test_nineteen_failure_first_lifecycle_cases(fixture, fault):
    documents, _, count, output = fixture
    encoder, index, reference = Encoder(), Index(), Encoder()
    encoder.fault = index.fault = reference.fault = fault
    if fault == 'parity':
        encoder.fault = None
    if fault == 'count':
        count['actual_chunks'] += 1
    elif fault == 'digest':
        count['streaming_sha256'] = '0' * 64
    elif fault == 'census':
        count['documents'] += 1
    elif fault == 'duplicate_document':
        documents[1] = documents[0]
    elif fault == 'empty':
        documents[0].update(title='', original='')
    elif fault == 'stratum':
        documents[0]['entry_key']['kind'] = 'episode'
    checks = 0

    def capacity():
        nonlocal checks
        checks += 1
        if fault == 'disk' and checks == 3:
            raise ValueError('BLOCKED_DISK: synthetic')

    def finalize():
        if fault == 'final_guard':
            raise ValueError('source changed')

    with pytest.raises((ValueError, RuntimeError)) as error:
        run(fixture, encoder, index, capacity, reference, finalize)
    report = build.read_json(output / 'execution-receipt.json')
    assert report['status'] == 'FAIL' and report['attempts'] == 1 and report['retained_partial']
    assert report['error_type'] == type(error.value).__name__
    assert report['error_message'] and report['executor_origin'] == build.EXECUTOR_ORIGIN
    assert not (output / 'manifest.json').exists()
    assert build.attempt_lock(output).exists()
    shutil.rmtree(output)
    with pytest.raises(ValueError, match='no retry'):
        run(fixture)
    assert not output.exists()


def test_atomic_sibling_claim_precedes_mkdir(tmp_path, monkeypatch):
    output = tmp_path / 'pack'
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == output:
            assert build.attempt_lock(output).exists()
            assert build.read_json(build.attempt_lock(output))['attempt'] == 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', mkdir)
    build.reserve(output, build.new_report())
    with pytest.raises(ValueError, match='no overwrite'):
        build.reserve(output, build.new_report())


def test_failure_after_reservation_before_mkdir(tmp_path, monkeypatch):
    output = tmp_path / 'pack'
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == output:
            raise OSError('mkdir failed')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', mkdir)
    with pytest.raises(OSError):
        build.lifecycle(output, build.new_report(), lambda: pytest.fail('work ran'))
    receipt = build.read_json(tmp_path / 'pack.execution-receipt.json')
    assert receipt['attempts'] == 1 and receipt['phase'] == 'reservation'
    assert receipt['retained_partial'] and build.attempt_lock(output).exists()


def test_claim_is_exclusive(tmp_path):
    output = tmp_path / 'pack'
    build.save_new(build.attempt_lock(output), {'attempt': 1})
    before = build.attempt_lock(output).read_bytes()
    with pytest.raises(ValueError, match='no retry'):
        build.reserve(output, build.new_report())
    assert build.attempt_lock(output).read_bytes() == before and not output.exists()


def test_mapping_closed_and_sample_selected_before_embedding(fixture):
    output = fixture[-1]

    def encoder():
        with full.readonly(output / 'chunks.sqlite') as db:
            assert tuple(db.execute('PRAGMA integrity_check').fetchone()) == ('ok',)
        assert (output / 'sample.json').exists()
        assert not (output / 'vectors.npy').exists()
        assert not (output / 'vectors.usearch').exists()
        return Encoder()

    result = run(fixture, encoder=encoder)
    assert result['phases'].index('mapping_readonly_integrity') < result['phases'].index('embedding')
    assert result['phases'].index('sample_reference_parity') < result['phases'].index('ann_construction')


def test_duplicate_chunk_identity_uses_sqlite_unique(fixture, monkeypatch):
    project = full.project

    def collision(*args, **kwargs):
        rows = project(*args, **kwargs)
        for row in rows:
            row['chunk_id'] = 'c' * 64
        return rows

    monkeypatch.setattr(full, 'project', collision)
    with pytest.raises(sqlite3.IntegrityError):
        run(fixture)
    shutil.rmtree(fixture[-1])


def test_ann_readonly_reload_complete_keys(fixture, monkeypatch):
    index = Index()
    index.fault = 'reload'
    monkeypatch.setattr(build, 'index_factory', lambda declaration: index)
    with pytest.raises(ValueError, match='missing ANN'):
        run(fixture)
    assert index.closed
    assert build.read_json(fixture[-1] / 'execution-receipt.json')['phase'] == 'ann_readonly_reload'


def test_sample_deterministic_boundaries_excluded(tmp_path):
    with sqlite3.connect(tmp_path / 'sample.sqlite') as db:
        db.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE)')
        db.executemany('INSERT INTO chunks VALUES (?,?)', ((i, str(i)) for i in range(1500)))
        sample = build.select_sample(db, 1500)
        assert sample == build.select_sample(db, 1500)
        assert len(sample['positions']) == len(set(sample['positions'])) == 1200
        assert len(sample['hash_ranked']) == 1000
        assert not set(sample['hash_ranked']) & (set(sample['first']) | set(sample['last']))
        with pytest.raises(ValueError, match='1200'):
            build.select_sample(db, 100)


def test_twenty_documents_full_lifecycle_inventory_and_mapping(fixture):
    result = run(fixture)
    output = fixture[-1]
    assert result['build']['documents'] == 20
    assert result['status'] == 'BUILD_COMPLETE_WAITING_REVIEW'
    manifest = build.read_json(output / 'manifest.json')
    assert set(manifest['artifacts']) == acceptance.ARTIFACTS
    records = manifest['inventory']
    assert records == sorted(records, key=lambda r: (r['path'], r['artifact']))
    assert manifest['inventory_sha256'] == hashlib.sha256(full.chunks.canonical(records)).hexdigest()
    assert manifest['FULL_SEMANTIC_PACK_SHA256'] == manifest['inventory_sha256']
    assert {r['artifact'] for r in records if r['role'] == 'build_only'} == {'vectors.npy', 'sample.json'}
    assert {r['artifact'] for r in records if r['role'] == 'runtime_required'} == acceptance.ARTIFACTS | {'snapshot', 'canonical'}
    assert len({r['path'] for r in records}) == len(records)
    assert not any(manifest['transient_existence'].values())
    receipt = build.read_json(output / 'execution-receipt.json')
    assert receipt['artifact_existence']['manifest.json']
    assert receipt['receipt_binding']['role'] == 'build_only'
    assert receipt['ann_build_seconds'] >= 0
    assert receipt['ann_binding'] == build.binding(output / 'vectors.usearch', output)
    with full.readonly(output / 'chunks.sqlite') as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(chunks)')}
        assert columns == {'position', 'chunk_id', 'document_id', 'entry_id', 'kind', 'namespace', 'value',
                           'source_id', 'evidence_id', 'text_sha256', 'token_start', 'token_end', 'metadata'}
        assert [r[2] for r in db.execute('PRAGMA index_info(chunks_document_id)')] == ['document_id']
        assert [r[2] for r in db.execute('PRAGMA index_info(chunks_typedkey)')] == ['kind', 'namespace', 'value']
        metadata = db.execute('SELECT metadata FROM chunks ORDER BY position DESC LIMIT 1').fetchone()[0]
        assert json.loads(metadata)['document_id'] == 20
    assert len((output / 'corpus.jsonl').read_text().splitlines()) == 20
    assert build.attempt_lock(output).exists()
    shutil.rmtree(output)


def test_runtime_rejects_build_only(fixture):
    run(fixture)
    output = fixture[-1]
    manifest = build.read_json(output / 'manifest.json')
    manifest['artifacts']['vectors'] = build.binding(output / 'vectors.npy', output)
    with pytest.raises(ValueError, match='exact FULL artifact'):
        build.attach_inventory(manifest, output)


def test_actual_validator_pilot_mixed_and_strict_seven(fixture, monkeypatch):
    run(fixture)
    _, declaration, count, output = fixture
    root = output.parent
    config_path = root / acceptance.CANONICAL_PATH
    snapshot = root / 'snapshot.sqlite'
    config = {'schema': 'p4-full-semantic-contract-v1', 'declarative_contract': declaration,
              'snapshot': build.binding(snapshot, root)}
    config_path.unlink()
    build.save_new(config_path, config)
    monkeypatch.setattr(acceptance, 'ROOT', root)
    monkeypatch.setattr(acceptance, 'CONFIG', config_path)
    monkeypatch.setattr(acceptance, 'validate_contract', lambda value: declaration if value == config else None)
    pilot_root = (root / full.pilot.PACK).parent
    pilot_root.mkdir(parents=True)
    artifacts = build.read_json(output / 'manifest.json')['artifacts']
    refs = {name: ([build.binding(root / name, pilot_root)] if name == 'external_data'
                  else build.binding(root / name, pilot_root)) for name in ('model', 'tokenizer', 'ort_dll', 'external_data')}
    monkeypatch.setattr(acceptance.pilot, 'DLL_SIZE', artifacts['ort_dll']['size'])
    monkeypatch.setattr(acceptance.pilot, 'DLL_SHA', artifacts['ort_dll']['sha256'])
    value = build.manifest(config, {'pack': {'artifacts': refs}}, output, count['actual_chunks'])
    assert value['pack_version'] == 'p4-full-semantic-v1'
    assert acceptance.validate_full_manifest(value, config, pack_root=output) == count['actual_chunks']
    value['lexical_metadata'] = {}
    with pytest.raises(ValueError, match='pilot sidecar'):
        acceptance.validate_full_manifest(value, config, pack_root=output)
    del value['lexical_metadata']
    value['artifacts']['vectors'] = build.binding(output / 'vectors.npy', output)
    with pytest.raises(ValueError, match='exact FULL artifact'):
        acceptance.validate_full_manifest(value, config, pack_root=output)


@pytest.mark.parametrize('version', ['generated', 'missing', 'empty'])
def test_real_rust_manifest_pack_version_gate(fixture, monkeypatch, version):
    configured = os.environ.get('SKNOW_RS_TEST_BIN')
    if not configured:
        pytest.skip('Rust manifest integration NOT_RUN: set SKNOW_RS_TEST_BIN explicitly')
    binary = Path(configured).resolve(strict=True)
    repository = Path(__file__).resolve().parents[1]
    config = build.read_json(repository / acceptance.CANONICAL_PATH)
    # FULL pins the real snapshot's identity/size/hash. A small synthetic DB cannot
    # pass that authority: prove manifest validation, then stop at file-size checks.
    with tempfile.TemporaryDirectory(prefix='p4-manifest-fixture-', dir=repository / 'build') as directory:
        root = Path(directory)
        monkeypatch.setattr(build, 'ROOT', root)
        documents, declaration, count, _ = fixture
        output = root / 'synthetic-pack'
        run((documents, declaration, count, output))
        snapshot = root / 'synthetic-snapshot.sqlite'
        with closing(sqlite3.connect(snapshot)) as db, db:
            db.execute('CREATE TABLE fixture(value TEXT)')
            db.execute("INSERT INTO fixture VALUES ('synthetic')")
        canonical = root / acceptance.CANONICAL_PATH
        canonical.write_bytes((repository / acceptance.CANONICAL_PATH).read_bytes())
        pilot_root = (root / full.pilot.PACK).parent
        pilot_root.mkdir(parents=True)
        refs = {name: ([build.binding(root / name, pilot_root)] if name == 'external_data'
                      else build.binding(root / name, pilot_root))
                for name in ('model', 'tokenizer', 'ort_dll', 'external_data')}
        synthetic_config = copy.deepcopy(config)
        synthetic_config['snapshot']['path'] = snapshot.name
        value = build.manifest(synthetic_config, {'pack': {'artifacts': refs}}, output, count['actual_chunks'])
        assert value['pack_version'] == 'p4-full-semantic-v1'
        # These are declaration-only authority claims, not authenticated assets.
        value['snapshot'].update(identity=config['snapshot']['path'],
                                 size=config['snapshot']['size'], sha256=config['snapshot']['sha256'])
        value['artifacts']['ort_dll'].update(size=full.pilot.DLL_SIZE, sha256=full.pilot.DLL_SHA)
        if version == 'missing':
            del value['pack_version']
        elif version == 'empty':
            value['pack_version'] = ' '
        manifest_path = output / 'rust-gate-manifest.json'
        build.save_new(manifest_path, value)
        env = os.environ.copy()
        if os.name == 'nt':
            env['PATH'] = 'C:/msys64/ucrt64/bin' + os.pathsep + env.get('PATH', '')
        command = [str(binary), 'retrieve', str(snapshot), str(manifest_path), 'synthetic']
        result = subprocess.run(command, env=env, capture_output=True, timeout=30, check=False)
        assert result.returncode == 1, (command, result.returncode, result.stderr)
        assert result.stdout == b''
        error = json.loads(result.stderr)
        assert error['error'] == 'SemanticError'
        expected = 'artifact file size mismatch' if version == 'generated' else 'missing/nontext pack_version'
        assert error['message'] == expected, (command, error)
        print(f'Rust manifest gate: command={command!r}; exit={result.returncode}; message={error["message"]}')
        # This is not full runtime compatibility: no snapshot/mapping/corpus read,
        # tokenizer/model loading, retrieval, GPU, or formal FULL execution occurs.


def test_synthetic_entry_complete_orchestration(tmp_path, monkeypatch):
    validator = acceptance.validate_full_manifest
    calls = []

    def validate(*args, **kwargs):
        calls.append(validator(*args, **kwargs))
        return calls[-1]

    monkeypatch.setattr(acceptance, 'validate_full_manifest', validate)
    report = build.synthetic_run(tmp_path)
    assert calls == [report['build']['chunks']]
    assert report['manifest_validator'] == 'actual_FULL_validator_with_synthetic_authorities'
    assert report['synthetic'] and report['build']['documents'] == 20
    assert report['phases'][0] == 'reservation' and report['phases'][-1] == 'complete'
    assert 'runtime_manifest_validation' in report['phases']
    assert build.attempt_lock(tmp_path / 'synthetic-pack').exists()
    assert (tmp_path / 'synthetic-pack/manifest.json').exists()


def test_create_new_never_overwrites(tmp_path):
    path = tmp_path / 'receipt.json'
    build.save_new(path, {'status': 'FAIL'})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        build.save_new(path, {'status': 'PASS'})
    assert path.read_bytes() == before


@pytest.mark.parametrize('fault', [np.nan, 2.0])
def test_all_saved_vectors_validated_before_ann(fixture, monkeypatch, fault):
    original = np.load

    def load(path, **kwargs):
        with_mapping = original(path, mmap_mode='r+', allow_pickle=False)
        with_mapping[-1, 0] = fault
        build.close_memmap(with_mapping)
        return original(path, **kwargs)

    monkeypatch.setattr(np, 'load', load)
    monkeypatch.setattr(build, 'select_sample', lambda *args, **kwargs: {'positions': [0]})
    with pytest.raises(ValueError):
        run(fixture, index=lambda: pytest.fail('ANN initialized before whole-vector scan'))
    receipt = build.read_json(fixture[-1] / 'execution-receipt.json')
    assert receipt['phase'] == 'whole_vector_validation' and receipt['completed_ann'] == 0


def test_optional_telemetry_failure_and_view_cleanup(fixture, monkeypatch):
    class BrokenTelemetry(Index):
        @property
        def memory_usage(self):
            raise RuntimeError('optional memory telemetry failure')

        @property
        def hardware_acceleration(self):
            raise RuntimeError('optional acceleration telemetry failure')

    index, reopened = BrokenTelemetry(), Index()
    monkeypatch.setattr(build, 'index_factory', lambda declaration: reopened)
    report = run(fixture, index=index)
    assert report['status'] == 'BUILD_COMPLETE_WAITING_REVIEW'
    assert report['telemetry']['memory_usage'] == 'NOT_AVAILABLE'
    assert report['telemetry']['hardware_acceleration'] == 'NOT_AVAILABLE'
    assert index.closed and reopened.closed
    shutil.rmtree(fixture[-1])


def test_close_index_best_effort_attempts_both():
    calls = []

    class Owner:
        def reset(self):
            calls.append('reset')
            raise RuntimeError('reset failed')

        def close(self):
            calls.append('close')

    build.close_index(Owner())
    assert calls == ['reset', 'close']


@pytest.fixture
def activation(fixture, monkeypatch):
    _, declaration, count, output = fixture
    root = output.parent
    monkeypatch.setattr(acceptance, 'ROOT', root)
    monkeypatch.setattr(build, 'OUTPUT', output.name)
    snapshot = root / 'snapshot.sqlite'
    snapshot.write_bytes(b'synthetic snapshot')
    config = {'snapshot': build.binding(snapshot, root), 'declarative_contract': declaration}
    source = {'tools/p4_full_preflight.py': {'git_blob': 'd' * 40}}
    source_sha = full.exact.canonical_hash(source)
    auth = {'count_review': {'expected_sha256': 'a' * 64, 'expected_capture_sha256': 'b' * 64},
            'disk_review': {'expected_sha256': 'c' * 64}, 'smoke_review': {},
            'preflight_producer_sha': 'b' * 40, 'preflight_evidence_sha': 'c' * 40,
            'reviewed_source_bindings': dict.fromkeys(('count', 'disk', 'smoke'), source_sha)}
    verified = {'inventory_sha256': 'e' * 64, 'bindings': {},
                'pack': {'artifacts': {'ort_dll': {}}}, 'model': {'asset_directory': str(root)},
                'contract': {}, 'job': {'threads': 1, 'batch_size': 3},
                'manifest': {'tokenizer_inventory_sha256': 'a' * 64}}

    @contextmanager
    def config_guard(value):
        yield

    @contextmanager
    def source_guard(*args):
        args[-1].update(source_inventory=source, source_inventory_sha256=source_sha)
        yield

    def reviewed(auth_value, config_value, verified_value, report, root_value):
        assert auth_value == auth and config_value == config and verified_value is verified and root_value == root
        assert report['source_inventory'] == source
        common = {'source_inventory': source, 'source_inventory_sha256': source_sha,
                  'inventory_sha256': verified['inventory_sha256'], 'count_receipt_sha256': 'a' * 64}
        disk = {**common, 'schema': 'p4-full-reviewed-disk-v1', 'status': 'DISK_PASS', 'disk': {},
                'count_capture_sha256': 'b' * 64}
        smoke = {**common, 'schema': 'p4-full-phase12-preflight-v1', 'status': 'READY_FOR_BUILD_REVIEW',
                 'gates': 'PASS', 'disk_receipt_sha256': 'c' * 64}
        return count, disk, smoke

    monkeypatch.setattr(full, 'config_guard', config_guard)
    monkeypatch.setattr(full, 'source_guard', source_guard)
    monkeypatch.setattr(full, 'assert_no_product', lambda root: None)
    monkeypatch.setattr(full, 'check_components', lambda output: None)
    monkeypatch.setattr(full, 'contained', lambda path: Path(path) if Path(path).is_absolute() else root / path)
    monkeypatch.setattr(full, 'inventory', lambda: verified)
    monkeypatch.setattr(build, 'reviewed_preflight', reviewed)
    monkeypatch.setattr(build, 'validate_activation_dll', lambda verified: None)
    monkeypatch.setattr(full, 'disk_capacity', lambda disk: {'status': 'PASS'})
    import torch
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: True)
    monkeypatch.setattr(torch.cuda, 'device_count', lambda: 1)
    monkeypatch.setattr(build, 'authorize', lambda *args, **kwargs: auth)
    monkeypatch.setattr(build, 'read_json', lambda path: config)
    monkeypatch.setattr(full, 'validate_contract', lambda value: None)
    return config, snapshot, output


@pytest.mark.parametrize('failure_exit', [1, 2, 3])
def test_execute_outer_guard_exit_before_terminal(fixture, activation, monkeypatch, failure_exit):
    documents = fixture[0]
    _, _, output = activation
    exits = 0

    @contextmanager
    def config_guard(value):
        nonlocal exits
        yield
        exits += 1
        if exits == failure_exit:
            raise ValueError('late outer config guard')

    monkeypatch.setattr(full, 'config_guard', config_guard)
    monkeypatch.setattr(full.exact, 'frozen_tokenizers', lambda path: (Tokenizer(), None))
    monkeypatch.setattr(full, 'readonly', lambda path: sqlite3.connect(':memory:'))
    monkeypatch.setattr(full, 'documents', lambda conn: (doc for doc in documents))
    monkeypatch.setattr(build, 'build_stream', lambda *args, **kwargs: {})
    monkeypatch.setattr(build, 'manifest', lambda *args: {'synthetic': True})
    monkeypatch.setattr(acceptance, 'validate_full_manifest', lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='late outer config guard') as error:
        build.execute(fixed_head='a' * 40)
    report = error.value.build_receipt
    assert report['status'] == 'FAIL' and not (output / 'manifest.json').exists()
    if failure_exit == 1:
        assert report['attempts'] == 0 and not build.attempt_lock(output).exists()
    else:
        receipt = json.loads((output / 'execution-receipt.json').read_bytes())
        assert receipt['attempts'] == 1 and receipt['status'] == 'FAIL'
        assert receipt['error_message'] == 'late outer config guard'


@pytest.mark.parametrize('fault', ['snapshot_size', 'snapshot_sha', 'disk'])
def test_execute_activation_gate_precedes_reservation(activation, monkeypatch, fault):
    config, snapshot, output = activation
    if fault == 'snapshot_size':
        config['snapshot']['size'] += 1
    elif fault == 'snapshot_sha':
        config['snapshot']['sha256'] = '0' * 64
    else:
        monkeypatch.setattr(full, 'disk_capacity', lambda disk: {'status': 'BLOCKED_DISK'})
    monkeypatch.setattr(build, 'lifecycle', lambda *args, **kwargs: pytest.fail('lifecycle before gate'))
    monkeypatch.setattr(build, 'reserve', lambda *args: pytest.fail('reservation before gate'))
    before = snapshot.read_bytes()
    message = 'BLOCKED_DISK' if fault == 'disk' else 'activation snapshot size/SHA mismatch'
    with pytest.raises(ValueError, match=message) as error:
        build.execute(fixed_head='a' * 40)
    report = error.value.build_receipt
    assert report['attempts'] == 0 and report['status'] == 'FAIL' and report['phase'] == 'activation'
    assert not output.exists() and not build.attempt_lock(output).exists()
    assert snapshot.read_bytes() == before
    assert not output.with_name(output.name + '.execution-receipt.json').exists()


def test_execute_actual_contract_mismatch_precedes_orchestration(tmp_path, monkeypatch):
    config = copy.deepcopy(build.read_json(full.CONFIG))
    assert full.validate_contract(config) == full.DECLARATIONS
    config['declarative_contract']['encoder']['dimension'] += 1
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build, 'authorize', lambda *args, **kwargs: {})
    monkeypatch.setattr(build, 'read_json', lambda path: config)
    monkeypatch.setattr(build, '_execute', lambda *args: pytest.fail('orchestration before contract'))
    monkeypatch.setattr(build, 'lifecycle', lambda *args, **kwargs: pytest.fail('lifecycle before contract'))
    monkeypatch.setattr(build, 'reserve', lambda *args: pytest.fail('reservation before contract'))
    with pytest.raises(ValueError, match='FULL contract mismatch') as error:
        build.execute(fixed_head='a' * 40)
    report = error.value.build_receipt
    assert report['attempts'] == 0 and report['status'] == 'FAIL' and report['phase'] == 'activation'
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('existing', ['output', 'lock'])
def test_reserve_existing_state_preserved_without_attempt(tmp_path, existing):
    output = tmp_path / 'synthetic'
    target = output if existing == 'output' else build.attempt_lock(output)
    target.write_bytes(b'pre-existing sentinel')
    report = build.new_report()
    report['output'] = str(output)
    before = target.read_bytes()
    with pytest.raises(ValueError, match='no overwrite' if existing == 'output' else 'no retry'):
        build.reserve(output, report)
    assert report['attempts'] == 0 and target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_duplicate_mapping_positions_use_sqlite_primary_key(fixture, monkeypatch):
    output = fixture[-1]
    original = build.phase

    def phase(report, name):
        original(report, name)
        if name == 'mapping_readonly_integrity':
            with sqlite3.connect(output / 'chunks.sqlite') as db:
                db.execute('UPDATE chunks SET position=0 WHERE position=1')

    monkeypatch.setattr(build, 'phase', phase)
    with pytest.raises(sqlite3.IntegrityError, match='UNIQUE constraint failed: chunks.position') as error:
        run(fixture, encoder=lambda: pytest.fail('encoder ran with duplicate positions'))
    receipt = build.read_json(output / 'execution-receipt.json')
    assert receipt['attempts'] == 1 and receipt['status'] == 'FAIL'
    assert receipt['phase'] == 'mapping_readonly_integrity' and receipt['completed_embeddings'] == 0
    assert error.value.build_receipt == receipt
    assert build.attempt_lock(output).exists() and not (output / 'manifest.json').exists()


@pytest.mark.parametrize('fault', ['write', 'fsync'])
def test_lock_io_failure_consumes_attempt_without_mkdir(tmp_path, monkeypatch, fault):
    output = tmp_path / 'synthetic'
    lock = build.attempt_lock(output)
    report = build.new_report()
    original_mkdir = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == output:
            pytest.fail('output mkdir after failed lock persistence')
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'mkdir', mkdir)
    if fault == 'fsync':
        original_fsync = build.os.fsync
        calls = 0

        def fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('synthetic lock fsync failure')
            return original_fsync(fd)

        monkeypatch.setattr(build.os, 'fsync', fsync)
    else:
        original_open = Path.open

        @contextmanager
        def open_lock(path, *args, **kwargs):
            with original_open(path, *args, **kwargs) as stream:
                if path == lock and args == ('xb',):
                    yield SimpleNamespace(write=lambda data: (_ for _ in ()).throw(
                        OSError('synthetic lock write failure')))
                else:
                    yield stream

        monkeypatch.setattr(Path, 'open', open_lock)
    with pytest.raises(OSError, match=f'synthetic lock {fault} failure') as error:
        build.lifecycle(output, report, lambda: pytest.fail('work after failed lock persistence'))
    assert report['attempts'] == 1 and report['status'] == 'FAIL' and report['phase'] == 'reservation'
    assert error.value.build_receipt is report
    assert lock.exists() and not output.exists()
    assert output.with_name(output.name + '.execution-receipt.json').exists()
    with pytest.raises(ValueError, match='no retry'):
        build.reserve(output, build.new_report())


@pytest.mark.parametrize('fault', ['valid', 'extra', 'missing', 'schema', 'operation', 'head', 'output',
                                  'attempts_bool', 'attempts_two', 'closure_missing', 'closure_extra',
                                  'source_digest', 'git_source'])
def test_authorization_exact_fields_policy_and_source_closure(tmp_path, monkeypatch, fault):
    head = 'b' * 40
    names = ('tools/p4_full_build.py', 'tests/test_p4_full_build.py',
             'docs/p4-full-semantic-v1.md', 'docs/STAGE_STATUS.md', 'rust/src/semantic.rs',
             'tools/p4_full_acceptance.py', 'tests/test_p4_full_acceptance.py')
    bindings = {}
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic source')
        bindings[name] = full.exact.sha(path)
    value = {'schema': build.AUTH_SCHEMA, 'operation': 'execute_full', 'fixed_code_sha': head,
             'preflight_producer_sha': 'c' * 40, 'preflight_evidence_sha': 'd' * 40,
             'reviewed_source_bindings': dict.fromkeys(('count', 'disk', 'smoke'), 'e' * 64),
             'output': build.OUTPUT, 'max_attempts': 1, 'count_review': {}, 'disk_review': {},
             'smoke_review': {}, 'executor_bindings': bindings}
    if fault == 'extra':
        value['extra'] = True
    elif fault == 'missing':
        del value['smoke_review']
    elif fault in ('schema', 'operation', 'output'):
        value[fault] = 'wrong'
    elif fault == 'head':
        value['fixed_code_sha'] = 'c' * 40
    elif fault in ('attempts_bool', 'attempts_two'):
        value['max_attempts'] = True if fault == 'attempts_bool' else 2
    elif fault == 'closure_missing':
        del bindings[names[0]]
    elif fault == 'closure_extra':
        bindings['extra.py'] = 'a' * 64
    elif fault == 'source_digest':
        bindings[names[0]] = '0' * 64
    git_calls = []

    def git(command, **kwargs):
        git_calls.append(command)
        return ('different' if fault == 'git_source' and command[1] == 'rev-parse' else 'same') + '\n'

    monkeypatch.setattr(build.subprocess, 'check_output', git)
    path = tmp_path / 'auth.json'
    build.save_new(path, value)
    digest = full.exact.sha(path)
    if fault == 'valid':
        assert build.authorize('auth.json', digest, fixed_head=head, root=tmp_path) == value
        assert len(git_calls) == 14
        assert all(command[2].startswith(head + ':') for command in git_calls if command[1] == 'rev-parse')
    else:
        message = ('exact future authorization fields' if fault in ('extra', 'missing') else
                   'executor source closure' if fault.startswith('closure_') else
                   'executor source changed' if fault == 'source_digest' else
                   'executor does not match fixed Git source' if fault == 'git_source' else
                   'future authorization policy mismatch')
        with pytest.raises(ValueError, match=message):
            build.authorize('auth.json', digest, fixed_head=head, root=tmp_path)
    assert not (tmp_path / build.OUTPUT).exists()


@pytest.mark.parametrize('fault', ['snapshot_changed', 'snapshot_hash', 'receipt_write', 'receipt_fsync', 'work_and_terminal'])
def test_terminal_failures_never_publish_complete(tmp_path, monkeypatch, fault):
    output, snapshot = tmp_path / 'pack', tmp_path / 'snapshot.sqlite'
    snapshot.write_bytes(b'original snapshot')
    report = build.new_report()
    report['activation'] = {'snapshot': build.binding(snapshot, tmp_path)}
    original_binding, original_save, original_fsync = build.binding, build.save_new, build.os.fsync
    terminal_started = False
    original_terminal = build.terminal

    def terminal(*args, **kwargs):
        nonlocal terminal_started
        terminal_started = True
        return original_terminal(*args, **kwargs)

    def binding(path, directory):
        if terminal_started and Path(path) == snapshot and fault in ('snapshot_hash', 'work_and_terminal'):
            raise OSError('synthetic terminal hash failure')
        return original_binding(path, directory)

    def save(path, value):
        if Path(path).name.startswith('execution-receipt.json') and fault == 'receipt_write':
            raise OSError('synthetic terminal write failure')
        return original_save(path, value)

    def fsync(fd):
        if terminal_started and fault == 'receipt_fsync':
            raise OSError('synthetic terminal fsync failure')
        return original_fsync(fd)

    def work():
        if fault == 'snapshot_changed':
            snapshot.write_bytes(b'changed snapshot')
        if fault == 'work_and_terminal':
            raise RuntimeError('primary work failure')
        return {'synthetic': True}

    monkeypatch.setattr(build, 'terminal', terminal)
    monkeypatch.setattr(build, 'binding', binding)
    monkeypatch.setattr(build, 'save_new', save)
    monkeypatch.setattr(build.os, 'fsync', fsync)
    with pytest.raises((ValueError, OSError, RuntimeError)) as error:
        build.lifecycle(output, report, work, snapshot=snapshot)
    assert error.value.build_receipt is report
    assert report['status'] == 'FAIL' and report['attempts'] == 1 and report['retained_partial']
    assert report['terminal_error'] and report['phase'] != 'complete' and 'complete' not in report['phases']
    assert build.attempt_lock(output).exists()
    if fault in ('snapshot_changed', 'snapshot_hash', 'work_and_terminal'):
        published = build.read_json(output / 'execution-receipt.json')
        assert published['status'] == 'FAIL' and published['retained_partial']
        assert published['snapshot_after_hash_status'] == ('CHANGED' if fault == 'snapshot_changed' else 'HASH_FAILED')
    if fault == 'work_and_terminal':
        assert isinstance(error.value, RuntimeError) and isinstance(error.value.__cause__, OSError)
        assert report['error_message'] == 'primary work failure'
        assert not (output / 'manifest.json').exists()
    shutil.rmtree(output)
    with pytest.raises(ValueError, match='no retry'):
        build.reserve(output, build.new_report())


@pytest.mark.parametrize('fault', ['chunks_positions', 'projection_positions', 'metadata', 'join'])
def test_readonly_mapping_audits_actual_closure(fixture, monkeypatch, fault):
    output, n = fixture[-1], fixture[2]['actual_chunks']
    original_phase, original_verify = build.phase, build.verify_mapping
    audited = []

    def phase(report, name):
        original_phase(report, name)
        if name == 'mapping_readonly_integrity':
            with sqlite3.connect(output / 'chunks.sqlite') as db:
                if fault in ('chunks_positions', 'projection_positions'):
                    table = 'chunks' if fault == 'chunks_positions' else 'projection'
                    db.execute(f'UPDATE {table} SET position=? WHERE position=1', (n + 1,))
                elif fault == 'metadata':
                    db.execute("UPDATE chunks SET metadata='{}' WHERE position=1")
                else:
                    rows = db.execute('SELECT row_json FROM projection WHERE position IN (0,1) ORDER BY position').fetchall()
                    db.execute('UPDATE projection SET row_json=? WHERE position=0', rows[1])
                    db.execute('UPDATE projection SET row_json=? WHERE position=1', rows[0])

    def verify(db, *args):
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute("UPDATE chunks SET metadata='{}' WHERE position=0")
        audited.append(True)
        return original_verify(db, *args)

    monkeypatch.setattr(build, 'phase', phase)
    monkeypatch.setattr(build, 'verify_mapping', verify)
    message = 'mapping positions mismatch' if fault.endswith('positions') else 'mapping corpus/projection closure mismatch'
    with pytest.raises(ValueError, match=message):
        run(fixture, encoder=lambda: pytest.fail('encoder before mapping closure'))
    assert audited == [True]
    receipt = build.read_json(output / 'execution-receipt.json')
    assert receipt['status'] == 'FAIL' and receipt['phase'] == 'mapping_readonly_integrity'
    assert receipt['completed_embeddings'] == receipt['completed_ann'] == 0
    assert not (output / 'sample.json').exists() and not (output / 'manifest.json').exists()


@pytest.mark.parametrize('fault', ['valid', 'historical_source_changed', 'evidence_bytes_mismatch', 'unknown_producer'])
def test_reviewed_preflight_distinct_authenticated_provenance(tmp_path, monkeypatch, fault):
    executor, producer, evidence = 'a' * 40, 'b' * 40, 'c' * 40
    names = set(full.SOURCE_PATHS) | (build.EXECUTOR_PATHS - {'docs/STAGE_STATUS.md'})
    blobs = {name: hashlib.sha1(name.encode()).hexdigest() for name in names}
    contents = {name: ('historical ' + name).encode() for name in names}
    source = {name: {'git_blob': blobs[name], 'index_git_blob': blobs[name],
                    'checkout_git_filtered_blob': blobs[name], 'size': len(contents[name]),
                    'sha256': hashlib.sha256(contents[name]).hexdigest(),
                    'checkout_size': len(contents[name]), 'checkout_sha256': hashlib.sha256(contents[name]).hexdigest()}
              for name in names}
    source_sha = full.exact.canonical_hash(source)
    current = copy.deepcopy(source)
    current['tools/p4_full_build.py']['git_blob'] = 'd' * 40
    if fault == 'historical_source_changed':
        current['tools/p4_full_preflight.py']['git_blob'] = 'e' * 40
    verified = {'inventory_sha256': 'f' * 64, 'manifest': {'tokenizer_inventory_sha256': 'a' * 64}}
    count = {'pilot_document_ids_sha256': full.exact.canonical_hash([1]),
             'full_only_chunk_references': [{'document_id': 2}]}
    receipts, reviews, published = {}, {}, {}
    for name in ('count', 'disk', 'smoke'):
        receipts[name] = {'source_inventory': source, 'source_inventory_sha256': source_sha,
                          'inventory_sha256': verified['inventory_sha256'],
                          'tokenizer_inventory_sha256': verified['manifest']['tokenizer_inventory_sha256']}
        path = tmp_path / (name + '.json')
        build.save_new(path, receipts[name])
        published[path.name] = path.read_bytes()
        reviews[name + '_review'] = {'path': path.name, 'expected_sha256': full.exact.sha(path)}
    auth = {**reviews, 'fixed_code_sha': executor,
            'preflight_producer_sha': '0' * 40 if fault == 'unknown_producer' else producer,
            'preflight_evidence_sha': evidence,
            'reviewed_source_bindings': dict.fromkeys(('count', 'disk', 'smoke'), source_sha)}
    report = {'source_inventory': current, 'fixed_code_sha': executor}
    calls = []

    def git(command, **kwargs):
        calls.append(command)
        assert kwargs['cwd'] == tmp_path
        if command[1] == 'ls-tree':
            if command[-1] != producer:
                raise build.subprocess.CalledProcessError(128, command)
            return b'\0'.join(name.encode() for name in sorted(names)) + b'\0'
        if command[1] == 'rev-parse':
            assert command[2].startswith(producer + ':')
            return blobs[command[2].split(':', 1)[1]] + '\n'
        assert command[1] == 'show'
        revision, name = command[2].split(':', 1)
        if revision == producer:
            return contents[name]
        assert revision == evidence
        return b'changed evidence bytes' if fault == 'evidence_bytes_mismatch' else published[name]

    def load(*, fixed_head, root, path, expected_sha256):
        assert fixed_head == auth['preflight_producer_sha'] and root == tmp_path
        assert full.exact.sha(tmp_path / path) == expected_sha256
        return receipts[Path(path).stem]

    def validate(receipt, config, **kwargs):
        assert receipt is receipts['count']
        assert kwargs == {'fixed_head': producer, 'source_binding': source_sha,
                          'inventory_binding': verified['inventory_sha256']}
        return count

    monkeypatch.setattr(build.subprocess, 'check_output', git)
    monkeypatch.setattr(full, 'load_reviewed_receipt', load)
    monkeypatch.setattr(full, 'validate_count_receipt', validate)
    monkeypatch.setattr(full, 'pilot_inputs', lambda value: ({1}, None, None, None, None))
    if fault == 'valid':
        assert build.reviewed_preflight(auth, {}, verified, report, tmp_path) == (count, receipts['disk'], receipts['smoke'])
        assert report['preflight_provenance'] == {'producer_sha': producer, 'evidence_sha': evidence,
                                                 'reviewed_source_bindings': auth['reviewed_source_bindings']}
        assert executor not in (producer, evidence)
        assert len([command for command in calls if command[1] == 'ls-tree']) == 3
    else:
        error_type = build.subprocess.CalledProcessError if fault == 'unknown_producer' else ValueError
        message = None if fault == 'unknown_producer' else (
            'shared preflight implementation changed' if fault == 'historical_source_changed' else
            'reviewed preflight evidence Git binding mismatch')
        with pytest.raises(error_type, match=message):
            build.reviewed_preflight(auth, {}, verified, report, tmp_path)
        assert 'preflight_provenance' not in report
    assert not (tmp_path / build.OUTPUT).exists()


class SyntheticAbort(BaseException):
    pass


@pytest.mark.parametrize('cancel_type', [KeyboardInterrupt, SystemExit, GeneratorExit, SyntheticAbort])
@pytest.mark.parametrize('where', ['work', 'reserve_after', 'vector_flush'])
def test_cancellation_retains_attempt_and_failure(tmp_path, monkeypatch, cancel_type, where):
    output, report = tmp_path / 'pack', build.new_report()
    cancellation = cancel_type('synthetic cancellation')
    if where == 'reserve_after':
        original, calls = build.os.fsync, 0

        def fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise cancellation
            return original(fd)

        monkeypatch.setattr(build.os, 'fsync', fsync)

    def work():
        (output / 'partial').write_bytes(b'retained')
        if where == 'vector_flush':
            vectors = np.lib.format.open_memmap(output / 'vectors.npy', mode='w+', dtype='float32', shape=(2, 4))
            monkeypatch.setattr(type(vectors), 'flush', lambda self: (_ for _ in ()).throw(cancellation))
            build.close_memmap(vectors)
        raise cancellation

    with pytest.raises(cancel_type) as error:
        build.lifecycle(output, report, work)
    assert error.value is cancellation
    target = output / 'execution-receipt.json' if output.is_dir() else tmp_path / 'pack.execution-receipt.json'
    published = build.read_json(target)
    assert published['status'] == 'FAIL' and published['attempts'] == 1
    assert published['error_type'] == cancel_type.__name__ and published['retained_partial']
    assert build.attempt_lock(output).exists()
    if where != 'reserve_after':
        assert (output / 'partial').read_bytes() == b'retained'
    with pytest.raises(ValueError):
        build.reserve(output, build.new_report())


def test_success_receipt_stage_fsync_failure_has_no_success_bytes(tmp_path, monkeypatch, capsys):
    output, report = tmp_path / 'pack', build.new_report()
    original_save, original_fsync = build.save_new, build.os.fsync
    in_terminal = False

    def save(path, value):
        nonlocal in_terminal
        if str(path).endswith('.staging'):
            in_terminal = True
        return original_save(path, value)

    def fsync(fd):
        if in_terminal:
            raise OSError('stage fsync failed')
        return original_fsync(fd)

    monkeypatch.setattr(build, 'save_new', save)
    monkeypatch.setattr(build.os, 'fsync', fsync)
    with pytest.raises(OSError, match='stage fsync failed'):
        build.lifecycle(output, report, lambda: {'synthetic': True})
    assert report['status'] == 'FAIL' and report['terminal_error_type'] == 'OSError'
    for path in output.iterdir():
        if path.name.startswith('execution-receipt.json'):
            assert b'BUILD_COMPLETE' not in path.read_bytes()
            assert build.read_json(path)['status'] == 'FAIL'
    assert not list(output.glob('*.staging'))
    published = build.read_json(output / 'execution-receipt.json')
    assert published['finalization_errors'][0]['error_type'] == 'OSError'
    accounting = json.loads(capsys.readouterr().err)
    assert accounting['attempts'] == 1 and accounting['status'] == 'FAIL'


def test_cancellation_before_reservation_has_no_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    cancellation = KeyboardInterrupt('activation cancelled')
    monkeypatch.setattr(build, 'authorize', lambda *args, **kwargs: (_ for _ in ()).throw(cancellation))
    with pytest.raises(KeyboardInterrupt) as error:
        build.execute()
    assert error.value is cancellation and error.value.build_receipt['attempts'] == 0
    assert list(tmp_path.iterdir()) == []


def test_original_cancellation_survives_terminal_cancellation(tmp_path, monkeypatch, capsys):
    output, cancellation = tmp_path / 'pack', KeyboardInterrupt('work cancelled')
    original = build.save_new

    def save(path, value):
        if str(path).endswith('.staging'):
            raise SystemExit('terminal cancelled')
        return original(path, value)

    monkeypatch.setattr(build, 'save_new', save)
    with pytest.raises(KeyboardInterrupt) as error:
        build.lifecycle(output, build.new_report(), lambda: (_ for _ in ()).throw(cancellation))
    assert error.value is cancellation and isinstance(error.value.__cause__, SystemExit)
    published = build.read_json(output / 'execution-receipt.json')
    assert published['error_type'] == 'KeyboardInterrupt'
    assert published['finalization_errors'][0]['error_type'] == 'SystemExit'
    accounting = json.loads(capsys.readouterr().err)
    assert accounting['attempts'] == 1 and accounting['error_type'] == 'KeyboardInterrupt'


def test_actual_builder_products_rust_reader_interop(fixture, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    (repository / 'build/p4interopfixture').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='reader-', dir=repository / 'build/p4interopfixture') as directory:
        root = Path(directory)
        monkeypatch.setattr(build, 'ROOT', root)
        documents, declaration, count, _ = fixture
        output = root / 'synthetic'
        report = run((documents, declaration, count, output))
        assert report['status'] == 'BUILD_COMPLETE_WAITING_REVIEW'
        config = {'schema': 'p4-full-semantic-contract-v1', 'declarative_contract': declaration,
                  'snapshot': {'path': 'snapshot.sqlite'}}
        pilot_root = (root / full.pilot.PACK).parent
        pilot_root.mkdir(parents=True)
        refs = {name: ([build.binding(root / name, pilot_root)] if name == 'external_data'
                      else build.binding(root / name, pilot_root))
                for name in ('model', 'tokenizer', 'ort_dll', 'external_data')}
        value = build.manifest(config, {'pack': {'artifacts': refs}}, output, count['actual_chunks'])
        build.save_new(root / 'builder-runtime-manifest.json', value)
        metadata = [{name: row[name] for name in ('entry_key', 'chunk_id', 'document_id',
                                                  'entry_id', 'source_id', 'evidence_id')}
                    for document in documents for row in full.project(document, Tokenizer(), 'a' * 64)]
        build.save_new(root / 'interop-expected.json', {'documents': documents, 'metadata': metadata})
        before = {name: (output / name).read_bytes() for name in
                  ('chunks.sqlite', 'corpus.jsonl', 'manifest.json', 'execution-receipt.json')}
        env = os.environ.copy()
        env['SKNOW_P4_BUILD_INTEROP_DIR'] = str(root)
        env['CARGO_TARGET_DIR'] = str(repository / 'build/p4-full-executor-check-target')
        if os.name == 'nt':
            env['PATH'] = 'C:/msys64/ucrt64/bin' + os.pathsep + env.get('PATH', '')
            for name, executable in [('CC', 'gcc'), ('CXX', 'g++'), ('DLLTOOL', 'dlltool')]:
                env[name] = f'C:/msys64/ucrt64/bin/{executable}.exe'
                env[name + '_x86_64_pc_windows_gnu'] = env[name]
        command = ['cargo', 'test', '--locked', '--features', 'semantic', '--lib',
                   'semantic::tests::builder_synthetic_reader_interop', '--', '--exact', '--nocapture']
        result = subprocess.run(command, cwd=repository / 'rust', env=env, capture_output=True,
                                timeout=300, check=False)
        assert result.returncode == 0, (command, result.returncode, result.stdout, result.stderr)
        assert b'1 passed' in result.stdout, (command, result.stdout, result.stderr)
        for name, content in before.items():
            assert (output / name).read_bytes() == content


@pytest.mark.parametrize('fault', ['valid', 'missing_rust', 'production_changed',
                                  'unapproved_test', 'wrong_fixed_rust', 'missing_acceptance_test',
                                  'test_raw', 'test_fixed', 'legal_test_change', 'other_shared_test'])
def test_rust_source_authorization_actual_git(tmp_path, monkeypatch, fault):
    env = os.environ.copy()
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_CONFIG_COUNT'):
        env.pop(key, None)

    def git(*args):
        return subprocess.check_output(
            ['git', '-c', 'user.name=P4 fixture', '-c', 'user.email=p4-fixture@example.invalid',
             '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false', *args],
            cwd=tmp_path, env=env)

    git('init')
    names = set(full.SOURCE_PATHS) | build.EXECUTOR_PATHS
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture source\n')
    rust = tmp_path / 'rust/src/semantic.rs'
    shown = (Path(build.ROOT) / 'rust/src/semantic.rs').read_bytes().replace(b'\r\n', b'\n')
    start = shown.index(b'    #[test]\n    fn builder_synthetic_reader_interop() {')
    end = shown.index(b'    #[test]\n    fn full_paths_controlled_assets_receipt_exception_and_aliases() {')
    block = shown[start:end]
    assert hashlib.sha256(block).hexdigest() == build.APPROVED_RUST_HARNESS_SHA256
    producer_bytes = shown[:start] + shown[end:]
    rust.write_bytes(producer_bytes)
    git('add', '.')
    git('commit', '-m', 'authorized historical fixture')
    producer = git('rev-parse', 'HEAD').decode().strip()

    def inventory():
        records = {}
        for name in names:
            data = git('show', 'HEAD:' + name)
            raw = (tmp_path / name).read_bytes()
            blob = git('rev-parse', 'HEAD:' + name).decode().strip()
            records[name] = {'git_blob': blob, 'index_git_blob': blob,
                             'checkout_git_filtered_blob': blob, 'size': len(data),
                             'sha256': hashlib.sha256(data).hexdigest(),
                             'checkout_size': len(raw), 'checkout_sha256': hashlib.sha256(raw).hexdigest()}
        return records

    historical = inventory()
    del historical['docs/STAGE_STATUS.md']  # Outside the producer's filtered inventory family.
    source_sha = full.exact.canonical_hash(historical)
    receipts = {phase: {'source_inventory': copy.deepcopy(historical),
                        'source_inventory_sha256': source_sha} for phase in ('count', 'disk', 'smoke')}
    original_receipts = copy.deepcopy(receipts)
    if fault == 'production_changed':
        shown = b'// unauthorized production change\n' + shown
    elif fault == 'unapproved_test':
        shown = shown.replace(b'// Env input is private to tests;', b'// Unapproved test edit;')
    rust.write_bytes(shown)
    if fault == 'legal_test_change':
        (tmp_path / 'tests/test_p4_full_acceptance.py').write_bytes(b'approved new tests\n')
    elif fault == 'other_shared_test':
        (tmp_path / 'tests/test_p4_full_preflight.py').write_bytes(b'unauthorized shared test\n')
    git('add', '.')
    git('commit', '-m', 'authorized current fixture')
    head = git('rev-parse', 'HEAD').decode().strip()
    current = inventory()
    if fault == 'wrong_fixed_rust':
        rust.write_bytes(shown + b'// uncommitted mutation\n')
    bindings = {name: full.exact.sha(tmp_path / name) for name in build.EXECUTOR_PATHS}
    if fault == 'missing_rust':
        del bindings['rust/src/semantic.rs']
    elif fault == 'missing_acceptance_test':
        del bindings['tests/test_p4_full_acceptance.py']
    elif fault == 'test_raw':
        bindings['tests/test_p4_full_acceptance.py'] = '0' * 64
    elif fault == 'test_fixed':
        (tmp_path / 'tests/test_p4_full_acceptance.py').write_bytes(b'uncommitted test\n')
        bindings['tests/test_p4_full_acceptance.py'] = full.exact.sha(tmp_path / 'tests/test_p4_full_acceptance.py')
    auth = {'schema': build.AUTH_SCHEMA, 'operation': 'execute_full', 'fixed_code_sha': head,
            'preflight_producer_sha': producer, 'preflight_evidence_sha': producer,
            'reviewed_source_bindings': dict.fromkeys(('count', 'disk', 'smoke'), source_sha),
            'output': build.OUTPUT, 'max_attempts': 1, 'count_review': {}, 'disk_review': {},
            'smoke_review': {}, 'executor_bindings': bindings}
    build.save_new(tmp_path / 'auth.json', auth)
    digest = full.exact.sha(tmp_path / 'auth.json')
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_CONFIG_COUNT'):
        monkeypatch.delenv(key, raising=False)

    def authenticate():
        build.authorize('auth.json', digest, fixed_head=head, root=tmp_path)
        for receipt in receipts.values():
            build.authenticate_preflight_source(receipt, producer, source_sha, current, tmp_path, auth=auth)

    if fault in ('valid', 'legal_test_change'):
        authenticate()
        assert len(bindings) == 7
    else:
        message = {'missing_rust': 'executor source closure',
                   'production_changed': 'shared preflight Rust implementation changed',
                   'unapproved_test': 'unapproved Rust test harness',
                   'wrong_fixed_rust': 'executor does not match fixed Git source',
                   'missing_acceptance_test': 'executor source closure',
                   'test_raw': 'executor source changed',
                   'test_fixed': 'executor does not match fixed Git source',
                   'other_shared_test': 'shared preflight implementation changed'}[fault]
        with pytest.raises(ValueError, match=message):
            authenticate()
    assert receipts == original_receipts
    assert not (tmp_path / build.OUTPUT).exists()


def test_activation_authority_failure_never_reserves(activation, monkeypatch):
    report = build.new_report()
    def forbidden(*args, **kwargs):
        pytest.fail('reservation/work must not start after authority failure')
    monkeypatch.setattr(build, 'reserve', forbidden)
    monkeypatch.setattr(build, 'lifecycle', forbidden)
    monkeypatch.setattr(acceptance, '_approved_dll_path', lambda: (_ for _ in ()).throw(ValueError('authority failure')))
    monkeypatch.setattr(build, 'validate_activation_dll', lambda verified: acceptance._approved_dll_path())
    with pytest.raises(ValueError, match='authority failure'):
        build._execute({}, {}, 'b' * 40, report, 'unused-auth', 'a' * 64)
    assert report['attempts'] == 0


@pytest.mark.parametrize('fault', ['valid', 'producer', 'added_code', 'raw_binding', 'fixed_binding'])
def test_acceptance_repair_review_closure_actual_git(tmp_path, monkeypatch, fault):
    repository = Path(__file__).resolve().parents[1]
    name = 'tools/p4_full_acceptance.py'
    old = subprocess.check_output(['git', 'show', 'ccc80fd8d2d700654a9003cc70e3785628275f99:' + name], cwd=repository)
    new = (repository / name).read_bytes().replace(b'\r\n', b'\n')
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(new + (b'\nraise RuntimeError("unapproved production code")\n' if fault == 'added_code' else b''))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    def git(*args):
        return subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false',
            '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', *args], cwd=tmp_path)
    git('init')
    git('add', '--', name)
    git('commit', '-m', 'authorized review fixture')
    head = git('rev-parse', 'HEAD').decode().strip()
    blob = git('rev-parse', 'HEAD:' + name).decode().strip()
    bindings = dict.fromkeys(build.EXECUTOR_PATHS, 'a' * 64)
    bindings[name] = full.exact.sha(path)
    if fault == 'producer':
        old += b'\nraise RuntimeError("wrong producer")\n'
    elif fault == 'raw_binding':
        bindings[name] = '0' * 64
    elif fault == 'fixed_binding':
        path.write_bytes(new + b'\n# uncommitted\n')
        bindings[name] = full.exact.sha(path)
    auth = {'fixed_code_sha': head, 'executor_bindings': bindings}
    if fault == 'valid':
        build.authenticate_acceptance_repair(old, {'git_blob': blob}, tmp_path, auth)
    else:
        with pytest.raises(ValueError):
            build.authenticate_acceptance_repair(old, {'git_blob': blob}, tmp_path, auth)


@pytest.fixture
def retry_history(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    # Fixture authorities are separate from production pins; all bytes are really read.
    output = tmp_path / build.OUTPUT
    output.mkdir(parents=True)
    report = build.new_report()
    report.update(attempts=1, phase='reservation', snapshot_after_hash_status='UNCHANGED')
    values = {'execution_receipt': (build.OUTPUT + '/execution-receipt.json', report),
              'authorization': ('build/old-auth.json', {'schema': build.AUTH_SCHEMA}),
              'command_receipt': ('reports/command.json', {'exit_code': 1}),
              'handoff': ('reports/handoff.json', {'status': 'FAIL'}),
              'attempt1_lock': (build.OUTPUT + '.attempt1.lock', {'attempt': 1})}
    pins = {}
    for key, (name, value) in values.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        build.save_new(path, value)
        pins[key] = {'path': name, 'size': path.stat().st_size, 'sha256': full.exact.sha(path)}
    monkeypatch.setattr(build, 'ATTEMPT1_BINDINGS', pins, raising=False)
    return tmp_path, pins


@pytest.mark.parametrize('fault', ['valid', 'old_output_missing', 'old_lock_missing',
    'execution_receipt', 'authorization', 'command_receipt', 'handoff', 'manifest',
    'new_output', 'new_lock', 'status', 'attempts', 'phase', 'documents', 'chunks',
    'embeddings', 'ann', 'snapshot'])
def test_retry_history_failure_first_real_bytes(retry_history, fault):
    root, pins = retry_history
    if fault == 'old_output_missing':
        (root / pins['execution_receipt']['path']).unlink()
        (root / build.OUTPUT).rmdir()
    elif fault == 'old_lock_missing':
        (root / pins['attempt1_lock']['path']).unlink()
    elif fault in pins:
        with (root / pins[fault]['path']).open('ab') as f:
            f.write(b' ')
    elif fault == 'manifest':
        (root / build.OUTPUT / 'manifest.json').write_bytes(b'{}')
    elif fault == 'new_output':
        (root / build.RETRY_OUTPUT).mkdir()
    elif fault == 'new_lock':
        build.attempt_lock(root / build.RETRY_OUTPUT, 2).write_bytes(b'occupied')
    elif fault != 'valid':
        path = root / pins['execution_receipt']['path']
        value = build.read_json(path)
        key = {'documents': 'completed_documents', 'chunks': 'completed_chunks',
               'embeddings': 'completed_embeddings', 'ann': 'completed_ann',
               'snapshot': 'snapshot_after_hash_status'}.get(fault, fault)
        value[key] = {'status': 'PASS', 'phase': 'projection', 'snapshot': 'CHANGED'}.get(fault, 2)
        path.write_bytes(full.chunks.canonical(value))
        pins['execution_receipt'].update(size=path.stat().st_size, sha256=full.exact.sha(path))
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    if fault == 'valid':
        result = build.validate_retry_history_and_no_retry_product(root=root)
        assert result['attempt1_lock'] == pins['attempt1_lock']
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            build.validate_retry_history_and_no_retry_product(root=root)
    assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('fault', ['valid', 'nan', 'norm', 'shape', 'dtype'])
def test_salvage_whole_vector_gate(tmp_path, fault):
    value = np.zeros((8, 4), dtype=np.float32)
    value[:, 0] = 1
    if fault == 'nan':
        value[7, 1] = np.nan
    elif fault == 'norm':
        value[7, 0] = 2
    elif fault == 'shape':
        value = value[:, :3]
    elif fault == 'dtype':
        value = value.astype(np.float64)
    path = tmp_path / 'vectors.npy'
    np.save(path, value)
    if fault == 'valid':
        assert build.validate_partial_vectors(path, rows=8, dimension=4)['FINITE'] == 'PASS'
    else:
        with pytest.raises(ValueError):
            build.validate_partial_vectors(path, rows=8, dimension=4)


@pytest.mark.parametrize('fault', ['valid', 'tokens', 'component', 'cosine', 'norm', 'nan'])
def test_salvage_cpu_parity_thresholds(fault):
    actual = np.zeros((8, 4), dtype=np.float32)
    actual[:, 0] = 1
    expected = actual.copy()
    tokens = [2] * 8
    if fault == 'tokens':
        tokens[-1] = 3
    elif fault == 'component':
        expected[-1, 1] = .0002
    elif fault == 'cosine':
        expected[-1] = [-1, 0, 0, 0]
    elif fault == 'norm':
        expected[-1, 0] = 1.00002
    elif fault == 'nan':
        expected[-1, 1] = np.nan
    if fault == 'valid':
        assert build.partial_parity_metrics(actual, expected, [2] * 8, tokens)['minimum_cosine'] == 1
    else:
        with pytest.raises(ValueError):
            build.partial_parity_metrics(actual, expected, [2] * 8, tokens)


@pytest.mark.parametrize('fault', ['valid', 'size', 'sha', 'mapping', 'sample', 'existing_ann', 'existing_manifest', 'receipt'])
def test_salvage_preservation_actual_bytes(retry_history, monkeypatch, fault):
    root, _ = retry_history
    output = root / build.RETRY_OUTPUT
    output.mkdir()
    receipt = retry_report()
    receipt.update(status='FAIL', phase='sample_reference_parity', attempts=2, attempt_reserved=True,
        completed_documents=1295638, completed_chunks=1366520, completed_embeddings=1366520,
        completed_ann=0, snapshot_after_hash_status='UNCHANGED')
    build.save_new(output / 'execution-receipt.json', receipt)
    history = {build.RETRY_OUTPUT + '/execution-receipt.json': full.exact.sha(output / 'execution-receipt.json')}
    products = {}
    for name in build.PARTIAL_PRODUCTS:
        path = output / name
        path.write_bytes(b'fixture product ' + name.encode())
        products[name] = (path.stat().st_size, full.exact.sha(path))
    monkeypatch.setattr(build, 'ATTEMPT2_HISTORY', history)
    monkeypatch.setattr(build, 'PARTIAL_PRODUCTS', products)
    if fault in ('size', 'sha', 'mapping', 'sample'):
        name = {'mapping': 'chunks.sqlite', 'sample': 'sample.json'}.get(fault, 'vectors.npy')
        path = output / name
        path.write_bytes(b'x' * path.stat().st_size if fault == 'sha' else path.read_bytes() + b'x')
    elif fault == 'existing_ann':
        (output / 'vectors.usearch').write_bytes(b'foreign')
    elif fault == 'existing_manifest':
        (output / 'manifest.json').write_bytes(b'foreign')
    elif fault == 'receipt':
        (output / 'execution-receipt.json').write_bytes(b'{}')
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    if fault == 'valid':
        assert build.validate_partial_preservation(root=root) == output
    else:
        with pytest.raises(ValueError):
            build.validate_partial_preservation(root=root)
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_continuation_no_authorization_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build, 'verify_fixed_current_dev', lambda *a: None)
    monkeypatch.setattr(build, 'reserve', lambda *a, **k: pytest.fail('continuation cannot reserve'))
    monkeypatch.setattr(full.exact, 'LocalEncoder', lambda *a, **k: pytest.fail('continuation cannot encode'))
    with pytest.raises(ValueError, match='separate explicit') as error:
        build.continue_partial(fixed_head='a' * 40)
    assert error.value.continuation_receipt['attempts'] == 2
    assert error.value.continuation_receipt['attempt3_created'] is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('fault', ['exit', 'request', 'positions', 'threads', 'metrics'])
def test_cpu_parent_rejects_untrusted_response(monkeypatch, fault):
    request = {'positions': list(range(1200))}
    response = {'status': 'PASS', 'request_sha256': full.exact.canonical_hash(request),
        'positions': request['positions'], 'sample_count': 1200, 'process_id': os.getpid() + 1,
        'encoder': {'actual_device': 'cpu', 'actual_dtype': 'torch.float32', 'threads': 8, 'interop_threads': 8},
        'metrics': {'max_component_error': 0.0, 'minimum_cosine': 1.0, 'max_norm_error': 0.0}}
    if fault == 'request':
        response['request_sha256'] = '0' * 64
    elif fault == 'positions':
        response['positions'] = [0] * 1200
    elif fault == 'threads':
        response['encoder']['interop_threads'] = 1
    elif fault == 'metrics':
        response['metrics']['max_component_error'] = 1
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1 if fault == 'exit' else 0,
        stdout=json.dumps(response).encode(), stderr=b'worker failed' if fault == 'exit' else b''))
    with pytest.raises(ValueError):
        build.run_partial_cpu_worker(request)


@pytest.mark.parametrize('fault', ['ann_failure', 'receipt_write', 'receipt_flush', 'receipt_fsync', 'snapshot_cancel', 'snapshot_changed'])
def test_continuation_synthetic_claim_preserves_old_products(activation, monkeypatch, fault):
    _config, snapshot, _ = activation
    root = build.ROOT
    output = root / build.RETRY_OUTPUT
    output.mkdir(parents=True)
    original = {'execution-receipt.json': b'immutable FAIL', 'chunks.sqlite': b'mapping',
                'corpus.jsonl': b'corpus', 'sample.json': b'sample', 'vectors.npy': b'vectors'}
    for name, value in original.items():
        (output / name).write_bytes(value)
    auth = build.authorize(None)
    reviewed = build.reviewed_preflight
    monkeypatch.setattr(build, 'reviewed_preflight', lambda a,c,v,r,rt: (dict(reviewed(a,c,v,r,rt)[0], actual_chunks=1366520),
        *reviewed(a,c,v,r,rt)[1:]))
    monkeypatch.setattr(full, 'contained', lambda path, *a: Path(path) if Path(path).is_absolute() else root / path)
    monkeypatch.setattr(build, 'verify_fixed_current_dev', lambda *a: None)
    monkeypatch.setattr(build, 'authorize_continuation', lambda *a, **k: auth)
    monkeypatch.setattr(build, 'validate_partial_preservation', lambda **k: output)
    monkeypatch.setattr(build, 'reserve', lambda *a, **k: pytest.fail('no new build reservation'))
    monkeypatch.setattr(full.exact, 'LocalEncoder', lambda *a, **k: pytest.fail('no embeddings'))
    monkeypatch.setattr(np, 'load', lambda *a, **k: np.zeros((0, 1024), dtype=np.float32))
    monkeypatch.setattr(build, 'close_memmap', lambda v: None)
    monkeypatch.setattr(build, 'index_factory', lambda d: (_ for _ in ()).throw(RuntimeError('synthetic ANN failure')))
    if fault.startswith('receipt_'):
        monkeypatch.setattr(build, 'save_new', lambda *a, **k: (_ for _ in ()).throw(OSError(fault)))
    elif fault in ('snapshot_cancel', 'snapshot_changed'):
        original_binding = build.binding
        calls = 0
        def binding(path, directory):
            nonlocal calls
            if path == snapshot:
                calls += 1
                if calls > 1:
                    if fault == 'snapshot_cancel':
                        raise KeyboardInterrupt('terminal snapshot cancel')
                    return {**original_binding(path, directory), 'sha256': '0' * 64}
            return original_binding(path, directory)
        monkeypatch.setattr(build, 'binding', binding)
    # ANN fails immediately; injected secondary terminal failures must not mask first.
    with pytest.raises(RuntimeError, match='synthetic ANN failure') as error:
        build.continue_partial(fixed_head='a' * 40)
    receipt = json.loads((output / 'continuation-receipt.json').read_bytes())
    assert receipt['status'] == 'FAIL' and receipt['attempts'] == 2
    assert receipt['continuation_claimed'] is True and receipt['attempt3_created'] is False
    assert error.value.continuation_receipt['attempts'] == 2
    assert all((output / name).read_bytes() == value for name, value in original.items())
    assert not (output / 'manifest.json').exists() and not (output / 'vectors.usearch').exists()
    assert not output.with_name(output.name + '.attempt3.lock').exists()


@pytest.mark.parametrize('fault', ['valid', 'worker', 'helper', 'import', 'chunks_import', 'ann_import',
    'export_import', 'request', 'response', 'historical_source'])
def test_cpu_qualification_source_tamper(tmp_path, monkeypatch, fault):
    repository = Path(__file__).resolve().parents[1]
    evidence_path = 'reports/P4/attempt2-partial-cpu-source-binding.json'
    evidence = json.loads((repository / evidence_path).read_bytes())
    transitive_name = 'reports/P4/attempt2-partial-cpu-transitive-binding.json'
    transitive = json.loads((repository / transitive_name).read_bytes())
    for name in [evidence_path, transitive_name, 'tools/p4_full_build.py', *transitive['bindings']]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((repository / name).read_bytes())
    if fault in ('worker', 'helper'):
        path = tmp_path / 'tools/p4_full_build.py'
        source = path.read_text('utf8')
        needle = 'def partial_cpu_worker(request):' if fault == 'worker' else 'def partial_parity_metrics(actual, expected, actual_tokens, expected_tokens):'
        path.write_text(source.replace(needle, needle + '\n    raise RuntimeError("unapproved code")'), encoding='utf8')
    elif fault in ('import', 'chunks_import', 'ann_import', 'export_import'):
        path = tmp_path / {'import': 'tools/p4_exact_pilot.py', 'chunks_import': 'tools/p4_chunks.py',
            'ann_import': 'tools/p4_ann_v1.py', 'export_import': 'tools/p4_onnx_export.py'}[fault]
        path.write_bytes(path.read_bytes() + b'\nraise RuntimeError("unapproved import")\n')
    elif fault in ('request', 'response', 'historical_source'):
        if fault == 'request':
            evidence['request']['source_sha256'] = '0' * 64
        elif fault == 'response':
            evidence['original_response']['request_sha256'] = '0' * 64
        else:
            evidence['qualification_source_reconstructed_utf8'] += '\nraise RuntimeError("tamper")\n'
        path = tmp_path / evidence_path
        path.write_text(json.dumps(evidence), encoding='utf8')
    original_check_output = subprocess.check_output
    monkeypatch.setattr(subprocess, 'check_output', lambda args, **kw: original_check_output(args, cwd=repository)
        if args[:2] == ['git', 'show'] else original_check_output(args, **kw))
    if fault == 'valid':
        assert build.validate_cpu_qualification_source(tmp_path)['request_sha256'] == evidence['request_sha256']
    else:
        with pytest.raises(ValueError):
            build.validate_cpu_qualification_source(tmp_path)


@pytest.mark.parametrize('fault', ['write', 'flush', 'fsync'])
def test_continuation_success_publication_durability_fail_closed(tmp_path, monkeypatch, fault):
    target = tmp_path / 'continuation-receipt.json'
    build.save_new(target, {'status': 'FAIL', 'attempts': 2})
    original_open = Path.open
    class File:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, value):
            if fault == 'write':
                raise OSError('write failed')
            return self.stream.write(value)
        def flush(self):
            if fault == 'flush':
                raise OSError('flush failed')
            self.stream.flush()
        def fileno(self):
            return self.stream.fileno()
    def open_file(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return File(stream) if path.name.endswith('.staging') else stream
    monkeypatch.setattr(Path, 'open', open_file)
    if fault == 'fsync':
        monkeypatch.setattr(os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('fsync failed')))
    with pytest.raises(OSError):
        build.publish_continuation_receipt(target, {'status': 'RECOVERED_FROM_QUALIFIED_ATTEMPT2_PARTIAL'})
    assert json.loads(target.read_bytes())['status'] == 'FAIL'


def test_continuation_replace_side_effect_cancel_scrubs_success(tmp_path, monkeypatch):
    target = tmp_path / 'continuation-receipt.json'
    build.save_new(target, {'status': 'FAIL', 'attempts': 2})
    replace = os.replace
    def interrupted(source, destination):
        replace(source, destination)
        raise KeyboardInterrupt('after replacement')
    monkeypatch.setattr(os, 'replace', interrupted)
    with pytest.raises(KeyboardInterrupt):
        build.publish_continuation_receipt(target, {'status': 'RECOVERED_FROM_QUALIFIED_ATTEMPT2_PARTIAL'})
    assert json.loads(target.read_bytes())['status'] == 'FAIL'
    assert not target.with_name(target.name + '.staging').exists()


@pytest.mark.parametrize('cancel', [False, True])
def test_continuation_publication_cleanup_secondary(tmp_path, monkeypatch, cancel):
    target = tmp_path / 'continuation-receipt.json'
    build.save_new(target, {'status': 'FAIL'})
    if cancel:
        monkeypatch.setattr(os, 'replace', lambda *a: (_ for _ in ()).throw(KeyboardInterrupt('first cancel')))
    else:
        monkeypatch.setattr(os, 'fsync', lambda *a: (_ for _ in ()).throw(OSError('first fsync')))
    monkeypatch.setattr(Path, 'unlink', lambda *a, **k: (_ for _ in ()).throw(PermissionError('cleanup secondary')))
    with pytest.raises(KeyboardInterrupt if cancel else OSError) as error:
        build.publish_continuation_receipt(target, {'status': 'RECOVERED_FROM_QUALIFIED_ATTEMPT2_PARTIAL'})
    assert 'cleanup secondary' in error.value.publication_cleanup_error
    assert json.loads(target.read_bytes())['status'] == 'FAIL'


def test_continuation_success_publication_no_post_replace_cleanup(tmp_path, monkeypatch):
    target = tmp_path / 'continuation-receipt.json'
    build.save_new(target, {'status': 'FAIL'})
    monkeypatch.setattr(Path, 'unlink', lambda *a, **k: pytest.fail('no post-replace cleanup'))
    build.publish_continuation_receipt(target, {'status': 'RECOVERED_FROM_QUALIFIED_ATTEMPT2_PARTIAL'})
    assert json.loads(target.read_bytes())['status'] == 'RECOVERED_FROM_QUALIFIED_ATTEMPT2_PARTIAL'


def test_continuation_success_work_terminal_snapshot_changed(activation, monkeypatch):
    _config, snapshot, _ = activation
    root = build.ROOT
    output = root / build.RETRY_OUTPUT
    output.mkdir(parents=True)
    old = {'execution-receipt.json': b'original FAIL', 'chunks.sqlite': b'mapping',
           'corpus.jsonl': b'corpus', 'sample.json': b'sample', 'vectors.npy': b'vectors'}
    for name, value in old.items():
        (output / name).write_bytes(value)
    auth = build.authorize(None)
    reviewed = build.reviewed_preflight
    monkeypatch.setattr(build, 'reviewed_preflight', lambda a,c,v,r,rt: (dict(reviewed(a,c,v,r,rt)[0], actual_chunks=1366520),
        *reviewed(a,c,v,r,rt)[1:]))
    monkeypatch.setattr(full, 'contained', lambda path, *a: Path(path) if Path(path).is_absolute() else root / path)
    monkeypatch.setattr(build, 'verify_fixed_current_dev', lambda *a: None)
    monkeypatch.setattr(build, 'authorize_continuation', lambda *a, **k: auth)
    monkeypatch.setattr(build, 'validate_partial_preservation', lambda **k: output)
    monkeypatch.setattr(build, 'reserve', lambda *a, **k: pytest.fail('no reservation'))
    monkeypatch.setattr(full.exact, 'LocalEncoder', lambda *a, **k: pytest.fail('no encoding'))
    # Empty batch views avoid work; every index/manifest operation is synthetic.
    monkeypatch.setattr(np, 'load', lambda *a, **k: np.zeros((0, 1024), dtype=np.float32))
    monkeypatch.setattr(build, 'close_memmap', lambda v: None)
    monkeypatch.setattr(full, 'disk_capacity', lambda *a: {'status': 'PASS'})
    class Index:
        def add(self, *a, **k):
            pass
        def save(self, path):
            Path(path).write_bytes(b'synthetic ANN only')
        def view(self, *a):
            pass
    monkeypatch.setattr(build, 'index_factory', lambda *a: Index())
    monkeypatch.setattr(build, 'close_index', lambda *a: None)
    monkeypatch.setattr(build, 'verify_keys', lambda *a: None)
    monkeypatch.setattr(build, 'manifest', lambda *a: {'inventory_exclusions': {}})
    monkeypatch.setattr(build.acceptance, 'validate_full_manifest', lambda *a, **k: None)
    original_binding = build.binding
    calls = 0
    def binding(path, directory):
        nonlocal calls
        result = original_binding(path, directory)
        if path == snapshot:
            calls += 1
            if calls == 3:  # Before and pre-publication equal; terminal alone changes.
                result = dict(result, sha256='0' * 64)
        return result
    monkeypatch.setattr(build, 'binding', binding)
    with pytest.raises(ValueError, match='terminal snapshot changed') as error:
        build.continue_partial(fixed_head='a' * 40)
    report = error.value.continuation_receipt
    assert report['status'] == 'FAIL' and report['snapshot_after_hash_status'] == 'CHANGED'
    receipt = json.loads((output / 'continuation-receipt.json').read_bytes())
    assert receipt['status'] == 'FAIL' and receipt['snapshot_after_hash_status'] == 'CHANGED'
    assert (output / 'manifest.json').exists()  # Retained partial work, not a success claim.
    assert all((output / name).read_bytes() == value for name, value in old.items())


def retry_policy():
    return {'schema': build.RETRY_SCHEMA, 'operation': 'execute_full_retry', 'fixed_code_sha': 'b' * 40,
        'attempt_number': 2, 'max_total_attempts': 2, 'retry_of': build.attempt1_history_binding(),
        'failure_class': build.FAILURE_CLASS, 'preflight_producer_sha': 'a' * 40,
        'preflight_evidence_sha': 'c' * 40, 'reviewed_source_bindings': dict.fromkeys(('count', 'disk', 'smoke'), 'd' * 64),
        'output': build.RETRY_OUTPUT, 'previous_output': build.OUTPUT, 'count_review': {},
        'disk_review': {}, 'smoke_review': {}, 'executor_bindings': {}}


@pytest.mark.parametrize('fault', ['valid', 'failure_class', 'attempt_number', 'max_total_attempts',
    'output', 'old_output', 'previous_output', 'retry_of', 'extra', 'missing', 'boolean_attempt',
    'boolean_history_count', 'operation'])
def test_retry_exact_policy(retry_history, fault):
    value = retry_policy()
    if fault == 'old_output':
        value['output'] = build.OUTPUT
    elif fault == 'boolean_attempt':
        value['attempt_number'] = True
    elif fault == 'boolean_history_count':
        value['retry_of']['completed_documents'] = False
    elif fault == 'extra':
        value['unknown'] = 1
    elif fault == 'missing':
        del value['max_total_attempts']
    elif fault != 'valid':
        value[fault] = 3 if fault in ('attempt_number', 'max_total_attempts') else 'wrong'
    if fault == 'valid':
        build.validate_retry_policy(value, 'b' * 40)
    else:
        with pytest.raises(ValueError):
            build.validate_retry_policy(value, 'b' * 40)


def retry_report():
    report = build.new_report()
    report.update(attempts=1, attempt_reserved=False, attempt_number=2,
        retry_of=build.attempt1_history_binding(), fixed_code_sha='b' * 40,
        authorization_sha256='c' * 64, BUILD_POLICY_EXCEPTION=build.POLICY_EXCEPTION)
    return report


@pytest.mark.parametrize('fault', ['success', 'work_fail', 'already_reserved', 'attempt3'])
def test_retry_lifecycle_total_and_old_bytes(retry_history, fault):
    root, pins = retry_history
    before = {key: (root / ref['path']).read_bytes() for key, ref in pins.items()}
    report = retry_report()
    output = root / build.RETRY_OUTPUT
    def work():
        build.save_new(output / 'partial.json', {'synthetic': True})
        if fault == 'work_fail':
            raise RuntimeError('synthetic work failed')
        return {'inventory_sha256': 'a' * 64, 'FULL_SEMANTIC_PACK_SHA256': 'a' * 64}
    if fault == 'already_reserved':
        build.attempt_lock(output, 2).write_bytes(b'occupied')
    if fault in ('work_fail', 'already_reserved', 'attempt3'):
        with pytest.raises((RuntimeError, ValueError)):
            build.lifecycle(output, report, work, attempt_number=3 if fault == 'attempt3' else 2)
    else:
        build.lifecycle(output, report, work, attempt_number=2)
    assert {key: (root / ref['path']).read_bytes() for key, ref in pins.items()} == before
    if fault in ('success', 'work_fail'):
        lock = build.read_json(build.attempt_lock(output, 2))
        assert lock['attempt'] == 2 and lock['retry_of'] == build.attempt1_history_binding()
        assert lock['fixed_code_sha'] == 'b' * 40 and lock['authorization_sha256'] == 'c' * 64
        receipt = build.read_json(output / 'execution-receipt.json')
        assert receipt['attempts'] == receipt['attempt_number'] == 2
        assert (output / 'partial.json').exists()
        assert receipt['retained_partial'] == (fault == 'work_fail')
        if fault == 'success':
            value = build.read_json(output / 'manifest.json')
            assert value['build_provenance'] == build.retry_build_provenance(report)
            assert value['FULL_SEMANTIC_PACK_SHA256'] == value['inventory_sha256'] == 'a' * 64
    else:
        assert report['attempts'] == 1 and not report['retained_partial']
        assert not output.exists()
        assert not output.with_name(output.name + '.execution-receipt.json').exists()
    assert not output.with_name(output.name + '.attempt3.lock').exists()


@pytest.mark.parametrize('fault', ['dll', 'snapshot', 'disk', 'gpu'])
def test_retry_activation_failure_before_claim(activation, monkeypatch, fault):
    root = build.ROOT
    config, _, _ = activation
    original_auth = build.authorize(None)
    auth = {**original_auth, 'schema': build.RETRY_SCHEMA, 'output': build.RETRY_OUTPUT}
    original_reviewed = build.reviewed_preflight
    monkeypatch.setattr(build, 'reviewed_preflight',
        lambda a, c, v, r, rt: original_reviewed(original_auth, c, v, r, rt))
    # Existing activation fixture supplies independently synthetic preflight/inputs.
    monkeypatch.setattr(build, 'authenticate_executor_bindings', lambda *a, **k: None)
    monkeypatch.setattr(full, 'historical_job_bindings', lambda **k: {})
    if fault == 'dll':
        monkeypatch.setattr(build, 'validate_activation_dll', lambda v: (_ for _ in ()).throw(ValueError('DLL failure')))
    elif fault == 'disk':
        monkeypatch.setattr(full, 'disk_capacity', lambda v: {'status': 'FAIL'})
    elif fault == 'snapshot':
        config['snapshot']['sha256'] = '0' * 64
    else:
        import torch
        monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    monkeypatch.setattr(build, 'reserve', lambda *a, **k: pytest.fail('must not reserve2'))
    report = retry_report()
    match = {'dll': 'DLL failure', 'snapshot': 'snapshot size/SHA mismatch',
             'disk': 'BLOCKED_DISK', 'gpu': 'GPU unavailable'}[fault]
    with pytest.raises(ValueError, match=match):
        build._execute(auth, config, 'b' * 40, report, 'unused', 'c' * 64)
    assert report['attempts'] == 1 and not report['attempt_reserved']
    assert not (root / build.RETRY_OUTPUT).exists()
    assert not build.attempt_lock(root / build.RETRY_OUTPUT, 2).exists()


@pytest.mark.parametrize('fault', ['history', 'after_hash', 'after_stat', 'cancel', 'after_cancel'])
def test_readiness_failures_are_structured_and_no_work(retry_history, monkeypatch, fault):
    root, pins = retry_history
    monkeypatch.setattr(build, 'verify_fixed_current_dev', lambda *a: None)
    original_sha = full.exact.sha
    original_stat = Path.stat
    calls = {}
    target = root / pins['authorization']['path']
    def sha(path):
        calls[path] = calls.get(path, 0) + 1
        if path == target and calls[path] > 1 and fault in ('after_hash', 'after_cancel'):
            if fault == 'after_cancel':
                raise KeyboardInterrupt('after cancellation')
            raise OSError('after hash failed')
        return original_sha(path)
    def stat(path, *a, **k):
        if path == target and calls.get(target, 0) >= 1 and fault == 'after_stat':
            raise OSError('after stat failed')
        return original_stat(path, *a, **k)
    monkeypatch.setattr(full.exact, 'sha', sha)
    monkeypatch.setattr(Path, 'stat', stat)
    def history(**kwargs):
        if fault == 'cancel':
            raise KeyboardInterrupt('probe cancelled')
        raise ValueError('history rejected')
    monkeypatch.setattr(build, 'validate_retry_history_and_no_retry_product', history)
    monkeypatch.setattr(build, 'reserve', lambda *a, **k: pytest.fail('readiness never reserves'))
    monkeypatch.setattr(full, 'inventory', lambda: pytest.fail('early failure cannot reach inventory'))
    if fault in ('cancel', 'after_cancel'):
        with pytest.raises(KeyboardInterrupt) as error:
            build.attempt2_readiness(fixed_head='b' * 40)
        report = error.value.readiness_receipt
    else:
        report = build.attempt2_readiness(fixed_head='b' * 40)
    assert report['status'] == report['ATTEMPT1_HISTORY'] == 'FAIL'
    assert report['AUTHORITY_PARITY'] == report['SNAPSHOT'] == report['DISK'] == report['GPU'] == 'NOT_RUN'
    assert report['error']['message'] in ('history rejected', 'probe cancelled')
    if fault.startswith('after_'):
        assert report['after_errors'] and report['ATTEMPT1_PRESERVED'] == 'NO'
    assert report['SECOND_ATTEMPT_STARTED'] == 'NO'
    assert not (root / build.RETRY_OUTPUT).exists()


@pytest.mark.parametrize('fault', ['valid', 'raw', 'fixed', 'extra_binding', 'missing_binding', 'wrong_hash', 'old_schema'])
def test_retry_authorization_actual_git(retry_history, monkeypatch, fault):
    root, _ = retry_history
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    def git(*args):
        return subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false',
            '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', *args], cwd=root)
    git('init')
    for name in build.EXECUTOR_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture source\n')
    git('add', '--', *sorted(build.EXECUTOR_PATHS))
    git('commit', '-m', 'retry implementation fixture')
    head = git('rev-parse', 'HEAD').decode().strip()
    value = retry_policy()
    value['fixed_code_sha'] = head
    value['executor_bindings'] = {n: full.exact.sha(root / n) for n in build.EXECUTOR_PATHS}
    if fault == 'raw':
        value['executor_bindings']['tools/p4_full_build.py'] = '0' * 64
    elif fault == 'fixed':
        (root / 'tools/p4_full_build.py').write_bytes(b'uncommitted code\n')
        value['executor_bindings']['tools/p4_full_build.py'] = full.exact.sha(root / 'tools/p4_full_build.py')
    elif fault == 'extra_binding':
        value['executor_bindings']['unknown.py'] = '0' * 64
    elif fault == 'missing_binding':
        del value['executor_bindings']['tests/test_p4_full_acceptance.py']
    elif fault == 'old_schema':
        value['schema'] = build.AUTH_SCHEMA
    path = root / 'fixture-retry-auth.json'
    build.save_new(path, value)
    digest = '0' * 64 if fault == 'wrong_hash' else full.exact.sha(path)
    if fault == 'valid':
        assert build.authorize_retry(path.name, digest, fixed_head=head, root=root) == value
    else:
        with pytest.raises(ValueError):
            build.authorize_retry(path.name, digest, fixed_head=head, root=root)
