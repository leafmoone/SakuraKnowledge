"""Mock-only collector safety; no network connection or new official acquisition."""
import io
import json
import sys
import urllib.error
import urllib.request

import pytest
from test_p3_review_cf807 import tool


@pytest.mark.parametrize('code',[301,302,303,307,308])
def test_redirect_never_creates_second_request(code):
    collector=tool('p3_acquire_native')
    request=urllib.request.Request('https://danbooru.donmai.us/tags.json')
    with pytest.raises(urllib.error.HTTPError):
        collector.NoRedirect().redirect_request(request,io.BytesIO(),code,'redirect',{},'https://elsewhere.invalid/')


@pytest.mark.parametrize('status',[302,401,403,429])
def test_http_stop_preserves_budget_and_retry_after(tmp_path,monkeypatch,status):
    collector=tool('p3_acquire_native')
    targets=tmp_path/'targets.json';targets.write_text(json.dumps({'targets':[{'title':'A'}]}))
    out=tmp_path/'receipt.json';calls=[]
    def open_mock(request,timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url,status,'mock stop',{'Retry-After':'60'},io.BytesIO(b'mock'))
    class MockOpener:
        open=staticmethod(open_mock)
    monkeypatch.setattr(urllib.request,'urlopen',open_mock)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *handlers:MockOpener())
    monkeypatch.setattr(sys,'argv',['collector','--targets',str(targets),'--out',str(out)])
    assert collector.main()==2
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['status']=='SOURCE_ACQUISITION_BLOCKED' and result['requests_including_prior_docs']==5
    assert len(calls)==1 and result['records'][0]['http_status']==status
    assert result['records'][0]['retry_after']=='60' and result['retries']==0


def test_request_budget_no_http_when_exhausted(tmp_path,monkeypatch):
    collector=tool('p3_acquire_native')
    targets=tmp_path/'targets.json';targets.write_text(json.dumps({'targets':[{'title':'A'}]}))
    previous=tmp_path/'previous.json';previous.write_text(json.dumps({'status':'SCOPED_COMPLETE',
        'requests_including_prior_docs':200,'download_bytes_this_collector':0}))
    out=tmp_path/'receipt.json'
    def forbidden(*args,**kwargs):raise AssertionError('network must not be attempted')
    monkeypatch.setattr(urllib.request,'urlopen',forbidden)
    class MockOpener:open=staticmethod(forbidden)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *handlers:MockOpener())
    monkeypatch.setattr(sys,'argv',['collector','--targets',str(targets),'--previous',str(previous),
                                  '--aliases-only','--out',str(out)])
    assert collector.main()==2
    result=json.loads(out.read_text())
    assert result['requests_including_prior_docs']==200 and result['records']==[]


def test_mock_request_spacing_before_each_request(tmp_path,monkeypatch):
    collector=tool('p3_acquire_native')
    targets=tmp_path/'targets.json';targets.write_text(json.dumps({'targets':[{'title':'A'},{'title':'B'}]}))
    previous=tmp_path/'previous.json';previous.write_text(json.dumps({'status':'SCOPED_COMPLETE',
        'requests_including_prior_docs':52,'download_bytes_this_collector':186307}))
    out=tmp_path/'receipt.json';clock=[100.0];starts=[];sleeps=[]
    class Response(io.BytesIO):
        status=200
        def __init__(self,value):
            super().__init__(value)
            self.headers={}
    def sleep(delay):sleeps.append(delay);clock[0]+=delay
    def open_mock(request,timeout):starts.append(clock[0]);return Response(b'[]')
    class MockOpener:open=staticmethod(open_mock)
    monkeypatch.setattr(collector.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(collector.time,'sleep',sleep)
    monkeypatch.setattr(urllib.request,'urlopen',open_mock)
    monkeypatch.setattr(urllib.request,'build_opener',lambda *handlers:MockOpener())
    monkeypatch.setattr(sys,'argv',['collector','--targets',str(targets),'--previous',str(previous),
                                  '--aliases-only','--out',str(out)])
    assert collector.main()==0
    result=json.loads(out.read_text())
    assert result['requests_including_prior_docs']==54 and len(starts)==2
    assert starts[1]-starts[0]>=1.05-1e-12 and sleeps==[1.05]
