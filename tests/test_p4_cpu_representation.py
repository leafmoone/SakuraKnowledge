import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import p4_cpu_representation as cpu

CASES = [{'case_id': f'{i:03}', 'query': '日本語'} for i in range(120)]
MEMORY = {'rss_bytes': 12, 'peak_rss_bytes': 42, 'peak_rss_source': 'Windows peak_wset'}


class Encoder:
    def __init__(self, model, contract, device, threads):
        assert device == 'cpu'
        self.info = {'provider': 'mock', 'actual_device': 'cpu', 'actual_dtype': 'float32'}


def retrieve(encoder, case, index=None):
    assert index is None
    return {'embedding_ms': 1.25, 'actual_tokens': 3}


def process(mode='reused', status='PASS'):
    schedule = ([('warmup', c) for c in CASES[:2]] + [('sample', c) for c in CASES]
                if mode == 'reused' else [('sample', CASES[0])])
    events = [{'event': 'record', 'kind': kind,
               'record': {'case_id': c['case_id'], 'status': 'PASS',
                          'embedding_ms': 1, 'operation_ms': 2, **MEMORY}}
              for kind, c in schedule]
    return {'status': status, 'events': events, 'timeout': False, 'process_elapsed_ms': 3}


class RepresentationTests(unittest.TestCase):
    def test_operation_timing_and_memory(self):
        record = cpu.operation(Encoder({}, {}, 'cpu', 1), CASES[0],
                               iter([0, 5]).__next__, retrieve, lambda: dict(MEMORY))
        self.assertEqual(record['status'], 'PASS')
        self.assertEqual(record['operation_ms'], 5000)
        self.assertEqual(record['embedding_ms'], 1.25)
        self.assertEqual(record['peak_wset_bytes'], 42)
        record = cpu.operation(None, CASES[0], iter([0, 5.001]).__next__, retrieve,
                               lambda: dict(MEMORY))
        self.assertEqual(record['status'], 'FAIL')

    def test_missing_memory_fails(self):
        for memory in ({}, {**MEMORY, 'peak_rss_bytes': 0}):
            record = cpu.operation(None, CASES[0], iter([0, 1]).__next__, retrieve,
                                   lambda memory=memory: memory)
            self.assertEqual(record['status'], 'FAIL')
        posix = cpu.memory_record(lambda: {**MEMORY, 'peak_rss_source': 'getrusage ru_maxrss'})
        self.assertIsNone(posix['peak_wset_bytes'])

    def test_worker_order_independent_warmups_and_load_timer(self):
        called = []
        def fake_retrieve(encoder, case, index=None):
            called.append(case['case_id'])
            return retrieve(encoder, case, index)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress'
            code = cpu.worker({'threads': 2}, 'reused', path,
                              prepare=lambda job: ({}, {}, {}, CASES), encoder_factory=Encoder,
                              clock=iter(range(246)).__next__, retrieve=fake_retrieve,
                              memory=lambda: dict(MEMORY))
            events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(called, ['000', '001'] + [c['case_id'] for c in CASES])
        self.assertEqual(next(e for e in events if e['event'] == 'setup')['model_load_ms'], 1000)
        self.assertEqual(sum(e.get('kind') == 'warmup' and e['event'] == 'record' for e in events), 2)

    def test_worker_stops_first_budget_failure(self):
        called = []
        def fake_retrieve(encoder, case, index=None):
            called.append(case['case_id'])
            return retrieve(encoder, case, index)
        with tempfile.TemporaryDirectory() as directory:
            code = cpu.worker({'threads': 1}, 'reused', Path(directory) / 'progress',
                              prepare=lambda job: ({}, {}, {}, CASES), encoder_factory=Encoder,
                              clock=iter([0, 1, 1, 7]).__next__, retrieve=fake_retrieve,
                              memory=lambda: dict(MEMORY))
        self.assertEqual(code, 1)
        self.assertEqual(called, ['000'])

    def test_launch_timeout_preserves_prefix_and_utf8(self):
        def runner(command, **kwargs):
            self.assertEqual(kwargs['timeout'], 15)
            progress = Path(command[command.index('--progress') + 1])
            cpu.emit(progress, {'event': 'start', 'kind': 'sample', 'case_id': '000'})
            raise subprocess.TimeoutExpired(command, 15, output='日本語'.encode(), stderr='失敗'.encode())
        result = cpu.launch(Path('job'), 'fresh', CASES[0], runner, iter([0, 15]).__next__)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['timeout'])
        self.assertIsNone(result['exit_code'])
        self.assertEqual(result['stdout']['text'], '日本語')
        self.assertEqual(result['stderr']['text'], '失敗')
        _, records = cpu.unpack(result)
        self.assertEqual(records[0]['status'], 'FAIL')
        self.assertNotIn('operation_ms', records[0])

    def test_fresh_envelope_and_exit_code(self):
        def runner(command, **kwargs):
            cpu.emit(command[command.index('--progress') + 1], {'event': 'done'})
            return subprocess.CompletedProcess(command, 7, b'out', b'err')
        result = cpu.launch(Path('job'), 'fresh', CASES[0], runner, iter([0, 16]).__next__)
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['process_elapsed_ms'], 16000)
        self.assertEqual(result['status'], 'FAIL')

    def benchmark(self, launcher):
        prepared = ({'obtained_receipt': {'files': [{'size': 17}]}}, {}, {}, CASES)
        with patch.object(cpu.exact, 'provenance', return_value={'model': 'b'}):
            return cpu.benchmark({'threads': 1, 'selection_receipt_sha256': 'hash'},
                                 Path('job'), prepared, launcher)

    def test_complete_120_each_and_fresh_warmups(self):
        calls = []
        def launcher(path, mode, case=None):
            calls.append((mode, case))
            value = process(mode)
            if mode == 'fresh':
                value['events'][0]['record']['case_id'] = case['case_id']
            return value
        result = self.benchmark(launcher)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(len(calls), 123)
        self.assertEqual([c[1]['case_id'] for c in calls[1:]],
                         ['000', '001'] + [c['case_id'] for c in CASES])
        for mode in ('fresh', 'reused'):
            self.assertEqual(result[mode]['summary']['attempts'], 120)
            self.assertTrue(result[mode]['summary']['coverage_pass'])
            self.assertEqual(len(result[mode]['warmups']), 2)

    def test_reused_failure_stops_fresh_and_preserves_prefix(self):
        value = process()
        value['events'] = value['events'][:4]
        value['events'][-1]['record']['status'] = 'FAIL'
        value['status'] = 'FAIL'
        with patch.object(cpu, 'launch', return_value=value) as launcher:
            result = self.benchmark(launcher)
        self.assertEqual(launcher.call_count, 1)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['reused']['summary']['failures'], 1)
        self.assertEqual(result['reused']['summary']['not_run'], 118)
        self.assertEqual(result['fresh']['summary']['not_run'], 120)

    def test_unknown_phase_fresh_timeout_is_failed_attempt(self):
        calls = []
        def launcher(path, mode, case=None):
            calls.append(mode)
            if mode == 'reused':
                return process()
            if len(calls) <= 3:
                return process('fresh')
            return {'status': 'FAIL', 'timeout': True, 'events': [], 'process_elapsed_ms': 15001}
        result = self.benchmark(launcher)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['fresh']['summary']['failures'], 1)
        self.assertEqual(result['fresh']['summary']['timeouts'], 1)
        self.assertEqual(result['fresh']['summary']['not_run'], 119)
        self.assertEqual(result['formal_qualification'], 'FAIL')

    def test_linear_percentiles_include_failed_attempts(self):
        value = cpu.summary([{'status': 'PASS', 'operation_ms': 1},
                             {'status': 'FAIL', 'operation_ms': 11}, {'status': 'NOT_RUN'}])
        self.assertEqual(value['operation']['p50_ms'], 6)
        self.assertEqual(value['operation']['p95_ms'], 10.5)
        self.assertIsNone(value['peak_rss_bytes'])
        self.assertFalse(value['coverage_pass'])


