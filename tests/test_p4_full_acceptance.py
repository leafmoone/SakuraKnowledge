"""Synthetic FULL acceptance fixtures: no actual FULL inventory/model/inference."""
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tools import p4_full_acceptance as acceptance
from tools import p4_full_preflight as full


def binding(path, name):
    data = path.read_bytes()
    return {'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


@pytest.fixture
def fixture_pack(tmp_path, monkeypatch):
    contract = json.loads(full.CONFIG.read_bytes())
    root = tmp_path
    config = root / acceptance.CANONICAL_PATH
    config.parent.mkdir()
    snapshot = root / 'snapshot.sqlite'
    conn = sqlite3.connect(snapshot)
    conn.executescript('''
        CREATE TABLE sources(source_id TEXT PRIMARY KEY,metadata TEXT);
        CREATE TABLE entries(id INTEGER PRIMARY KEY,kind TEXT,namespace TEXT,value TEXT,conflicted INTEGER);
        CREATE TABLE entry_evidence(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT);
        CREATE TABLE aliases(entry_id INTEGER,source_id TEXT,evidence_id TEXT,text TEXT,status TEXT);
        CREATE TABLE documents(id INTEGER PRIMARY KEY,entry_id INTEGER,title TEXT,original TEXT,
                               status TEXT,source_id TEXT,evidence_id TEXT);
        INSERT INTO sources VALUES ('source','{"family":"fixture"}');
        INSERT INTO entries VALUES (1,'subject','bangumi.subject','same',0);
        INSERT INTO entries VALUES (2,'character','bangumi.character','same',0);
        INSERT INTO entry_evidence VALUES (1,'source','proof1','source_backed');
        INSERT INTO entry_evidence VALUES (2,'source','proof2','source_backed');
        INSERT INTO aliases VALUES (1,'source','alias1','alias','source_backed');
        INSERT INTO documents VALUES (1,1,'title','original','source_backed','source','docproof');
    ''')
    conn.commit()
    conn.close()
    contract['snapshot'] = binding(snapshot, 'snapshot.sqlite')
    config.write_text(json.dumps(contract), encoding='utf-8')
    # Authority substitution is confined to this synthetic fixture, not global FULL constants.
    monkeypatch.setattr(acceptance, 'ROOT', root)
    monkeypatch.setattr(acceptance, 'CONFIG', config)

    def fixture_contract(value):
        if value != contract:
            raise ValueError('fixture contract mismatch')
        return value['declarative_contract']

    monkeypatch.setattr(acceptance, 'validate_contract', fixture_contract)
    pack = root / 'pack'
    pack.mkdir()
    artifacts = {}
    for name in sorted(acceptance.ARTIFACTS):
        path = pack / name
        path.write_bytes(('synthetic-' + name).encode())
        record = binding(path, name)
        artifacts[name] = [record] if name == 'external_data' else record
    monkeypatch.setattr(acceptance.pilot, 'DLL_SIZE', artifacts['ort_dll']['size'])
    monkeypatch.setattr(acceptance.pilot, 'DLL_SHA', artifacts['ort_dll']['sha256'])
    manifest = {'schema': acceptance.PACK_SCHEMA, 'object_type': 'runtime_pack',
                'implementation_origin': full.IMPLEMENTATION, 'recovered_original_source': False,
                'canonical_contract': {'schema': contract['schema'],
                                       **binding(config, acceptance.CANONICAL_PATH)},
                'declarative_contract': copy.deepcopy(contract['declarative_contract']),
                'snapshot': {'identity': 'snapshot.sqlite',
                             **binding(snapshot, '../snapshot.sqlite')},
                'contract': acceptance.runtime_contract(contract['declarative_contract'], 7),
                'full_chunk_count': 7, 'artifacts': artifacts}
    return root, config, snapshot, pack, contract, manifest


def test_complete_synthetic_inventory(fixture_pack):
    _, _, _, pack, contract, manifest = fixture_pack
    assert acceptance.validate_full_manifest(manifest, contract, pack_root=pack) == 7


@pytest.mark.parametrize('fault', [
    'empty', 'missing_corpus', 'extra', 'empty_external', 'duplicate_external', 'cross_duplicate',
    'zero_size', 'bool_size', 'bad_sha', 'wrong_sha', 'wrong_size', 'escape', 'absolute',
    'dll_pin', 'schema', 'type', 'binding', 'declaration', 'bool_count', 'zero_count',
    'disagree_count', 'sidecar', 'origin', 'snapshot_hash', 'snapshot_path',
])
def test_manifest_fail_closed(fixture_pack, fault):
    root, _, _, pack, contract, manifest = fixture_pack
    artifacts = manifest['artifacts']
    if fault == 'empty':
        manifest['artifacts'] = {}
    elif fault == 'missing_corpus':
        del artifacts['corpus']
    elif fault == 'extra':
        artifacts['extra'] = artifacts['corpus']
    elif fault == 'empty_external':
        artifacts['external_data'] = []
    elif fault == 'duplicate_external':
        artifacts['external_data'] *= 2
    elif fault == 'cross_duplicate':
        artifacts['external_data'] = [artifacts['model']]
    elif fault in ('zero_size', 'bool_size', 'wrong_size'):
        artifacts['model']['size'] = {'zero_size': 0, 'bool_size': True, 'wrong_size': 1}[fault]
    elif fault in ('bad_sha', 'wrong_sha'):
        artifacts['model']['sha256'] = 'bad' if fault == 'bad_sha' else '0' * 64
    elif fault == 'escape':
        artifacts['model']['path'] = '../snapshot.sqlite'
    elif fault == 'absolute':
        artifacts['model']['path'] = str(root / 'snapshot.sqlite')
    elif fault == 'dll_pin':
        artifacts['ort_dll'] = artifacts['corpus']
    elif fault == 'schema':
        manifest['schema'] = 'p4-rust-semantic-pack-v1'
    elif fault == 'type':
        manifest['object_type'] = 'canonical_contract'
    elif fault == 'binding':
        manifest['canonical_contract']['sha256'] = '0' * 64
    elif fault == 'declaration':
        manifest['declarative_contract']['chunk']['max_tokens'] = 385
    elif fault in ('bool_count', 'zero_count', 'disagree_count'):
        manifest['full_chunk_count'] = {'bool_count': True, 'zero_count': 0, 'disagree_count': 8}[fault]
    elif fault == 'sidecar':
        manifest['lexical_metadata'] = {}
    elif fault == 'origin':
        manifest['recovered_original_source'] = True
    elif fault == 'snapshot_hash':
        (root / 'snapshot.sqlite').write_bytes(b'not the bound snapshot')
    else:
        manifest['snapshot']['path'] = 'model'
    with pytest.raises((ValueError, FileNotFoundError)):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)


