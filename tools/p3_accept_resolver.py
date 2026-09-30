"""Actual Rust resolver vs independent oracle plus frozen raw-source golden expectations."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from p3_evidence import save, store
from p3_resolver_oracle import result


def command(binary,db,case):
    argv=[str(Path(binary).resolve()),'resolve-tag',str(Path(db).resolve()),case['query']]
    for name in ('kind','namespace','category','limit'):
        if case.get(name) is not None:
            argv.extend(['--'+name,str(case[name])])
    if case.get('exact'):
        argv.append('--key')
    argv.extend(['--target-namespace','danbooru.tag'])
    return argv


def check(value,case):
    expected=case['expected']
    good=value['status']==expected['status'] and value['tag_key']==expected.get('tag_key')
    if expected.get('candidates') is not None:
        keys=[x.get('tag_key',x.get('entry_key')) for x in value['candidates']]
        good=good and keys==expected['candidates']
    if expected.get('matched_by') is not None:
        good=good and value['matched_by']==expected['matched_by']
    if expected.get('description'):
        good=good and bool(value['descriptions'])
    if expected.get('descriptions_empty'):
        good=good and value['descriptions']==[]
    if 'unresolved_reasons' in expected:
        good=good and value.get('unresolved_reasons')==expected['unresolved_reasons']
    for assertion in expected.get('evidence_assertions',[]):
        good=good and any(all(ref.get(k)==v for k,v in assertion.items()) for ref in value['evidence_chain'])
    return good


def main():
    parser=argparse.ArgumentParser()
    for flag in ('db','bin','gold','out'):
        parser.add_argument('--'+flag,type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    gold=json.loads(args.gold.read_text(encoding='utf-8'))
    records=[]
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    for case in gold['cases']:
        expected=result(args.db,case['query'],**{k:case[k] for k in ('category','kind','namespace','exact','limit') if k in case})
        argv=command(args.bin,args.db,case);start=time.perf_counter()
        proc=subprocess.run(argv,capture_output=True,timeout=15,check=False,env=env)
        row={'case_id':case['id'],'argv':argv,'exit':proc.returncode,'elapsed_s':time.perf_counter()-start,
             'stdout':store(proc.stdout),'stderr':store(proc.stderr),'oracle_json':store(json.dumps(expected,ensure_ascii=False,separators=(',',':')).encode()),
             'expected_behavior_passed':False,'full_json_passed':False,'error':None}
        if proc.returncode==0 and not proc.stderr:
            try:
                value=json.loads(proc.stdout.decode('utf-8',errors='strict'))
                row['expected_behavior_passed']=check(value,case)
                row['full_json_passed']=value==expected
                row['actual_status']=value['status']
                row['unexpected_resolved']=value['status']=='resolved' and (case['expected']['status']!='resolved' or value['tag_key']!=case['expected'].get('tag_key'))
            except (ValueError,KeyError,TypeError) as error:
                row['error']=type(error).__name__
        records.append(row)
    positives=[r for r,c in zip(records,gold['cases'],strict=True) if c['expected']['status']=='resolved']
    negatives=[r for r,c in zip(records,gold['cases'],strict=True) if c['expected']['status']!='resolved']
    passed=sum(r['full_json_passed'] and r['expected_behavior_passed'] for r in records)
    output={'status':'PASS' if passed==len(records) else 'FAIL','attempted':len(records),'passed':passed,'retries':0,
            'positive_denominator':len(positives),'positive_correct':sum(r['expected_behavior_passed'] for r in positives),
            'nonresolved_denominator':len(negatives),'nonresolved_correct':sum(r['expected_behavior_passed'] for r in negatives),
            'wrong_resolved':sum(r.get('unexpected_resolved',False) for r in records),'records':records,
            'limits':{'inner_s':5,'outer_s':15,'total_response_bytes':524288},
            'limitations':gold['limitations'],'gold_path':str(args.gold)}
    save(args.out,output)
    print(json.dumps({k:output[k] for k in ('status','attempted','passed','positive_denominator','positive_correct','nonresolved_denominator','nonresolved_correct','wrong_resolved')}))
    return 0 if output['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
