"""Read-only reference gates and mocked export tests; no model execution."""
import copy
import hashlib
import json
import tempfile
import types
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from tools import p4_onnx_export as export


def fixture_save(path, value):
    # Test-owned temporary fixtures intentionally mutate for rejection tests.
    path.write_text(json.dumps(value), encoding='utf-8')


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = export.exact.load(export.exact.ROOT / 'configs/p4-onnx-representation-v2.json')
        self.job = {'threads': 8, 'index': 'build/p4/continuation-dense-b-v1'}
        self.reference = export.exact.local(self.contract['query_reference'])

    def test_frozen_contract(self):
        export.validate_contract(self.contract, self.job, self.reference)

    def test_export_options_fail_closed(self):
        for key, value in [('dynamo', True), ('dynamo', 0), ('opset', 18),
                           ('external_data', False), ('dtype', 'float16'),
                           ('quantization', 'int8'), ('attention_implementation', 'sdpa'),
                           ('export_attempt_limit', 2), ('fallback_exporter', 'other'),
                           ('query_reference_scope', 'historical')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                export.validate_contract({**self.contract, key: value}, self.job, self.reference)

    def test_sample_rule(self):
        self.assertEqual(len(set(export.SAMPLE_ROWS)), 128)
        self.assertEqual(export.SAMPLE_ROWS[0], 0)
        self.assertEqual(export.SAMPLE_ROWS[-1], 52663)
        self.assertEqual(list(export.SAMPLE_ROWS), [i * 52663 // 127 for i in range(128)])

    def test_actual_reference_read_only(self):
        if not self.reference.is_file():
            self.skipTest('authorized local reference is not available')
        job = export.exact.load(export.exact.local(export.producer.JOB))
        prepared = export.cpu.validate(job)
        paths = export.verify_reference(self.reference, self.contract, job, prepared)
        self.assertIn(self.reference.parent / 'cases.json', paths)
        self.assertIn(self.reference.parent / 'inputs.json', paths)
        self.assertIn(export.exact.local('tools/p4_query_reference.py'), paths)
        weights = export.exact.local(prepared[0]['asset_directory']) / 'pytorch_model.bin'
        self.assertIn(weights, paths)
        self.assertTrue(weights.is_file())


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch.object(export.exact, 'ROOT', self.root))
        self.directory = self.root / 'reference'
        self.directory.mkdir()
        self.path = self.directory / 'manifest.json'
        self.contract = {'query_reference_scope': export.REFERENCE_SCOPE}
        self.job = {key: key + '.json' for key in (
            'summary', 'corpus', 'gold', 'chunks_manifest', 'chunks',
            'authorization', 'selection_receipt')}
        for key, value in self.job.items():
            if key != 'selection_receipt':
                fixture_save(self.root / value, {})
        fixture_save(self.root / 'selection_receipt.json', {
            'input_hash_validations': {'extra': {'path': 'extra.json'}}})
        fixture_save(self.root / 'extra.json', {})
        job_path = export.exact.local(export.producer.JOB)
        job_path.parent.mkdir(parents=True)
        fixture_save(job_path, self.job)
        (self.root / 'tools').mkdir()
        for name in ('p4_query_reference', 'p4_cpu_representation', 'p4_exact_pilot', 'p4_selection_v2'):
            (self.root / 'tools' / (name + '.py')).write_text('# frozen\n', encoding='utf-8')
        (self.root / 'assets').mkdir()
        weights = self.root / 'assets/pytorch_model.bin'
        weights.write_bytes(b'weights')
        fixture_save(self.root / 'native.json', {})
        model = {'asset_directory': 'assets', 'contract': {'path': 'native.json'},
                 'obtained_receipt': {'files': [{'path': 'pytorch_model.bin',
                                                'sha256': export.exact.sha(weights)}]}}
        cases = [{'case_id': f'case-{i:03}', 'query': f'query {i} 日本語'} for i in range(120)]
        self.prepared = (model, {'max_sequence_tokens': 8192}, {}, cases)
        self.provenance = {'model_inventory_sha256': 'model', 'tokenizer_inventory_sha256': 'tokens'}
        self.enterContext(patch.object(export.exact, 'provenance', return_value=self.provenance))
        inputs = export.producer.snapshot(job_path, self.job, self.prepared)
        fixture_save(self.directory / 'inputs.json', inputs)
        ordered = [{'row': row, 'case_id': case['case_id'], 'actual_tokens': 4,
                    'query_text_sha256': hashlib.sha256(case['query'].encode('utf-8')).hexdigest()}
                   for row, case in enumerate(cases)]
        fixture_save(self.directory / 'cases.json', ordered)
        vectors = np.zeros((120, 1024), dtype=np.float32)
        vectors[:, 0] = 1
        np.save(self.directory / 'vectors.npy', vectors, allow_pickle=False)
        validation = {'status': 'PASS', 'snapshot_sha256': export.exact.canonical_hash(inputs)}
        self.manifest = {
            'status': 'PASS', 'authorization_scope': export.producer.SCOPE,
            'historical_pilot': False, 'native_qualification_retry': False,
            'selection_rerun': False, 'ranking': False, 'warmups': 0,
            'attempted_queries': 120, 'completed_queries': 120,
            'shape': [120, 1024], 'dtype': 'float32',
            'frozen_provenance': self.provenance, **self.provenance,
            'code_sha256': inputs['code_sha256'], 'versions': {},
            'versions_sha256': export.exact.canonical_hash({}),
            'encoder': {'provider': 'huggingface/torch', 'actual_device': 'cpu',
                        'requested_device': 'cpu', 'actual_dtype': 'torch.float32',
                        'threads': 8, 'interop_threads': 8},
            'input_validations': {'before': validation, 'after': copy.deepcopy(validation)},
        }
        self.refresh()

    def refresh(self):
        self.manifest['payload_sha256'] = {
            name: export.exact.sha(self.directory / name)
            for name in ('vectors.npy', 'cases.json', 'inputs.json')}
        self.manifest['vectors_sha256'] = self.manifest['payload_sha256']['vectors.npy']
        fixture_save(self.path, self.manifest)

    def verify(self, repin=True):
        # Synthetic fixtures authorize only their own bytes, never the production pin.
        with ExitStack() as stack:
            if repin:
                stack.enter_context(patch.object(export, 'REFERENCE_MANIFEST_SHA256',
                                                 export.exact.sha(self.path)))
                stack.enter_context(patch.object(export, 'REFERENCE_VECTORS_SHA256',
                                                 self.manifest['vectors_sha256']))
            return export.verify_reference(self.path, self.contract, self.job, self.prepared)

    def test_actual_producer_format_and_complete_binding(self):
        paths = self.verify()
        for name in ('reference/manifest.json', 'reference/vectors.npy', 'reference/cases.json',
                     'reference/inputs.json', 'extra.json', 'assets/pytorch_model.bin',
                     'tools/p4_query_reference.py', 'tools/p4_selection_v2.py'):
            self.assertIn(self.root / name, paths)

    def test_unauthorized_manifest_digest(self):
        with self.assertRaises(ValueError):
            self.verify(repin=False)

    def test_semantic_rejections_even_if_manifest_reauthorized(self):
        original = copy.deepcopy(self.manifest)
        for key, value in (
            ('status', 'FAIL'), ('authorization_scope', export.REFERENCE_SCOPE),
            ('historical_pilot', True), ('historical_pilot', 0),
            ('native_qualification_retry', True), ('selection_rerun', True), ('ranking', True),
            ('warmups', 1), ('attempted_queries', 119), ('completed_queries', 119),
            ('shape', [119, 1024]), ('dtype', 'float16'), ('frozen_provenance', {}),
            ('model_inventory_sha256', 'bad'), ('code_sha256', {}),
            ('input_validations', {'before': original['input_validations']['before'],
                                   'after': {'status': 'FAIL', 'snapshot_sha256': 'bad'}}),
            ('versions_sha256', 'bad')):
            with self.subTest(key=key, value=value):
                self.manifest = {**copy.deepcopy(original), key: value}
                self.refresh()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_corrupt_payload_or_bound_source(self):
        for name in ('reference/vectors.npy', 'reference/cases.json', 'reference/inputs.json',
                     'extra.json', 'tools/p4_selection_v2.py', 'assets/pytorch_model.bin'):
            with self.subTest(name=name):
                path = self.root / name
                before = path.read_bytes()
                try:
                    path.write_bytes(b'corrupt')
                    with self.assertRaises(ValueError):
                        self.verify()
                finally:
                    path.write_bytes(before)

    def test_query_identity_order_and_token_bounds(self):
        path = self.directory / 'cases.json'
        original = export.exact.load(path)
        for key, value in (('row', 1), ('case_id', 'other'), ('query_text_sha256', 'bad'),
                           ('actual_tokens', 0), ('actual_tokens', 8193), ('actual_tokens', True)):
            with self.subTest(key=key, value=value):
                ordered = copy.deepcopy(original)
                ordered[0][key] = value
                fixture_save(path, ordered)
                self.refresh()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_vector_shape_dtype_finiteness_and_normalization(self):
        for shape, dtype, value in (((119, 1024), np.float32, 0),
                                    ((120, 1024), np.float64, 0),
                                    ((120, 1024), np.float32, np.nan),
                                    ((120, 1024), np.float32, 0)):
            with self.subTest(shape=shape, dtype=dtype, value=value):
                np.save(self.directory / 'vectors.npy', np.full(shape, value, dtype=dtype))
                self.refresh()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_provisional_schema_not_accepted(self):
        fixture_save(self.path, {'schema': 'p4-query-reference-v2', 'status': 'PASS',
                                     'scope': export.REFERENCE_SCOPE})
        with self.assertRaises((KeyError, ValueError)):
            self.verify()


class ExporterTests(unittest.TestCase):
    def test_single_path_export_and_explicit_options(self):
        calls = []

        def exporter(model, inputs, path, *, dynamo, external_data, opset_version,
                     do_constant_folding, **kwargs):
            calls.append((model, inputs, path, dynamo, external_data, opset_version,
                          do_constant_folding, kwargs))

        tensor = Mock()
        tensor.to.return_value = tensor
        tokenizer = Mock()
        tokenizer.pad.return_value = {'input_ids': tensor, 'attention_mask': tensor}
        torch = types.SimpleNamespace(onnx=types.SimpleNamespace(export=exporter), no_grad=nullcontext)
        with patch.dict('sys.modules', {'torch': torch}):
            export.export_once('wrapper', {'rows': [{'input_ids': [0, 2], 'attention_mask': [1, 1]}]},
                               tokenizer, Path('model.onnx'))
        self.assertEqual(len(calls), 1)
        model, inputs, path, dynamo, external, opset, folding, kwargs = calls[0]
        self.assertEqual((model, path, dynamo, external, opset, folding),
                         ('wrapper', 'model.onnx', False, True, 17, True))
        self.assertEqual(len(inputs), 2)
        self.assertEqual(kwargs['input_names'], ['input_ids', 'attention_mask'])
        self.assertEqual(kwargs['dynamic_axes']['input_ids'], {0: 'batch', 1: 'sequence'})
        self.assertEqual(kwargs['dynamic_axes']['attention_mask'], {0: 'batch', 1: 'sequence'})
        self.assertEqual(kwargs['dynamic_axes']['embeddings'], {0: 'batch'})
        self.assertNotIn('fallback', kwargs)

    def test_unsupported_exporter_never_called(self):
        exporter = Mock()
        torch = types.SimpleNamespace(onnx=types.SimpleNamespace(export=exporter))
        with patch.dict('sys.modules', {'torch': torch}), self.assertRaisesRegex(ValueError, 'lacks frozen'):
            export.export_once(None, {}, None, Path('model.onnx'))
        exporter.assert_not_called()

    def test_checker_receives_path_not_proto(self):
        checker = Mock()
        with patch.dict('sys.modules', {'onnx': types.SimpleNamespace(checker=checker)}):
            export.check_model(Path('large.onnx'))
        checker.check_model.assert_called_once_with('large.onnx')


class RunTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.output = self.root / 'output'
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(export.exact, 'ROOT', self.root))
        self.job = {'threads': 8, 'index': 'index',
                    **{k: k + '.json' for k in ('chunks', 'chunks_manifest', 'gold', 'corpus',
                                               'summary', 'authorization', 'selection_receipt')}}
        for value in self.job.values():
            if isinstance(value, str) and value.endswith('.json'):
                fixture_save(self.root / value, {})
        (self.root / 'index').mkdir()
        (self.root / 'assets').mkdir()
        (self.root / 'assets' / 'weights').write_bytes(b'original')
        (self.root / 'index' / 'vectors.npy').write_bytes(b'frozen-vector-file')
        fixture_save(self.root / 'native.json', {})
        self.model = {'repository': export.cpu.B_REPOSITORY, 'revision': export.cpu.B_REVISION,
                      'asset_directory': 'assets', 'contract': {'path': 'native.json'},
                      'obtained_receipt': {'files': [{'path': 'weights'}]}}
        self.prepared = (self.model, {}, {}, [])
        self.contract = {'passage_sample': {'reference': 'index/vectors.npy'}}
        fixture_save(self.root / 'job.json', self.job)
        fixture_save(self.root / 'contract.json', self.contract)
        fixture_save(self.root / 'reference.json', {'status': 'PASS'})
        fixture_save(self.root / 'index' / 'index.json', {
            'shape': [52664, 1024], 'dtype': 'float32', 'provenance': {},
            'vectors_sha256': export.exact.sha(self.root / 'index' / 'vectors.npy')})
        stack.enter_context(patch.object(export, 'validate_contract'))
        self.validate = stack.enter_context(patch.object(export.cpu, 'validate',
                                                        return_value=self.prepared))
        stack.enter_context(patch.object(export.exact, 'provenance', return_value={}))
        self.reference = stack.enter_context(patch.object(
            export, 'verify_reference', return_value=[self.root / 'reference.json']))
        stack.enter_context(patch.object(export.exact, 'frozen_tokenizers', return_value=(None, None)))
        stack.enter_context(patch.object(export, 'select_passages', return_value={'rows': []}))
        self.loader = stack.enter_context(patch.object(export, 'load_model', return_value='wrapper'))
        stack.enter_context(patch.object(export, 'versions', return_value={'torch': 'mock'}))
        self.exporter = stack.enter_context(patch.object(export, 'export_once',
                                                        side_effect=self.fake_export))
        self.checker = stack.enter_context(patch.object(export, 'check_model'))

    def fake_export(self, wrapper, sample, tokenizer, path):
        self.assertTrue((self.output / 'passage-sample.json').is_file())
        self.assertFalse((self.output / 'manifest.json').exists())
        path.write_bytes(b'onnx')
        (path.parent / 'model.onnx.data').write_bytes(b'external-weights')

    def run_export(self):
        return export.run(self.root / 'job.json', self.root / 'contract.json',
                          self.root / 'reference.json', self.output)

    def test_success_checks_and_hashes_all_files(self):
        self.assertEqual(self.run_export(), 0)
        self.exporter.assert_called_once()
        self.loader.assert_called_once_with(self.model, 8)
        self.checker.assert_called_once_with(self.output / 'model.onnx')
        manifest = export.exact.load(self.output / 'manifest.json')
        self.assertEqual(manifest['status'], 'PASS')
        self.assertEqual(manifest['revision'], export.cpu.B_REVISION)
        self.assertEqual(manifest['export_attempts'], 1)
        files = {r['path']: r for r in manifest['files']}
        self.assertEqual(set(files), {'passage-sample.json', 'model.onnx', 'model.onnx.data'})
        for name, record in files.items():
            self.assertEqual(record['sha256'], export.exact.sha(self.output / name))
        self.assertEqual(self.validate.call_count, 2)

    def test_existing_directory_untouched(self):
        self.output.mkdir()
        sentinel = self.output / 'sentinel'
        sentinel.write_bytes(b'keep')
        self.assertEqual(self.run_export(), 1)
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.validate.assert_not_called()
        self.exporter.assert_not_called()

    def test_missing_reference_fails_before_load(self):
        (self.root / 'reference.json').unlink()
        self.assertEqual(self.run_export(), 1)
        self.loader.assert_not_called()
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertEqual(export.exact.load(self.output / 'failure.json')['export_attempts'], 0)

    def test_reference_rejection_before_model(self):
        self.reference.side_effect = ValueError('manifest digest mismatch')
        self.assertEqual(self.run_export(), 1)
        self.loader.assert_not_called()
        self.exporter.assert_not_called()
        self.assertEqual(export.exact.load(self.output / 'failure.json')['export_attempts'], 0)

    def test_export_failure_no_fallback_or_pass(self):
        self.exporter.side_effect = RuntimeError('export failed')
        self.assertEqual(self.run_export(), 1)
        self.exporter.assert_called_once()
        self.checker.assert_not_called()
        self.assertFalse((self.output / 'manifest.json').exists())
        failure = export.exact.load(self.output / 'failure.json')
        self.assertEqual(failure['phase'], 'export')
        self.assertEqual(failure['export_attempts'], 1)
        self.assertTrue((self.output / 'passage-sample.json').exists())
        self.assertEqual(self.run_export(), 1)
        self.exporter.assert_called_once()

    def test_checker_failure(self):
        self.checker.side_effect = ValueError('invalid graph')
        self.assertEqual(self.run_export(), 1)
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertEqual(export.exact.load(self.output / 'failure.json')['phase'], 'onnx_checker')

    def test_changed_input_or_reference_never_passes(self):
        for name in ('job.json', 'reference.json', 'assets/weights', 'index/vectors.npy'):
            with self.subTest(name=name):
                self.output = self.root / ('output-' + name.replace('/', '-'))

                def mutate(*args, name=name):
                    self.fake_export(*args)
                    (self.root / name).write_bytes(b'changed')

                self.exporter.side_effect = mutate
                before = (self.root / name).read_bytes()
                self.assertEqual(self.run_export(), 1)
                self.assertFalse((self.output / 'manifest.json').exists())
                (self.root / name).write_bytes(before)

    def test_index_hash_mismatch_before_model(self):
        (self.root / 'index' / 'vectors.npy').write_bytes(b'corrupt')
        self.assertEqual(self.run_export(), 1)
        self.exporter.assert_not_called()
        self.loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
