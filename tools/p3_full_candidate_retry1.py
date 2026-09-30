"""Separate root-authorized retry1; the exhausted original attempt stays frozen.

Copied from p3_full_candidate.py. Only the authorization/ledger/deadline and
preservation proofs differ; the normal atomic builder and projections do not.
"""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
import traceback
from pathlib import Path

from p3_evidence import save, store

from sakura_knowledge.storage import build, digest, load_manifest
from sakura_knowledge.tag_decisions import replay

P3_BASE='894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
IMPLEMENTATION='8a5b3d23695a43970d1902d6d6dea7c9e7dd1882'
APPROVED='28cf51bda963ded8bed2def289fd316a4db6bfd0'
PREVIOUS_SUBMISSION='97c3c4969dfb637093e78e7151fc561c91913b78'
PREVIOUS_BUILD='0aa46a57b1dcb4ac9a04a3c3ba49b97234ea616d'
RETRY1_MAX_ATTEMPTS=1
OLD=Path('build/snapshot-full-20bf5b3/knowledge.sqlite')
OLD_SHA='4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073'
CUT=Path('build/p3-owner-8a5b3d2-inputs/candidate-manifest.json')
MANIFEST=Path('build/p3-full-retry1-manifest.json')
OUTPUT=Path('build/p3-full-authorized-retry1')
GATE=Path('reports/P3/full-retry1-gate.json')
ATTEMPT=Path('reports/P3/full-retry1-attempt.json')
RESULT=Path('reports/P3/full-retry1-build.json')
RAW=Path('reports/P3/raw')
TIMEOUT_TESTS=Path('reports/P3/full-retry1-check-timeout.json')
PREVIOUS_ATTEMPT=Path('reports/P3/full-authorized-attempt.json')
PREVIOUS_OUTPUT=Path('build/p3-full-authorized-once')
PARTIAL=Path('build/.sknow-z7dkmnsi')
DECISIONS=Path('reports/P3/review-d01-decisions.jsonl')
DECISION_SHA='4fdd2cbcf56c8e97398898dd27482ec67abd0c58c29133d947d44639523a63d6'
ORIGINAL_SHAS={
    'bangumi-complete-6a75aefb769a':'6a75aefb769a62f0eaa3b58ed76fb172a5dc1922a9e5be40bd7de2ff8343dcc4',
    'moegirl-complete-5072f7cf3e3e':'5072f7cf3e3ee4e558fb7421aadf9c9b600b8303b8f9c61cf3da9871018ac99d',
    'mapping-complete-c8263a535096':'c8263a5350964534170d833f560fb50758e3a4215e86b8f5c72cd51b72266f1f',
    'danbooru-complete-a26a3829dd42':'a26a3829dd42155848392c0636daebd6ca01acf540d3509fec2ac3219f8596c5',
    'tag_wiki-complete-a2eb055c578d':'a2eb055c578d37e82b71df787cd11b7616e77768eb319cf0839831cfdbb28fef'}
ALLOWED_CODE_CHANGES={
    'tools/record_check.py','tools/p3_full_candidate_retry1.py',
    'tests/test_record_check.py','tests/test_p3_full_candidate_retry1.py',
    'docs/p3-full-coverage-contract.md'}
TEST_CODE=[
    'tools/record_check.py','tools/p3_full_candidate_retry1.py',
    'tests/test_record_check.py','tests/test_p3_full_candidate_retry1.py']
TEST_COMMAND=['python','-m','pytest','-q',*TEST_CODE[2:]]
EXPECTED_INVOCATION=[
    'python','tools/record_check.py','--timeout','0','--out',
    'reports/P3/full-retry1-build-command.json','--',
    'python','-u','tools/p3_full_candidate_retry1.py','--execute']
HOST_ENV={'SKNOW_FULL_RETRY1_HOST_TIMEOUT':'0','SKNOW_FULL_RETRY1_MANAGED_TASK':'1'}
FAILURE_ACTION='STOP; no retry2, resume, new path, old write, or automatic retry'


def authorized_delta(names):
    return all(n in ALLOWED_CODE_CHANGES or n.startswith('reports/P3/full-retry1-') for n in names)


