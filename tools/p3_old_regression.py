"""Run immutable old151 table/policy; preserve every process stream once byhash."""
import argparse
import base64
from pathlib import Path

import check_parity as old
from p3_evidence import save, store


def main():
    parser=argparse.ArgumentParser()
    for flag in ('db','bin','out'):
        parser.add_argument('--'+flag,type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    old.DB=args.db.resolve()
    rows=[]
    for case in old.CASES:
        row=old.run_case(case,args.bin.resolve())
        for side in ('python','rust'):
            for stream in ('stdout','stderr'):
                data=base64.b64decode(row[side].pop(stream+'_base64'))
                row[side][stream+'_ref']=store(data)
                row[side].pop(stream,None)
            row[side].pop('value',None)
        rows.append(row)
    summary=old.summarize(rows,len(old.CASES))
    save(args.out,{'summary':summary,'mode':'formal unchanged old151','retries':0,'warmup_rounds':0,
                  'outer_timeout_s':15,'inner_budget_s':5,'cases':rows,
                  'snapshot':str(args.db),'raw_policy':'each byte stream once, hashes reference local evidence',
                  'table_sha256':old.sha256(old.ROOT/'tools/parity_repair_expected.py'),
                  'rust_bin_sha256':old.sha256(args.bin)})
    print(summary)
    return 0 if summary['overall']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
