"""Actual modular single-query sender fixtures, not real-source validation."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.normalized_source import build_normalized, normalize
from tools.p4_rust_pilot import MAX_BYTES


@pytest.mark.parametrize('oversized', [False, True])
def test_config_single_retrieve_uses_bounded_semantic_sender(tmp_path, oversized):
    configured = os.environ.get('SKNOW_RS_TEST_BIN')
    if not configured:
        pytest.skip('Rust fixture integration NOT_RUN: set SKNOW_RS_TEST_BIN explicitly')
    binary = Path(configured).resolve()
    assert binary.is_file()
    # Synthetic source-backed fixture identity; full UTF-8 body is never clipped.
    text = 'alpha ' + ('日' * (MAX_BYTES // 5) if oversized else '日' * 10)
    raw = tmp_path / 'raw.json'
    items = [{'type': 'subject', 'id': f's{number}',
              'name': f'Synthetic alpha fixture {number}', 'description': text}
             for number in range(2 if oversized else 1)]
    raw.write_text(json.dumps({'items': items, 'relations': []}, ensure_ascii=False), encoding='utf-8')
    bundle = tmp_path / 'normalized'
    normalize(raw, 'examples.source_pack.demo_adapter:DemoAdapter', bundle, 'future-fixture')
    root = tmp_path / 'root'
    (root / 'bin').mkdir(parents=True)
    # Builder workspace remains outside the runtime discovery directory.
    pack = tmp_path / 'source-pack'
    build_normalized(bundle, pack)
    shutil.copytree(pack, root / 'packs/future-fixture')
    config = root / 'sknow-config.json'
    config.write_text(json.dumps({'packs_directory': 'packs', 'model_directory': 'model',
                                  'bin_directory': 'bin'}), encoding='utf-8')
    result = subprocess.run([str(binary), '--config', str(config), 'retrieve', 'alpha',
                             '--source', 'future-fixture', '--topk', '100'],
                            capture_output=True, timeout=15, check=False)
    assert result.stdout.endswith(b'\n')
    assert result.stdout.count(b'\n') == 1
    response = json.loads(result.stdout)
    profile = json.loads(result.stderr)
    assert profile['sent_bytes'] == len(result.stdout) <= MAX_BYTES
    assert profile['response_too_large'] == oversized
    if oversized:
        assert result.returncode == 1
        assert response['status'] == 'FAIL'
        assert response['error'] == 'response_too_large'
        assert response['limit_bytes'] == MAX_BYTES
        assert response['response_bytes'] == profile['response_bytes'] > MAX_BYTES
        assert response['retries'] == 0
        assert 'documents' not in response and 'candidates' not in response
    else:
        assert result.returncode == 0 and response['status'] == 'PASS'
        assert response['documents'][0]['original'] == text
        assert profile['response_bytes'] == len(result.stdout)
        assert response['lexical_mode'] == 'trusted_documents_and_identity'
        assert response['dense_hits'] == [] and not (root / 'model').exists()