def git(*args):return subprocess.check_output(['git',*args]).decode().strip()


def raw(data):return store(data,root=RAW)


def optional_coverage(verified):
    return {'policy':'OPTIONAL_COVERAGE','verified_entity_tag_real_positive_required':False,
            'verified_entity_tag':len(verified),'zero_is_legal':True,
            'identity_safety':'candidate/name/score never promoted; tag_decisions/resolver unchanged'}


def command_argv(command):
    # Use Windows' parser, not whitespace splitting: executable paths can contain spaces.
    if os.name!='nt':
        raise RuntimeError('retry1 host proof requires actual Win32 parent command')
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    shell.CommandLineToArgvW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
    count=ctypes.c_int()
    argv=shell.CommandLineToArgvW(command,ctypes.byref(count))
    if not argv:raise ctypes.WinError(ctypes.get_last_error())
    try:return [argv[i] for i in range(count.value)]
    finally:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.LocalFree.argtypes=[ctypes.c_void_p]
        kernel.LocalFree.restype=ctypes.c_void_p
        kernel.LocalFree(ctypes.cast(argv,ctypes.c_void_p))


def process_proof():
    # Exact old builder matcher is retained from the original stop inspection.
    script=(
        '$ErrorActionPreference="Stop"; '
        '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); '
        f'$c=Get-CimInstance Win32_Process -Filter "ProcessId = {os.getpid()}"; '
        '$p=Get-CimInstance Win32_Process -Filter "ProcessId = $($c.ParentProcessId)"; '
        '$old=@(Get-CimInstance Win32_Process | Where-Object { '
        '$_.Name -eq "python.exe" -and $_.CommandLine -match '
        '" -u tools/p3_full_candidate[.]py --execute$" } | '
        'Select-Object ProcessId,ParentProcessId,Name,CommandLine); '
        '$r=@{current=($c | Select-Object ProcessId,ParentProcessId,Name,CommandLine); '
        'parent=($p | Select-Object ProcessId,ParentProcessId,Name,CommandLine); '
        'old_builders=$old}; ConvertTo-Json -InputObject $r -Depth 5')
    argv=['powershell.exe','-NoProfile','-Command',script]
    p=subprocess.run(argv,capture_output=True,check=False,timeout=None,
                     env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUTF8='1'))
    evidence={'argv':argv,'exit':p.returncode,'stdout':raw(p.stdout),'stderr':raw(p.stderr),
              'encoding':'PowerShell Console UTF-8 without BOM','timeout':None}
    if p.returncode!=0:raise RuntimeError(f'Win32 process inspection failed: {evidence}')
    evidence['observed']=json.loads(p.stdout.decode('utf-8-sig'))
    return evidence


def timeout_policy(processes):
    observed=processes['observed'];parent=observed['parent'];current=observed['current']
    parent_argv=command_argv(parent['CommandLine'])
    child_argv=command_argv(current['CommandLine'])
    # Python may expose its absolute executable path in CommandLine; all other
    # argv elements must be the exact frozen invocation, including explicit 0.
    parent_ok=(bool(parent_argv) and Path(parent_argv[0]).name.lower() in ('python','python.exe') and
               parent_argv[1:]==EXPECTED_INVOCATION[1:] and
               parent['ProcessId']==current['ParentProcessId'] and
               parent['ProcessId']==os.getppid() and current['ProcessId']==os.getpid())
    child_ok=(bool(child_argv) and Path(child_argv[0]).name.lower() in ('python','python.exe') and
              child_argv[1:]==EXPECTED_INVOCATION[8:])
    environment={k:os.environ.get(k) for k in HOST_ENV}
    return {'requested':0,'effective':None,'disabled':True,
            'expected_invocation':EXPECTED_INVOCATION,'parent_argv':parent_argv,
            'current_argv':child_argv,'parent_exact':parent_ok,'current_exact':child_ok,
            'environment':environment,'environment_exact':environment==HOST_ENV,
            'record_check_source_sha256':digest('tools/record_check.py'),
            'host_contract':'caller tool bash timeout=0, managed background task, no tighter shell/subprocess deadline',
            'host_contract_observable_limit':'outer tool deadline is not a Win32 property; required environment is caller attestation',
            'ok':parent_ok and child_ok and environment==HOST_ENV}


