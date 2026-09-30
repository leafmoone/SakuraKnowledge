"""Authorized OPTIONAL_COVERAGE gate and one-shot normal full builder, never retry."""
import argparse
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
OLD=Path('build/snapshot-full-20bf5b3/knowledge.sqlite')
OLD_SHA='4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073'
CUT=Path('build/p3-owner-8a5b3d2-inputs/candidate-manifest.json')
MANIFEST=Path('build/p3-full-authorized-manifest.json')
OUTPUT=Path('build/p3-full-authorized-once')
GATE=Path('reports/P3/full-authorized-gate.json')
ATTEMPT=Path('reports/P3/full-authorized-attempt.json')
RESULT=Path('reports/P3/full-authorized-build.json')
DECISIONS=Path('reports/P3/review-d01-decisions.jsonl')
DECISION_SHA='4fdd2cbcf56c8e97398898dd27482ec67abd0c58c29133d947d44639523a63d6'
ORIGINAL_SHAS={
    'bangumi-complete-6a75aefb769a':'6a75aefb769a62f0eaa3b58ed76fb172a5dc1922a9e5be40bd7de2ff8343dcc4',
    'moegirl-complete-5072f7cf3e3e':'5072f7cf3e3ee4e558fb7421aadf9c9b600b8303b8f9c61cf3da9871018ac99d',
    'mapping-complete-c8263a535096':'c8263a5350964534170d833f560fb50758e3a4215e86b8f5c72cd51b72266f1f',
    'danbooru-complete-a26a3829dd42':'a26a3829dd42155848392c0636daebd6ca01acf540d3509fec2ac3219f8596c5',
    'tag_wiki-complete-a2eb055c578d':'a2eb055c578d37e82b71df787cd11b7616e77768eb319cf0839831cfdbb28fef'}
ALLOWED_CODE_CHANGES={
    'tools/p3_full_candidate.py','tools/p3_freeze_gate.py','tests/test_p3_full_candidate.py',
    'docs/P3_PLAN.md','docs/STAGE_STATUS.md','docs/p3-full-coverage-contract.md'}


def authorized_delta(names):
    return all(n in ALLOWED_CODE_CHANGES or n.startswith('reports/P3/full-authorized-') for n in names)


def git(*args):return subprocess.check_output(['git',*args]).decode().strip()


def optional_coverage(verified):
    return {'policy':'OPTIONAL_COVERAGE','verified_entity_tag_real_positive_required':False,
            'verified_entity_tag':len(verified),'zero_is_legal':True,
            'identity_safety':'candidate/name/score never promoted; tag_decisions/resolver unchanged'}


def audit_gate():
    if any(p.exists() for p in (MANIFEST,GATE,ATTEMPT,RESULT,OUTPUT)):
        raise FileExistsError('gate/manifest/attempt/result/output must all be new; do not retry')
    head=git('rev-parse','HEAD');status=git('status','--porcelain');main=git('rev-parse','main')
    remote=dict(line.split()[::-1] for line in git('ls-remote','origin','refs/heads/dev','refs/heads/main').splitlines())
    worktrees=git('worktree','list','--porcelain')
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
    # At least100GiB reserve AND explicit old/new/private frozen input/WAL/safety plan.
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
    # Audited frozen normalized sources are the exact five original groups, plus
    # existing reviewed scoped native/alias/Wiki projection records; no remapping.
    groups={s['source_id']:s['local_sha256'] for s in data['sources'] if s['source_id'] in original_shas}
    changes=git('diff','--name-only',APPROVED,head).splitlines()
    ancestry=subprocess.run(['git','merge-base','--is-ancestor',APPROVED,head],check=False).returncode==0
    gates={'code_clean':not status,'main_unchanged':main==remote.get('refs/heads/main')==P3_BASE,
           'single_worktree':worktrees.count('worktree ')==1,
           'approved_baseline_ancestor':ancestry,'authorized_delta_only':authorized_delta(changes),
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
           'attempt_not_started':not ATTEMPT.exists()}
    for name in ('pytest','ruff','diff','fmt','rust-test','clippy','release'):
        r=json.loads(Path('reports/P3/review-d01-check-'+name+'.json').read_text(encoding='utf-8'))
        gates['reviewed_check_'+name]=r['exit']==0 and r['head']==IMPLEMENTATION
    data.update(full_build_code_sha=head,approved_implementation_sha=IMPLEMENTATION,
                p3_coverage_policy='verified_entity_tag_real_positive=OPTIONAL_COVERAGE',
                decision_receipt={'path':str(DECISIONS),'sha256':digest(DECISIONS),'verified':len(verified)},
                authorization='root explicit P3 closure only; one attempt; no newGET/human/main/P4')
    save(MANIFEST,data)
    outcome={'status':'READY' if all(gates.values()) else 'BLOCKED','gates':gates,
        'fixed_code_sha':head,'implementation_sha':IMPLEMENTATION,'P3_BASE':P3_BASE,
        'preflight_baseline':APPROVED,'authorized_changes':changes,'working_tree_before_outputs':status,'worktrees':worktrees,'remote_refs':remote,
        'manifest':{'path':str(MANIFEST),'sha256':digest(MANIFEST),'bytes':MANIFEST.stat().st_size},
        'inputs':inputs,'decisions':{'path':str(DECISIONS),'sha256':digest(DECISIONS),'candidates':len(rows),'human_verified':0},
        'coverage':optional_coverage(verified),'disk_budget':dict(budget,required_free_bytes=required),
        'pilot':{'path':str(pilot),'sha256':pilotsha,'bytes':pilot.stat().st_size},
        'old_snapshot':{'path':str(OLD),'bytes':OLD.stat().st_size,'sha256':oldsha},
        'output':str(OUTPUT),'attempts':0,'attempt_cap':1,'failure_action':'STOP, no automatic retry'}
    save(GATE,outcome)
    return outcome


