import json

import pytest

from tools import p4_tokenizer_parity as parity


def test_scan_checks_every_chunk_and_query(monkeypatch):
    calls = []

    def checked(raw, wrapper, texts, prefix, maximum):
        calls.append((texts, prefix, maximum))
        return {}, [len(texts[0])]

    monkeypatch.setattr(parity.pilot, 'checked_tokens', checked)
    contract = {'passage_prefix': 'p: ', 'query_prefix': 'q: ', 'max_sequence_tokens': 9}
    chunks = [{'text': 'a', 'inference_token_count': 1},
              {'text': 'bb', 'inference_token_count': 2}]
    cases = [{'case_id': 'q1', 'query': 'ccc'}]
    result = parity.scan(None, None, iter(chunks), cases, contract, 2)
    assert result['chunk_count'] == 2
    assert result['max_passage_tokens'] == 2
    assert result['query_count'] == 1
    assert calls == [(['a'], 'p: ', 9), (['bb'], 'p: ', 9), (['ccc'], 'q: ', 9)]
    with pytest.raises(ValueError, match='chunk count mismatch'):
        parity.scan(None, None, iter(chunks), cases, contract, 3)
    chunks[1]['inference_token_count'] = 1
    with pytest.raises(ValueError, match='token count mismatch'):
        parity.scan(None, None, iter(chunks), cases, contract, 2)


def test_failure_receipt_exclusive_no_model_loading(tmp_path):
    output = tmp_path / 'receipt.json'
    assert parity.run(tmp_path / 'missing.json', output) == 1
    receipt = json.loads(output.read_text(encoding='utf-8'))
    assert receipt['status'] == 'FAIL'
    assert receipt['error']['type'] == 'FileNotFoundError'
    assert receipt['model_loaded'] is False
    assert receipt['embedding_executed'] is False
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        parity.run(tmp_path / 'missing.json', output)
    assert output.read_bytes() == original