def timeout_tests_receipt(head):
    receipt=json.loads(TIMEOUT_TESTS.read_text(encoding='utf-8'))
    # Evidence may be committed after its code commit, but tested code must stay
    # byte-identical. Never substitute a receipt from a different implementation.
    unchanged=not git('diff','--name-only',receipt['head'],head,'--',*TEST_CODE)
    ancestor=subprocess.run(['git','merge-base','--is-ancestor',receipt['head'],head],check=False).returncode==0
    return {'path':TIMEOUT_TESTS.as_posix(),'bytes':TIMEOUT_TESTS.stat().st_size,
            'sha256':digest(TIMEOUT_TESTS),'git_blob':git('rev-parse',head+':'+TIMEOUT_TESTS.as_posix()),
            'tested_head':receipt['head'],'argv':receipt['argv'],'tested_code_unchanged':unchanged,
            'ok':receipt['status']=='PASS' and receipt['exit']==0 and receipt['argv']==TEST_COMMAND and
                 not receipt['working_tree'] and unchanged and ancestor}


def frozen_reports():
    rows=[]
    tree=subprocess.check_output(['git','ls-tree','-r','-z',PREVIOUS_SUBMISSION,'--','reports/P3'])
    for entry in tree.split(b'\0'):
        if not entry:continue
        meta,name=entry.split(b'\t',1);_,kind,blob=meta.decode().split()
        if kind!='blob':raise ValueError('unexpected non-blob old report')
        name=name.decode('utf-8');expected=subprocess.check_output(['git','cat-file','blob',blob])
        p=Path(name);actual=p.read_bytes()
        # Compare committed blobs separately from Windows checkout bytes: reviewed
        # binding declared Markdown LF/CRLF; JSON/JSONL are always exact bytes.
        current_blob=git('rev-parse','HEAD:'+name)
        byte_match=actual==expected
        eol_only=name.endswith('.md') and actual.replace(b'\r\n',b'\n')==expected.replace(b'\r\n',b'\n')
        rows.append({'path':name,'git_blob':blob,'bytes':len(expected),
                     'git_bytes_sha256':hashlib.sha256(expected).hexdigest(),
                     'current_bytes':len(actual),'current_sha256':hashlib.sha256(actual).hexdigest(),
                     'worktree_byte_exact':byte_match,'markdown_EOL_equivalence_only':eol_only and not byte_match,
                     'unchanged':not p.is_symlink() and current_blob==blob and (byte_match or eol_only)})
    if not rows or not any(r['path']=='reports/P3/FULL_AUTHORIZED_STOP_REPORT.md' for r in rows):
        raise ValueError('old report inventory/STOP report missing')
    return rows


def preserved_files(refs):
    # Hash bytes only. In particular, NEVER SQLite-open the unverified old partial.
    rows=[]
    for ref in refs:
        p=Path(ref['path'])
        try:
            size=p.stat().st_size;sha=digest(p)
            rows.append(dict(ref,observed_bytes=size,observed_sha256=sha,
                             unchanged=not p.is_symlink() and size==ref['bytes'] and sha==ref['sha256']))
        except OSError as exc:
            rows.append(dict(ref,unchanged=False,error=str(exc)))
    return rows


