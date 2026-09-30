"""Append-only review repair delivery, never acquires data or launches full builds."""
import base64
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from p3_evidence import save, verify

from sakura_knowledge.storage import digest
from sakura_knowledge.tag_decisions import replay

SOURCE='7393d601a6d95432f41da243395ed5d3e0a2fda1'
PREFIX='review-cf807-'
ROOT=Path('reports/P3')
ART=Path('dist/p3-review-7393d60')


def git(*args):return subprocess.check_output(['git',*args])


def receipt(name):return json.loads((ROOT/(PREFIX+name+'.json')).read_text(encoding='utf-8'))


def main():
    checks={}
    for name in ('pytest','ruff','diff','fmt','rust-test','clippy','release'):
        r=receipt('check-'+name)
        assert r['exit']==0 and r['head']==SOURCE
        checks[name]={'path':str(ROOT/(PREFIX+'check-'+name+'.json')),'exit':0,'sha256':digest(ROOT/(PREFIX+'check-'+name+'.json'))}
    real=receipt('release-acceptance');old=receipt('old151');perf=receipt('performance')
    external=receipt('artifact-external');abc=receipt('artifact-abc')
    assert real['passed']==55 and real['wrong_resolved']==0
    assert old['summary']['passed']==151 and perf['status']=='PASS' and perf['measured']==780
    assert external['status']==abc['status']=='PASS'
    assert git('diff','--name-only',SOURCE,'--','src','rust').strip()==b''
    wheel=ART/'sakura_knowledge-0.2.0-py3-none-any.whl'
    modules=[]
    with zipfile.ZipFile(wheel) as z:
        for name in z.namelist():
            if name.startswith('sakura_knowledge/') and name.endswith('.py'):
                blob=git('show',SOURCE+':src/'+name)
                data=z.read(name);export=(ART/'source/src'/name).read_bytes()
                assert data==export and data.replace(b'\r\n',b'\n')==blob.replace(b'\r\n',b'\n')
                modules.append({'module':name,'committed_blob_sha256':hashlib.sha256(blob).hexdigest(),'committed_bytes':len(blob),
                                'wheel_export_sha256':hashlib.sha256(data).hexdigest(),'wheel_export_bytes':len(data),
                                'byte_exact_git_blob':data==blob,'exact_export_match':True,'eol_normalized_match':True})
    files=[wheel,ART/'source/rust/target/release/sknow-rs.exe',ART/'source/rust/target/release/examples/bench_resolver.exe',
           Path('build/p3-review-cf807-final-pilot/knowledge.sqlite'),Path('build/p3-review-cf807-final-inputs/pilot-manifest.json'),
           Path('build/p3-review-cf807-final-inputs/candidate-manifest.json'),Path('build/p3-review-cf807-final-inputs/native.jsonl')]
    artifacts=[{'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p)} for p in files]
    references={};embedded=0
    def walk(v):
        nonlocal embedded
        if isinstance(v,dict):
            if {'path','bytes','sha256'}<=v.keys() and str(v['path']).startswith('reports/P3/raw/'):
                verify(v);references[v['path']]=dict(v)
            elif {'raw_path','bytes','sha256'}<=v.keys():
                ref={'path':v['raw_path'],'bytes':v['bytes'],'sha256':v['sha256']};verify(ref);references[ref['path']]=ref
            for s in ('stdout','stderr'):
                if s+'_base64' in v:
                    assert hashlib.sha256(base64.b64decode(v[s+'_base64'])).hexdigest()==v[s+'_sha256'];embedded+=1
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    for path in sorted(ROOT.iterdir()):
        if path.suffix=='.json':walk(json.loads(path.read_text(encoding='utf-8')))
        elif path.suffix=='.jsonl':
            for line in path.read_text(encoding='utf-8').splitlines():walk(json.loads(line))
    # This remains a no-launch gate. New inputs/old snapshot are actually hashed,
    # not substituted with historical claims; historical52requests are unchanged.
    manifest=Path('build/p3-review-cf807-final-inputs/candidate-manifest.json')
    sources=json.loads(manifest.read_text(encoding='utf-8'))['sources'];inputs=[]
    for source in sources:
        p=Path(source['path']);p=p if p.is_absolute() else manifest.parent/p
        observed=digest(p);assert observed==source['local_sha256']
        inputs.append({'source_id':source['source_id'],'path':str(p),'bytes':p.stat().st_size,'expected_sha256':source['local_sha256'],'observed_sha256':observed})
    olddb=Path('build/snapshot-full-20bf5b3/knowledge.sqlite');oldsha=digest(olddb)
    assert oldsha=='4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073'
    decisions=[json.loads(x) for x in (ROOT/(PREFIX+'final-decisions.jsonl')).read_text(encoding='utf-8').splitlines()]
    verified=replay(decisions);assert len(decisions)==100 and not verified
    mainsha=git('rev-parse','main').decode().strip();assert mainsha=='894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
    acquisition=json.loads((ROOT/'alias-acquisition.json').read_text(encoding='utf-8'))
    free=shutil.disk_usage(olddb.parent).free
    gate={'status':'BLOCKED','candidate_build':'NOT_RUN','attempts':0,'overall_P3':'NOT_READY',
          'source_artifact_commit':SOURCE,'observed_HEAD':git('rev-parse','HEAD').decode().strip(),'main_sha':mainsha,
          'gates':{'fixed_production_code_matches_clean_committed_source':True,'main_unchanged':True,'frozen_inputs_all_sha':True,
                   'old_snapshot_unchanged':True,'disk_100GiB_budget':free>100*1024**3,
                   'official_budget':acquisition['requests_including_prior_docs']<=200 and acquisition['cumulative_collector_bytes']+acquisition['documentation_byte_reserve']<=268435456,
                   'realpilot_acceptance':True,'native_real_positive':True,'wiki_real_positive':True,
                   'necessary_verified_entity_tag_real_positive':False},
          'working_tree':git('status','--porcelain').decode(),'source_clean_semantics':'src/rust exactly source7393; receipt/doc audit changes listed separately, not falsely called whole-tree clean',
          'full_build_authorization':False,'blocker':'0verified entity_tag. Need genuine explicit cross-sourceID/link or actual scoped human decisions; no agent confidence/name promotion.',
          'decision_count':100,'decisions_verified':0,'human_verified':0,'inputs':inputs,'manifest':artifacts[5],
          'old_snapshot':{'path':str(olddb),'bytes':olddb.stat().st_size,'sha256':oldsha},'free_bytes':free}
    save(ROOT/(PREFIX+'full-candidate-gate.json'),gate)
    save(ROOT/(PREFIX+'artifact-manifest.json'),{'source_commit':SOURCE,'artifacts':artifacts,'wheel_source_modules':modules,
         'build':'new git archive fixed7393 SHA, fresh wheel/release/examples/newvenv, external-I-Xutf8',
         'EOL_boundary':'12Python exports CRLF vs GitLF; exactexport hash and blobhash separate, onlyEOLnormalized equality, historical strictFAILretained',
         'external_UTF8_environment':external['environment']})
    save(ROOT/(PREFIX+'delivery.json'),{'status':'BLOCKED','overall_P3':'NOT_READY','code_review_state':'PENDING_REVIEW',
         'review_baseline':'cf807c1a5179ce4b451b9a85870b6684d2dccaf3','source_artifact_commit':SOURCE,
         'repairs':['knownendpoint native/official only beforecategory; no Wiki substitution','allaliasstep scope including intermediates',
                    'actualWiki edge+bothcompatiblecuts+description IDs or quarantineproof','canonical_unknown explicitreason',
                    'new55raw/input gold includes realcandidate/4characterambiguous/unknown/quarantineemptydocs',
                    'no redirects countedoneHTTP hop; mockedredirect/401403429/limit/rate; no liveGET'],
         'checks':checks,'real_gold':{k:real[k] for k in ('status','attempted','passed','positive_denominator','positive_correct','nonresolved_denominator','nonresolved_correct','wrong_resolved')},
         'old151':old['summary'],'performance':{'scope':'PILOT_ONLY','status':perf['status'],'workloads':13,'measured':780,'warmups':26,'retries':0,
             'max_reused_p95_s':max(x['p95_s'] for x in perf['summary'] if x['mode']=='reused_connection'),
             'max_cli_p95_s':max(x['p95_s'] for x in perf['summary'] if x['mode']=='independent_cli')},
         'source_external':{'P2pairs':8,'Rustresolver_fullJSON_expected':55,'ABCpairs':10,'UTF8verified':True},
         'full_candidate':{'status':'BLOCKED/NOT_RUN','attempts':0,'verified_entity_tag':0,'candidate_decisions':100,'human_verified':0},
         'official_acquisition':'Historical52requests unchanged; zero reviewrepair GETs; mock only; no claim historicalredirect/overbudget actuallyoccurred',
         'new_pilot_snapshot':json.loads(receipt('final-pilot-build-command')['stdout'])['snapshot'],
         'artifacts':artifacts,'unique_raw_files_verified':len(references),'embedded_streams_verified':embedded,'raw_inventory':list(references.values()),
         'inventory_boundary':'Counts computed before this collectioncommand/output and newbinding; finalpostcommit audit counts entireclosedset independently',
         'old_snapshot':gate['old_snapshot'],
         'limitations':['P3_NOT_READY realverifiedcrosssourcepositiveabsent','Fullcandidate/RSS/perfNOT_RUN',
                        'Linux/Pi/Pool/dbstat/fullhumanfactsNOT_RUN','rawsource licenseunknown local-only','No main/P4/Pythonproductionresolver'],
         'historical_preservation':'Old50gold/49FAIL,cf807delivery/binding/P1P2/151 unchanged; newrepairreceipts separatepaths; allfailedsetup/fixture receipts retained'})
    print(json.dumps({'status':'BLOCKED','realgold':55,'checks':7,'unique_raw_verified':len(references),'embedded_streams':embedded,'modules':len(modules),'artifacts':artifacts}))


if __name__=='__main__':main()
