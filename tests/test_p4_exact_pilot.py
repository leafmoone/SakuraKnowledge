import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from tools import p4_exact_pilot as pilot


def row(value, chunk, namespace='test'):
    return {'entry_key': {'kind': 'tag', 'namespace': namespace, 'value': value},
            'chunk_id': chunk, 'document_id': 1, 'source_id': 's', 'evidence_id': 'e'}


def test_exact_max_entry_and_ties_are_typed(tmp_path):
    vectors = np.array([[1, 0], [0, 1], [1, 0], [1, 0]], dtype=np.float32)
    mapping = [row('z', 'a'), row('z', 'b'), row('a', 'c'), row('a', 'd', 'other')]
    hits = pilot.exact_rank(vectors, mapping, vectors[0], block_size=1)
    assert [(h['entry']['namespace'], h['entry']['value']) for h in hits] == [
        ('other', 'a'), ('test', 'a'), ('test', 'z')]
    assert hits[-1]['chunk_id'] == 'a'
    db = tmp_path / 'mapping.sqlite'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY, metadata TEXT)')
        connection.executemany('INSERT INTO chunks VALUES (?, ?)', enumerate(map(json.dumps, mapping)))
    disk = pilot.DiskMapping(db)
    try:
        assert pilot.exact_rank(vectors, disk, vectors[0], block_size=3) == hits
    finally:
        disk.connection.close()


def test_best_chunk_tie_deterministic():
    vectors = np.array([[1, 0], [1, 0]], dtype=np.float32)
    assert pilot.exact_rank(vectors, [row('a', 'z'), row('a', 'a')], vectors[0])[0]['chunk_id'] == 'a'


def test_depth_applies_after_entry_aggregation():
    vectors = np.tile(np.array([[1, 0]], dtype=np.float32), (105, 1))
    hits = pilot.exact_rank(vectors, [row(f'{i:03}', str(i)) for i in range(105)], vectors[0])
    assert len(hits) == 100 and hits[-1]['entry']['value'] == '099'


@pytest.mark.parametrize('vectors', [np.array([[0, 0]], dtype=np.float32),
    np.array([[1, 0]], dtype=np.float64), np.array([[np.nan, 0]], dtype=np.float32)])
def test_invalid_vectors(vectors):
    with pytest.raises(ValueError):
        pilot.validate_vectors(vectors, 2)


def test_summary_counts_failures_and_linear_percentiles():
    summary = pilot.summarize([{'elapsed_ms': n, 'status': 'FAIL' if n == 30 else 'PASS'}
                              for n in range(1, 31)] + [{'status': 'NOT_RUN'}])
    assert summary['failures'] == 1 and summary['attempts'] == 30 and summary['not_run'] == 1
    assert summary['p50_ms'] == 15.5 and summary['p95_ms'] == pytest.approx(28.55)
    assert pilot.summarize([{'status': 'NOT_RUN'}])['p50_ms'] is None


def test_measure_does_not_retry(monkeypatch):
    attempts = []
    def fail(case):
        attempts.append(case)
        raise RuntimeError('injected')
    monkeypatch.setattr(pilot, 'rss', lambda: {'rss_bytes': 4})
    record = pilot.measure(fail, {'case_id': 'a'})
    assert record['status'] == 'FAIL' and len(attempts) == 1 and record['rss_bytes'] == 4


