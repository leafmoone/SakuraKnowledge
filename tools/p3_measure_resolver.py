"""Fixed new-resolver dual-mode performance, all failures counted, zero retries."""
import argparse
import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path

from p3_accept_resolver import check, command
from p3_evidence import save, store
from p3_resolver_oracle import result


def main():
    parser=argparse.ArgumentParser()
    for flag in ('db','bin','reused-bin','gold','out'):
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--samples',type=int,default=30)
    parser.add_argument('--review-cf807',action='store_true')
    parser.add_argument('--snapshot-scope',choices=('PILOT','FULLSNAPSHOT'),default='PILOT')
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    if args.samples!=30:raise ValueError('protocol fixed at30 samples')
    cases=json.loads(args.gold.read_text(encoding='utf-8'))['cases']
    # Predeclared eight representatives by ID; not selected by final timings/results.
    ids=['G01','G21','G36','G37','G42','G43','G44','G45']
    if args.review_cf807:
        ids+=['G51','G52','G53','G54','G55']  # fixed review cases before any timing
    workloads=[next(c for c in cases if c['id']==i) for i in ids]
    oracle={c['id']:result(args.db,c['query'],**{k:c[k] for k in ('category','kind','namespace','exact','limit') if k in c}) for c in workloads}
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    records=[];processes=[]
    requests=[dict(c,round=r,warmup=r==-1) for r in range(-1,args.samples) for c in workloads]
    batch=''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in requests).encode()
    start=time.perf_counter()
    try:
        proc=subprocess.run([str(args.reused_bin.resolve()),str(args.db.resolve())],input=batch,
                            capture_output=True,timeout=600,env=env,check=False)
    except subprocess.TimeoutExpired as error:
        proc=subprocess.CompletedProcess([str(args.reused_bin),str(args.db)],-1,error.stdout or b'',error.stderr or b'')
    process={'mode':'reused_connection','argv':[str(args.reused_bin.resolve()),str(args.db.resolve())],
             'exit':proc.returncode,'elapsed_s':time.perf_counter()-start,
             'input':store(batch),'stdout':store(proc.stdout),'stderr':store(proc.stderr)}
    processes.append(process)
    decoded=[]
    try:
        decoded=[json.loads(line) for line in proc.stdout.decode('utf-8',errors='strict').splitlines()]
    except ValueError:
        pass
    complete=proc.returncode==0 and not proc.stderr and len(decoded)==len(requests)
    for index,c in enumerate(requests):
        row=decoded[index] if complete else {}
        success=complete and row.get('case_id')==c['id'] and row.get('value')==oracle[c['id']] and check(row.get('value',{}),c)
        elapsed=row.get('elapsed_s')
        success=success and isinstance(elapsed,(float,int)) and 0<=elapsed<=5
        records.append({'mode':'reused_connection','case_id':c['id'],'round':c['round'],'warmup':c['warmup'],
                        'success':bool(success),'elapsed_s':elapsed,'process_row':index,
                        'value_sha256':hashlib.sha256(json.dumps(row.get('value'),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()})
    for c in requests:
        argv=command(args.bin,args.db,c);start=time.perf_counter()
        try:
            proc=subprocess.run(argv,capture_output=True,timeout=15,env=env,check=False)
            elapsed=time.perf_counter()-start
            value=json.loads(proc.stdout) if proc.returncode==0 and not proc.stderr else None
            success=proc.returncode==0 and not proc.stderr and value==oracle[c['id']] and check(value,c)
            row={'exit':proc.returncode,'stdout':store(proc.stdout),'stderr':store(proc.stderr)}
        except subprocess.TimeoutExpired as error:
            elapsed=time.perf_counter()-start;success=False
            row={'exit':None,'timeout':True,'stdout':store(error.stdout or b''),'stderr':store(error.stderr or b'')}
        except (ValueError,TypeError,KeyError):
            success=False;row={'exit':proc.returncode,'stdout':store(proc.stdout),'stderr':store(proc.stderr),'invalid_json':True}
        records.append(dict(row,mode='independent_cli',case_id=c['id'],round=c['round'],warmup=c['warmup'],
                            success=bool(success),elapsed_s=elapsed,argv=argv))
    summary=[]
    for mode in ('reused_connection','independent_cli'):
        for c in workloads:
            rows=[r for r in records if r['mode']==mode and r['case_id']==c['id'] and not r['warmup']]
            timings=sorted(r['elapsed_s'] for r in rows if r['success'])
            def percentile(p,values=timings):
                return values[max(0,math.ceil(len(values)*p)-1)] if values else None
            summary.append({'mode':mode,'case_id':c['id'],'attempted':len(rows),'success':len(timings),
                            'failed_rounds':[r['round'] for r in rows if not r['success']],
                            'p50_s':percentile(.5),'p95_s':percentile(.95)})
    passed=all(r['success'] for r in records)
    from sakura_knowledge.storage import digest
    save(args.out,{'status':'PASS' if passed else 'FAIL','samples':30,'workloads':ids,'retries':0,
                   'snapshot_scope':args.snapshot_scope,'database_sha256':digest(args.db),
                   'gold_sha256':digest(args.gold),'binary_sha256':digest(args.bin),
                   'reused_binary_sha256':digest(args.reused_bin),
                   'measured':sum(not r['warmup'] for r in records),'warmups':sum(r['warmup'] for r in records),
                   'records':records,'reused_processes':processes,'summary':summary,
                   'protocol':{'inner_s':5,'cli_outer_s':15,'reused_batch_outer_s':600,
                               'percentile':'nearest rank on successful samples, attempts/failures separate',
                               'rss':'NOT_RUN for P3 resolver-specific measurement; no peak-memory claim',
                               'raw':'content-addressed files retained once locally, receipt hashes reference them'}})
    print(json.dumps({'status':'PASS' if passed else 'FAIL','measured':len(workloads)*30*2,'warmups':len(workloads)*2,'summary':summary}))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