def test_canonical_control_and_actual_bytes(fixture_pack, monkeypatch):
    root, config, _, pack, contract, manifest = fixture_pack
    alternate = root / 'alternate.json'
    alternate.write_bytes(config.read_bytes())
    monkeypatch.setattr(acceptance, 'CONFIG', alternate)
    with pytest.raises(ValueError, match='controlled canonical'):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)
    monkeypatch.setattr(acceptance, 'CONFIG', config)
    config.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='canonical bytes'):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)


@pytest.mark.parametrize('target', ['model', 'parent', 'canonical', 'snapshot'])
def test_symlink_rejected(fixture_pack, target):
    root, config, snapshot, pack, contract, manifest = fixture_pack
    path = {'model': pack / 'model', 'parent': pack, 'canonical': config,
            'snapshot': snapshot}[target]
    moved = root / ('moved-' + target)
    path.rename(moved)
    try:
        path.symlink_to(moved, target_is_directory=target == 'parent')
    except OSError as exc:
        pytest.skip(f'OS does not permit symlink fixture: {exc}')
    with pytest.raises(ValueError, match='symlink'):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)


def test_inventory_change_during_hash(fixture_pack, monkeypatch):
    _, _, _, pack, contract, manifest = fixture_pack
    original = acceptance.pilot.sha

    def changing_hash(path):
        result = original(path)
        if path.name == 'model':
            path.write_bytes(b'changed')
        return result

    monkeypatch.setattr(acceptance.pilot, 'sha', changing_hash)
    with pytest.raises(ValueError, match='changed'):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)