def execute_once(gate):
    if gate['status']!='READY':return 2
    # Persistent exclusive reservation immediately precedes the only build call.
    fd=os.open(ATTEMPT,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
        json.dump({'attempts':1,'maximum':1,'status':'STARTED','code_sha':gate['fixed_code_sha'],
                   'manifest':gate['manifest'],'output':str(OUTPUT),'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                   'automatic_retry_forbidden':True},f,indent=2)
        f.flush();os.fsync(f.fileno())
    begin=time.perf_counter()
    try:
        report=build(MANIFEST,OUTPUT)
        db=OUTPUT/'knowledge.sqlite'
        # The normal builder already verified integrity/FK/FTS/ledger/projections
        # before atomic publication. This additional read-only check is explicit.
        uri=db.resolve().as_uri()+'?mode=ro&immutable=1'
        with sqlite3.connect(uri,uri=True) as conn:
            conn.execute('PRAGMA query_only=ON')
            counts={'tag_resolutions':conn.execute('SELECT count(*) FROM tag_resolutions').fetchone()[0],
                    'verified_entity_tag':conn.execute("SELECT count(*) FROM links WHERE relation='entity_tag' AND verification_status='verified'").fetchone()[0],
                    'native_wiki_tag':conn.execute("SELECT count(*) FROM links WHERE relation='wiki_tag' AND verification_status='native'").fetchone()[0],
                    'capability':conn.execute("SELECT value FROM build_meta WHERE key='p3_resolver_version'").fetchone()[0]}
        oldafter=digest(OLD)
        ok=report['verification']['ok'] and counts=={'tag_resolutions':352,'verified_entity_tag':0,'native_wiki_tag':28,'capability':'1'} and oldafter==OLD_SHA
        save(RESULT,{'status':'PASS' if ok else 'FAIL','attempts':1,'automatic_retries':0,'code_sha':gate['fixed_code_sha'],
            'implementation_sha':IMPLEMENTATION,'report':report,'readonly_projection_counts':counts,
            'database':{'path':str(db),'bytes':db.stat().st_size,'sha256':digest(db)},
            'old_snapshot_after':{'sha256':oldafter,'unchanged':oldafter==OLD_SHA},
            'manifest':gate['manifest'],'elapsed_s':time.perf_counter()-begin,'coverage':gate['coverage']})
        return 0 if ok else 1
    except BaseException:  # noqa: BLE001 -- retain KeyboardInterrupt/SystemExit attempt evidence, never retry
        raw=traceback.format_exc().encode('utf-8')
        save(RESULT,{'status':'FAIL','attempts':1,'automatic_retries':0,'code_sha':gate['fixed_code_sha'],
            'exception':store(raw),'elapsed_s':time.perf_counter()-begin,'output_present':OUTPUT.exists(),
            'failure_action':'STOP. Reservation and frozenmanifest/logs retained. Normalbuilder staging cleanup semantics unchanged; no fake retainedDB claim.'})
        return 1


def main():
    p=argparse.ArgumentParser();p.add_argument('--execute',required=True,action='store_true');p.parse_args()
    gate=audit_gate();print(json.dumps({'gate':gate['status'],'gates':gate['gates'],'coverage':gate['coverage']}),flush=True)
    code=execute_once(gate);print(json.dumps({'exit':code,'attempts':1 if ATTEMPT.exists() else 0,'output':str(OUTPUT)}),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
