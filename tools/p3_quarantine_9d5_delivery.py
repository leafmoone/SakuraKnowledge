"""Append-only delivery for one terminal quarantine propagation repair; no builds/GET."""
import base64
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from p3_evidence import save, verify

from sakura_knowledge.storage import digest

SOURCE='229c2ddcc43c0d3919d44a4ea823f6a999a48a57'
BASE='9d5f26ddeb5335c8d449eb72335bb2df603d5e28'
PREFIX='review-9d5-'
ROOT=Path('reports/P3')
ART=Path('dist/p3-quarantine-229c2dd')


def git(*args):return subprocess.check_output(['git',*args])


def receipt(name):return json.loads((ROOT/(PREFIX+name+'.json')).read_text(encoding='utf-8'))


def main(owner_receipt=None):
    checks={}
    for name in ('pytest','ruff','diff','fmt','rust-test','clippy','release'):
        r=receipt('check-'+name);assert r['exit']==0 and r['head']==SOURCE
        checks[name]={'path':str(ROOT/(PREFIX+'check-'+name+'.json')),'sha256':digest(ROOT/(PREFIX+'check-'+name+'.json')),'exit':0}
    equality=receipt('real-input-equality');assert equality['exit']==0
    equality_value=json.loads(equality['stdout']);assert equality_value['status']=='PASS'
    equal_files=equality_value['real_inputs_unchanged'] if 'real_inputs_unchanged' in equality_value else equality_value['files']
    assert all(r['identical'] for r in equal_files)
    owner=receipt(owner_receipt) if owner_receipt else None
    if owner is not None:
        assert owner['status']=='PASS' and owner['passed']==owner['attempted']==18 and owner['retries']==0
        assert all(r['passed'] and r['quarantine_owners']==r['expected_owners'] for r in owner['records'])
    real=receipt('release-acceptance');old=receipt('old151');perf=receipt('performance')
    quarantine=receipt('quarantine-release');external=receipt('artifact-external');abc=receipt('artifact-abc')
    assert real['passed']==55 and real['wrong_resolved']==0 and old['summary']['passed']==151
    assert perf['status']=='PASS' and perf['measured']==780 and perf['warmups']==26
    assert quarantine['passed']==8 and quarantine['status']==external['status']==abc['status']=='PASS'
    assert git('diff','--name-only',SOURCE,'--','src','rust').strip()==b''
    assert git('diff','--name-only',BASE,'--','src','rust','reports/P1','reports/P2').strip()==b''
    historic=git('ls-tree','-r','--name-only',BASE,'reports/P3').decode().splitlines()
    for path in historic:assert git('rev-parse',BASE+':'+path)==git('rev-parse','HEAD:'+path)
    artifacts=[]
    for path in (ART/'sakura_knowledge-0.2.0-py3-none-any.whl',ART/'source/rust/target/release/sknow-rs.exe',
                 ART/'source/rust/target/release/examples/bench_resolver.exe'):
        artifacts.append({'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size})
    prior=json.loads((ROOT/'review-cf807-artifact-manifest.json').read_text(encoding='utf-8'))
    for ref in prior['artifacts'][3:]:
        path=Path(ref['path']);assert digest(path)==ref['sha256'] and path.stat().st_size==ref['bytes']
        artifacts.append(dict(ref,unchanged_from_reviewed_9d5=True))
    # Sole real active alias terminates at a compatible cut: no new realpilot is
    # needed. Frozen55 and existing pilot are deliberately preserved, not replaced.
    modules=[]
    with zipfile.ZipFile(ART/'sakura_knowledge-0.2.0-py3-none-any.whl') as z:
        for name in z.namelist():
            if name.startswith('sakura_knowledge/') and name.endswith('.py'):
                blob=git('show',SOURCE+':src/'+name);data=z.read(name);export=(ART/'source/src'/name).read_bytes()
                assert data==export and data.replace(b'\r\n',b'\n')==blob.replace(b'\r\n',b'\n')
                modules.append({'module':name,'committed_sha256':hashlib.sha256(blob).hexdigest(),'committed_bytes':len(blob),
                                'wheel_export_sha256':hashlib.sha256(data).hexdigest(),'wheel_export_bytes':len(data),
                                'byte_exact_blob':data==blob,'exact_export':True,'EOL_normalized_blob':True})
    refs={};streams=0
    def walk(v):
        nonlocal streams
        if isinstance(v,dict):
            if {'path','bytes','sha256'}<=v.keys() and str(v['path']).startswith('reports/P3/raw/'):
                verify(v);refs[v['path']]=dict(v)
            elif {'raw_path','bytes','sha256'}<=v.keys():
                r={'path':v['raw_path'],'bytes':v['bytes'],'sha256':v['sha256']};verify(r);refs[r['path']]=r
            for s in ('stdout','stderr'):
                if s+'_base64' in v:
                    assert hashlib.sha256(base64.b64decode(v[s+'_base64'])).hexdigest()==v[s+'_sha256'];streams+=1
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    for path in sorted(ROOT.iterdir()):
        if path.suffix=='.json':walk(json.loads(path.read_text(encoding='utf-8')))
        elif path.suffix=='.jsonl':
            for line in path.read_text(encoding='utf-8').splitlines():walk(json.loads(line))
    gate=json.loads((ROOT/'review-cf807-full-candidate-gate.json').read_text(encoding='utf-8'))
    for source in gate['inputs']:
        assert digest(source['path'])==source['expected_sha256']
    assert digest(gate['old_snapshot']['path'])==gate['old_snapshot']['sha256']=='4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073'
    mainsha=git('rev-parse','main').decode().strip();assert mainsha=='894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
    save(ROOT/(PREFIX+'artifact-manifest.json'),{'source_commit':SOURCE,'artifacts':artifacts,'wheel_modules':modules,
        'origin':f'fresh git archive {SOURCE} release/examples/wheel/newvenv; no relabeled outputs; realpilot/data unchanged byhash',
        'UTF8_external_environment':external['environment']})
    save(ROOT/(PREFIX+'full-candidate-gate.json'),{'status':'BLOCKED','overall_P3':'NOT_READY','candidate_build':'NOT_RUN','attempts':0,
        'necessary_verified_entity_tag_real_positive':False,'verified_entity_tag':0,'candidate_count':100,'human_verified':0,
        'source_commit':SOURCE,'main':mainsha,'inputs_rehashed':gate['inputs'],'old_snapshot_rehashed':gate['old_snapshot'],
        'new_GETs':0,'new_human_review':0,'full_build_authorized':False,
        'blocker':'Need genuine cross-source ID/link evidence or actual scoped human decisions. Do not automatically launch/retry build.'})
    save(ROOT/(PREFIX+'delivery.json'),{'overall_P3':'BLOCKED/NOT_READY','code_review_state':'PENDING_REVIEW','review_base':BASE,
        'source_artifact_commit':SOURCE,'single_repair':('quarantine reference own typed tag_key aggregated/deduplicated, no nativealias target overwrite or foreign quarantine propagation' if owner else 'actual canonical terminal Wiki quarantine propagated to same typed target projections after cut comparison'),
        'closed_items':'typedendpoint/category,realgold,redirect not reopened; Rust/Pythonpublic/src all byteunchanged',
        'quarantine_fixture':{'cases':8,'passed':8,'fullJSON_expected_and_oracle':True,'normal_builder_atomic':True,
                              'paths':'A/B/C ordinary+explicit and verifiedheroA/heroC','synthetic_not_real_verified_positive':True},
        'owner_fixture':({'cases':18,'passed':18,'fullJSON_independent_expected_and_oracle':True,
                          'orders':['original','reversed'],'paths':'A/B/C ordinary+explicit and verifiedheroA/B/C',
                          'canonical_target':'A','invariant':'A/B and heroA/B contain A/Wiki9 quarantine only; C/heroC retain original C/Wiki19 plus terminal A/Wiki9',
                          'normal_builder_atomic':True,'synthetic_not_real_verified_positive':True} if owner else None),
        'checks':checks,'real55':{k:real[k] for k in ('passed','positive_denominator','nonresolved_denominator','wrong_resolved')},
        'old151':old['summary'],'external':{'P2pairs':8,'Rustresolver':55,'ABCpairs':10,'UTF8_verified':True},
        'performance':{'scope':'UNCHANGED_REALPILOT_ONLY','workloads':13,'measured':780,'fixed_warmups':26,'retries':0,
            'status':perf['status'],'max_reused_p95_s':max(x['p95_s'] for x in perf['summary'] if x['mode']=='reused_connection'),
            'max_cli_p95_s':max(x['p95_s'] for x in perf['summary'] if x['mode']=='independent_cli')},
        'artifacts':artifacts,'raw_unique_verified':len(refs),'embedded_streams_verified':streams,'raw_inventory':list(refs.values()),
        'inventory_boundary':'precollection-output/command,binding; finalclosedset independentlyverified',
        'prior_P3_files_unchanged':len(historic),'realpilot_input_protection':'original fiveinputs,old55gold,publishedpilot,old21.5GB actualSHA match',
        'recompiled_real_inputs_byte_identical':equal_files,'realpilot_rebuilt':False,
        'overall_blocker':{'verified_entity_tag':0,'candidate':100,'human':0,'fullcandidate_attempts':0},
        'limitations':['0GET/0human/0fullcandidate','Linux/Pi/Pool/dbstat/fullhumanfacts/RSS/fullrefreshNOT_RUN',
                       'raw licenseunknown localonly','No main/P4/Pythonproductionresolver'],
        'failures':('newbefore18FAIL real ownervscanonicaltarget bug; after26PASS includes prior8; historicalfailedreceiptsunchanged' if owner else 'initialbefore8FAIL containedwrongfixturelinkeID+globalprojection assertions; correctedbefore5FAIL3PASS preservesrealbug; no historicalreceipt rewritten')})
    print(json.dumps({'status':'BLOCKED','checks':7,'quarantine_fullJSON_cases':8,'owner_fullJSON_cases':18 if owner else 0,'realgold':55,'old151':151,
                      'raw_unique':len(refs),'embedded_streams':streams,'artifacts':artifacts[:3]}))


if __name__=='__main__':main()
