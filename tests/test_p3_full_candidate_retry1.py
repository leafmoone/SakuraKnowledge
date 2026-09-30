import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
SPEC=importlib.util.spec_from_file_location('retry1',ROOT/'tools/p3_full_candidate_retry1.py')
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    for key in ('ATTEMPT','RESULT','MANIFEST','OUTPUT','GATE','RAW'):
        monkeypatch.setattr(M,key,tmp_path/key)
    return tmp_path


def test_authorization_and_anchors():
    assert M.RETRY1_MAX_ATTEMPTS==1
    assert M.PREVIOUS_SUBMISSION=='97c3c4969dfb637093e78e7151fc561c91913b78'
    assert M.PREVIOUS_BUILD=='0aa46a57b1dcb4ac9a04a3c3ba49b97234ea616d'
    assert len(M.ORIGINAL_SHAS)==5
    assert M.DECISION_SHA=='4fdd2cbcf56c8e97398898dd27482ec67abd0c58c29133d947d44639523a63d6'
    assert M.authorized_delta(['tools/record_check.py','tools/p3_full_candidate_retry1.py',
                               'reports/P3/full-retry1-check-timeout.json'])
    for forbidden in ('tools/p3_full_candidate.py','tools/p3_evidence.py',
                      'reports/P3/full-authorized-attempt.json','reports/P3/FULL_AUTHORIZED_STOP_REPORT.md',
                      'src/sakura_knowledge/storage.py','rust/src/lib.rs'):
        assert not M.authorized_delta([forbidden])
    assert M.OUTPUT.as_posix()=='build/p3-full-authorized-retry1'
    assert M.ATTEMPT.as_posix()=='reports/P3/full-retry1-attempt.json'


def test_zero_verified_optional():
    assert M.optional_coverage([])['zero_is_legal'] is True
    assert M.optional_coverage([])['verified_entity_tag_real_positive_required'] is False
    assert M.optional_coverage([])['verified_entity_tag']==0


@pytest.mark.parametrize('status',['BLOCKED','FAILED'])
def test_blocked_never_build(isolated,monkeypatch,status):
    monkeypatch.setattr(M,'build',lambda *_:pytest.fail('blocked gate may not build'))
    assert M.execute_once({'status':status})==2
    assert not M.ATTEMPT.exists()


@pytest.mark.parametrize('missing',list(M.HOST_ENV))
def test_missing_host_contract_blocks_before_process_or_builder(isolated,monkeypatch,missing):
    for k,v in M.HOST_ENV.items():monkeypatch.setenv(k,v)
    monkeypatch.delenv(missing)
    monkeypatch.setattr(M,'process_proof',lambda:pytest.fail('must block before process inspection'))
    monkeypatch.setattr(M,'build',lambda *_:pytest.fail('must not build'))
    gate=M.audit_gate()
    assert gate['status']=='BLOCKED'
    assert json.loads(M.GATE.read_text())['gates']['host_deadline_contract'] is False
    assert M.execute_once(gate)==2
    assert not M.ATTEMPT.exists()
    assert not M.MANIFEST.exists()


def test_gate_exception_retained_before_reservation(isolated,monkeypatch):
    for k,v in M.HOST_ENV.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(M,'git',lambda *_:'fixture')
    def failed_inspection():raise RuntimeError('fixture process inspection failure')
    monkeypatch.setattr(M,'process_proof',failed_inspection)
    monkeypatch.setattr(M,'build',lambda *_:pytest.fail('must not build'))
    gate=M.audit_gate()
    assert gate['status']=='FAILED'
    assert Path(gate['exception']['path']).read_bytes().endswith(b'fixture process inspection failure\n')
    assert json.loads(M.GATE.read_text())['attempts']==0
    assert M.execute_once(gate)==2
    assert not M.ATTEMPT.exists()
    with pytest.raises(FileExistsError):M.audit_gate()


@pytest.mark.parametrize(('policy_ok','old_builders'),[(False,[]),(True,[{'ProcessId':123}])])
def test_wrong_parent_or_active_old_builder_blocks(isolated,monkeypatch,policy_ok,old_builders):
    for k,v in M.HOST_ENV.items():monkeypatch.setenv(k,v)
    events=[]
    def git(*args):
        events.append(args)
        return '' if args[0]=='status' else 'fixture'
    def process():
        assert ('status','--porcelain') in events
        return {'observed':{'old_builders':old_builders}}
    monkeypatch.setattr(M,'git',git)
    monkeypatch.setattr(M,'process_proof',process)
    monkeypatch.setattr(M,'timeout_policy',lambda _: {'ok':policy_ok})
    monkeypatch.setattr(M,'previous_audit',lambda:pytest.fail('blocked before old files'))
    monkeypatch.setattr(M,'build',lambda *_:pytest.fail('must not build'))
    gate=M.audit_gate()
    assert gate['status']=='BLOCKED' and gate['working_tree_before_outputs']==''
    assert M.execute_once(gate)==2
    assert not M.ATTEMPT.exists()


