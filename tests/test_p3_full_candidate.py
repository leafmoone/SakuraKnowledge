"""Safety tests for OPTIONAL coverage gate and exclusive one-shot reservation."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
SPEC=importlib.util.spec_from_file_location('full_candidate',ROOT/'tools/p3_full_candidate.py')
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def test_authorization_allowlist():
    assert M.authorized_delta(['tools/p3_full_candidate.py','reports/P3/full-authorized-preflight-old151.json'])
    assert not M.authorized_delta(['tools/p3_evidence.py'])
    assert not M.authorized_delta(['src/sakura_knowledge/tag_decisions.py'])


def test_reviewed_digest_anchors():
    assert len(M.ORIGINAL_SHAS)==5
    assert M.ORIGINAL_SHAS['bangumi-complete-6a75aefb769a']=='6a75aefb769a62f0eaa3b58ed76fb172a5dc1922a9e5be40bd7de2ff8343dcc4'
    assert M.DECISION_SHA=='4fdd2cbcf56c8e97398898dd27482ec67abd0c58c29133d947d44639523a63d6'


def test_zero_verified_optional():
    assert M.optional_coverage([])['zero_is_legal'] is True
    assert M.optional_coverage([])['verified_entity_tag_real_positive_required'] is False
    assert M.optional_coverage([])['verified_entity_tag']==0


def test_blocked_never_build(tmp_path,monkeypatch):
    monkeypatch.setattr(M,'ATTEMPT',tmp_path/'attempt.json')
    monkeypatch.setattr(M,'build',lambda *_:pytest.fail('blocked gate may not build'))
    assert M.execute_once({'status':'BLOCKED'})==2
    assert not M.ATTEMPT.exists()


def test_failed_build_reserves_once_and_cannot_retry(tmp_path,monkeypatch):
    for key in ('ATTEMPT','RESULT','MANIFEST','OUTPUT'):
        monkeypatch.setattr(M,key,tmp_path/key)
    monkeypatch.setattr(M,'store',lambda raw:{'traceback':raw.decode()})
    calls=[]
    def fail(*_):
        calls.append('attempt')
        raise RuntimeError('deliberate fixture-only builder failure')
    monkeypatch.setattr(M,'build',fail)
    gate={'status':'READY','fixed_code_sha':'testSHA','manifest':{'path':str(M.MANIFEST)}}
    assert M.execute_once(gate)==1
    assert calls==['attempt']
    assert json.loads(M.ATTEMPT.read_text())['attempts']==1
    assert json.loads(M.RESULT.read_text())['status']=='FAIL'
    with pytest.raises(FileExistsError):M.execute_once(gate)
    assert calls==['attempt']