def test_build_streams_actual_text_to_mmap(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    text = 'actual chunk, not a title or search field'
    records = [dict(row('a', str(i)), text=text, search_text='DO NOT EMBED',
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    tokenizer_inventory_sha256='inventory', inference_token_count=4) for i in range(3)]
    chunks = tmp_path / 'chunks.jsonl'
    chunks.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
    (tmp_path / 'manifest.json').write_text('{}', encoding='utf-8')
    calls = []
    class SyntheticEncoder:
        info: ClassVar[dict[str, bool]] = {'synthetic': True}
        def __init__(self, *args):
            pass
        def encode(self, texts):
            calls.append(texts)
            return np.tile(np.array([[1, 0]], dtype=np.float32), (len(texts), 1)), [4] * len(texts)
    job = {'index': 'index', 'device': 'cpu', 'threads': 1, 'batch_size': 2, 'chunks': 'chunks.jsonl',
           'chunks_manifest': 'manifest.json', 'model': 'a', 'summary_sha256': 's',
           'gold_sha256': 'g', 'corpus_sha256': 'c'}
    model = {'repository': 'synthetic', 'revision': 'r',
             'obtained_receipt': {'inventory_sha256': 'i', 'files': [{'size': 123}]},
             'contract': {'file_sha256': 'c'}}
    manifest = {'chunk_count': 3, 'chunks_sha256': pilot.sha(chunks), 'tokenizer_inventory_sha256': 'inventory'}
    pilot.build(job, (model, {'dimension': 2}, manifest, []), encoder_factory=SyntheticEncoder)
    assert calls == [[text, text], [text]]
    vectors, mapping = pilot.open_index(job, (model, {'dimension': 2}, manifest, []))
    try:
        assert isinstance(vectors, np.memmap) and vectors.shape == (3, 2)
        assert isinstance(mapping, pilot.DiskMapping)
        receipt = pilot.load(tmp_path / 'index/index.json')
        assert receipt['max_actual_tokens'] == 4 and receipt['chunks_per_second'] > 0
        assert receipt['model_plus_index_payload_bytes'] == receipt['index_payload_bytes'] + 123
    finally:
        mapping.connection.close()


def test_no_inference_dependency_on_import():
    completed = subprocess.run([sys.executable, '-c',
        ('import sys; import tools.p4_exact_pilot; '
         'assert "torch" not in sys.modules; assert "transformers" not in sys.modules')],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_benchmark_forbids_sample_override():
    with pytest.raises(ValueError, match='samples override forbidden'):
        pilot.benchmark({'samples': 30}, Path('not-opened'), None)


def cases():
    return [{'case_id': f'{i:03}', 'query': 'hello'} for i in range(120)]


def test_worker_embedding_only_never_opens_index(monkeypatch):
    monkeypatch.setattr(pilot, 'prepare', lambda job: ({}, {}, {}, cases()))
    class Encoder:
        info: ClassVar[dict] = {}
        def __init__(self, *args):
            pass
        def encode(self, texts, query):
            return np.array([[1, 0]], dtype=np.float32), [1]
    monkeypatch.setattr(pilot, 'LocalEncoder', Encoder)
    monkeypatch.setattr(pilot, 'open_index', lambda *args: pytest.fail('index touched'))
    monkeypatch.setattr(pilot, 'rss', lambda: {'peak_rss_bytes': 10})
    result = pilot.worker({'threads': 1}, 'reused')
    assert [r['case_id'] for r in result['samples']] == [c['case_id'] for c in cases()]
    assert len(result['warmups']) == 2 and result['summary']['attempts'] == 120
    assert all('embedding_ms' in r and 'exact_search_ms' not in r for r in result['samples'])


def test_setup_failure_has_zero_attempts(monkeypatch):
    monkeypatch.setattr(pilot, 'prepare', lambda job: ({}, {}, {}, cases()))
    def fail(*args):
        raise RuntimeError('setup failed')
    monkeypatch.setattr(pilot, 'LocalEncoder', fail)
    result = pilot.worker({'threads': 1}, 'reused')
    assert result['setup']['status'] == 'FAIL'
    assert result['summary']['attempts'] == 0 and result['summary']['not_run'] == 120
    assert all('elapsed_ms' not in r for r in result['samples'])


def test_windows_peak_is_not_instantaneous(monkeypatch):
    import psutil
    class Memory:
        rss = 3
        peak_wset = 77
    class Process:
        def memory_info(self):
            return Memory()
    monkeypatch.setattr(psutil, 'Process', Process)
    assert pilot.rss()['peak_rss_bytes'] == 77
    assert pilot.rss()['rss_bytes'] == 3


def test_real_tokenizer_correspondence_no_models():
    tokenizers = pytest.importorskip('tokenizers')
    transformers = pytest.importorskip('transformers')
    raw = tokenizers.Tokenizer(tokenizers.models.WordLevel(
        {'[UNK]': 0, '[CLS]': 1, '[SEP]': 2, 'hello': 3, 'query': 4, ':': 5}, unk_token='[UNK]'))
    raw.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    raw.post_processor = tokenizers.processors.TemplateProcessing(
        single='[CLS] $A [SEP]', special_tokens=[('[CLS]', 1), ('[SEP]', 2)])
    wrapper = transformers.PreTrainedTokenizerFast(tokenizer_object=raw, unk_token='[UNK]')
    encoded, counts = pilot.checked_tokens(raw, wrapper, ['hello'], 'query: ', 5)
    assert encoded['input_ids'] == [[1, 4, 5, 3, 2]] and counts == [5]
    with pytest.raises(ValueError, match='budget exceeded'):
        pilot.checked_tokens(raw, wrapper, ['hello'], 'query: ', 4)
    changed = tokenizers.Tokenizer(tokenizers.models.WordLevel(
        {'[UNK]': 0, 'hello': 4, 'query': 3, ':': 5}, unk_token='[UNK]'))
    changed.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    wrong = transformers.PreTrainedTokenizerFast(tokenizer_object=changed, unk_token='[UNK]')
    with pytest.raises(ValueError, match='ID mismatch'):
        pilot.checked_tokens(raw, wrong, ['hello'], '', 10)
    raw.enable_truncation(2)
    with pytest.raises(ValueError, match='truncation enabled'):
        pilot.checked_tokens(raw, wrapper, ['hello hello hello'], '', 10)


@pytest.fixture
def frozen_tokenizer_directory(tmp_path):
    tokenizers = pytest.importorskip('tokenizers')
    transformers = pytest.importorskip('transformers')
    raw = tokenizers.Tokenizer(tokenizers.models.WordLevel(
        {'[UNK]': 0, '[CLS]': 1, '[SEP]': 2, '[PAD]': 3,
         'hello': 4, 'query:': 5, ' ': 6, 'passage:': 7}, unk_token='[UNK]'))
    raw.pre_tokenizer = tokenizers.pre_tokenizers.Split(' ', behavior='isolated')
    raw.post_processor = tokenizers.processors.TemplateProcessing(
        single='[CLS] $A [SEP]', special_tokens=[('[CLS]', 1), ('[SEP]', 2)])
    wrapper = transformers.PreTrainedTokenizerFast(
        tokenizer_object=raw, unk_token='[UNK]', pad_token='[PAD]',
        bos_token='[CLS]', eos_token='[SEP]',
        model_input_names=['input_ids', 'attention_mask'])
    wrapper.save_pretrained(tmp_path)
    return tmp_path


@pytest.mark.parametrize('prefix', ['passage: ', 'query: '])
def test_frozen_tokenizer_whitespace_specials_and_padding(frozen_tokenizer_directory, prefix):
    raw, wrapper = pilot.frozen_tokenizers(frozen_tokenizer_directory)
    assert json.loads(raw.to_str()) == json.loads(wrapper.backend_tokenizer.to_str())
    assert raw.padding is None and wrapper.backend_tokenizer.padding is None
    assert raw.truncation is None and wrapper.backend_tokenizer.truncation is None
    assert raw.encode('hello ', add_special_tokens=False).ids == [4, 6]
    texts = ['hello ', 'hello  ', 'hello\t', 'hello\n', ' hello',
             'hello\u00a0', 'hello\u3000', 'hello\thello',
             '[CLS] hello [SEP] [PAD]', '', '日本語 ']
    encoded, counts = pilot.checked_tokens(raw, wrapper, texts, prefix, 100)
    assert set(encoded) == {'input_ids', 'attention_mask'}
    assert all(ids[0] == 1 and ids[-1] == 2 for ids in encoded['input_ids'])
    assert encoded['attention_mask'] == [[1] * n for n in counts]
    padded = wrapper.pad(encoded, padding=True)
    for ids, mask, original, count in zip(
            padded['input_ids'], padded['attention_mask'], encoded['input_ids'], counts):
        assert ids[:count] == original
        assert ids[count:] == [wrapper.pad_token_id] * (max(counts) - count)
        assert mask == [1] * count + [0] * (max(counts) - count)


def test_frozen_tokenizer_checks_entire_backend(frozen_tokenizer_directory, monkeypatch):
    import tokenizers
    import transformers

    original = transformers.PreTrainedTokenizerFast.from_pretrained

    def changed(*args, **kwargs):
        assert kwargs == {'local_files_only': True, 'trust_remote_code': False}
        wrapper = original(*args, **kwargs)
        wrapper.backend_tokenizer.normalizer = tokenizers.normalizers.Lowercase()
        return wrapper

    monkeypatch.setattr(transformers.PreTrainedTokenizerFast, 'from_pretrained', changed)
    with pytest.raises(ValueError, match='frozen tokenizer backend mismatch'):
        pilot.frozen_tokenizers(frozen_tokenizer_directory)


def test_frozen_tokenizer_disables_serialized_padding_and_truncation(frozen_tokenizer_directory):
    import tokenizers

    path = frozen_tokenizer_directory / 'tokenizer.json'
    raw = tokenizers.Tokenizer.from_file(str(path))
    raw.enable_padding(length=20, pad_id=3, pad_token='[PAD]')
    raw.enable_truncation(max_length=4)
    raw.save(str(path))
    raw, wrapper = pilot.frozen_tokenizers(frozen_tokenizer_directory)
    encoded, counts = pilot.checked_tokens(raw, wrapper, ['hello hello'], 'query: ', 7)
    assert encoded['input_ids'] == [[1, 5, 6, 4, 6, 4, 2]]
    assert counts == [7]
    with pytest.raises(ValueError, match='budget exceeded'):
        pilot.checked_tokens(raw, wrapper, ['hello hello'], 'query: ', 6)


@pytest.fixture
def frozen_job(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    def put(name, value):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return pilot.sha(path)
    contract = {'tokenizer_files': ['tokenizer.json'], 'pooling': 'mean', 'normalize': True}
    contract_hash = put('contract.json', contract)
    tokenizer_hash = put('assets/tokenizer.json', {})
    model = {'repository': 'synthetic', 'revision': 'a' * 40, 'asset_directory': 'assets',
             'contract': {'path': 'contract.json', 'file_sha256': contract_hash, 'reviewed': contract},
             'obtained_receipt': {'files': [{'path': 'tokenizer.json', 'sha256': tokenizer_hash,
                                            'size': (tmp_path / 'assets/tokenizer.json').stat().st_size}]}}
    job = {'model': 'a', 'device': 'cpu', 'threads': 1, 'batch_size': 2,
           'authorization': 'auth.json', 'index': 'index', 'output': 'output.json'}
    for key, value in [('summary', {'status': 'PASS', 'models': {'a': model}}),
                       ('corpus', {}), ('gold', {'status': pilot.FROZEN,
                                                'base_snapshot_sha256': 'b' * 64, 'cases': cases()})]:
        job[key] = key + '.json'
        job[key + '_sha256'] = put(job[key], value)
    inventory = {'repository': 'synthetic', 'revision': 'a' * 40, 'contract': contract,
                 'tokenizer_json_sha256': tokenizer_hash, 'truncation': False, 'padding': False}
    job['chunks'] = 'chunks.json'
    chunks_hash = put(job['chunks'], {})
    manifest = {'chunks_sha256': chunks_hash, 'corpus_sha256': job['corpus_sha256'],
                'document_count': 50000, 'chunk_count': 1, 'base_snapshot_sha256': 'b' * 64,
                'tokenizer_inventory': inventory, 'tokenizer_inventory_sha256': pilot.canonical_hash(inventory)}
    job['chunks_manifest'] = 'manifest.json'
    job['chunks_manifest_sha256'] = put('manifest.json', manifest)
    auth = {k: job[k] for k in ('summary_sha256', 'gold_sha256', 'corpus_sha256', 'chunks_manifest_sha256')}
    put('auth.json', dict(auth, authorized=True, gold_status=pilot.FROZEN, chunks_sha256=chunks_hash))
    return job


def test_prepare_accepts_real_manifest_shape(frozen_job):
    assert len(pilot.prepare(frozen_job)[3]) == 120


def test_prepare_rejects_mutable_gold(frozen_job):
    path = pilot.local(frozen_job['gold'])
    gold = pilot.load(path)
    gold['status'] = 'DRAFT'
    path.write_text(json.dumps(gold), encoding='utf-8')
    frozen_job['gold_sha256'] = pilot.sha(path)
    auth_path = pilot.local(frozen_job['authorization'])
    auth = pilot.load(auth_path)
    auth['gold_sha256'] = frozen_job['gold_sha256']
    auth_path.write_text(json.dumps(auth), encoding='utf-8')
    with pytest.raises(ValueError, match='gold not frozen'):
        pilot.prepare(frozen_job)


def test_local_containment(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    monkeypatch.setattr(pilot, 'ROOT', root)
    with pytest.raises(ValueError, match='repository-relative'):
        pilot.local('../outside')
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (root / 'escape').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlink privilege unavailable')
    with pytest.raises(ValueError, match='path escape'):
        pilot.local('escape/file')
