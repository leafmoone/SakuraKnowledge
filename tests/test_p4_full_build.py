import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
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


def test_config_failure_attaches_activation_report(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(full, 'CONFIG', tmp_path / 'absent.json')
    monkeypatch.setattr(full, 'inventory', lambda: pytest.fail('inventory before config'))
    with pytest.raises(FileNotFoundError):
        build.execute()
    assert list(tmp_path.iterdir()) == []


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
    assert not build.attempt_lock(output).exists()
    with pytest.raises(ValueError, match='output already exists'):
        run(fixture)
    assert output.exists()


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
    assert not build.attempt_lock(output).exists()
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
    pilot_root = root
    artifacts = build.read_json(output / 'manifest.json')['artifacts']
    refs = {name: ([build.binding(root / name, pilot_root)] if name == 'external_data'
                  else build.binding(root / name, pilot_root)) for name in ('model', 'tokenizer', 'ort_dll', 'external_data')}
    monkeypatch.setattr(acceptance.pilot, 'DLL_SIZE', artifacts['ort_dll']['size'])
    monkeypatch.setattr(acceptance.pilot, 'DLL_SHA', artifacts['ort_dll']['sha256'])
    monkeypatch.setattr(acceptance, 'approved_full_dll', lambda: {'path': str(root / 'ort_dll'),
        'size': artifacts['ort_dll']['size'], 'sha256': artifacts['ort_dll']['sha256']})
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
        pilot_root = root
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
    assert not build.attempt_lock(tmp_path / 'synthetic-pack').exists()
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
    assert not build.attempt_lock(output).exists()
    if where != 'reserve_after':
        assert (output / 'partial').read_bytes() == b'retained'
    if where != 'reserve_after':
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

@pytest.mark.parametrize('fault', ['exit', 'request', 'positions', 'threads', 'metrics'])
def test_cpu_parent_rejects_untrusted_response(monkeypatch, fault):
    request = {'positions': list(range(1200))}
    response = {'status': 'PASS', 'request_sha256': full.exact.canonical_hash(request),
        'positions': request['positions'], 'sample_count': 1200, 'process_id': os.getpid() + 1,
        'encoder': {'actual_device': 'cpu', 'actual_dtype': 'torch.float32', 'threads': 8, 'interop_threads': 8},
        'metrics': {'max_component_error': 0.0, 'minimum_cosine': 1.0, 'max_norm_error': 0.0}}
    if fault == 'request':
        response['request_sha256'] = '0' * 64