def previous_audit():
    reports=frozen_reports()
    ledger=json.loads(PREVIOUS_ATTEMPT.read_text(encoding='utf-8'))
    previous=json.loads(Path('reports/P3/full-authorized-build.json').read_text(encoding='utf-8'))
    command=json.loads(Path('reports/P3/full-authorized-build-command.json').read_text(encoding='utf-8'))
    delivery=json.loads(Path('reports/P3/full-authorized-delivery.json').read_text(encoding='utf-8'))
    refs=delivery['partial_staging']['files']+[
        r['builder_private_frozen'] for r in delivery['builder_private_input_copies']]
    expected_paths={str(PARTIAL/f) for f in (
        'knowledge.sqlite','knowledge.sqlite-wal','knowledge.sqlite-shm',
        '.inputs/0','.inputs/1','.inputs/2','.inputs/3','.inputs/4','.inputs/5')}
    expected_paths={Path(p).as_posix() for p in expected_paths}
    if len(refs)!=9 or {Path(r['path']).as_posix() for r in refs}!=expected_paths:
        raise ValueError('previous partial inventory must be exactly sqlite/WAL/SHM and six private copies')
    actual_paths={p.as_posix() for p in PARTIAL.rglob('*') if p.is_file()}
    lock=delivery['partial_staging']['lock']
    if (Path(lock['path'])!=Path('build/.p3-full-authorized-once.sknow.lock') or
            lock['bytes']!=0 or lock['sha256']!=hashlib.sha256(b'').hexdigest()):
        raise ValueError('old zero-byte lock reference changed')
    refs=refs+[lock]
    files=preserved_files(refs)
    ledger_ref=next(r for r in reports if r['path']==PREVIOUS_ATTEMPT.as_posix())
    gates={
        'all_old_report_bytes_blobs_unchanged':all(r['unchanged'] for r in reports),
        'previous_attempt_exact':ledger_ref['unchanged'] and ledger['attempts']==ledger['maximum']==1 and
            ledger['code_sha']==PREVIOUS_BUILD and ledger['automatic_retry_forbidden'] is True,
        'previous_host_timeout':previous['status']=='FAIL_HOST_TIMEOUT' and previous['attempts']==1 and
            previous['child_exit'] is None and previous['command_exit']==124 and
            300<=previous['elapsed_s']<301 and command['exit'] is None and
            command['head']==PREVIOUS_BUILD and 300<=command['elapsed_s']<301,
        'old_published_output_absent':not PREVIOUS_OUTPUT.exists() and
            delivery['published_output']['exists'] is False and previous['database'] is None,
        'previous_partial_inventory_exact':actual_paths==expected_paths and not PARTIAL.is_symlink() and
            not (PARTIAL/'.inputs').is_symlink(),
        'previous_partial_and_lock_unchanged':all(r['unchanged'] for r in files)}
    return {'gates':gates,'report_bindings':reports,'attempt_binding':ledger_ref,
            'attempt_ledger':ledger,'preserved_refs':refs,'preserved_files':files,
            'partial_is_not_input':True,'partial_never_sqlite_opened':True}


def audit_gate():
    if any(p.exists() or p.is_symlink() for p in (MANIFEST,GATE,ATTEMPT,RESULT,OUTPUT)):
        raise FileExistsError('retry1 gate/manifest/attempt/result/output must all be new; STOP')
    evidence={}
    try:return _audit_gate(evidence)
    except BaseException:  # noqa: BLE001 -- pre-reservation failures must retain evidence
        evidence.update(status='FAILED',exception=raw(traceback.format_exc().encode('utf-8')),
                        attempts=0,attempt_cap=RETRY1_MAX_ATTEMPTS,failure_action=FAILURE_ACTION)
        if not GATE.exists():save(GATE,evidence)
        return evidence


