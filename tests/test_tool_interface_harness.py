"""Verify acceptance helpers cannot mistake malformed or unproven results for PASS.

These tests are small helper fixtures, not substitutes for real native engine acceptance.
"""
import json
import sqlite3
import subprocess
from copy import deepcopy

import pytest

from tools import tool_integration_validate as topk
from tools import tool_resident_validate as resident


@pytest.fixture
def databases():
    result = {}
    for pack in ('pack-a', 'pack-b'):
        conn = sqlite3.connect(':memory:')
        conn.executescript('''
            CREATE TABLE entries(id INTEGER PRIMARY KEY,kind TEXT,namespace TEXT,value TEXT,conflicted INTEGER);
            CREATE TABLE sources(source_id TEXT PRIMARY KEY);
            CREATE TABLE entry_evidence(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT);
            CREATE TABLE aliases(entry_id INTEGER,source_id TEXT,evidence_id TEXT,status TEXT);
            CREATE TABLE documents(id INTEGER PRIMARY KEY,entry_id INTEGER,source_id TEXT,
                evidence_id TEXT,status TEXT,original TEXT,payload TEXT);
        ''')
        conn.executemany('INSERT INTO entries VALUES(?,?,?,?,0)', [
            (1, 'tag', 'test.tag', 'selected'), (2, 'tag', 'test.tag', 'not-selected'),
            (3, 'character', 'test.character', 'pin-only'),
        ])
        conn.execute("INSERT INTO sources VALUES('same-source-id')")
        conn.executemany('INSERT INTO entry_evidence VALUES(?,?,?,?)', [
            (1, 'same-source-id', 'identity', 'source_backed'),
            (2, 'same-source-id', 'unselected-identity', 'source_backed'),
            (3, 'same-source-id', 'pin-identity', 'source_backed'),
        ])
        conn.executemany('INSERT INTO documents VALUES(?,?,?,?,?,?,?)', [
            (1, 1, 'same-source-id', 'same-evidence-id', 'source_backed', pack + ': body', '{}'),
            (2, 2, 'same-source-id', 'unselected-doc', 'source_backed', 'other body', '{}'),
            (3, 1, 'same-source-id', 'second-doc', 'generated_from_evidence', 'generated body', '{}'),
        ])
        result[pack] = conn
    yield result
    for conn in result.values():
        conn.close()


def candidate(pack='pack-a', value='selected', kind='tag', namespace='test.tag'):
    return {'entry': {'kind': kind, 'namespace': namespace, 'value': value},
            'source_packs': [pack], 'hybrid_rank': 1}


def document(pack='pack-a', identity=1):
    selected = identity != 2
    return {'document_id': str(identity),
            'entry_key': {'kind': 'tag', 'namespace': 'test.tag',
                          'value': 'selected' if selected else 'not-selected'},
            'source_id': 'same-source-id',
            'evidence_id': {1: 'same-evidence-id', 2: 'unselected-doc', 3: 'second-doc'}[identity],
            'status': 'generated_from_evidence' if identity == 3 else 'source_backed',
            'original': {1: pack + ': body', 2: 'other body', 3: 'generated body'}[identity],
            'source_packs': [pack]}


def response(documents=None, candidates=None, pins=None):
    docs = [document()] if documents is None else documents
    proof = [{name: record[name] for name in
              ('document_id', 'source_id', 'evidence_id', 'source_packs')} for record in docs]
    return {'candidates': [candidate()] if candidates is None else candidates,
            'trusted_pins': pins or [], 'documents': docs,
            'evidence': deepcopy(proof), 'citations': deepcopy(proof),
            'sources': [{'source_id': 'same-source-id', 'source_packs': [pack]}
                        for pack in sorted({pack for record in docs for pack in record['source_packs']})]}


def errors(result):
    return {row['error'] for row in result['violations']}


def test_candidate_ranking_is_json_roundtrip_stable():
    data = response()
    data['candidates'][0]['rrf_score'] = 1 / 61
    ranked = topk.candidate_ranking(data)
    assert ranked == json.loads(json.dumps(ranked))


def test_cross_pack_numeric_ids_and_same_typed_key_keep_both_proofs(databases):
    data = response([document('pack-a'), document('pack-b')],
                    [candidate('pack-a'), candidate('pack-b')])
    audit = topk.proof_scope(data, databases)
    assert audit['status'] == 'PASS'
    assert audit['source_qualified_documents'] == 2
    assert audit['allowed_typed_key_origins'] == 2


def test_one_selected_candidate_multiple_documents_generated_text_requires_identity(databases):
    assert topk.proof_scope(response([document(), document(identity=3)]), databases)['status'] == 'PASS'
    databases['pack-a'].execute("DELETE FROM entry_evidence WHERE entry_id=1")
    with pytest.raises(ValueError, match='source-backed identity'):
        topk.proof_scope(response([document(identity=3)]), databases)


def test_unselected_document_is_scope_failure_without_relabeling_runtime(databases):
    audit = topk.proof_scope(response([document(), document(identity=2)]), databases)
    assert audit['status'] == 'FAIL'
    assert errors(audit) == {'document_outside_topk_or_pin'}


