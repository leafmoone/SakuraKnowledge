"""Independent synthetic profile/episode contract checks; no FULL snapshot."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from test_core import manifest, record

from sakura_knowledge.api import Knowledge
from sakura_knowledge.storage import build


@pytest.fixture
def binary():
    path = os.environ.get('SKNOW_RS_TEST_BIN')
    if not path:
        pytest.skip('explicit Rust binary required')
    return Path(path)


@pytest.fixture
def db(tmp_path):
    ep = record('episode', 'fixture.episode', 'episode-key', 'episode needle')
    ep['aliases'] = [{'text': 'episode alias', 'status': 'source_backed'}]
    page = record('page', 'fixture.page', 'page-key', 'page needle')
    build(manifest(tmp_path, [ep, page]), tmp_path / 'snapshot')
    return tmp_path / 'snapshot/knowledge.sqlite'


def invoke(binary, db, query, sink=None, kind='episode'):
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    env.pop('SKNOW_SEARCH_PROFILE_OUT', None)
    if sink is not None:
        env['SKNOW_SEARCH_PROFILE_OUT'] = str(sink)
    return subprocess.run([str(binary), 'search', str(db), query, '--kind', kind, '--topk', '20'],
                          capture_output=True, env=env, timeout=15, check=False)


@pytest.mark.parametrize('query', ['episode-key', 'episode alias', 'absent phrase', 'needle'])
def test_false_exact_alias_nohit_preserved_and_single_profile(binary, db, tmp_path, query):
    sink = tmp_path / 'profile.json'
    proc = invoke(binary, db, query, sink)
    assert proc.returncode == 0 and not proc.stderr
    with Knowledge(db) as api:
        assert json.loads(proc.stdout) == api.search(query, kind='episode', topk=20)
    profile = json.loads(sink.read_bytes())
    assert profile['query_invocations'] == 1 and profile['query_succeeded']
    assert profile['profile']['fts_skipped_kind_not_indexed'] is True
    assert profile['profile']['scanned_rows'] == 0


def test_default_no_profile_and_other_kind_fts(binary, db, tmp_path):
    proc = invoke(binary, db, 'needle', kind='page')
    assert proc.returncode == 0 and not proc.stderr
    assert json.loads(proc.stdout)['candidates'][0]['matched_by'] == 'fts'
    assert not (tmp_path / 'profile.json').exists()
    proc = invoke(binary, db, 'needle', tmp_path / 'profile.json', kind='page')
    profile = json.loads((tmp_path / 'profile.json').read_bytes())
    assert proc.returncode == 0 and profile['query_invocations'] == 1
    assert profile['profile']['scanned_rows'] > 0
    assert 'fts_skipped_kind_not_indexed' not in profile['profile']


@pytest.mark.parametrize('existing', [True, False])
def test_sink_reservation_failure_before_query(binary, db, tmp_path, existing):
    sink = tmp_path / 'profile.json' if existing else tmp_path / 'missing/profile.json'
    if existing:
        sink.write_bytes(b'preserve me')
    proc = invoke(binary, db, 'episode-key', sink)
    assert proc.returncode == 2 and not proc.stdout
    assert 'sink reservation failed' in json.loads(proc.stderr)['message']
    if existing:
        assert sink.read_bytes() == b'preserve me'
    else:
        assert not sink.parent.exists()


def test_original_query_error_retained(binary, db, tmp_path):
    sink = tmp_path / 'error-profile.json'
    proc = invoke(binary, db, 'x' * 4097, sink)
    assert proc.returncode == 2 and not proc.stdout
    assert json.loads(proc.stderr)['error'] == 'ValueError'
    profile = json.loads(sink.read_bytes())
    assert profile['query_invocations'] == 1 and not profile['query_succeeded']
    assert profile['query_error']