def _audit_gate(evidence):
    # Fail closed before hashing gigabytes or reserving anything if the caller
    # has not explicitly attested the otherwise unobservable outer tool policy.
    environment={k:os.environ.get(k) for k in HOST_ENV}
    if environment!=HOST_ENV:
        evidence.update(status='BLOCKED',gates={'host_deadline_contract':False},
                        timeout_policy={'environment':environment,'required':HOST_ENV},
                        attempts=0,attempt_cap=RETRY1_MAX_ATTEMPTS,failure_action=FAILURE_ACTION)
        save(GATE,evidence);return evidence
    # Capture cleanliness BEFORE any new process/raw/gate evidence is written.
    head=git('rev-parse','HEAD');status=git('status','--porcelain');main=git('rev-parse','main')
    evidence.update(fixed_code_sha=head,working_tree_before_outputs=status)
    processes=process_proof();evidence['process_proof']=processes
    policy=timeout_policy(processes);evidence['timeout_policy']=policy
    if not policy['ok'] or processes['observed']['old_builders']:
        evidence.update(status='BLOCKED',gates={'host_deadline_contract':policy['ok'],
                        'old_exact_builder_absent':not processes['observed']['old_builders']},
                        attempts=0,attempt_cap=RETRY1_MAX_ATTEMPTS,failure_action=FAILURE_ACTION)
        save(GATE,evidence);return evidence
    tests=timeout_tests_receipt(head);policy['timeout_none_tests_receipt']=tests
    # Local tracking refs only: this authorization adds no network operation.
    remote=dict(line.split()[::-1] for line in git('ls-remote','origin','refs/heads/dev','refs/heads/main').splitlines())
    worktrees=git('worktree','list','--porcelain')
    previous=previous_audit();evidence['previous']=previous
    data,_=load_manifest(CUT)
    original,_=load_manifest('build/real-full-7afe7fb/manifest.json')
    original_shas={s['source_id']:s['local_sha256'] for s in original['sources']}
    inputs=[]
    for s in data['sources']:
        p=Path(s['path']);observed=digest(p)
        inputs.append({'source_id':s['source_id'],'path':str(p),'bytes':p.stat().st_size,
                       'expected_sha256':s['local_sha256'],'observed_sha256':observed,
                       'unchanged':observed==s['local_sha256'],'original_group':s['source_id'] in original_shas})
    rows=[json.loads(t) for t in DECISIONS.read_text(encoding='utf-8').splitlines()]
    verified=replay(rows)
    scoped=[json.loads(t) for t in Path(data['sources'][-1]['path']).read_text(encoding='utf-8').splitlines()]
    identity=sum('key' in r for r in scoped)
    wiki_links=sum(r.get('relation')=='wiki_tag' for r in scoped)
    oldsha=digest(OLD);free=shutil.disk_usage(OUTPUT.parent).free
    input_bytes=sum(r['bytes'] for r in inputs)
    budget={'existing_old_bytes':OLD.stat().st_size,'new_candidate_allowance':OLD.stat().st_size*2,
            'private_frozen_inputs':input_bytes,'WAL_and_working_allowance':OLD.stat().st_size*2,
            'safety_reserve':50*1024**3,'free_bytes':free}
    required=budget['new_candidate_allowance']+budget['private_frozen_inputs']+budget['WAL_and_working_allowance']+budget['safety_reserve']
    acceptance=json.loads(Path('reports/P3/full-authorized-preflight-pilot55.json').read_text(encoding='utf-8'))
    regression=json.loads(Path('reports/P3/full-authorized-preflight-old151.json').read_text(encoding='utf-8'))
    pilot=Path('build/p3-review-cf807-final-pilot/knowledge.sqlite')
    pilotsha=digest(pilot)
    acquisition=json.loads(Path('reports/P3/alias-acquisition.json').read_text(encoding='utf-8'))
    groups={s['source_id']:s['local_sha256'] for s in data['sources'] if s['source_id'] in original_shas}
    changes=git('diff','--name-only',PREVIOUS_SUBMISSION,head).splitlines()
    ancestry=subprocess.run(['git','merge-base','--is-ancestor',PREVIOUS_SUBMISSION,head],check=False).returncode==0
    gates={'code_clean':not status,'main_unchanged':main==remote.get('refs/heads/main')==P3_BASE,
           'single_worktree':worktrees.count('worktree ')==1,
           'previous_submission_ancestor':ancestry,'authorized_delta_only':authorized_delta(changes),
           'reviewed_implementation_unchanged':not git('diff','--name-only',IMPLEMENTATION,head,'--','src','rust','tools/p3_compile_inputs.py'),
           'five_original_groups_exact':len(original_shas)==len(groups)==5 and groups==original_shas==ORIGINAL_SHAS,
           'scoped_records_frozen':all(r['unchanged'] for r in inputs) and len(inputs)==6 and inputs[-1]['observed_sha256']=='6fbdc0b9462bcfa1931dcdb5dd1694c8cca4b04a3440bd74eb3ee6a582647b16',
           'decisions_replay_safe':len(rows)==100 and not verified and digest(DECISIONS)==DECISION_SHA and all(r.get('reviewer_kind')=='execution_agent' and r.get('decision')=='candidate' for r in rows),
           'old_snapshot_actual_SHA':oldsha==OLD_SHA and OLD.stat().st_size==21516320768,
           'pilot_actual_SHA':pilotsha=='a36579bc2662213a97d8f0db8549071e31e843e65a05ab83f806210850e9ef1f' and pilot.stat().st_size==6008832,
           'pilot_real55_pass':acceptance['status']=='PASS' and acceptance['passed']==55 and acceptance['wrong_resolved']==0,
           'scoped_gold_immutable':not git('diff','--name-only',APPROVED,head,'--','reports/P3/review-cf807-real-gold.json'),
           'decisions_immutable':not git('diff','--name-only',APPROVED,head,'--',str(DECISIONS)),
           'P2_old151_pass':regression['summary']['overall']=='PASS' and regression['summary']['passed']==151,
           'native_real_positive':identity==30,'wiki_real_positive':wiki_links==28,
           'official_budget_unchanged':acquisition['requests_including_prior_docs']<=200 and acquisition['cumulative_collector_bytes']+acquisition['documentation_byte_reserve']<=268435456,
           'disk_budget':free>max(100*1024**3,required),'new_output_absent':not OUTPUT.exists(),
           'attempt_not_started':not ATTEMPT.exists(),'host_deadline_contract':policy['ok'],
           'timeout_none_tests_pass':tests['ok'],
           'old_exact_builder_absent':not processes['observed']['old_builders'],
           'old_partial_not_input':all(not Path(r['path']).resolve().is_relative_to(PARTIAL.resolve()) for r in inputs)}
    gates.update(previous['gates'])
    for name in ('pytest','ruff','diff','fmt','rust-test','clippy','release'):
        r=json.loads(Path('reports/P3/review-d01-check-'+name+'.json').read_text(encoding='utf-8'))
        gates['reviewed_check_'+name]=r['exit']==0 and r['head']==IMPLEMENTATION
    data.update(full_build_code_sha=head,approved_implementation_sha=IMPLEMENTATION,
                p3_coverage_policy='verified_entity_tag_real_positive=OPTIONAL_COVERAGE',
                decision_receipt={'path':str(DECISIONS),'sha256':digest(DECISIONS),'verified':len(verified)},
                authorization='root explicit NEW retry1 only; previous exhausted cap1 unchanged; no retry2/newGET/human/main/P4')
    save(MANIFEST,data)
    evidence.update(status='READY' if all(gates.values()) else 'BLOCKED',gates=gates,
        fixed_code_sha=head,implementation_sha=IMPLEMENTATION,P3_BASE=P3_BASE,
        previous_submission=PREVIOUS_SUBMISSION,previous_build=PREVIOUS_BUILD,
        authorized_changes=changes,working_tree_before_outputs=status,worktrees=worktrees,local_tracking_refs=remote,
        manifest={'path':str(MANIFEST),'sha256':digest(MANIFEST),'bytes':MANIFEST.stat().st_size},
        inputs=inputs,decisions={'path':str(DECISIONS),'sha256':digest(DECISIONS),'candidates':len(rows),'human_verified':0},
        coverage=optional_coverage(verified),disk_budget=dict(budget,required_free_bytes=required),
        pilot={'path':str(pilot),'sha256':pilotsha,'bytes':pilot.stat().st_size},
        old_snapshot={'path':str(OLD),'bytes':OLD.stat().st_size,'sha256':oldsha},
        output=str(OUTPUT),attempts=0,attempt_cap=RETRY1_MAX_ATTEMPTS,failure_action=FAILURE_ACTION)
    save(GATE,evidence)
    return evidence