def test_missing_all_candidate_proof_and_sources_are_rejected(databases):
    audit = topk.proof_scope(response([]), databases)
    assert 'selected_key_or_pin_has_no_public_proof' in errors(audit)
    data = response()
    data['sources'] = []
    assert 'required_source_missing' in errors(topk.proof_scope(data, databases))


def test_independent_pin_proof_without_document_and_alias_proof(databases):
    pin = candidate(value='pin-only', kind='character', namespace='test.character')
    data = response(pins=[pin])
    for field in ('citations', 'evidence'):
        data[field].append({'source_id': 'same-source-id', 'evidence_id': 'pin-identity',
                            'source_packs': ['pack-a']})
    assert topk.proof_scope(data, databases)['status'] == 'PASS'
    databases['pack-a'].execute("UPDATE entry_evidence SET status='fixture' WHERE entry_id=3")
    assert 'identity_proof_outside_topk_or_pin' in errors(topk.proof_scope(data, databases))


@pytest.mark.parametrize('tamper', ['source_id', 'evidence_id', 'status', 'original', 'entry_key'])
def test_returned_document_must_bind_exact_db_identity_and_bytes(databases, tamper):
    data = response()
    data['documents'][0][tamper] = ('wrong' if tamper != 'entry_key' else
                                   {'kind': 'tag', 'namespace': 'other.tag', 'value': 'selected'})
    with pytest.raises(ValueError, match='binding failed'):
        topk.proof_scope(data, databases)


def test_proof_cannot_borrow_document_id_with_wrong_evidence_and_extra_sources(databases):
    data = response()
    data['citations'].append({'document_id': '1', 'source_id': 'same-source-id',
                              'evidence_id': 'unselected-identity', 'source_packs': ['pack-a']})
    with pytest.raises(ValueError, match='different source/evidence'):
        topk.proof_scope(data, databases)
    data = response()
    databases['pack-a'].execute("INSERT INTO sources VALUES('unused')")
    data['sources'].append({'source_id': 'unused', 'source_packs': ['pack-a']})
    assert 'orphan_source' in errors(topk.proof_scope(data, databases))


def fake_native_resident(config=True):
    opened = {'event': 'opened', 'open_timings_ms': {'model_sessions': 1}}
    responses, encodings = [opened], 0
    for case in resident.request_sequence(config):
        record = {'case_id': case['expected_case_id'], 'status': case['expected_status']}
        if record['status'] == 'PASS':
            encodings += 1
            record['timings_ms'] = {'total': 1, 'query_encodings': 1,
                                    'process_query_encodings': encodings}
        else:
            record.update(error='fixture_request_error', message='fixture rejection', retries=0)
        responses.append(record)
    return responses


def install_fake_process(monkeypatch, messages, exit_code=0, newline=True):
    data = ('\n'.join(json.dumps(record, ensure_ascii=False) for record in messages)
            + ('\n' if newline else '')).encode('utf-8')
    monkeypatch.setattr(resident.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], exit_code, data, b''))


def test_helper_fixed_sequence_native_failure_is_null_not_regex_guessed():
    cases = resident.request_sequence(True)
    assert [case['expected_status'] for case in cases[:3]] == ['PASS', 'FAIL', 'PASS']
    assert cases[3]['input'].startswith('{"case_id":"not-reliably-json"')
    assert cases[3]['expected_case_id'] is None
    assert cases[-1]['expected_case_id'] == ' 結尾-验证😀 '


def test_resident_helper_checks_complete_lifecycle_encoding_and_create_new(tmp_path, monkeypatch):
    install_fake_process(monkeypatch, fake_native_resident())
    result = resident.run('fixture.exe', tmp_path / 'new', config='fixture-config.json')
    assert result['status'] == 'PASS'
    assert result['opened_events'] == 1 and result['exit'] == 0
    assert result['encoding_evidence']['process_query_encodings'] == [1, 2, 3]
    assert result['business_responses'] == len(resident.request_sequence(True))
    with pytest.raises(FileExistsError):
        resident.run('fixture.exe', tmp_path / 'new', config='fixture-config.json')


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'opened_twice', 'fatal_exit',
                                     'wrong_id', 'missing_retry', 'encoded_failure', 'new_session',
                                     'no_final_newline', 'no_message'])
def test_resident_helper_does_not_turn_protocol_or_fatal_failures_into_pass(tmp_path, monkeypatch, mutation):
    messages = fake_native_resident()
    exit_code, newline = 0, True
    if mutation == 'missing':
        messages.pop()
    elif mutation == 'duplicate':
        messages.append(deepcopy(messages[-1]))
    elif mutation == 'opened_twice':
        messages.insert(1, deepcopy(messages[0]))
    elif mutation == 'fatal_exit':
        exit_code = 1
    elif mutation == 'wrong_id':
        messages[4]['case_id'] = 'guessed-from-malformed-JSON'
    elif mutation == 'missing_retry':
        del messages[2]['retries']
    elif mutation == 'encoded_failure':
        messages[3]['timings_ms']['process_query_encodings'] = 3
    elif mutation == 'new_session':
        messages[0]['open_timings_ms']['model_sessions'] = 2
    elif mutation == 'no_final_newline':
        newline = False
    elif mutation == 'no_message':
        del messages[2]['message']
    install_fake_process(monkeypatch, messages, exit_code, newline)
    assert resident.run('fixture.exe', tmp_path / mutation,
                        config='fixture-config.json')['status'] == 'FAIL'
