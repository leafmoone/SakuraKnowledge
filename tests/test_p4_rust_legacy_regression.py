import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p4_rust_legacy_regression as regression

from tools import p4_full_acceptance as acceptance


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
        for option in ('--execute', '--run-id', '--target-dir', '--knowledge', '--binary', '--results-dir'):
            self.assertIn(option, proc.stdout)
        self.assertNotIn('--runtime-sha', proc.stdout)

    def test_direct_cli_requires_execute_without_pythonpath(self):
        proc = self.run_cli('--run-id', 'cli-light', '--target-dir', 'unused-cli-light-target')
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn('--execute requires --run-id and --target-dir', proc.stderr)
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


class ExistingBinaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.binary = self.root / 'build/existing-target/release/sknow-rs.exe'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'tiny binary fixture')
        self.cache = self.root / 'build/existing-target/cache'
        self.cache.write_bytes(b'preserve cache bytes')
        self.knowledge = self.root / 'data/Knowledge.db'
        self.knowledge.parent.mkdir()
        self.knowledge.write_bytes(b'tiny snapshot fixture')
        self.contract = self.root / 'contract.json'
        self.snapshot = self.binding(self.knowledge)
        self.contract.write_text(json.dumps({'snapshot': self.snapshot}), encoding='utf-8')
        for obj, name, value in ((regression, 'ROOT', self.root),
                                 (regression.approved, 'DB', self.knowledge),
                                 (regression.fullpreflight, 'FULL_CONTRACT', self.contract),
                                 (acceptance, 'ROOT', self.root)):
            self.enterContext(mock.patch.object(obj, name, value))
        self.calls = []
        self.cases = [self.case('P2', 'first'), self.case('gold', 'second')]
        self.session = acceptance.AcceptanceSession()
        self.addCleanup(self.session.close)
        self.output = self.root / 'results'

    def binding(self, path):
        data = path.read_bytes()
        return {'path': path.relative_to(self.root).as_posix(), 'size': len(data),
                'sha256': hashlib.sha256(data).hexdigest()}

    def case(self, suite, cid):
        return (suite, {'case_id': cid, 'original_case': {'mode': 'value', 'expected': {}}},
                {'process': {'argv': ['historical-binary', cid]}}, {})

    def runner(self, argv, **kwargs):
        self.calls.append(argv)
        self.assertEqual(argv[0], str(self.binary))
        self.assertNotIn('cargo', argv)
        return subprocess.CompletedProcess(argv, 0, b'{}', b'')

    def execute(self, *, runner=None, loader=None):
        if loader is None:
            loader = lambda run: ({'baseline_corpus_manifest': {'fixture': True}}, self.cases)
        with mock.patch.object(regression, 'load_baseline', side_effect=loader), \
                mock.patch.object(regression.subprocess, 'run', side_effect=runner or self.runner), \
                mock.patch.object(regression.RunContext, 'reserve', side_effect=AssertionError('no reserve')), \
                mock.patch.object(regression.RunContext, 'build', side_effect=AssertionError('no build')), \
                contextlib.redirect_stdout(io.StringIO()):
            code = regression.existing_binary(binary=self.binary, results_dir=self.output,
                                              knowledge=self.knowledge, verified_session=self.session)
        return code, json.loads((self.output / 'evaluation.json').read_bytes())

    def test_all_cases_actual_session_partial_is_not_pass_and_cache_preserved(self):
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([c['passed'] for c in report['cases']], [True, True])
        self.assertEqual(report['counts'], {'P2': {'executed': 1, 'passed': 1, 'expected': 151},
                                           'gold': {'executed': 1, 'passed': 1, 'expected': 55}})
        self.assertEqual(report['binary_binding'], self.binding(self.binary))
        self.assertEqual(self.session._inventory._verified[self.binary],
                         (self.binary.stat().st_size, self.binding(self.binary)['sha256']))
        self.assertEqual(len(self.session._inventory._verified), 2)
        self.assertEqual(self.cache.read_bytes(), b'preserve cache bytes')
        self.assertEqual(self.binary.read_bytes(), b'tiny binary fixture')

    def test_timeout_exception_and_mismatch_keep_raw_and_continue(self):
        self.cases.append(self.case('gold', 'third'))
        def runner(argv, **kwargs):
            self.calls.append(argv)
            if argv[1] == 'first':
                raise subprocess.TimeoutExpired(argv, 15, output=b'partial', stderr=b'timeout stderr')
            if argv[1] == 'second':
                raise OSError('launch failure')
            return subprocess.CompletedProcess(argv, 9, b'{"extra":1}', b'failure stderr')
        code, report = self.execute(runner=runner)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(report['cases']), 3)
        first, second, third = [c['process'] for c in report['cases']]
        self.assertTrue(first['timeout'])
        self.assertIsNone(first['exit'])
        self.assertEqual(second['exception']['message'], 'launch failure')
        self.assertEqual(third['exit'], 9)
        for rec, want in ((first, b'timeout stderr'), (second, b''), (third, b'failure stderr')):
            self.assertEqual((self.root / rec['stderr']['path']).read_bytes(), want)
            self.assertEqual(rec['argv'][0], str(self.binary))
        self.assertIn('approved_whole_json_mismatch', report['cases'][2]['problems'])

    def test_baseline_command_failure_retains_raw_stderr_and_evaluation(self):
        def loader(run):
            run(['git', 'show', 'fixture-anchor'])
        def runner(argv, **kwargs):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 128, b'partial baseline', b'git failure')
        code, report = self.execute(loader=loader, runner=runner)
        self.assertEqual(code, 1)
        self.assertEqual(report['failure']['type'], 'ValueError')
        rec = report['commands'][0]
        self.assertEqual(rec['argv'], ['git', 'show', 'fixture-anchor'])
        self.assertEqual((self.root / rec['stderr']['path']).read_bytes(), b'git failure')
        self.assertEqual(rec['exit'], 128)

    def test_primary_error_survives_session_end_failure(self):
        def loader(run):
            self.knowledge.write_bytes(b'mutated fixture')
            raise ValueError('primary baseline failure')
        code, report = self.execute(loader=loader)
        self.assertEqual(code, 1)
        self.assertEqual(report['failure']['message'], 'primary baseline failure')
        self.assertEqual(report['end_failure']['message'], 'inventory changed')
        # Restore the fixture before the real session's cleanup check.
        self.knowledge.write_bytes(b'tiny snapshot fixture')
        self.session._closed = True

    def test_output_collision_and_escape_refused_without_commands(self):
        self.output.mkdir()
        sentinel = self.output / 'evaluation.json'
        sentinel.write_bytes(b'old evidence')
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(sentinel.read_bytes(), b'old evidence')
        self.output = self.root.parent / (self.root.name + '-escape')
        with self.assertRaises(ValueError):
            self.execute()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_snapshot_pin_is_actually_checked(self):
        self.contract.write_text(json.dumps({'snapshot': {**self.snapshot, 'sha256': '0' * 64}}), encoding='utf-8')
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn('actual file binding mismatch', report['failure']['message'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
