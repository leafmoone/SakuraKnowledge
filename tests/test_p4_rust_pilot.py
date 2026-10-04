"""Generate-only pack and fail-closed qualification tests."""
import copy
import queue

import pytest

from tools import p4_rust_pilot as pilot


def hit(value, rank=1, namespace='test'):
    return {'entry': {'kind': 'subject', 'namespace': namespace, 'value': value},
            'rank': rank, 'score': .5, 'document_id': str(rank), 'chunk_id': None,
            'source_id': 's', 'evidence_id': 'e'}


def response_fixture():
    lexical = {'raw_hits': [hit('a')], 'trusted_pins': []}
    response = {'status': 'PASS', 'case_id': 'q', 'query': 'query',
                'identity_status': 'not_asserted', 'promoted_identities': [],
                'canonical': None, 'entity_tag': None, 'contract': pilot.fixed_contract(),
                'lexical_hits': lexical['raw_hits'], 'trusted_pins': [],
                'dense_hits': [hit('b')],
                'hybrid': [{**hit('a'), 'hybrid_rank': 1}, {**hit('b'), 'hybrid_rank': 2}],
                'timings_ms': {'total': 10, 'ort': 5}}
    response['candidates'] = copy.deepcopy(response['hybrid'])
    return response, {'case_id': 'q', 'query': 'query'}, lexical


def test_contract_tracks_actual_rust_fixed_values():
    c = pilot.fixed_contract()
    assert c['dimension'] == 1024 and c['normalize'] and c['pooling'] == 'cls'
    assert c['ann'] == {'rows': 52664, 'metric': 'cos', 'dtype': 'f32', 'connectivity': 16,
                        'expansion_add': 256, 'expansion_search': 128,
                        'chunk_depth': 512, 'entry_depth': 100}
    assert c['intra_threads'] == 8 and c['inter_threads'] == 1 and c['sequential']
    assert c['rrf_k'] == 60 and c['pins'] == 'trusted_exact_alias'
    assert pilot.POLICY['warmups'] == 2 and pilot.POLICY['formal'] == 120
    assert pilot.POLICY['retries'] == 0 and pilot.MAX_BYTES == 524288


def test_fusion_pins_ties_and_first_document_rank():
    lex = [hit('b', 1), hit('b', 2), hit('a', 3)]
    dense = [hit('a', 1), hit('c', 2)]
    pins = [{'entry': hit('z')['entry']}, {'entry': hit('y')['entry']}]
    keys = pilot.fusion_ids(lex, dense, pins)
    assert [k[2] for k in keys] == ['y', 'z', 'a', 'b', 'c']
    assert pilot.fusion_ids([hit('b')], [hit('a')], []) == [
        ('subject', 'test', 'a'), ('subject', 'test', 'b')]


def test_actual_rust_fusion_is_independently_checked():
    response, case, lexical = response_fixture()
    pilot.validate_response(response, case, lexical)
    response['hybrid'].reverse()
    with pytest.raises(ValueError, match='actual Rust fused IDs'):
        pilot.validate_response(response, case, lexical)


@pytest.mark.parametrize('mutation,match', [
    (lambda r: r.update(candidates=[]), 'candidate IDs'),
    (lambda r: r.update(promoted_identities=['x']), 'identity promotion'),
    (lambda r: r.update(case_id='other'), 'case/status'),
    (lambda r: r.update(lexical_hits=[]), 'lexical/pin'),
    (lambda r: r['timings_ms'].update(total=5001), 'query budget'),
    (lambda r: r['timings_ms'].update(total=float('nan')), 'invalid timings'),
    (lambda r: r['contract'].update(rrf_k=61), 'response contract'),
])
def test_response_fail_closed(mutation, match):
    response, case, lexical = response_fixture()
    mutation(response)
    with pytest.raises(ValueError, match=match):
        pilot.validate_response(response, case, lexical)


def test_numeric_diagnostics_and_nonfinite_rejection():
    vector = [1 / 32] * 1024
    result = pilot.vector_diagnostics(vector, vector)
    assert result == {'max_component_error': 0, 'norm': 1, 'cosine': 1, 'pass': True}
    changed = vector.copy()
    changed[0] += .001
    assert not pilot.vector_diagnostics(changed, vector)['pass']
    changed[0] = float('nan')
    with pytest.raises(ValueError, match='invalid vectors'):
        pilot.vector_diagnostics(changed, vector)


def test_overlap_gates_include_per_case_minima():
    rows = [{'10': 1., '20': 1., '100': 1.} for _ in range(120)]
    assert all(r['pass'] for r in pilot.ann.approximation(rows).values())
    rows[0]['10'] = .7
    assert not pilot.ann.approximation(rows)['10']['pass']


def test_create_new_and_local_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    pilot.save_new(tmp_path / 'receipt.json', {'status': 'NOT_RUN'})
    with pytest.raises(FileExistsError):
        pilot.save_new(tmp_path / 'receipt.json', {})
    with pytest.raises(ValueError, match='escapes'):
        pilot.local('../outside')


