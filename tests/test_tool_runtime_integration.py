"""Native interface tests over synthetic packs, not real-source/model qualification.

Set SKNOW_RS_TEST_BIN and SKNOW_PILOT_TEST_BIN explicitly to the already-built
Core executables. No test builds a binary, downloads a model, or reads real packs.
"""

import json
import os
import queue
import sqlite3
import subprocess
import threading
from contextlib import ExitStack, closing
from pathlib import Path

import pytest

from tools.modular_validate import normalize as business_json
from tools.normalized_source import build_normalized, normalize
from tools.source_pack import binding
from tools.tool_integration_validate import MAX_BYTES, owners, proof_scope, typed_key

TIMEOUT = 30
ADAPTER = 'examples.source_pack.demo_adapter:DemoAdapter'


def _binary(variable):
    configured = os.environ.get(variable)
    if not configured:
        pytest.skip(f'Native fixture integration NOT_RUN: set {variable} explicitly')
    binary = Path(configured).resolve()
    assert binary.is_file(), f'{variable} is not an executable file: {binary}'
    return binary


@pytest.fixture(scope='module')
def core_binary():
    return _binary('SKNOW_RS_TEST_BIN')


@pytest.fixture(scope='module')
def pilot_binary():
    return _binary('SKNOW_PILOT_TEST_BIN')


def _environment():
    environment = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    # These optional diagnostic hooks would change the raw stderr contract.
    environment.pop('SKNOW_DIAGNOSTICS', None)
    environment.pop('SKNOW_SEARCH_PROFILE_OUT', None)
    return environment