def host_processes(parent_argv,child_argv):
    return {'observed':{'parent':{'CommandLine':parent_argv,'ProcessId':os.getppid()},
                        'current':{'CommandLine':child_argv,'ProcessId':os.getpid(),
                                   'ParentProcessId':os.getppid()},'old_builders':[]}}


def test_parent_timeout_none_contract(monkeypatch):
    for k,v in M.HOST_ENV.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(M,'command_argv',lambda argv:argv)
    monkeypatch.setattr(M,'digest',lambda _: 'record_checkSHA')
    parent=list(M.EXPECTED_INVOCATION)
    child=['python',*parent[8:]]
    proof=M.timeout_policy(host_processes(parent,child))
    assert proof['ok'] is True
    assert proof['requested']==0 and proof['effective'] is None and proof['disabled'] is True
    assert proof['expected_invocation']==M.EXPECTED_INVOCATION
    parent[3]='300'
    assert M.timeout_policy(host_processes(parent,child))['ok'] is False
    parent[3]='0';parent[2:4]=[]
    assert M.timeout_policy(host_processes(parent,child))['ok'] is False


@pytest.mark.skipif(os.name!='nt',reason='actual Windows argv parser')
def test_windows_command_parser_without_starting_process():
    argv=M.command_argv('"C:\\Program Files\\Python\\python.exe" tools/record_check.py --timeout 0')
    assert argv==['C:\\Program Files\\Python\\python.exe','tools/record_check.py','--timeout','0']


def test_exact_process_capture_retains_utf8_command_and_raw(isolated,monkeypatch):
    observed={'parent':{},'current':{},'old_builders':[]}
    def capture(argv,**kwargs):
        assert argv[:3]==['powershell.exe','-NoProfile','-Command']
        assert '[System.Text.UTF8Encoding]::new($false)' in argv[3]
        assert ' -u tools/p3_full_candidate[.]py --execute$' in argv[3]
        assert kwargs['timeout'] is None
        return subprocess.CompletedProcess(argv,0,json.dumps(observed).encode(),b'')
    monkeypatch.setattr(M.subprocess,'run',capture)
    proof=M.process_proof()
    assert proof['observed']==observed
    assert Path(proof['stdout']['path']).read_bytes()==json.dumps(observed).encode()
    assert Path(proof['stderr']['path']).read_bytes()==b''


@pytest.mark.parametrize('changed',[False,True])
def test_timeout_tests_receipt_requires_same_tested_code(isolated,monkeypatch,changed):
    receipt=isolated/'timeout-tests.json'
    receipt.write_text(json.dumps({'head':'testedSHA','status':'PASS','exit':0,
                                   'argv':M.TEST_COMMAND,'working_tree':''}))
    monkeypatch.setattr(M,'TIMEOUT_TESTS',receipt)
    def git(*args):
        if args[0]=='diff':
            assert args[2:4]==('testedSHA','executionSHA')
            assert args[5:]==tuple(M.TEST_CODE)
            return 'tools/record_check.py' if changed else ''
        assert args[0]=='rev-parse'
        return 'receiptBlob'
    monkeypatch.setattr(M,'git',git)
    monkeypatch.setattr(M.subprocess,'run',lambda *_a,**_k:subprocess.CompletedProcess([],0))
    proof=M.timeout_tests_receipt('executionSHA')
    assert proof['ok'] is (not changed)
    assert proof['git_blob']=='receiptBlob' and proof['sha256']==M.digest(receipt)