class GateTests(unittest.TestCase):
    def setUp(self):
        self.job = {'model': 'b', 'device': 'cpu', 'threads': 1, 'batch_size': 1,
                    'summary_sha256': 'summary-digest', 'gold_sha256': 'gold-digest',
                    'corpus_sha256': 'corpus-digest'}
        self.model = {'repository': 'BAAI/bge-m3', 'revision': cpu.B_REVISION}
        self.contract = {'dimension': 1024, 'pooling': 'cls', 'normalize': True,
                         'query_prefix': '', 'passage_prefix': ''}
        self.prepared = (self.model, self.contract, {'manifest': True}, CASES)
        self.prepare = patch.object(cpu.exact, 'prepare', return_value=self.prepared)
        self.prepare = self.prepare.start()
        self.addCleanup(patch.stopall)

    def test_prepare_is_called_with_product_input_digests(self):
        self.assertEqual(cpu.validate(self.job), self.prepared)
        self.prepare.assert_called_once_with(self.job)
        self.assertEqual(self.job['summary_sha256'], 'summary-digest')
        self.assertEqual(self.job['gold_sha256'], 'gold-digest')
        self.assertEqual(self.job['corpus_sha256'], 'corpus-digest')

    def test_model_repository_and_revision_are_pinned(self):
        for key, value in (('repository', 'BAAI/bge-other'), ('revision', '0' * 40)):
            with self.subTest(key=key):
                self.prepare.return_value = ({**self.model, key: value},
                                              self.contract, {}, CASES)
                with self.assertRaisesRegex(ValueError, 'pinned BGE-M3 model'):
                    cpu.validate(self.job)

    def test_contract_is_pinned(self):
        for key, value in (('dimension', 768), ('pooling', 'mean'), ('normalize', False),
                           ('query_prefix', 'query: '), ('passage_prefix', 'passage: ')):
            with self.subTest(key=key):
                contract = {**self.contract, key: value}
                self.prepare.return_value = (self.model, contract, {}, CASES)
                with self.assertRaisesRegex(ValueError, 'pinned BGE-M3 contract'):
                    cpu.validate(self.job)

    def test_exactly_120_cases_and_sorted_order_are_required(self):
        for cases, message in ((CASES[:-1], 'exactly 120'),
                               (list(reversed(CASES)), 'cases must be sorted'),
                               ([*CASES[:-1], CASES[0]], 'exactly 120')):
            with self.subTest(message=message):
                self.prepare.return_value = (self.model, self.contract, {}, cases)
                with self.assertRaisesRegex(ValueError, message):
                    cpu.validate(self.job)

    def test_query_scope_and_sample_overrides_are_rejected(self):
        for job, message in (({**self.job, 'benchmark_scope': 'total_retrieve'},
                              'query representation'),
                             ({**self.job, 'samples': 1}, 'sample override')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                cpu.validate(job)
        self.assertEqual(self.prepare.call_count, 0)


if __name__ == '__main__':
    unittest.main()
