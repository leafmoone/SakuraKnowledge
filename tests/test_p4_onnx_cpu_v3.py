"""No-inference tests for the explicit ONNX CPU v3 benchmark."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools import p4_onnx_cpu_v3 as v3


def cases():
    return [{'case_id': f'q{i:03}', 'query': 'frozen'} for i in range(120)]


def record(case, status='PASS'):
    return {'case_id': case['case_id'], 'status': status,
            'operation_ms': 2.0, 'embedding_ms': 1.0}


def reused():
    return {'status': 'PASS', 'events': [
        {'event': 'query', 'kind': kind, 'record': record(c)}
        for kind, batch in [('warmup', cases()[:2]), ('sample', cases())] for c in batch]}


def fresh(case, status='PASS', blocking=False):
    return {'case_id': case['case_id'], 'status': status, 'blocking_failure': blocking,
            'process_elapsed_ms': 15001 if status == 'FAIL' else 5,
            'query': record(case, status)}


def test_all_fresh_continue_and_do_not_fail_qualification():
    calls = []

    def launch(path, digest, mode, case=None):
        calls.append((mode, case))
        return reused() if mode == 'reused' else fresh(case, 'FAIL')

    result = v3.benchmark('config', 'digest', cases(), launch)
    assert len(calls) == 123
    assert [c['case_id'] for _, c in calls[3:]] == [c['case_id'] for c in cases()]
    assert result['status'] == 'PASS'
    assert result['performance_qualified'] is True
    assert result['fresh']['status'] == 'FAIL'
    assert result['fresh']['process_summary']['failures'] == 120
    assert result['fresh']['process_summary']['p95_ms'] == 15001


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'slow', 'warmup', 'exit', 'blocking'])
def test_no_false_qualification(defect):
    process = reused()
    samples = [fresh(c) for c in cases()]
    warmups = [fresh(c) for c in cases()[:2]]
    if defect == 'missing':
        process['events'].pop()
    elif defect == 'duplicate':
        process['events'][-1]['record']['case_id'] = 'q000'
    elif defect == 'slow':
        process['events'][-1]['record']['operation_ms'] = 5000.01
    elif defect == 'warmup':
        process['events'][0]['record']['status'] = 'FAIL'
    elif defect == 'exit':
        process['status'] = 'FAIL'
    else:
        samples[-1]['blocking_failure'] = True
    result = v3.evaluate(cases(), process, warmups, samples)
    assert result['status'] == 'FAIL'
    assert result['performance_qualified'] is False


def test_percentiles_include_measured_failures_and_null_missing():
    result = v3.summarize([{'status': 'PASS', 'ms': 1}, {'status': 'FAIL', 'ms': 5},
                           {'status': 'FAIL', 'ms': None}], 'ms')
    assert result['p50_ms'] == 3
    assert result['p95_ms'] == pytest.approx(4.8)
    assert result['missing_timing'] == 1
    assert v3.summarize([], 'ms')['p50_ms'] is None


def test_timeout_retains_event_prefix_and_raw_utf8():
    clock = iter([0, 15.2])

    def runner(command, **kwargs):
        assert kwargs['timeout'] == 15
        assert kwargs['env']['PYTHONUTF8'] == '1'
        assert kwargs['env']['PYTHONIOENCODING'] == 'utf-8'
        path = Path(command[command.index('--progress') + 1])
        path.write_bytes(b'{"event":"setup","setup_ms":12}\n'
                         b'{"event":"memory","rss_bytes":50,"peak_rss_bytes":99}\n'
                         b'{"event":"query_start","case_id":"q000"}\n{"event":')
        raise subprocess.TimeoutExpired(command, 15, output='日本語'.encode(), stderr=b'bad\xff')

    result = v3.launch(Path('config'), 'sha', 'fresh', cases()[0], runner, lambda: next(clock))
    assert result['status'] == 'FAIL' and result['timeout'] is True
    assert result['exit_code'] is None
    assert result['setup_ms'] == 12
    assert result['session_load_ms'] is None
    assert result['query']['operation_ms'] is None
    assert result['peak_rss_bytes'] == 99
    assert len(result['events']) == 3
    assert result['event_prefix']['text'].endswith('{"event":')
    assert result['stdout']['text'] == '日本語'
    assert result['stderr']['bytes_base64'] == 'YmFk/w=='


def test_nonzero_exit_and_missing_peak_are_not_fabricated():
    result = v3.launch(Path('config'), 'sha', 'fresh', cases()[0],
                       lambda *a, **k: SimpleNamespace(returncode=2, stdout=b'', stderr=b'error'),
                       iter([0, 1]).__next__)
    assert result['status'] == 'FAIL'
    assert result['exit_code'] == 2
    assert result['peak_rss_bytes'] is None
    assert result['query']['embedding_ms'] is None


def test_operation_timers_and_failure():
    class Encoder:
        def encode(self, texts, query):
            raise RuntimeError('ORT failed')

    result = v3.operation(Encoder(), cases()[0], iter([0, .1, .4, 5.1]).__next__)
    assert result['status'] == 'FAIL'
    assert result['embedding_ms'] == pytest.approx(300)
    assert result['operation_ms'] == 5100


def test_quality_gate_requires_bound_pass(monkeypatch):
    bound = []
    monkeypatch.setattr(v3.exact, 'bound', lambda p, h: bound.append((p, h)))
    monkeypatch.setattr(v3.exact, 'load', lambda p: {'status': 'FAIL'})
    with pytest.raises(ValueError, match='must PASS'):
        v3.quality_gate('receipt', 'expected')
    assert bound == [('receipt', 'expected')]


def test_setup_failure_is_blocking(tmp_path):
    progress = tmp_path / 'events'

    def prepare(*args):
        raise ValueError('tampered inputs')

    assert v3.worker('config', 'sha', 'fresh', progress, prepare=prepare) == 1
    events = [json.loads(line) for line in progress.read_text().splitlines()]
    assert events[1]['blocking'] is True
    assert events[1]['phase'] == 'setup'


def test_reused_worker_two_fixed_warmups_and_120_even_failed_query(tmp_path, monkeypatch):
    progress = tmp_path / 'events'
    monkeypatch.setattr(v3.exporter, 'snapshot', lambda paths: {})
    calls = []

    class Encoder:
        def __init__(self, *args):
            pass

        def encode(self, texts, query):
            calls.append(texts)
            if len(calls) == 3:
                raise RuntimeError('failure')
            return None, [3]

    prepared = ({}, {}, {}, cases())
    code = v3.worker('config', 'sha', 'reused', progress,
                     prepare=lambda *args: ({}, prepared, tmp_path, {}),
                     encoder_factory=Encoder,
                     memory=lambda: {'rss_bytes': 10, 'peak_rss_bytes': 20,
                                     'peak_rss_source': 'getrusage ru_maxrss'})
    assert code == 1
    assert len(calls) == 122
    events = [json.loads(line) for line in progress.read_text().splitlines()]
    queries = [e for e in events if e['event'] == 'query']
    assert [q['record']['case_id'] for q in queries[:2]] == ['q000', 'q001']
    assert len([q for q in queries if q['kind'] == 'sample']) == 120
    assert {'event': 'validation_after', 'status': 'PASS'} in events


def test_encoder_checked_token_ids_padding_and_fp32(monkeypatch):
    encoder = object.__new__(v3.Encoder)
    encoder.raw = object()
    encoder.tokenizer = SimpleNamespace(padding_side='right', pad_token_id=0)
    encoder.contract = {'query_prefix': '', 'max_sequence_tokens': 8192}
    calls = []

    def checked(raw, tokenizer, texts, prefix, maximum):
        calls.append((texts, prefix, maximum))
        return {'input_ids': [[2, 3]], 'attention_mask': [[1, 1]]}, [2]

    def run(names, batch):
        assert names == ['embeddings']
        assert batch['input_ids'].dtype == np.int64
        result = np.zeros((1, 1024), dtype=np.float32)
        result[0, 0] = 1
        return [result]

    monkeypatch.setattr(v3.exact, 'checked_tokens', checked)
    encoder.session = SimpleNamespace(run=run)
    assert encoder.encode(['frozen'])[1] == [2]
    assert calls == [(['frozen'], '', 8192)]
    encoder.tokenizer.padding_side = 'left'
    with pytest.raises(ValueError, match='right padding'):
        encoder.encode(['frozen'])


@pytest.mark.parametrize('bad', ['provider', 'threads', 'dtype'])
def test_ort_setup_gates_with_mock_runtime(bad):
    class Options:
        pass

    class Session:
        def __init__(self, path, sess_options, providers):
            assert providers == ['CPUExecutionProvider']
            assert sess_options.intra_op_num_threads == sess_options.inter_op_num_threads == 8
            assert sess_options.graph_optimization_level == 'ALL'
            self.options = sess_options

        def disable_fallback(self):
            pass

        def get_providers(self):
            return ['CUDAExecutionProvider'] if bad == 'provider' else ['CPUExecutionProvider']

        def get_session_options(self):
            if bad == 'threads':
                self.options.intra_op_num_threads = 1
            return self.options

        def get_inputs(self):
            return [SimpleNamespace(name=n, type='tensor(int64)', shape=['batch', 'sequence'])
                    for n in ('input_ids', 'attention_mask')]

        def get_outputs(self):
            return [SimpleNamespace(name='embeddings', type='tensor(double)', shape=['batch', 1024])]

    ort = SimpleNamespace(SessionOptions=Options, InferenceSession=Session,
                          GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL='ALL'))
    with pytest.raises(ValueError):
        v3.agreement.session('model.onnx', ort)


@pytest.mark.parametrize('absolute', [False, True])
def test_launcher_passes_repo_relative_config(absolute):
    relative = Path('configs/cpu-v3.json')
    path = v3.exact.local(relative) if absolute else relative

    def runner(command, **kwargs):
        name = command[command.index('--config') + 1]
        assert name == relative.as_posix()
        assert v3.exact.local(name) == v3.exact.local(relative)
        assert kwargs['cwd'] == v3.exact.ROOT
        assert '-Xutf8' in command
        return SimpleNamespace(returncode=1, stdout=b'', stderr=b'')

    v3.launch(path, 'sha', 'fresh', cases()[0], runner)


@pytest.mark.parametrize('error', ['provider', 'threads', 'dtype', 'padding'])
def test_load_gate_failure_blocks_fresh_qualification(tmp_path, monkeypatch, error):
    monkeypatch.setattr(v3.exporter, 'snapshot', lambda paths: {})

    def encoder(*args):
        raise ValueError(error)

    def runner(command, **kwargs):
        progress = command[command.index('--progress') + 1]
        code = v3.worker('config', 'sha', 'fresh', progress, cases()[0]['case_id'],
                         prepare=lambda *args: ({}, ({}, {}, {}, cases()), tmp_path, {}),
                         encoder_factory=encoder,
                         memory=lambda: {'peak_rss_bytes': 20, 'peak_rss_source': 'mock'})
        return SimpleNamespace(returncode=code, stdout=b'', stderr=b'')

    process = v3.launch('config', 'sha', 'fresh', cases()[0], runner)
    assert process['blocking_failure'] is True
    assert any(e.get('phase') == 'load' and e.get('blocking') for e in process['events'])
    samples = [process, *[fresh(c) for c in cases()[1:]]]
    result = v3.evaluate(cases(), reused(), [fresh(c) for c in cases()[:2]], samples)
    assert result['performance_qualified'] is False


@pytest.fixture
def quality_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(v3.exact, 'ROOT', tmp_path)
    manifest = v3.exact.local(v3.agreement.EXPORT) / 'manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{}', encoding='utf-8')
    contract = v3.exact.local(v3.QUALITY_CONTRACT)
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps({'schema': 'p4-onnx-representation-contract-v3',
                                    'export_manifest_sha256': v3.exact.sha(manifest)}), encoding='utf-8')
    job = v3.exact.local(v3.exporter.producer.JOB)
    job.parent.mkdir(parents=True, exist_ok=True)
    job.write_text('{"threads":8}', encoding='utf-8')
    bindings = v3.exporter.snapshot([manifest, contract, job])
    value = {'schema': 'p4-onnx-quality-v3', 'status': 'PASS',
             'quality': {'failures': [], 'gates': {'regression': {'pass': True}}},
             'queries': [record(c) for c in cases()],
             'passages': [{'status': 'PASS', 'batch_size': size, 'offset': offset}
                          for size in (1, 8) for offset in range(0, 128, size)],
             'ranking': [{'case_id': c['case_id'], 'diagnostic_only': True,
                          'ordered': {'10': False, '100': False}} for c in cases()],
             'input_sha256': bindings, 'bindings_sha256': v3.exact.canonical_hash(bindings),
             'input_validations': {'before': 'PASS', 'after': 'PASS'}}
    return tmp_path / 'receipt.json', value, bindings.copy()


def save_receipt(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return v3.exact.sha(path)


def test_quality_actual_schema_accepts_rank_differences(quality_receipt):
    path, value, required = quality_receipt
    digest = save_receipt(path, value)
    assert v3.quality_gate(path, digest, required, cases()) == value


@pytest.mark.parametrize('defect', [
    'schema', 'failures', 'empty_gates', 'gate', 'query_count', 'query_fail', 'query_duplicate',
    'passage_count', 'passage_fail', 'passage_duplicate', 'ranking_count', 'ranking_not_diagnostic',
    'ranking_order', 'after', 'snapshot_hash', 'contract_missing', 'manifest_missing',
    'input_changed', 'receipt_hash', 'contract_changed', 'export_mismatch', 'outside_input',
])
def test_quality_gate_rejects_incomplete_or_unbound_receipts(quality_receipt, defect):
    path, value, required = quality_receipt
    if defect == 'schema':
        value['schema'] = 'v2'
    elif defect == 'failures':
        value['quality']['failures'] = ['failed']
    elif defect == 'empty_gates':
        value['quality']['gates'] = {}
    elif defect == 'gate':
        value['quality']['gates']['regression']['pass'] = False
    elif defect.endswith('_count'):
        value[{'query_count': 'queries', 'passage_count': 'passages',
               'ranking_count': 'ranking'}[defect]].pop()
    elif defect in ('query_fail', 'passage_fail'):
        value['queries' if defect == 'query_fail' else 'passages'][0]['status'] = 'FAIL'
    elif defect == 'query_duplicate':
        value['queries'][1] = value['queries'][0]
    elif defect == 'passage_duplicate':
        value['passages'][1] = value['passages'][0]
    elif defect == 'ranking_not_diagnostic':
        value['ranking'][0]['diagnostic_only'] = False
    elif defect == 'ranking_order':
        value['ranking'].reverse()
    elif defect == 'after':
        value['input_validations']['after'] = 'NOT_COMPLETED'
    elif defect == 'snapshot_hash':
        value['bindings_sha256'] = '0' * 64
    elif defect in ('contract_missing', 'manifest_missing'):
        name = v3.exact.local(v3.QUALITY_CONTRACT) if defect == 'contract_missing' else (
            v3.exact.local(v3.agreement.EXPORT) / 'manifest.json')
        del value['input_sha256'][str(name.resolve())]
        value['bindings_sha256'] = v3.exact.canonical_hash(value['input_sha256'])
    elif defect in ('input_changed', 'contract_changed'):
        name = v3.exact.local(v3.QUALITY_CONTRACT) if defect == 'contract_changed' else (
            v3.exact.local(v3.agreement.EXPORT) / 'manifest.json')
        name.write_text('tampered', encoding='utf-8')
    elif defect == 'export_mismatch':
        name = v3.exact.local(v3.QUALITY_CONTRACT)
        contract = v3.exact.load(name)
        contract['export_manifest_sha256'] = '0' * 64
        name.write_text(json.dumps(contract), encoding='utf-8')
        value['input_sha256'][str(name.resolve())] = v3.exact.sha(name)
        required = value['input_sha256'].copy()
        value['bindings_sha256'] = v3.exact.canonical_hash(value['input_sha256'])
    elif defect == 'outside_input':
        value['input_sha256'][str(path.parent.parent / 'outside')] = '0' * 64
        value['bindings_sha256'] = v3.exact.canonical_hash(value['input_sha256'])
    digest = save_receipt(path, value)
    if defect == 'receipt_hash':
        digest = '0' * 64
    with pytest.raises(ValueError):
        v3.quality_gate(path, digest, required, cases())


def test_validate_binds_quality_inputs_and_preserves_them(quality_receipt, monkeypatch):
    path, value, bindings = quality_receipt
    digest = save_receipt(path, value)
    manifest = v3.exact.local(v3.agreement.EXPORT) / 'manifest.json'
    job = v3.exact.local(v3.exporter.producer.JOB)
    config = {'job': v3.exporter.producer.JOB, 'job_sha256': v3.exact.sha(job),
              'quality_receipt': path.name, 'quality_receipt_sha256': digest,
              'export_manifest': manifest.relative_to(v3.exact.ROOT).as_posix(),
              'export_manifest_sha256': v3.exact.sha(manifest), 'output': 'output.json'}
    config_path = v3.exact.ROOT / 'config.json'
    config_digest = save_receipt(config_path, config)
    monkeypatch.setattr(v3.cpu, 'validate', lambda job: ({}, {}, {}, cases()))
    monkeypatch.setattr(v3.agreement, 'validate_export', lambda *args: (
        {}, v3.exporter.snapshot([manifest, job])))
    _, _, _, before = v3.validate(config_path, config_digest)
    assert all(before[name] == digest for name, digest in bindings.items())
    assert before[str(path.resolve())] == digest
    assert before[str(config_path.resolve())] == config_digest
    value['queries'][0]['status'] = 'FAIL'
    config['quality_receipt_sha256'] = save_receipt(path, value)
    config_digest = save_receipt(config_path, config)
    with pytest.raises(ValueError, match='numerical checks'):
        v3.validate(config_path, config_digest)
