"""Audit the stopped sole attempt read-only; never execute/retry a builder."""
import base64
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from p3_evidence import save, store, verify
from p3_full_candidate import IMPLEMENTATION, OLD, OLD_SHA, P3_BASE

from sakura_knowledge.storage import digest

BASE='28cf51bda963ded8bed2def289fd316a4db6bfd0'
BUILD_SHA='0aa46a57b1dcb4ac9a04a3c3ba49b97234ea616d'
ART=Path('dist/p3-full-0aa46a5')
STAGING=Path('build/.sknow-z7dkmnsi')
OUT=Path('build/p3-full-authorized-once')
PREFIX='full-authorized-'


def git(*args):return subprocess.check_output(['git',*args]).decode().strip()


def ref(p):
    p=Path(p);return {'path':p.as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}


def receipt(n):return json.loads(Path('reports/P3/'+PREFIX+n+'.json').read_text(encoding='utf-8'))


def walk(value,refs,embedded):
    if isinstance(value,dict):
        if {'path','bytes','sha256'}<=value.keys() and '/raw/' in value['path']:refs[value['path']]=value
        for k,v in value.items():
            if k.endswith('_base64') and isinstance(v,str):
                data=base64.b64decode(v);label=k.removesuffix('_base64')
                assert hashlib.sha256(data).hexdigest()==value[label+'_sha256']
                if isinstance(value.get(label+'_bytes'),int):assert len(data)==value[label+'_bytes']
                embedded.append({'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
            walk(v,refs,embedded)
    elif isinstance(value,list):
        for v in value:walk(v,refs,embedded)


def main():
    gate=receipt('gate');attempt=receipt('attempt');process=receipt('build-command')
    assert gate['status']=='READY' and all(gate['gates'].values())
    assert attempt['attempts']==attempt['maximum']==1 and attempt['status']=='STARTED'
    assert process['status']=='FAIL' and process['exit'] is None and 300<=process['elapsed_s']<310
    assert not OUT.exists() and STAGING.exists()
    inspect=receipt('process-inspection-exact')
    assert inspect['exit']==0 and not inspect['stderr'] and json.loads(inspect['stdout'])==[]
    assert gate['fixed_code_sha']==attempt['code_sha']==process['head']==BUILD_SHA
    assert not git('diff','--name-only',IMPLEMENTATION,'--','src','rust','tools/p3_compile_inputs.py')
    assert git('rev-parse','main')==P3_BASE
    old=ref(OLD);assert old['sha256']==OLD_SHA and old['bytes']==21516320768
    inputs=[]
    for n,r in enumerate(gate['inputs']):
        frozen=ref(r['path']);private=ref(STAGING/'.inputs'/str(n))
        assert frozen['sha256']==private['sha256']==r['observed_sha256']==r['expected_sha256']
        assert frozen['bytes']==private['bytes']==r['bytes']
        inputs.append({'original':frozen,'builder_private_frozen':private})
    partial=[ref(p) for p in sorted(STAGING.rglob('*')) if p.is_file() and '.inputs' not in p.parts]
    lock=ref('build/.p3-full-authorized-once.sknow.lock')
    manifest=ref(gate['manifest']['path']);assert manifest['sha256']==gate['manifest']['sha256'] and manifest['bytes']==gate['manifest']['bytes']
    manifest_raw=store(Path(manifest['path']).read_bytes())
    artifacts=[ref(p) for p in (next(ART.glob('*.whl')),ART/'source/rust/target/release/sknow-rs.exe',ART/'source/rust/target/release/examples/bench_resolver.exe')]
    modules=[]
    with zipfile.ZipFile(next(ART.glob('*.whl'))) as z:
        for n in z.namelist():
            if not n.startswith('sakura_knowledge/') or not n.endswith('.py'):continue
            body=z.read(n);export=(ART/'source/src'/n).read_bytes();installed=(ART/'venv/Lib/site-packages'/n).read_bytes()
            blob=subprocess.check_output(['git','show',BUILD_SHA+':src/'+n])
            assert body==export==installed and body.replace(b'\r\n',b'\n')==blob.replace(b'\r\n',b'\n')
            modules.append({'module':n,'archive_wheel_installed_byte_exact':True,'export_sha256':hashlib.sha256(body).hexdigest(),'export_bytes':len(body),'git_blob_sha256':hashlib.sha256(blob).hexdigest(),'git_blob_bytes':len(blob),'git_vs_export_only_EOL_equivalence':True})
    checks={}
    for name in ('pytest','ruff','diff','fmt','rust-test','clippy','release'):
        r=receipt('check-'+name);assert r['head']==BUILD_SHA
        checks[name]={'argv':r['argv'],'exit':r['exit'],'elapsed_s':r['elapsed_s'],'receipt':ref('reports/P3/'+PREFIX+'check-'+name+'.json'),
                      'stdout':store(base64.b64decode(r['stdout_base64'])),'stderr':store(base64.b64decode(r['stderr_base64']))}
    old151=receipt('preflight-old151');gold=receipt('preflight-pilot55')
    assert old151['summary']['overall']=='PASS' and old151['summary']['passed']==151
    assert gold['status']=='PASS' and gold['passed']==55 and gold['wrong_resolved']==0
    oldnames=git('ls-tree','-r','--name-only',BASE,'--','reports/P3').splitlines()
    assert not git('diff','--name-only',BASE,'--',*oldnames)
    refs={};embedded=[];files=sorted(Path('reports/P3').glob(PREFIX+'*.json'))
    for p in files:walk(json.loads(p.read_text(encoding='utf-8')),refs,embedded)
    for v in refs.values():verify(v)
    realgold=json.loads(Path('reports/P3/review-cf807-real-gold.json').read_text(encoding='utf-8'))
    chinese=[c for c in realgold['cases'] if any('\u4e00'<=ch<='\u9fff' for ch in c['query'])]
    coverage={'scope':'approved PILOT and frozen inputs ONLY; no published FULL snapshot',
        'native':{'identities':30,'frozen_targets':30},'official_alias':{'active':1,'acquired_records':4},
        'wiki':{'compatible_links':28,'native_observations':30,'quarantines':2},
        'Chinese_gold':{'resolved':sum(c['expected']['status']=='resolved' for c in chinese),'queries':len(chinese)},
        'verified_entity_tag':{'verified':0,'candidate_decisions':100,'human':0,'policy':'OPTIONAL_COVERAGE','zero_is_legal':True}}
    blocked=['FULL integrity/FK/FTScoverage/integrity/sourceledger/inputhash/projection validation',
        'FULL readonlyruntime/realgold/wrongtag','FULL old151P2compatibility with predeclared deltas',
        'FULL reusedconnection+CLIperformance all7pathfamilies','FULL sourceexternalinstalledartifactruntime']
    result={'P3':'NOT_READY','code_review':'WAITING_REVIEW stopped execution evidence, not sourcebug claim',
        'P3_BASE':P3_BASE,'IMPLEMENTATION':IMPLEMENTATION,'FULL_BUILD_SHA':BUILD_SHA,'BASELINE':BASE,
        'SUBMISSION':'verify actual finalHEAD/REMOTE after ordinary evidence commits/push; no selfhash fiction',
        'attempts':1,'maximum':1,'automatic_retries':0,'gate':'READY all mandatory noncoverage gates passed',
        'build':'FAIL_HOST_TIMEOUT','command_exit':124,'child_exit':None,'elapsed_s':process['elapsed_s'],
        'cause':'Our launcher omitted record_check --timeout override: its default300s killed sole builder; bash timeout0 did not override inner Python process deadline. Execution error, not verifiedcoverage blocker or resolver/storage bug.',
        'published_output':{'path':OUT.as_posix(),'exists':False,'bytes':None,'sha256':None},
        'partial_staging':{'path':STAGING.as_posix(),'files':partial,'lock':lock,'unverified_not_snapshot':True,'preserved':True,'no_cleanup_or_patching':True},
        'builder_private_input_copies':inputs,'manifest':manifest,'manifest_raw':manifest_raw,
        'old_snapshot_after':dict(old,unchanged=True),'active_builder_processes':[],
        'active_process_proof':ref('reports/P3/'+PREFIX+'process-inspection-exact.json'),
        'coverage':coverage,'preflight':{'pilot_gold':{'passed':55,'wrong_resolved':0},'old_snapshot151':'151PASS135completeJSON16errorcontracts0retry0timeout'},
        'blocked_full_acceptance':{k:'BLOCKED / NOT_RUN; no validated publishedFULL output' for k in blocked},
        'checks':checks,'check_failures_preserved':['full-authorized-check-ruff.json PERF402 in our speculative untracked collector, never run or committed; file removed after buildSTOP; no firstFAIL relabeled','full-authorized-stop-audit-command.json initialauditasserted allchecksPASS but actualruffFAILED; actualold/input/partialhash completed beforeassert, correctedcollectionretains bothreceipts'],
        'final_delivery_ruff':{'receipt':ref('reports/P3/'+PREFIX+'check-delivery-ruff.json'),'exit':receipt('check-delivery-ruff')['exit']},
        'fresh_artifacts':artifacts,'wheel_modules':modules,
        'receipt_boundary':{'before_ownoutputs':len(files),'unique_raw_refs':len(refs),'embedded_streams':len(embedded),'raw_and_embedded_hashes_verified':True},
        'historical_P3_blobs_unchanged':len(oldnames),'P1P2_Pythonpublic_Rust_compiler_unchanged':True,
        'main_merge':'NO','P4':'NO','Pool':'NO','Sakuratool':'NO','newGETs':0,'human_review':0,
        'STOP':'oneattempt exhausted; no restart/resume/retry/alternateoutput; only explicit new root/user authorization could permit further execution, not requested automatically'}
    save('reports/P3/'+PREFIX+'artifact-manifest.json',{'source_sha':BUILD_SHA,'artifacts':artifacts,'wheel_modules':modules,'not_fullsnapshot_acceptance':True})
    save('reports/P3/'+PREFIX+'build.json',{'status':'FAIL_HOST_TIMEOUT','attempts':1,'command_exit':124,'child_exit':None,'elapsed_s':process['elapsed_s'],'original_command_receipt':ref('reports/P3/'+PREFIX+'build-command.json'),'database':None,'partial_files':partial,'manifest':manifest,'old_snapshot_after':old,'no_retry':True})
    save('reports/P3/'+PREFIX+'delivery.json',result)
    print(json.dumps({'P3':'NOT_READY','attempts':1,'build':'FAIL_HOST_TIMEOUT','old_snapshot_unchanged':True,'partial_files':partial,'new_artifacts':3,'checks':7,'blocked_full_acceptance':blocked}))


if __name__=='__main__':main()