@pytest.fixture
def response_fixture(fixture_pack):
    _, _, snapshot, _, contract, _ = fixture_pack
    response = {'contract_version': '2', 'response_version': 'p4-semantic-evidence-v1',
                'identity_status': 'not_asserted', 'promoted_identities': [], 'canonical': None,
                'entity_tag': None, 'query': 'same', 'status': 'PASS',
                'snapshot': {'identity': 'snapshot.sqlite', **contract['snapshot']},
                'candidates': [], 'sources': [{'source_id': 'source', 'metadata': {'family': 'fixture'}}],
                'evidence': [], 'documents': [], 'citations': [], 'trusted_pins': []}
    for eid, kind in enumerate(('subject', 'character'), 1):
        entry = {'kind': kind, 'namespace': 'bangumi.' + kind, 'value': 'same'}
        pin = {'entry': entry, 'match': 'exact', 'source_id': 'source', 'evidence_id': f'proof{eid}'}
        response['trusted_pins'].append(pin)
        response['candidates'].append({'entry': entry, 'provenance': [], 'trusted_pins': [pin],
                                      'typed_identity': {'kind': kind, 'namespace': 'bangumi.' + kind,
                                                         'entry_id': str(eid)}})
    with full.readonly(snapshot) as conn:
        yield response, conn


def test_typed_ambiguity_pin_only_snapshot_proof(response_fixture):
    response, conn = response_fixture
    assert acceptance.validate_response(response, snapshot_conn=conn) == 2
    assert conn.execute('SELECT count(*) FROM entries').fetchone()[0] == 2  # caller still owns it


def test_structure_is_not_complete_verification(response_fixture):
    response, _ = response_fixture
    assert acceptance.validate_response_structure(response) == 2
    with pytest.raises(ValueError, match='connection required'):
        acceptance.validate_response(response)


@pytest.mark.parametrize('fault', ['promotion', 'identity_status', 'canonical', 'entity_tag',
                                  'invented_field', 'episode', 'no_proof', 'missing_sources',
                                  'foreign_source', 'foreign_evidence', 'wrong_typed_key',
                                  'wrong_entry_id', 'query', 'duplicate', 'extra_evidence',
                                  'source_metadata', 'writable_connection', 'snapshot_binding'])
def test_response_fail_closed(response_fixture, fault):
    response, conn = response_fixture
    candidate = response['candidates'][0]
    if fault == 'promotion':
        response['promoted_identities'] = ['same']
    elif fault == 'identity_status':
        response['identity_status'] = 'asserted'
    elif fault in ('canonical', 'entity_tag'):
        response[fault] = 'same'
    elif fault == 'invented_field':
        response['identity_assertions'] = []
    elif fault == 'episode':
        candidate['entry']['kind'] = 'episode'
    elif fault == 'no_proof':
        candidate['trusted_pins'] = []
    elif fault == 'missing_sources':
        response['sources'] = []
    elif fault == 'foreign_source':
        candidate['trusted_pins'][0]['source_id'] = 'foreign'
    elif fault == 'foreign_evidence':
        candidate['trusted_pins'][0]['evidence_id'] = 'foreign'
    elif fault == 'wrong_typed_key':
        candidate['entry'] = response['candidates'][1]['entry']
    elif fault == 'wrong_entry_id':
        candidate['typed_identity']['entry_id'] = '2'
    elif fault == 'query':
        response['query'] = 'other'
    elif fault == 'duplicate':
        response['candidates'].append(copy.deepcopy(candidate))
    elif fault == 'extra_evidence':
        response['evidence'] = [{'evidence_id': 'unverified'}]
    elif fault == 'source_metadata':
        response['sources'][0]['metadata'] = {}
    elif fault == 'writable_connection':
        conn.execute('PRAGMA query_only=OFF')
    else:
        response['snapshot']['sha256'] = '0' * 64
    with pytest.raises(ValueError):
        acceptance.validate_response(response, snapshot_conn=conn)


def add_document(response):
    candidate = response['candidates'][0]
    hit = {'entry': candidate['entry'], 'document_id': '1', 'source_id': 'source',
           'evidence_id': 'docproof'}
    candidate['provenance'] = [{'hit': hit}]
    doc = {'document_id': '1', 'entry_id': '1', 'entry_key': candidate['entry'], 'title': 'title',
           'original': 'original', 'status': 'source_backed', 'source_id': 'source',
           'evidence_id': 'docproof'}
    response['documents'] = [doc]
    response['evidence'] = [{key: doc[key] for key in
                             ('document_id', 'entry_id', 'status', 'source_id', 'evidence_id')}]
    response['citations'] = [{key: doc[key] for key in ('document_id', 'source_id', 'evidence_id')}]


@pytest.mark.parametrize('fault', [None, 'missing_document', 'missing_evidence', 'missing_citation',
                                  'foreign_document', 'foreign_source', 'foreign_evidence', 'typed'])