def _json_file(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def _key(kind, value, namespace=None):
    return {'kind': kind, 'namespace': namespace or f'demo.{kind}', 'value': value}


def _build_pack(work, root, pack_id, items, relations=(), *, extra=(), two_documents=False):
    """Build only tiny synthetic normalized records, outside runtime discovery."""
    work.mkdir()
    raw = work / 'raw.json'
    _json_file(raw, {'items': items, 'relations': list(relations)})
    bundle = work / 'normalized'
    manifest = normalize(raw, ADAPTER, bundle, pack_id)
    records_path = bundle / 'records.jsonl'
    records = [json.loads(line) for line in records_path.read_text(encoding='utf-8').splitlines()]
    records.extend(extra)
    source_id = f'synthetic-{pack_id}'
    manifest['sources'][0]['source_id'] = source_id
    namespaces = set()
    for record in records:
        record['source_id'] = source_id
        for field in ('key', 'src', 'dst'):
            if field in record:
                namespaces.add(record[field]['namespace'])
        if record.get('verification_status') == 'native':
            record['method'] = 'demo_native_fact'
        if two_documents and 'documents' in record:
            original = record['documents'][0]
            record['documents'].append({**original, 'original': original['original'] + ' second'})
        for index, document in enumerate(record.get('documents', [])):
            document['evidence_id'] = f"{record['evidence_id']}:document:{index}"
    records_path.write_text(''.join(json.dumps(record, ensure_ascii=False) + '\n'
                                    for record in records), encoding='utf-8')
    manifest['namespaces'] = sorted(namespaces)
    manifest['records'] = {**binding(records_path), 'count': len(records)}
    _json_file(bundle / 'manifest.json', manifest)
    pack = work / 'pack'
    report = build_normalized(bundle, pack)
    assert report['validation'] == 'PASS'
    installed = root / 'packs' / pack_id
    installed.parent.mkdir(parents=True, exist_ok=True)
    # Rename the new fixture; never copy an existing production source pack.
    pack.rename(installed)
    return installed


def _config(root):
    (root / 'bin').mkdir(parents=True, exist_ok=True)
    config = root / 'sknow-config.json'
    _json_file(config, {'packs_directory': 'packs', 'model_directory': 'model',
                        'bin_directory': 'bin'})
    assert not (root / 'model').exists()
    return config


def _small_install(base):
    root = base / '中文 空格 runtime'
    items = [
        {'type': 'subject', 'id': 's-main', 'name': 'Tiny 青空',
         'description': 'tiny alpha 青空 synthetic subject'},
        {'type': 'character', 'id': 'c-native', 'name': 'Native character',
         'description': 'native character source fact'},
        {'type': 'character', 'id': 'c-verified', 'name': 'Verified character',
         'description': 'verified character source fact'},
        {'type': 'character', 'id': 'c-candidate', 'name': 'Candidate character',
         'description': 'candidate character identity, not a verified relation'},
    ]
    relations = [{'character': f'c-{status}', 'subject': 's-main', 'status': status}
                 for status in ('native', 'verified', 'candidate')]
    extra = [
        {'key': _key('tag', 'synthetic_tag', 'danbooru.tag'), 'status': 'source_backed',
         'aliases': [], 'documents': [], 'evidence_id': 'synthetic:tag'},
        {'record_type': 'link', 'src': _key('subject', 's-main'),
         'dst': _key('tag', 'synthetic_tag', 'danbooru.tag'), 'relation': 'entity_tag',
         'verification_status': 'candidate', 'method': 'synthetic_candidate_only',
         'evidence_id': 'synthetic:candidate-mapping'},
    ]
    pack = _build_pack(base / 'builder', root, 'fixture-small', items, relations, extra=extra)
    # The normalized builder requests P3, which must include the native inverse index.
    with closing(sqlite3.connect(pack / 'knowledge.sqlite')) as connection:
        columns = [row[2] for row in connection.execute("PRAGMA index_info('link_dst')")]
        assert columns == ['dst', 'relation', 'verification_status']
        assert connection.execute('SELECT count(*) FROM entries').fetchone()[0] == 5
        assert connection.execute('SELECT count(*) FROM documents').fetchone()[0] == 4
    return _config(root), pack


@pytest.fixture(scope='module')
def small_install(tmp_path_factory, core_binary):
    return _small_install(tmp_path_factory.mktemp('native-small'))


@pytest.fixture(scope='module')
def resident_install(tmp_path_factory, pilot_binary):
    return _small_install(tmp_path_factory.mktemp('native-resident'))


def _run(binary, args, *, input_bytes=None):
    return subprocess.run([str(binary), *map(str, args)], input=input_bytes,
                          capture_output=True, env=_environment(), timeout=TIMEOUT, check=False)


def _lines(raw):
    assert raw.endswith(b'\n'), repr(raw[:500])
    lines = raw.split(b'\n')[:-1]
    assert lines and all(lines), repr(raw[:500])
    assert all(len(line) + 1 <= MAX_BYTES for line in lines)
    values = [json.loads(line.decode('utf-8', errors='strict')) for line in lines]
    assert all(isinstance(value, dict) for value in values)
    return values


def _single(result):
    assert result.returncode == 0, (result.returncode, result.stdout[:500], result.stderr)
    records = _lines(result.stdout)
    assert len(records) == 1
    assert result.stderr == b'', result.stderr
    return records[0]


def _request(case_id, query='tiny', **options):
    return {'case_id': case_id, 'query': query, **options}


def _input(requests):
    return ''.join((request if isinstance(request, str) else
                    json.dumps(request, ensure_ascii=False)) + '\n'
                   for request in requests).encode('utf-8')


def _resident(binary, config, requests):
    result = _run(binary, ['--config', config], input_bytes=_input(requests))
    assert result.returncode == 0, (result.returncode, result.stdout[:500], result.stderr)
    records = _lines(result.stdout)
    assert len(records) == len(requests) + 1
    assert sum(record.get('event') == 'opened' for record in records) == 1
    opened = records[0]
    assert opened['event'] == 'opened' and opened['retries'] == 0
    assert opened['open_timings_ms']['model_sessions'] == 0
    profiles = _lines(result.stderr)
    assert len(profiles) == len(requests)
    for raw, response, profile in zip(result.stdout.split(b'\n')[1:-1], records[1:], profiles):
        assert response['timings_ms']['process_query_encodings'] == 0
        assert profile['case_id'] == response['case_id']
        assert profile['sent_bytes'] == len(raw) + 1 <= MAX_BYTES
        assert profile['response_too_large'] == (response.get('error') == 'response_too_large')
        if response['status'] == 'PASS':
            assert response['timings_ms']['query_encodings'] == 0
            assert response['semantic_capable_packs'] == []
            assert response['dense_hits'] == []
            assert response['lexical_mode'] == 'trusted_documents_and_identity'
        else:
            assert response['status'] == 'FAIL' and response['retries'] == 0
            assert isinstance(response['message'], str) and response['message']
    assert not (config.parent / 'model').exists()
    return records[1:], profiles


def test_native_resident_pass_invalid_limit_pass_eof(pilot_binary, resident_install):
    config, _ = resident_install
    responses, _ = _resident(pilot_binary, config, [
        _request('q1', source='fixture-small'),
        _request('q2', limit='bad'),
        _request('查询-三-雪', query='青空', limit=1, source=['fixture-small']),
    ])
    assert [response['case_id'] for response in responses] == ['q1', 'q2', '查询-三-雪']
    assert [response['status'] for response in responses] == ['PASS', 'FAIL', 'PASS']
    assert responses[1]['error'] == 'invalid_limit'
    assert responses[0]['documents'][0]['original'] == 'tiny alpha 青空 synthetic subject'
    assert responses[2]['documents'][0]['original'] == 'tiny alpha 青空 synthetic subject'


def test_native_resident_protocol_errors_keep_ids_and_continue(pilot_binary, resident_install):
    config, _ = resident_install
    invalid = [
        ('{"case_id":"not-recoverable-json","query":', None, 'invalid_json'),
        ([], None, 'invalid_request'),
        (None, None, 'invalid_request'),
        ({'query': 'tiny'}, None, 'invalid_case_id'),
        (_request(None), None, 'invalid_case_id'),
        (_request(123), None, 'invalid_case_id'),
        (_request(''), None, 'invalid_case_id'),
        (_request('source-type', source=42), 'source-type', 'invalid_source'),
        (_request('source-empty', source=[]), 'source-empty', 'invalid_source'),
        (_request('source-path', source='../fixture-small'), 'source-path', 'invalid_source'),
        (_request('source-comma', source='fixture-small,'), 'source-comma', 'invalid_source'),
        (_request('source-missing', source='not-installed'), 'source-missing', 'source_pack_missing'),
        (_request('kind-invalid', kind='not-a-kind'), 'kind-invalid', 'invalid_kind'),
        (_request('kind-type', kind=7), 'kind-type', 'invalid_filter'),
        (_request('namespace-empty', namespace=' '), 'namespace-empty', 'invalid_namespace'),
        (_request('namespace-long', namespace='n' * 1025), 'namespace-long', 'invalid_namespace'),
        (_request('namespace-type', namespace=[]), 'namespace-type', 'invalid_filter'),
        (_request('query-long', query='日' * 4097), 'query-long', 'invalid_query'),
        (_request('query-type', query=9), 'query-type', 'invalid_query'),
        (_request('limit-zero', limit=0), 'limit-zero', 'invalid_limit'),
        (_request('limit-101', limit=101), 'limit-101', 'invalid_limit'),
        (_request('limit-bool', limit=True), 'limit-bool', 'invalid_limit'),
    ]
    responses, _ = _resident(pilot_binary, config, [row[0] for row in invalid] + [
        _request('末尾-正常', query='青空', source='fixture-small', limit=1),
    ])
    for response, (_, case_id, error) in zip(responses, invalid):
        assert response['case_id'] == case_id
        assert response['status'] == 'FAIL' and response['error'] == error
        assert 'documents' not in response and 'candidates' not in response
    assert responses[-1]['case_id'] == '末尾-正常' and responses[-1]['status'] == 'PASS'


def test_native_resident_response_too_large_then_next_pass(pilot_binary, tmp_path):
    root = tmp_path / 'runtime'
    # Two independent exact alias pins keep both giant source documents at Top1.
    # Their complete UTF-8 bodies alone exceed 2 MiB; no clipping can fake PASS.
    body = 'huge ' + '日' * (MAX_BYTES // 6 + 4096)
    assert MAX_BYTES < 2 * len(body.encode('utf-8')) < 3 * 1024 * 1024
    items = [{'type': 'subject', 'id': f'huge-{index}', 'name': 'huge', 'description': body}
             for index in range(2)]
    items.append({'type': 'subject', 'id': 'tiny-only', 'name': 'tinysolo',
                  'description': 'tinysolo intact 小さい source text'})
    _build_pack(tmp_path / 'builder', root, 'fixture-giant', items)
    config = _config(root)
    responses, profiles = _resident(pilot_binary, config, [
        _request('巨大-完整', query='huge', limit=1, source='fixture-giant'),
        _request('tiny-next', query='tinysolo', limit=1, source='fixture-giant'),
    ])
    oversized, tiny = responses
    assert oversized['case_id'] == '巨大-完整'
    assert oversized['status'] == 'FAIL' and oversized['error'] == 'response_too_large'
    assert oversized['limit_bytes'] == MAX_BYTES
    assert oversized['response_bytes'] == profiles[0]['response_bytes'] > MAX_BYTES
    assert 'documents' not in oversized and 'candidates' not in oversized
    assert tiny['case_id'] == 'tiny-next' and tiny['status'] == 'PASS'
    assert len(tiny['documents']) == 1
    assert tiny['documents'][0]['original'] == items[-1]['description']
    assert tiny['documents'][0]['source_packs'] == ['fixture-giant']
    assert profiles[1]['response_too_large'] is False


@pytest.mark.parametrize('invalid_config', ['missing', 'malformed', 'asset-path'])
def test_native_pilot_initialization_failure_has_no_opened(pilot_binary, tmp_path, invalid_config):
    config = tmp_path / 'sknow-config.json'
    if invalid_config == 'malformed':
        config.write_bytes(b'{not-json')
    elif invalid_config == 'asset-path':
        _json_file(config, {'packs_directory': '../packs', 'model_directory': 'model',
                            'bin_directory': 'bin'})
    result = _run(pilot_binary, ['--config', config], input_bytes=_input([_request('never-run')]))
    assert result.returncode != 0
    assert result.stdout == b'', result.stdout
    assert result.stderr and b'opened' not in result.stderr
    assert b'never-run' not in result.stderr


def _start_pilot(binary, config):
    return subprocess.Popen([str(binary), '--config', str(config)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_environment())


def _opened(process):
    # A blocked pipe read must not hang pytest if initialization regresses.
    received = queue.Queue()

    def read_line():
        try:
            received.put(process.stdout.readline())
        except OSError as error:
            received.put(error)

    reader = threading.Thread(target=read_line, daemon=True)
    reader.start()
    try:
        raw = received.get(timeout=TIMEOUT)
    except queue.Empty:
        process.kill()
        reader.join(timeout=TIMEOUT)
        process.wait(timeout=TIMEOUT)
        pytest.fail('native pilot did not deliver opened before the timeout')
    reader.join(timeout=TIMEOUT)
    assert isinstance(raw, bytes), raw
    records = _lines(raw)
    assert len(records) == 1 and records[0]['event'] == 'opened'
    assert records[0]['open_timings_ms']['model_sessions'] == 0
    assert records[0]['retries'] == 0
    return raw


def _communicate(process, payload):
    try:
        return process.communicate(input=payload, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=TIMEOUT)
        raise


def _stop(process):
    if process.poll() is None:
        process.kill()
        process.wait(timeout=TIMEOUT)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def test_native_lexical_corruption_after_open_is_fatal_once(pilot_binary, tmp_path):
    config, pack = _small_install(tmp_path)
    process = _start_pilot(pilot_binary, config)
    try:
        opened = _opened(process)
        # Only this test's fresh fixture is mutated. Lexical DB open is lazy.
        (pack / 'knowledge.sqlite').write_bytes(b'corrupt synthetic snapshot, not SQLite')
        stdout, stderr = _communicate(process, _input([
            _request('fatal-db', source='fixture-small'), _request('must-not-run'),
        ]))
        assert process.returncode != 0
        records = _lines(opened + stdout)
        assert len(records) == 2
        assert sum(row.get('event') == 'opened' for row in records) == 1
        failure = records[1]
        assert failure['case_id'] == 'fatal-db' and failure['status'] == 'FAIL'
        assert failure['error'] == 'runtime_error' and failure['retries'] == 0
        assert failure['timings_ms']['process_query_encodings'] == 0
        assert b'must-not-run' not in stdout + stderr
        diagnostics = [json.loads(line) for line in stderr.split(b'\n') if line.startswith(b'{')]
        assert len(diagnostics) == 1 and diagnostics[0]['case_id'] == 'fatal-db'
        assert diagnostics[0]['sent_bytes'] == len(stdout)
        assert diagnostics[0]['response_too_large'] is False
        assert stderr.strip(), stderr
    finally:
        _stop(process)


def test_native_stdout_broken_pipe_is_fatal_without_false_delivery(pilot_binary, resident_install):
    config, _ = resident_install
    process = _start_pilot(pilot_binary, config)
    try:
        opened = _opened(process)
        process.stdout.close()
        process.stdout = None
        stdout, stderr = _communicate(process, _input([_request('broken-pipe')]))
        assert process.returncode != 0
        assert stdout is None  # No readable stdout remains; no delivered FAIL is claimed.
        assert len(_lines(opened)) == 1
        diagnostics = [json.loads(line) for line in stderr.split(b'\n') if line.startswith(b'{')]
        assert len(diagnostics) == 1, stderr
        diagnostic = diagnostics[0]
        assert diagnostic['case_id'] == 'broken-pipe' and diagnostic['phase'] == 'transmission'
        assert isinstance(diagnostic['error'], str) and diagnostic['error']
        assert 'sent_bytes' not in diagnostic and 'status' not in diagnostic
        assert b'"status":"FAIL"' not in stderr
    finally:
        _stop(process)


BAD_CLI = [
    [], ['unknown-command'], ['retrieve', 'tiny', '--unknown'],
    ['retrieve', 'tiny', '--topk'], ['retrieve', 'tiny', '--topk', '--source', 'fixture-small'],
    ['retrieve', 'tiny', '--limit', '0'], ['retrieve', 'tiny', '--limit', '101'],
    ['retrieve', 'tiny', '--topk', '0'], ['retrieve', 'tiny', '--topk', '101'],
    ['retrieve', 'tiny', '--limit', '1', '--topk', '5'],
    ['lookup', 'tiny', '--limit', '1'], ['inspect', '--key'], ['packs', '--source', 'fixture-small'],
    ['retrieve', 'tiny', '--direction', 'in'], ['related', 's-main'],
    ['resolve-tag', 'tiny', '--target-namespace', 'danbooru.tag',
     '--target-tag-namespace', 'other.tag'],
    ['search', 'tiny', '--source', ''], ['search', 'tiny', '--source', ',fixture-small'],
    ['search', 'tiny', '--source', 'fixture-small,'],
    ['search', 'tiny', '--source', 'fixture-small,,other'],
    ['related', 'subject', 'demo.subject', 's-main', '--direction', 'sideways'],
]


@pytest.mark.parametrize('arguments', BAD_CLI)
def test_native_modular_cli_usage_error_precedes_config_io(core_binary, tmp_path, arguments):
    missing = tmp_path / 'must-not-open-config.json'
    assert not missing.exists()
    result = _run(core_binary, ['--config', missing, *arguments])
    assert result.returncode == 2
    assert result.stdout == b'', result.stdout
    errors = _lines(result.stderr)
    assert len(errors) == 1 and errors[0]['error'] == 'UsageError'
    assert isinstance(errors[0]['message'], str) and errors[0]['message']
    assert missing.name not in errors[0]['message']


def test_native_repeated_and_comma_sources_select_same_pack(core_binary, small_install):
    config, _ = small_install
    common = ['--config', config, 'search', 'tiny', '--topk', '5']
    once = _single(_run(core_binary, [*common, '--source', 'fixture-small']))
    repeated = _single(_run(core_binary, [*common, '--source', 'fixture-small,fixture-small',
                                        '--source', 'fixture-small']))
    assert repeated == once
    assert repeated['participating_packs'] == ['fixture-small']
    assert repeated['candidates']
    assert all(candidate['source_packs'] == ['fixture-small']
               for candidate in repeated['candidates'])


@pytest.mark.parametrize('form', ['value', 'legacy'])
@pytest.mark.parametrize('direction,kind,value', [
    ('out', 'character', 'c-native'), ('out', 'character', 'c-verified'),
    ('in', 'subject', 's-main'),
])
def test_native_related_matches_direct_business_json(core_binary, small_install,
                                                    form, direction, kind, value):
    config, pack = small_install
    namespace = f'demo.{kind}'
    suffix = ['--direction', direction, '--relation', 'character_of', '--limit', '5']
    if form == 'value':
        arguments = [value, '--kind', kind, '--namespace', namespace, *suffix]
    else:
        arguments = [kind, namespace, value, *suffix]
    direct = _single(_run(core_binary, ['related', pack / 'knowledge.sqlite', *arguments]))
    modular = _single(_run(core_binary, ['--config', config, 'related', *arguments,
                                       '--source', 'fixture-small']))
    assert business_json(modular) == business_json(direct)
    assert modular['status'] == 'found'
    assert modular['entry_key'] == _key(kind, value)
    relations = modular['relations']
    assert len(relations) == (2 if direction == 'in' else 1)
    assert all(row['source_packs'] == ['fixture-small'] for row in relations)
    if direction == 'in':
        assert {row['src']['value'] for row in relations} == {'c-native', 'c-verified'}
        assert {row['verification_status'] for row in relations} == {'native', 'verified'}
        assert all(row['dst'] == _key('subject', 's-main') for row in relations)
    else:
        assert relations[0]['dst'] == _key('subject', 's-main')
        assert relations[0]['verification_status'] == value.removeprefix('c-')
    assert all(row['source_id'] == 'synthetic-fixture-small' and row['evidence_id']
               for row in relations)


def test_native_resolve_target_alias_preserves_candidate_unmapped(core_binary, small_install):
    config, pack = small_install
    source_key = ['s-main', '--key', '--kind', 'subject', '--namespace', 'demo.subject',
                  '--limit', '5']
    direct = _single(_run(core_binary, ['resolve-tag', pack / 'knowledge.sqlite', *source_key,
                                      '--target-namespace', 'danbooru.tag']))
    values = []
    for alias in ('--target-namespace', '--target-tag-namespace'):
        values.append(_single(_run(core_binary, ['--config', config, 'resolve-tag', *source_key,
                                                alias, 'danbooru.tag', '--source', 'fixture-small'])))
    assert values[0] == values[1]
    assert business_json(values[0]) == business_json(direct)
    assert values[0]['status'] == 'entity_found_tag_unmapped'
    assert values[0]['source_key'] == _key('subject', 's-main')
    assert values[0]['tag_key'] is None and values[0]['canonical_status'] == 'unknown'
    assert values[0]['relations'] == [] and values[0]['evidence_chain'] == []
    unknown_target = _run(core_binary, ['--config', config, 'resolve-tag', *source_key,
                                       '--target-namespace', 'unknown.tag'])
    assert unknown_target.returncode == 2 and unknown_target.stdout == b''
    assert _lines(unknown_target.stderr)[0]['error'] == 'ValueError'


@pytest.fixture(scope='module')
def many_install(tmp_path_factory, core_binary):
    base = tmp_path_factory.mktemp('native-topk')
    root = base / 'runtime'
    packs = {}
    for pack_id in ('fixture-a', 'fixture-b'):
        items = [{'type': 'subject', 'id': f's{index}',
                  'name': 'anchor' if index >= 5 else f'Entry {index}',
                  'description': f'orbit anchor complete 小さい body {pack_id} {index}'}
                 for index in range(7)]
        packs[pack_id] = _build_pack(base / pack_id, root, pack_id, items, two_documents=True)
    return _config(root), packs


@pytest.mark.parametrize('topk', [1, 5])
@pytest.mark.parametrize('query,has_pins', [('orbit', False), ('anchor', True)])
def test_native_topk_closes_documents_proofs_and_sources(core_binary, many_install,
                                                        topk, query, has_pins):
    config, packs = many_install
    result = _run(core_binary, ['--config', config, 'retrieve', query, '--topk', topk,
                                '--source', 'fixture-a,fixture-b', '--source', 'fixture-a'])
    assert result.returncode == 0, (result.stdout[:500], result.stderr)
    records, profiles = _lines(result.stdout), _lines(result.stderr)
    assert len(records) == len(profiles) == 1
    response, profile = records[0], profiles[0]
    assert profile['sent_bytes'] == profile['response_bytes'] == len(result.stdout) <= MAX_BYTES
    assert profile['response_too_large'] is False
    assert response['status'] == 'PASS'
    assert response['timings_ms']['query_encodings'] == 0
    assert response['timings_ms']['process_query_encodings'] == 0
    assert response['semantic_capable_packs'] == [] and response['dense_hits'] == []
    assert response['identity_status'] == 'not_asserted' and response['promoted_identities'] == []
    assert response['canonical'] is None and response['entity_tag'] is None
    candidates = response['candidates']
    assert len(candidates) == topk
    assert [candidate['hybrid_rank'] for candidate in candidates] == list(range(1, topk + 1))
    assert all(set(candidate['source_packs']) == set(packs) for candidate in candidates)
    pins = response['trusted_pins']
    assert bool(pins) == has_pins
    if has_pins:
        assert {typed_key(pin) for pin in pins} == {('subject', 'demo.subject', 's5'),
                                                   ('subject', 'demo.subject', 's6')}
        if topk == 1:
            assert {typed_key(pin) for pin in pins} - {typed_key(candidates[0])}
    allowed = {(pack, typed_key(record)) for record in [*candidates, *pins]
               for pack in owners(record, packs)}
    expected_documents = set()
    with ExitStack() as stack:
        connections = {pack: stack.enter_context(closing(sqlite3.connect(
            (path / 'knowledge.sqlite').resolve().as_uri() + '?mode=ro', uri=True,
        ))) for pack, path in packs.items()}
        for pack, connection in connections.items():
            assert connection.execute('SELECT count(*) FROM entries').fetchone()[0] == 7
            assert connection.execute('SELECT count(*) FROM documents').fetchone()[0] == 14
            assert connection.execute('SELECT min(id) FROM documents').fetchone()[0] == 1
            for document_id, kind, namespace, value in connection.execute(
                'SELECT d.id,e.kind,e.namespace,e.value FROM documents d '
                'JOIN entries e ON e.id=d.entry_id',
            ):
                if (pack, (kind, namespace, value)) in allowed:
                    expected_documents.add((pack, str(document_id)))
        scope = proof_scope(response, connections)
        assert scope['status'] == 'PASS', scope
    documents = response['documents']
    actual_documents = {(pack, str(document['document_id'])) for document in documents
                        for pack in owners(document, packs)}
    assert actual_documents == expected_documents
    assert len(documents) == len(actual_documents) == (8 if has_pins and topk == 1 else topk * 4)
    assert scope['source_qualified_documents'] == len(documents)
    # Same numeric document IDs and typed keys in two packs must not deduplicate proofs.
    assert {did for pack, did in actual_documents if pack == 'fixture-a'} == {
        did for pack, did in actual_documents if pack == 'fixture-b'}
    assert {(pack, source['source_id']) for source in response['sources']
            for pack in owners(source, packs)} == {
                (pack, f'synthetic-{pack}') for pack in packs}
    for field in ('citations', 'evidence'):
        proofs = response[field]
        locators = [(pack, str(proof['document_id'])) for proof in proofs
                    if proof.get('document_id') is not None for pack in owners(proof, packs)]
        assert set(locators) == actual_documents and len(locators) == len(actual_documents)
    assert not (config.parent / 'model').exists()
