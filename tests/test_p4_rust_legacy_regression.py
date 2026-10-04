import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p4_rust_legacy_regression as regression


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        env.pop('PYTHONPATH', None)
        return subprocess.run([sys.executable, 'tools/p4_rust_legacy_regression.py', *args],
                              cwd=regression.ROOT, env=env, capture_output=True,
                              encoding='utf-8', timeout=30, check=False)

    def test_direct_help_without_pythonpath(self):
        proc = self.run_cli('--help')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        for option in ('--execute', '--run-id', '--target-dir', '--knowledge'):
            self.assertIn(option, proc.stdout)
        self.assertNotIn('--runtime-sha', proc.stdout)

    def test_direct_cli_requires_execute_without_pythonpath(self):
        proc = self.run_cli('--run-id', 'cli-light', '--target-dir', 'unused-cli-light-target')
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn('the following arguments are required: --execute', proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)


class ComparisonTests(unittest.TestCase):
    def compare(self, value, baseline, suite='gold', mode='value', expected=None,
                exit_code=0, stderr=b''):
        row = {'original_case': {'mode': mode, 'expected': expected or {}}}
        rec = {'timeout': False, 'exit': exit_code}
        return regression.compare(suite, row, rec, json.dumps(value).encode(), stderr, baseline)[1]

    def test_whole_gold_nested_mismatch(self):
        self.assertIn('approved_whole_json_mismatch', self.compare(
            {'status': 'resolved', 'nested': [2]}, {'status': 'resolved', 'nested': [1]}))

    def test_key_order_is_not_semantic(self):
        self.assertEqual([], self.compare({'a': 1, 'b': [2]}, {'b': [2], 'a': 1}))

    def test_source_assertions_independent(self):
        self.assertIn('status', self.compare({'status': 'unresolved'}, {'status': 'unresolved'},
                                              expected={'status': 'resolved'}))

    def test_stderr_rejected_on_success(self):
        self.assertIn('value_exit_or_stderr', self.compare({}, {}, stderr=b'noise'))

    def test_error_whole_message_and_contract(self):
        row = {'original_case': {'mode': 'error', 'historical_expect': {'error': 'bad'}}}
        baseline = {'error': 'ValueError', 'message': 'bad'}
        rec = {'timeout': False, 'exit': 2}
        self.assertEqual([], regression.compare('P2', row, rec, b'', json.dumps(baseline).encode(), baseline)[1])
        self.assertIn('approved_whole_json_mismatch', regression.compare(
            'P2', row, rec, b'', b'{"error":"ValueError","message":"other"}', baseline)[1])

    def test_timeout_rejected(self):
        row = {'original_case': {'mode': 'value', 'expected': {}}}
        self.assertIn('process_failure', regression.compare(
            'gold', row, {'timeout': True, 'exit': 0}, b'{}', b'', {})[1])


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.knowledge = self.root / regression.approved.DB.relative_to(regression.ROOT)
        self.knowledge.parent.mkdir(parents=True)
        self.knowledge.write_bytes(b'synthetic Knowledge')
        self.target = self.root / 'build/legacy-unit-target'
        self.calls = []

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, b'{}', b'')

    def context(self, **kwargs):
        return regression.RunContext(kwargs.pop('run_id', 'unit'), kwargs.pop('target_dir', self.target),
                                     kwargs.pop('knowledge', self.knowledge), root=self.root,
                                     runner=kwargs.pop('runner', self.runner), **kwargs)

    def test_new_paths_old_preservation_and_no_overwrite(self):
        old = self.root / 'build/p4-rust-default-target'
        old.mkdir(parents=True)
        (old / 'sentinel').write_bytes(b'old')
        context = self.context()
        context.reserve()
        self.assertEqual(context.report_path, self.root / 'reports/P4/legacy-unit.json')
        self.assertEqual(context.env['CARGO_TARGET_DIR'], str(self.target))
        self.assertEqual((old / 'sentinel').read_bytes(), b'old')
        with self.assertRaises(FileExistsError):
            self.context().reserve()

    def test_existing_report_prevents_target_creation(self):
        context = self.context()
        context.report_path.parent.mkdir(parents=True)
        context.report_path.write_bytes(b'old report')
        with self.assertRaises(FileExistsError):
            context.reserve()
        self.assertFalse(self.target.exists())
        self.assertEqual(context.report_path.read_bytes(), b'old report')

    def test_strict_context(self):
        for overrides in ({'run_id': '../old'}, {'run_id': ''},
                          {'target_dir': self.root}, {'knowledge': self.root}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.context(**overrides)

    def test_capture_failure_preserves_utf8_and_no_retry(self):
        def fail(argv, **kwargs):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 7, b'out', '失敗'.encode())
        context = self.context(runner=fail)
        context.reserve()
        with self.assertRaises(ValueError):
            context.run(['synthetic'])
        rec = json.loads((context.local / 'command-0000.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['stderr_utf8'], '失敗')
        self.assertEqual(rec['exit'], 7)
        self.assertEqual(len(self.calls), 1)

    def test_build_failure_retains_provenance(self):
        def fail(argv, **kwargs):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 1, b'', b'build failed')
        context = self.context(runner=fail)
        context.reserve()
        with self.assertRaisesRegex(ValueError, 'build failed'):
            context.build()
        rec = json.loads((context.local / 'build.json').read_text(encoding='utf-8'))
        self.assertEqual(rec['process']['exit'], 1)
        self.assertNotIn('source_sha', rec)
        self.assertEqual(len(self.calls), 1)

    def test_build_binds_actual_contained_binary(self):
        context = self.context()
        context.reserve()
        def build(argv, **kwargs):
            binary = context.target / ('release/sknow-rs.exe' if os.name == 'nt' else 'release/sknow-rs')
            binary.parent.mkdir()
            binary.write_bytes(b'synthetic binary bytes')
            return subprocess.CompletedProcess(argv, 0, b'', b'')
        context.runner = build
        binary, provenance = context.build()
        self.assertEqual(provenance['binary']['sha256'], regression.approved.file_binding(binary)['sha256'])
        self.assertTrue(binary.is_relative_to(context.target))


if __name__ == '__main__':
    unittest.main()