def test_document_snapshot_closure(response_fixture, fault):
    response, conn = response_fixture
    add_document(response)
    if fault in ('missing_document', 'missing_evidence', 'missing_citation'):
        response[{'missing_document': 'documents', 'missing_evidence': 'evidence',
                  'missing_citation': 'citations'}[fault]] = []
    elif fault in ('foreign_document', 'foreign_source', 'foreign_evidence'):
        key = {'foreign_document': 'document_id', 'foreign_source': 'source_id',
               'foreign_evidence': 'evidence_id'}[fault]
        response['candidates'][0]['provenance'][0]['hit'][key] = 'foreign'
    elif fault == 'typed':
        response['candidates'][0]['provenance'][0]['hit']['entry'] = response['candidates'][1]['entry']
    if fault:
        with pytest.raises(ValueError):
            acceptance.validate_response(response, snapshot_conn=conn)
    else:
        assert acceptance.validate_response(response, snapshot_conn=conn) == 2


def test_alias_proof(response_fixture):
    response, conn = response_fixture
    response['candidates'] = response['candidates'][:1]
    response['trusted_pins'] = response['trusted_pins'][:1]
    pin = response['trusted_pins'][0]
    pin.update(match='alias', evidence_id='alias1')
    response['query'] = 'alias'
    assert acceptance.validate_response(response, snapshot_conn=conn) == 1


def test_nested_pack_reuses_root_assets(fixture_pack):
    root, _, snapshot, pack, contract, manifest = fixture_pack
    nested = root / 'build' / 'fullpack'
    nested.mkdir(parents=True)
    model = root / 'model' / 'foo'
    model.parent.mkdir()
    (pack / 'model').rename(model)
    manifest['artifacts']['model']['path'] = '../../model/foo'
    for kind, record in manifest['artifacts'].items():
        for item in record if isinstance(record, list) else [record]:
            if kind != 'model':
                item['path'] = '../../pack/' + item['path']
    manifest['snapshot']['path'] = '../../' + snapshot.name
    assert acceptance.validate_full_manifest(manifest, contract, pack_root=nested) == 7


def test_duplicate_resolved_path(fixture_pack):
    _, _, _, pack, contract, manifest = fixture_pack
    record = copy.deepcopy(manifest['artifacts']['model'])
    record['path'] = '../pack/model'
    manifest['artifacts']['external_data'] = [record]
    with pytest.raises(ValueError, match='duplicate inventory path'):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)


@pytest.fixture
def external_dll(fixture_pack, monkeypatch):
    root, _, _, pack, _, manifest = fixture_pack
    outside = root.parent / (root.name + '-approved.dll')
    outside.write_bytes((pack / 'ort_dll').read_bytes())
    outside.chmod(0o444)
    monkeypatch.setattr(acceptance, '_approved_dll_path', lambda: outside.resolve())
    manifest['artifacts']['ort_dll'] = binding(outside, str(outside))
    try:
        yield outside
    finally:
        outside.chmod(0o666)
        outside.unlink()


def test_exact_approved_external_dll(fixture_pack, external_dll):
    _, _, _, pack, contract, manifest = fixture_pack
    assert acceptance.validate_full_manifest(manifest, contract, pack_root=pack) == 7


@pytest.mark.parametrize('kind', sorted(acceptance.ARTIFACTS - {'ort_dll'}))
def test_no_generic_external_exception(fixture_pack, external_dll, kind):
    _, _, _, pack, contract, manifest = fixture_pack
    record = binding(external_dll, os.path.relpath(external_dll, pack))
    manifest['artifacts'][kind] = [record] if kind == 'external_data' else record
    with pytest.raises(ValueError, match='path escape'):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)


@pytest.mark.parametrize('fault', ['path', 'size', 'sha', 'kind', 'bytes', 'blocked'])
def test_external_dll_authority_fail_closed(fixture_pack, external_dll, monkeypatch, fault):
    _, _, _, pack, contract, manifest = fixture_pack
    record = manifest['artifacts']['ort_dll']
    if fault == 'path':
        other = pack.parent / 'other.dll'
        other.write_bytes(external_dll.read_bytes())
        # Same bytes at another external location do not confer path authority.
        monkeypatch.setattr(acceptance, 'ROOT', pack)
        record['path'] = str(other)
        with pytest.raises(ValueError, match='unapproved external'):
            acceptance._artifact_path(other, 'ort_dll', record)
        return
    if fault == 'size':
        record['size'] += 1
    elif fault == 'sha':
        record['sha256'] = '0' * 64
    elif fault == 'kind':
        record['kind'] = 'ort_dll'
    elif fault == 'bytes':
        external_dll.chmod(0o666)
        external_dll.write_bytes(b'x' * record['size'])
    else:
        def blocked():
            raise ValueError('BLOCKED: approved external ORT DLL binding unavailable')
        monkeypatch.setattr(acceptance, '_approved_dll_path', blocked)
    with pytest.raises(ValueError):
        acceptance.validate_full_manifest(manifest, contract, pack_root=pack)