def test_binding_detects_same_size_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    path = tmp_path / 'artifact'
    path.write_bytes(b'old')
    record = pilot.binding(path, tmp_path)
    pilot.verify_binding(record, tmp_path)
    path.write_bytes(b'new')
    with pytest.raises(ValueError, match='changed'):
        pilot.verify_binding(record, tmp_path)


def test_export_inventory_binds_every_tensor_without_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    directory = tmp_path / 'export'
    directory.mkdir()
    records = []
    for name in ('model.onnx', 'tensor-one', 'tensor-two', 'passage-sample.json'):
        (directory / name).write_bytes(name.encode())
        records.append(pilot.binding(directory / name, directory))
    pilot.save_new(directory / 'manifest.json', {'files': records})
    artifacts = pilot.export_artifacts(directory, tmp_path)
    assert len(artifacts['external_data']) == 2
    assert {r['path'] for r in artifacts['external_data']} == {
        'export/tensor-one', 'export/tensor-two'}
    (directory / 'unlisted-tensor').write_bytes(b'new')
    with pytest.raises(ValueError, match='unlisted'):
        pilot.export_artifacts(directory, tmp_path)


def test_export_session_checks_unique_assets_once_and_rejects_raw_links(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    directory = tmp_path / 'export'
    directory.mkdir()
    records = []
    for name in ('model.onnx', 'tensor'):
        path = directory / name
        path.write_bytes(b'asset')
        records.append(pilot.binding(path, directory))
    pilot.save_new(directory / 'manifest.json', {'files': records})
    calls = []
    def verify(path, record):
        calls.append(path)
        pilot.verify_binding(record, directory)
    pilot.export_artifacts(directory, tmp_path, verified=verify)
    assert calls == [directory / 'model.onnx', directory / 'tensor']
    import stat
    original = type(directory).lstat
    def reparse(path):
        info = original(path)
        if path == directory / 'tensor':
            from types import SimpleNamespace
            return SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT, st_mode=info.st_mode)
        return info
    monkeypatch.setattr(type(directory), 'lstat', reparse)
    calls.clear()
    with pytest.raises(ValueError, match='symlink/reparse/junction'):
        pilot.export_artifacts(directory, tmp_path, verified=verify)
    assert directory / 'tensor' not in calls


def test_export_manifest_cannot_escape_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    directory = tmp_path / 'export'
    directory.mkdir()
    model = directory / 'model.onnx'
    model.write_bytes(b'model')
    manifest = {'files': [pilot.binding(model, directory), {'path': '../outside'}]}
    pilot.save_new(directory / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='escapes export'):
        pilot.export_artifacts(directory, tmp_path)


@pytest.mark.parametrize('raw', [b'', b'{}', b'x' * (pilot.MAX_BYTES + 1), b'{"a":NaN}\n'],
                         ids=['eof', 'unterminated', 'oversize', 'nonfinite'])
def test_driver_rejects_eof_unterminated_oversize_nonfinite(raw):
    driver = object.__new__(pilot.Driver)
    driver.lines = queue.Queue()
    driver.lines.put(raw)
    with pytest.raises(ValueError):
        driver.receive(.01)


def test_driver_timeout_no_retry():
    driver = object.__new__(pilot.Driver)
    driver.lines = queue.Queue()
    with pytest.raises(TimeoutError, match='no retry'):
        driver.receive(.001)


def test_failure_keeps_attempt_counts_with_one_asset_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    job_path = tmp_path / 'job.json'
    pilot.save_new(job_path, {'output': 'receipt.json'})
    calls = []
    monkeypatch.setattr(pilot, 'validate_job', lambda job: calls.append('check'))
    def fail(job, receipt):
        receipt['warmups'] = [{'status': 'PASS'}, {'status': 'PASS'}]
        receipt['formal'] = [{'status': 'PASS'}, {'status': 'FAIL', 'error': 'timeout'}]
        raise TimeoutError('timeout')
    monkeypatch.setattr(pilot, 'qualify', fail)
    receipt = pilot.run(job_path)
    assert receipt['status'] == 'FAIL' and calls == ['check']
    assert receipt['formal_counts'] == {'attempted': 2, 'failed': 1, 'not_run': 118}
    assert receipt['warmups_counts'] == {'attempted': 2, 'failed': 0, 'not_run': 0}
    assert receipt['retries'] == 0




def test_pack_cli_is_generate_only(monkeypatch):
    calls = []
    monkeypatch.setattr(pilot, 'build_pack', lambda *args: calls.append(args))
    monkeypatch.setattr(pilot, 'run', lambda *args: pytest.fail('inference not authorized'))
    assert pilot.main(['pack', '--snapshot', 'snapshot', '--ort-dll', 'dll']) == 0
    assert calls == [('snapshot', 'dll', pilot.PACK)]


def test_job_cli_does_not_qualify(monkeypatch):
    calls = []
    monkeypatch.setattr(pilot, 'create_job', lambda *args: calls.append(args))
    monkeypatch.setattr(pilot, 'run', lambda *args: pytest.fail('inference not authorized'))
    assert pilot.main(['job', '--binary', 'binary']) == 0
    assert calls == [('binary', pilot.JOB, pilot.PACK)]
