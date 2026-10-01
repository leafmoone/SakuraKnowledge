"""Synthetic reference tests: never import or execute a real model."""
import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from tools import p4_query_reference as reference


class QueryReferenceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(reference.exact, 'ROOT', self.root))
        self.stderr = self.stack.enter_context(redirect_stderr(StringIO()))
        (self.root / 'tools').mkdir()
        for name in ('p4_query_reference.py', 'p4_cpu_representation.py',
                     'p4_exact_pilot.py', 'p4_selection_v2.py'):
            (self.root / 'tools' / name).write_text('# synthetic dependency\n', encoding='utf-8')
        self.job = {'threads': 8, 'model': 'b', 'device': 'cpu'}
        for key in ('summary', 'corpus', 'gold', 'chunks_manifest', 'chunks',
                    'authorization', 'selection_receipt'):
            path = self.root / (key + '.json')
            value = {'input_hash_validations': {}} if key == 'selection_receipt' else {}
            reference.exact.save(path, value)
            self.job[key] = path.name
            self.job[key + '_sha256'] = reference.exact.sha(path)
        job_path = self.root / reference.JOB
        job_path.parent.mkdir(parents=True)
        reference.exact.save(job_path, self.job)
        reference.exact.save(self.root / 'contract.json', {})
        self.model = {'repository': 'BAAI/bge-m3', 'revision': 'a' * 40,
                      'obtained_receipt': {'inventory_sha256': 'b' * 64},
                      'contract': {'path': 'contract.json', 'file_sha256': 'c' * 64}}
        self.contract = {'max_sequence_tokens': 8192}
        self.chunk_manifest = {'chunks_sha256': 'd' * 64, 'tokenizer_inventory_sha256': 'e' * 64}
        self.cases = [{'case_id': f'{i:03}', 'query': f'日本語 {i}'} for i in range(120)]
        self.prepared = (self.model, self.contract, self.chunk_manifest, self.cases)
        self.validate = self.stack.enter_context(patch.object(
            reference.cpu, 'validate', return_value=self.prepared))
        self.encoder = Mock()
        self.encoder.info = {'provider': 'huggingface/torch', 'actual_device': 'cpu',
                             'actual_dtype': 'torch.float32', 'threads': 8, 'interop_threads': 8,
                             'torch': 'synthetic', 'transformers': 'synthetic', 'tokenizers': 'synthetic'}
        self.encoder.encode.side_effect = self.encode
        self.factory = self.stack.enter_context(patch.object(
            reference.exact, 'LocalEncoder', return_value=self.encoder))
        self.output = self.root / reference.OUTPUT

    @staticmethod
    def encode(texts, query):
        assert query is True
        vector = np.zeros((1, 1024), dtype=np.float32)
        vector[0, int(texts[0].split()[-1])] = 1
        return vector, [5]

    def run_reference(self):
        return reference.run(reference.JOB, reference.OUTPUT)

    def assert_failed(self, attempts):
        self.assertEqual(self.run_reference(), 1)
        self.assertFalse((self.output / 'manifest.json').exists())
        failure = reference.exact.load(self.output / 'failure.json')
        self.assertEqual(failure['attempted_queries'], attempts)
        self.assertFalse(failure['retry_attempted'])
        self.assertEqual(self.encoder.encode.call_count, attempts)
        return failure

    def test_exactly_once_order_fp32_and_all_payload_hashes(self):
        self.assertEqual(self.run_reference(), 0)
        self.assertEqual(self.validate.call_count, 2)
        self.factory.assert_called_once_with(self.model, self.contract, 'cpu', 8)
        self.assertEqual(self.encoder.encode.call_count, 120)
        for call, case in zip(self.encoder.encode.call_args_list, self.cases, strict=True):
            self.assertEqual(call.args, ([case['query']],))
            self.assertEqual(call.kwargs, {'query': True})
        vectors = np.load(self.output / 'vectors.npy', allow_pickle=False)
        self.assertEqual(vectors.shape, (120, 1024))
        self.assertEqual(vectors.dtype, np.float32)
        np.testing.assert_array_equal(vectors.argmax(axis=1), np.arange(120))
        records = reference.exact.load(self.output / 'cases.json')
        self.assertEqual([r['case_id'] for r in records], [c['case_id'] for c in self.cases])
        self.assertEqual([r['actual_tokens'] for r in records], [5] * 120)
        self.assertEqual(records[0]['query_text_sha256'],
                         hashlib.sha256(self.cases[0]['query'].encode()).hexdigest())
        manifest = reference.exact.load(self.output / 'manifest.json')
        self.assertEqual(manifest['authorization_scope'], reference.SCOPE)
        self.assertEqual(manifest['warmups'], 0)
        self.assertEqual(manifest['input_validations']['before'], manifest['input_validations']['after'])
        for name, digest in manifest['payload_sha256'].items():
            self.assertEqual(digest, reference.exact.sha(self.output / name))
        self.assertFalse((self.output / 'failure.json').exists())

    def test_asset_validation_failure_precedes_model_load(self):
        self.validate.side_effect = ValueError('unsafe or mismatched asset')
        self.assert_failed(0)
        self.factory.assert_not_called()

    def test_bad_case_count_precedes_model_load(self):
        self.cases.pop()
        self.assert_failed(0)
        self.factory.assert_not_called()

    def test_unsorted_cases_rejected(self):
        self.cases.reverse()
        self.assert_failed(0)
        self.factory.assert_not_called()

    def test_duplicate_cases_rejected(self):
        self.cases[1] = self.cases[0]
        self.assert_failed(0)
        self.factory.assert_not_called()

    def test_first_encode_failure_stops_without_retry(self):
        self.encoder.encode.side_effect = [self.encode(['日本語 0'], True), RuntimeError('failed')]
        failure = self.assert_failed(2)
        self.assertEqual(failure['completed_queries'], 1)
        self.assertEqual(failure['case_id'], '001')
        self.assertEqual(self.validate.call_count, 1)

    def test_nonfinite_vector_stops(self):
        self.encoder.encode.side_effect = None
        self.encoder.encode.return_value = (np.full((1, 1024), np.nan, dtype=np.float32), [5])
        self.assert_failed(1)

    def test_wrong_dtype_stops(self):
        self.encoder.encode.side_effect = None
        self.encoder.encode.return_value = (np.ones((1, 1024), dtype=np.float64), [5])
        self.assert_failed(1)

    def test_invalid_token_count_stops(self):
        self.encoder.encode.side_effect = None
        self.encoder.encode.return_value = (self.encode(['日本語 0'], True)[0], [8193])
        self.assert_failed(1)

    def test_wrong_actual_device_stops_before_encoding(self):
        self.encoder.info['actual_device'] = 'cuda:0'
        self.assert_failed(0)

    def test_after_validation_failure_has_no_success_manifest(self):
        self.validate.side_effect = [self.prepared, ValueError('changed assets')]
        failure = self.assert_failed(120)
        self.assertEqual(failure['phase'], 'input_validation_after')
        self.assertFalse((self.output / 'vectors.npy').exists())

    def test_changed_snapshot_is_rejected(self):
        changed = copy.deepcopy(self.prepared)
        changed[3][0]['query'] = 'changed'
        self.validate.side_effect = [self.prepared, changed]
        self.assert_failed(120)

    def test_existing_output_is_never_overwritten_or_retried(self):
        self.output.mkdir(parents=True)
        reference.exact.save(self.output / 'manifest.json', {'existing': True})
        digest = reference.exact.sha(self.output / 'manifest.json')
        self.assertEqual(self.run_reference(), 1)
        self.assertEqual(digest, reference.exact.sha(self.output / 'manifest.json'))
        self.assertFalse((self.output / 'failure.json').exists())
        self.assertEqual(json.loads(self.stderr.getvalue())['phase'], 'output_reservation')
        self.validate.assert_not_called()
        self.factory.assert_not_called()

    def test_load_failure_no_retry(self):
        self.factory.side_effect = RuntimeError('load failed')
        self.assert_failed(0)
        self.factory.assert_called_once()

    def test_bad_threads_precedes_validation_and_load(self):
        job_path = self.root / reference.JOB
        job_path.unlink()
        reference.exact.save(job_path, {**self.job, 'threads': 4})
        self.assert_failed(0)
        self.validate.assert_not_called()
        self.factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
