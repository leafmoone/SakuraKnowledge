"""Fixed new-resolver dual-mode performance, diagnostic warmups, zero retries."""
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


def evaluate(records, workloadids, samples=30):
    """Evaluate the fixed sample grid without running queries or dropping evidence."""
    modes = ('reused_connection', 'independent_cli')
    errors = []
    if type(samples) is not int or samples != 30:
        errors.append('protocol fixed at 30 samples')
    if not isinstance(workloadids, (list, tuple)) or not workloadids:
        errors.append('workload IDs must be a nonempty sequence')
        ids = []
    elif any(not isinstance(case_id, str) or not case_id for case_id in workloadids):
        errors.append('workload IDs must be nonempty strings')
        ids = []
    else:
        ids = list(dict.fromkeys(workloadids))
        if len(ids) != len(workloadids):
            errors.append('duplicate workload IDs')
    grouped = {(mode, case_id, round_): []
               for mode in modes for case_id in ids for round_ in range(-1, 30)}
    if not isinstance(records, (list, tuple)):
        errors.append('records must be a sequence')
        rows = []
    else:
        rows = records
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f'record {index}: must be an object')
            continue
        mode, case_id, round_ = row.get('mode'), row.get('case_id'), row.get('round')
        if (not isinstance(mode, str) or mode not in modes
                or not isinstance(case_id, str) or case_id not in ids
                or type(round_) is not int or round_ not in range(-1, 30)):
            errors.append(f'record {index}: unexpected mode, case ID, or round')
            continue
        grouped[(mode, case_id, round_)].append(row)
        if type(row.get('warmup')) is not bool or row['warmup'] != (round_ == -1):
            errors.append(f'record {index}: warmup must match round -1')
        if type(row.get('success')) is not bool:
            errors.append(f'record {index}: success must be a boolean')
        if 'elapsed_s' not in row:
            errors.append(f'record {index}: missing elapsed_s')
        elif row.get('success') is True:
            elapsed = row['elapsed_s']
            if (type(elapsed) not in (int, float) or not math.isfinite(elapsed)
                    or elapsed < 0):
                errors.append(f'record {index}: successful sample requires a finite timing')
        # Failed attempts may retain absent/invalid runtime timings as diagnostic evidence.
    for (mode, case_id, round_), entries in grouped.items():
        if len(entries) != 1:
            errors.append(f'{mode}/{case_id}/round {round_}: expected once, got {len(entries)}')

    summary = []
    warmup_summary = []
    formal_rows = []
    warmup_rows = []
    for mode in modes:
        for case_id in ids:
            formal = [row for round_ in range(30) for row in grouped[(mode, case_id, round_)]]
            warmup = grouped[(mode, case_id, -1)]
            formal_rows.extend(formal)
            warmup_rows.extend(warmup)
            timings = sorted(row['elapsed_s'] for row in formal
                             if row.get('success') is True
                             and type(row.get('elapsed_s')) in (int, float)
                             and math.isfinite(row['elapsed_s']) and row['elapsed_s'] >= 0)

            def counts(entries):
                success = sum(row.get('success') is True for row in entries)
                return {'attempted': len(entries), 'success': success,
                        'failed': len(entries) - success}

            def percentile(p, values=timings):
                return values[max(0, math.ceil(len(values) * p) - 1)] if values else None

            summary.append({'mode': mode, 'case_id': case_id, **counts(formal),
                            'failed_rounds': [row['round'] for row in formal
                                              if row.get('success') is not True],
                            'p50_s': percentile(.5), 'p95_s': percentile(.95)})
            warmup_summary.append({'mode': mode, 'case_id': case_id, **counts(warmup),
                                   'failed_rounds': [row['round'] for row in warmup
                                                     if row.get('success') is not True]})
    formal_success = sum(row.get('success') is True for row in formal_rows)
    warmup_success = sum(row.get('success') is True for row in warmup_rows)
    passed = not errors and formal_success == len(ids) * 30 * len(modes)
    return {'status': 'PASS' if passed else 'FAIL', 'samples': 30, 'workloads': list(ids),
            'measured': len(formal_rows), 'warmups': len(warmup_rows), 'records': records,
            'formal_counts': {'attempted': len(formal_rows), 'success': formal_success,
                              'failed': len(formal_rows) - formal_success},
            'warmup_counts': {'attempted': len(warmup_rows), 'success': warmup_success,
                              'failed': len(warmup_rows) - warmup_success},
            'summary': summary, 'warmup_summary': warmup_summary, 'structure_errors': errors}


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
    evaluation=evaluate(records,ids,args.samples)
    passed=evaluation['status']=='PASS'
    from sakura_knowledge.storage import digest
    save(args.out,{**evaluation,'retries':0,
                   'snapshot_scope':args.snapshot_scope,'database_sha256':digest(args.db),
                   'gold_sha256':digest(args.gold),'binary_sha256':digest(args.bin),
                   'reused_binary_sha256':digest(args.reused_bin),
                   'reused_processes':processes,
                   'protocol':{'inner_s':5,'cli_outer_s':15,'reused_batch_outer_s':600,
                               'percentile':'nearest rank on successful formal samples, attempts/failures separate',
                               'acceptance':'complete fixed formal grid must pass; complete warmups are diagnostic only',
                               'rss':'NOT_RUN for P3 resolver-specific measurement; no peak-memory claim',
                               'raw':'content-addressed files retained once locally, receipt hashes reference them'}})
    print(json.dumps({k:evaluation[k] for k in ('status','measured','warmups','formal_counts',
                                              'warmup_counts','summary','warmup_summary','structure_errors')}))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