def test_failed_build_cap_and_after_preservation(isolated,monkeypatch):
    calls=[]
    real_fsync=M.os.fsync
    def fsync(fd):
        calls.append('fsync');real_fsync(fd)
    monkeypatch.setattr(M.os,'fsync',fsync)
    def fail(*_):
        # The ledger is durably reserved before any normal build activity.
        assert calls==['fsync']
        ledger=json.loads(M.ATTEMPT.read_text())
        assert ledger['previous_attempts']==ledger['retry1_count']==ledger['maximum']==1
        assert ledger['total_attempts']==2 and ledger['retry2_forbidden'] is True
        assert ledger['automatic_retry_forbidden'] is True
        calls.append('build')
        raise RuntimeError('fixture-only builder failure')
    def preserved(gate):
        calls.append('preservation_after')
        return {'unchanged':True,'partial_never_sqlite_opened':True}
    monkeypatch.setattr(M,'build',fail)
    monkeypatch.setattr(M,'preservation_after',preserved)
    gate={'status':'READY','fixed_code_sha':'testSHA','manifest':{'path':str(M.MANIFEST)},
          'previous':{'attempt_binding':{'git_blob':'oldBlob'}},'timeout_policy':{'effective':None}}
    assert M.execute_once(gate)==1
    assert calls==['fsync','build','preservation_after']
    result=json.loads(M.RESULT.read_text())
    assert result['status']=='FAIL' and result['total_attempts']==2
    assert result['preservation_after']['unchanged'] is True
    with pytest.raises(FileExistsError):M.execute_once(gate)
    assert calls==['fsync','build','preservation_after']


@pytest.mark.parametrize(('counts','verification','preserved','expected'),[
    ([352,0,28,'1'],True,True,0),([351,0,28,'1'],True,True,1),
    ([352,0,28,'1'],False,True,1),([352,0,28,'1'],True,False,1)])
def test_new_output_readonly_counts_and_preservation_gate(isolated,monkeypatch,counts,verification,preserved,expected):
    calls=[]
    def fixture_build(manifest,output):
        assert manifest==M.MANIFEST and output==M.OUTPUT and M.ATTEMPT.exists()
        output.mkdir();(output/'knowledge.sqlite').write_bytes(b'fixture-only output')
        return {'verification':{'ok':verification}}
    values=iter(counts)
    class Readonly:
        def __enter__(self):return self
        def __exit__(self,*_):return False
        def execute(self,sql):
            calls.append(sql);return self
        def fetchone(self):return (next(values),)
    def connect(database,**kwargs):
        assert database==(M.OUTPUT/'knowledge.sqlite').resolve().as_uri()+'?mode=ro&immutable=1'
        assert kwargs=={'uri':True}
        return Readonly()
    monkeypatch.setattr(M,'build',fixture_build)
    monkeypatch.setattr(M.sqlite3,'connect',connect)
    monkeypatch.setattr(M,'preservation_after',lambda _: {'unchanged':preserved})
    gate={'status':'READY','fixed_code_sha':'testSHA','manifest':{},'previous':{'attempt_binding':{}},
          'timeout_policy':{},'coverage':M.optional_coverage([])}
    assert M.execute_once(gate)==expected
    result=json.loads(M.RESULT.read_text())
    assert result['status']==('PASS' if expected==0 else 'FAIL')
    assert list(result['readonly_projection_counts'].values())==counts
    assert calls[0]=='PRAGMA query_only=ON' and len(calls)==5


def test_preserved_partial_only_hashed_never_opened_as_sqlite(isolated,monkeypatch):
    partial=isolated/'partial'
    partial.write_bytes(b'unverified SQLite bytes')
    ref={'path':str(partial),'bytes':partial.stat().st_size,'sha256':M.digest(partial)}
    monkeypatch.setattr(M.sqlite3,'connect',lambda *_a,**_k:pytest.fail('never SQLite-open previous partial'))
    assert M.preserved_files([ref])[0]['unchanged'] is True
    partial.write_bytes(b'mutation')
    assert M.preserved_files([ref])[0]['unchanged'] is False
    partial.unlink()
    assert M.preserved_files([ref])[0]['unchanged'] is False


def test_old_report_git_blob_current_bytes_exact(isolated,monkeypatch):
    monkeypatch.chdir(isolated)
    stop=Path('reports/P3/FULL_AUTHORIZED_STOP_REPORT.md')
    stop.parent.mkdir(parents=True)
    stop.write_bytes(b'frozen\r\n')
    blob='a'*40
    def git_capture(argv):
        if argv[1]=='ls-tree':
            assert M.PREVIOUS_SUBMISSION in argv
            return f'100644 blob {blob}\t{stop.as_posix()}\0'.encode()
        if argv[1]=='rev-parse':return blob.encode()
        assert argv==['git','cat-file','blob',blob]
        return b'frozen\r\n'
    monkeypatch.setattr(M.subprocess,'check_output',git_capture)
    assert M.frozen_reports()[0]['unchanged'] is True
    stop.write_bytes(b'frozen\n')
    assert M.frozen_reports()[0]['unchanged'] is True
    assert M.frozen_reports()[0]['markdown_EOL_equivalence_only'] is True
    stop.write_bytes(b'mutated\n')
    assert M.frozen_reports()[0]['unchanged'] is False
