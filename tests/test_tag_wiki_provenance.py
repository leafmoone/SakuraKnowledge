import json

import pytest

from sakura_knowledge.adapters import iter_tag_wiki
from sakura_knowledge.tag_wiki_provenance import ProofRejected, derive, digest, whitespace

BODY = 'A character with brown colored eyes. This description is supported by the actual source page.'


def record(text=BODY, status='source_backed', table='full_annotation_cache'):
    return {'table': table, 'locator': 'cache_key:k', 'tag_key': 'brown_eyes', 'status': status,
            'text': json.dumps({'tag_key': 'brown_eyes', 'detailed_description': text}) if table == 'full_annotation_cache' else text}


def wiki(body=BODY, deleted=0):
    return {'wiki_id': 1, 'body': body, 'is_deleted': deleted}


@pytest.mark.parametrize('status', ['source_backed', 'verified', 'ai_annotated', 'no_reference'])
def test_status_alone_not_proof(status):
    with pytest.raises(ProofRejected, match='text_not_derivable'):
        derive(record('Producer fabricated a claim with no supporting source.', status), wiki(), [{'wiki_id': 1}])


@pytest.mark.parametrize('status', ['source_backed', 'verified', 'ai_annotated', 'no_reference'])
def test_independently_proved_text_ignores_status(status):
    text, p = derive(record(status=status), wiki(), [{'wiki_id': 1}])
    assert text == BODY and p['method'] == 'whitespace_prefix'
    assert p['trusted_text_sha256'] == digest(BODY)
    assert p['wiki_body_sha256'] == digest(BODY)
    assert p['tag_key']['namespace'] == 'local.tag_aggregate'
    assert 'identity_status' not in p and 'verification_status' not in p


@pytest.mark.parametrize('page,candidates,reason', [
    (wiki(), [], 'no_tag_evidence'),
    (None, [{'wiki_id': 1}], 'missing_wiki'),
    (wiki(deleted=1), [{'wiki_id': 1}], 'deleted_wiki'),
    (wiki(body=''), [{'wiki_id': 1}], 'empty_wiki'),
    (wiki(), [{'wiki_id': 1}, {'wiki_id': 2}], 'multiple_wiki_candidates'),
])
def test_invalid_candidate_closed(page, candidates, reason):
    with pytest.raises(ProofRejected, match=reason):
        derive(record(), page, candidates)


def test_duplicate_candidate_rows_same_page_not_ambiguous():
    assert derive(record(), wiki(), [{'wiki_id': 1}, {'wiki_id': 1}])[0] == BODY


def test_case_change_not_normalization():
    with pytest.raises(ProofRejected, match='text_not_derivable'):
        derive(record(BODY.upper()), wiki(), [{'wiki_id': 1}])


def test_punctuation_change_rejected():
    with pytest.raises(ProofRejected, match='text_not_derivable'):
        derive(record(BODY.replace('.', '!')), wiki(), [{'wiki_id': 1}])


def test_whitespace_only_normalization():
    assert derive(record(BODY.replace(' ', '\n\t')), wiki(), [{'wiki_id': 1}])[0] == BODY


def test_short_excerpt_rejected():
    with pytest.raises(ProofRejected, match='too_short'):
        derive(record('A character'), wiki(), [{'wiki_id': 1}])


def test_contiguous_excerpt():
    text, proof = derive(record('This description is supported by the actual source page.'), wiki(), [{'wiki_id': 1}])
    assert text in BODY and proof['method'] == 'whitespace_contiguous_excerpt'


def test_invalid_json():
    r = record()
    r['text'] = '{'
    with pytest.raises(ProofRejected, match='json_parse'):
        derive(r, wiki(), [{'wiki_id': 1}])


def test_wrong_json_tag():
    r = record()
    r['text'] = json.dumps({'tag_key': 'wrong', 'detailed_description': BODY})
    with pytest.raises(ProofRejected, match='json_schema'):
        derive(r, wiki(), [{'wiki_id': 1}])


def test_annotations_same_proof():
    assert derive(record(table='annotations'), wiki(), [{'wiki_id': 1}])[0] == BODY


def test_unproved_fields_not_in_output():
    r = record()
    r['text'] = json.dumps({'tag_key': 'brown_eyes', 'detailed_description': BODY, 'short_summary': 'Fabricated claim', 'safety_label': 'safe'})
    text, p = derive(r, wiki(), [{'wiki_id': 1}])
    assert text == BODY and 'safe' not in p


def test_digest_exact_utf8_bytes():
    assert digest('a\nb') != digest('a b')
    assert whitespace('a\u00a0b') == 'a b'


@pytest.mark.parametrize('field', ['wiki_body_sha256', 'trusted_text_sha256', 'method'])
def test_proof_tamper_rejected(field):
    from sakura_knowledge.tag_wiki_provenance import verify_text_proof
    text, p = derive(record(), wiki(), [{'wiki_id': 1}])
    assert verify_text_proof(text, BODY, p)
    p[field] = 'wrong'
    with pytest.raises(ProofRejected):
        verify_text_proof(text, BODY, p)


def test_adapter_opt_in_uses_same_proof_envelope():
    source = 'build/source-cache-v2/tag_wiki-frozen.sqlite'
    dan = 'build/modular-components/SakuraKnowledge-pack-danbooru/knowledge.sqlite'
    with open('build/tag-provenance-audit-v1.proofs.jsonl', encoding='utf-8') as stream:
        expected = json.loads(next(stream))
    actual = None
    for entity in iter_tag_wiki(source, sample=1, danbooru_snapshot=dan):
        if entity.get('documents') and entity['documents'][0]['status'] == 'generated_from_evidence':
            actual = entity['documents'][0]
            break
    assert actual is not None
    assert actual['original'] == expected['text']
    assert actual['text_provenance'] == expected['text_provenance']
