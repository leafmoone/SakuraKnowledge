import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p4_rust_legacy_regression as regression


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
        value = {'status': 'unresolved'}
        self.assertIn('status', self.compare(value, value, expected={'status': 'resolved'}))

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


if __name__ == '__main__':
    unittest.main()