def test_external_guard_rechecks_authority(fixture_pack, external_dll, monkeypatch):
    _, _, _, pack, _, manifest = fixture_pack
    records = acceptance._verify_inventory(manifest['artifacts'], pack,
                                           expected_dll=(acceptance.pilot.DLL_SIZE,
                                                         acceptance.pilot.DLL_SHA))
    with pytest.raises(ValueError, match='unapproved external'), acceptance._inventory_guard(records):
        monkeypatch.setattr(acceptance, '_approved_dll_path', lambda: pack / 'ort_dll')


def test_mutable_pilot_job_cannot_grant_authority(historical_dll_authority):
    _, job, _, _, _, _ = historical_dll_authority
    job.write_text('{"manifest":"invented.json"}', encoding='utf-8')
    with pytest.raises(ValueError, match='BLOCKED') as error:
        acceptance._approved_dll_path()
    assert error.value.__cause__ is not None
    assert 'mismatch' in str(error.value.__cause__)


@pytest.mark.parametrize('target', ['parent', 'traversed_parent'])
def test_junction_component_rejected(fixture_pack, target):
    if os.name != 'nt' or not hasattr(Path(), 'is_junction'):
        pytest.skip('Windows junction support required')
    root, _, _, pack, contract, manifest = fixture_pack
    moved = root / 'moved-pack'
    pack.rename(moved)
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(pack), str(moved)],
                            capture_output=True, check=False)
    if result.returncode:
        pytest.skip(f'OS does not permit junction fixture: {result.stderr!r}')
    try:
        if target == 'traversed_parent':
            manifest['artifacts']['model']['path'] = '../pack/../moved-pack/model'
            pack = moved
        with pytest.raises(ValueError, match='junction'):
            acceptance.validate_full_manifest(manifest, contract, pack_root=pack)
    finally:
        os.rmdir(root / 'pack')


@pytest.mark.parametrize('limit', [0, 1])
def test_top_level_pins_survive_candidate_truncation(response_fixture, limit):
    response, conn = response_fixture
    response['candidates'] = response['candidates'][:limit]
    assert acceptance.validate_response(response, snapshot_conn=conn) == limit
    assert len(response['trusted_pins']) == 2


@pytest.mark.parametrize('fault', ['query', 'evidence', 'source', 'duplicate', 'match'])
def test_truncated_pin_still_requires_snapshot_closure(response_fixture, fault):
    response, conn = response_fixture
    response['candidates'] = []
    pin = response['trusted_pins'][1]
    if fault == 'query':
        response['query'] = 'unrelated'
    elif fault == 'evidence':
        pin['evidence_id'] = 'invented'
    elif fault == 'source':
        pin['source_id'] = 'invented'
    elif fault == 'duplicate':
        response['trusted_pins'].append(copy.deepcopy(pin))
    else:
        pin['match'] = 'invented'
    with pytest.raises(ValueError):
        acceptance.validate_response(response, snapshot_conn=conn)