def preservation_after(gate):
    files=preserved_files(gate['previous']['preserved_refs'])
    proof={'previous_partial_and_lock':files,'partial_never_sqlite_opened':True}
    try:
        oldsha=digest(OLD);oldbytes=OLD.stat().st_size
        proof['old_snapshot']={'path':str(OLD),'bytes':oldbytes,'sha256':oldsha,
                               'unchanged':oldsha==OLD_SHA and oldbytes==21516320768}
    except OSError as exc:
        proof['old_snapshot']={'path':str(OLD),'unchanged':False,'error':str(exc)}
    try:proof['old_report_bindings']=frozen_reports()
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        proof['old_report_bindings']=[];proof['old_report_error']=str(exc)
    proof['unchanged']=(proof['old_snapshot']['unchanged'] and not proof.get('old_report_error') and
                        all(r['unchanged'] for r in files+proof['old_report_bindings']))
    return proof


def execute_once(gate):
    if gate['status']!='READY':return 2
    if OUTPUT.exists() or RESULT.exists():raise FileExistsError('retry1 output/result already exists; STOP')
    # Persistent independent exclusive reservation immediately precedes the only build call.
    fd=os.open(ATTEMPT,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
        json.dump({'attempts':1,'maximum':RETRY1_MAX_ATTEMPTS,'previous_attempts':1,
                   'retry1_count':1,'total_attempts':2,'status':'STARTED','code_sha':gate['fixed_code_sha'],
                   'previous_submission':PREVIOUS_SUBMISSION,'previous_build':PREVIOUS_BUILD,
                   'previous_attempt_binding':gate['previous']['attempt_binding'],
                   'timeout_policy':gate['timeout_policy'],'manifest':gate['manifest'],'output':str(OUTPUT),
                   'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                   'automatic_retry_forbidden':True,'retry2_forbidden':True},f,indent=2)
        f.flush();os.fsync(f.fileno())
    begin=time.perf_counter()
    result={'attempts':1,'previous_attempts':1,'total_attempts':2,'automatic_retries':0,
            'code_sha':gate['fixed_code_sha'],'implementation_sha':IMPLEMENTATION,
            'manifest':gate['manifest'],'failure_action':FAILURE_ACTION}
    ok=False
    try:
        report=build(MANIFEST,OUTPUT)
        db=OUTPUT/'knowledge.sqlite'
        # Normal builder verifies integrity/FK/FTS/ledger/projections before atomic
        # publication; this is an additional read-only check of the NEW output.
        uri=db.resolve().as_uri()+'?mode=ro&immutable=1'
        with sqlite3.connect(uri,uri=True) as conn:
            conn.execute('PRAGMA query_only=ON')
            counts={'tag_resolutions':conn.execute('SELECT count(*) FROM tag_resolutions').fetchone()[0],
                    'verified_entity_tag':conn.execute("SELECT count(*) FROM links WHERE relation='entity_tag' AND verification_status='verified'").fetchone()[0],
                    'native_wiki_tag':conn.execute("SELECT count(*) FROM links WHERE relation='wiki_tag' AND verification_status='native'").fetchone()[0],
                    'capability':conn.execute("SELECT value FROM build_meta WHERE key='p3_resolver_version'").fetchone()[0]}
        ok=report['verification']['ok'] and counts=={'tag_resolutions':352,'verified_entity_tag':0,'native_wiki_tag':28,'capability':'1'}
        result.update(report=report,readonly_projection_counts=counts,
                      database={'path':str(db),'bytes':db.stat().st_size,'sha256':digest(db)},
                      coverage=gate['coverage'])
    except BaseException:  # noqa: BLE001 -- retain interrupt/exit evidence, never retry
        result['exception']=raw(traceback.format_exc().encode('utf-8'));ok=False
    # Always rehash the previous partial/lock AND old snapshot, even on build failure.
    try:
        result['preservation_after']=preservation_after(gate)
        ok=ok and result['preservation_after']['unchanged']
    except BaseException:  # noqa: BLE001 -- preservation failure also means STOP
        result['preservation_exception']=raw(traceback.format_exc().encode('utf-8'));ok=False
    result.update(status='PASS' if ok else 'FAIL',elapsed_s=time.perf_counter()-begin,
                  output_present=OUTPUT.exists())
    save(RESULT,result)
    return 0 if ok else 1


def main():
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--execute',action='store_true')
    mode.add_argument('--timeout-policy',action='store_true',help='inspect actual host/parent proof only; never build')
    args=p.parse_args()
    if args.timeout_policy:
        proof=timeout_policy(process_proof());print(json.dumps(proof),flush=True)
        return 0 if proof['ok'] else 2
    gate=audit_gate();print(json.dumps({'gate':gate['status'],'gates':gate.get('gates',{}),'coverage':gate.get('coverage')}),flush=True)
    code=execute_once(gate);print(json.dumps({'exit':code,'attempts':1 if ATTEMPT.exists() else 0,'output':str(OUTPUT)}),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