@pytest.fixture
def historical_dll_authority(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    monkeypatch.setattr(acceptance, 'ROOT', root)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)

    def git(*args):
        return subprocess.check_output(['git', '-c', 'core.autocrlf=false',
            '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', *args], cwd=root)

    git('init')
    (root / '.gitattributes').write_text('*.json text eol=lf\n', encoding='utf8')
    dll = tmp_path / 'external.dll'
    dll.write_bytes(b'fixture external ORT bytes')
    monkeypatch.setattr(acceptance.pilot, 'DLL_SIZE', dll.stat().st_size)
    monkeypatch.setattr(acceptance.pilot, 'DLL_SHA', full.exact.sha(dll))
    pack = root / acceptance.pilot.PACK
    pack.parent.mkdir(parents=True)
    pack.write_text(json.dumps({'artifacts': {'ort_dll': binding(dll, str(dll))}}), encoding='utf8')
    names = ['configs/p4-rust-pilot-v1.json', 'configs/p4-pilot-job-b.json']
    jobs = {}
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({'manifest': acceptance.pilot.PACK,
                          'frozen_sha256': {acceptance.pilot.PACK: full.exact.sha(pack)}}, indent=2) + '\n'
        path.write_bytes(data.encode('utf8'))
        jobs[name] = path
    git('add', '.')
    git('commit', '-m', 'authorized authority fixture')
    sources = {name: hashlib.sha256(git('show', 'HEAD:' + name)).hexdigest() for name in names}
    authorities = []
    for i, name in enumerate(names):
        jobs[name].write_bytes(jobs[name].read_bytes().replace(b'\n', b'\r\n'))
        digest = full.exact.sha(jobs[name])
        receipt = root / f'receipt{i}.json'
        receipt.write_text(json.dumps({'status': 'PASS', 'job_sha256': digest}), encoding='utf8')
        authorities.append({'path': receipt.name, 'sha256': full.exact.sha(receipt), 'job_sha256': digest})
        assert digest != sources[name]
    monkeypatch.setattr(full, 'PINNED_JOBS', sources)
    monkeypatch.setattr(full, 'HISTORICAL_RUST_JOB_RECEIPT', authorities[0])
    monkeypatch.setattr(full, 'HISTORICAL_MODEL_B_JOB_RECEIPT', authorities[1])
    return root, jobs[names[0]], pack, dll, authorities[0], git


@pytest.mark.parametrize('fault', ['valid', 'raw_wrong', 'source_wrong', 'receipt_bytes',
                                  'receipt_status', 'receipt_job', 'pack_hash', 'dll_size', 'dll_hash'])
def test_source_raw_authority_domains_real_git(historical_dll_authority, monkeypatch, fault):
    root, job, pack, dll, authority, git = historical_dll_authority
    if fault == 'raw_wrong':
        job.write_bytes(job.read_bytes().replace(b'\r\n', b'\n'))
    elif fault == 'source_wrong':
        job.write_bytes(job.read_bytes() + b' \r\n')
        git('add', '.')
        git('commit', '-m', 'unauthorized fixture source')
        job.write_bytes(job.read_bytes()[:-3])  # Correct historical raw, wrong HEAD source.
    elif fault == 'receipt_bytes':
        (root / authority['path']).write_bytes(b'{}')
    elif fault in ('receipt_status', 'receipt_job'):
        path = root / authority['path']
        value = json.loads(path.read_bytes())
        value['status' if fault == 'receipt_status' else 'job_sha256'] = 'FAIL' if fault == 'receipt_status' else '0' * 64
        path.write_text(json.dumps(value), encoding='utf8')
        authority['sha256'] = full.exact.sha(path)  # Independently pinned fixture bytes still require semantic PASS.
    elif fault == 'pack_hash':
        pack.write_bytes(pack.read_bytes() + b' ')
    elif fault == 'dll_size':
        dll.write_bytes(b'x')
    elif fault == 'dll_hash':
        dll.write_bytes(b'x' * dll.stat().st_size)
    if fault == 'valid':
        historical = full.historical_job_bindings(root=root)
        assert historical['configs/p4-rust-pilot-v1.json']['source_blob_sha256'] != authority['job_sha256']
        assert acceptance._approved_dll_path() == dll.resolve()
    else:
        with pytest.raises(ValueError, match='approved external ORT DLL binding unavailable'):
            acceptance._approved_dll_path()


@pytest.mark.parametrize('fault', ['valid', 'path', 'size', 'hash'])
def test_activation_real_authority_inventory_parity(historical_dll_authority, monkeypatch, fault):
    from tools import p4_full_build as build
    root, _, _, dll, _, _ = historical_dll_authority
    monkeypatch.setattr(build, 'ROOT', root)
    record = binding(dll, str(dll))
    if fault == 'path':
        other = dll.with_name('wrong-location.dll')
        other.write_bytes(dll.read_bytes())
        record['path'] = str(other)
    elif fault == 'size':
        record['size'] += 1
    elif fault == 'hash':
        record['sha256'] = '0' * 64
    verified = {'pack': {'artifacts': {'ort_dll': record}}}
    if fault == 'valid':
        assert build.validate_activation_dll(verified) == acceptance._approved_dll_path()
        # Work inventory uses the identical authority primitive, without loading ORT.
        with acceptance._inventory_guard([(dll, record, 'ort_dll')]):
            pass
    else:
        with pytest.raises(ValueError, match='activation external ORT DLL'):
            build.validate_activation_dll(verified)
