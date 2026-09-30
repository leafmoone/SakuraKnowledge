"""Freeze eighteen owner-vs-terminal full-JSON raw/compiler/builder counterexamples."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from p3_evidence import save, store
from p3_resolver_oracle import result

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_p3_quarantine_owner_d01 import PATHS, owner_expected, owner_fixture


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bin',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    binary=args.bin.resolve();output=args.out.resolve();root=Path.cwd();rawroot=root/'reports/P3/raw'
    if output.exists():raise FileExistsError(output)
    records=[];fixtures=[]
    for reverse in (False,True):
        with tempfile.TemporaryDirectory(prefix='sknow-owner-d01-') as directory,pytest.MonkeyPatch.context() as patch:
            db,snapshot,chains,links,projections,eids=owner_fixture(Path(directory),patch,reverse)
            files=[{'fixture_path':p.relative_to(directory).as_posix(),'raw':store(p.read_bytes(),rawroot)}
                   for p in sorted(Path(directory).rglob('*')) if p.is_file() and p.suffix in ('.raw','.json','.jsonl')]
            fixtures.append({'reverse':reverse,'snapshot':snapshot,'raw_files':files,'compiled_projections':projections,
                             'normal_builder_atomic_verified':True})
            for name,exact in PATHS:
                want,kind,namespace=owner_expected(snapshot,name,exact,chains,links,eids)
                argv=[str(binary),'resolve-tag',str(db),name]
                if exact:argv+=['--key','--kind',kind,'--namespace',namespace]
                process=subprocess.run(argv,capture_output=True,timeout=15,check=False,
                                       env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'))
                actual=json.loads(process.stdout) if process.returncode==0 and not process.stderr else None
                oracle=result(db,name,kind=kind if exact else None,namespace=namespace if exact else None,exact=exact)
                refs=actual.get('evidence_chain',[]) if actual else []
                expected_owners=['C','A'] if name in ('C','heroC') else ['A']
                owners=[ref['tag_key']['value'] for ref in refs if ref['role']=='wiki_association_quarantined']
                good=actual==want==oracle and owners==expected_owners
                records.append({'name':name,'exact':exact,'reverse':reverse,'argv':argv,'exit':process.returncode,
                    'stdout':store(process.stdout,rawroot),'stderr':store(process.stderr,rawroot),
                    'expected':store(json.dumps(want,ensure_ascii=False,separators=(',',':')).encode('utf-8'),rawroot),
                    'oracle':store(json.dumps(oracle,ensure_ascii=False,separators=(',',':')).encode('utf-8'),rawroot),
                    'independent_fullJSON':actual==want,'oracle_fullJSON':actual==oracle,'quarantine_owners':owners,
                    'expected_owners':expected_owners,'passed':good,'retries':0})
    def portable(value):
        if isinstance(value,dict):
            if {'path','bytes','sha256'}<=value.keys():value['path']=Path(value['path']).relative_to(root).as_posix()
            for v in value.values():portable(v)
        elif isinstance(value,list):
            for v in value:portable(v)
    portable(records);portable(fixtures)
    passed=sum(r['passed'] for r in records)
    save(output,{'status':'PASS' if passed==18 else 'FAIL','attempted':18,'passed':passed,'retries':0,
        'fixtures':fixtures,'records':records,'expectation_origin':'raw/input owner keypairs A/Wiki9 C/Wiki19 with unequal dates; hardcoded expected all steps/scopes/typed identities, never resolver-derived',
        'canonical_target':'A','owner_invariant':'No C/Wiki19 propagated to A or B; C original observation retained plus A actual terminal ref; not last-writer and both raw input orders',
        'real_verified_positive':False,'upstream_GETs':0,'fullcandidate_attempts':0})
    print(json.dumps({'status':'PASS' if passed==18 else 'FAIL','attempted':18,'passed':passed,'retries':0}))
    return 0 if passed==18 else 1


if __name__=='__main__':raise SystemExit(main())
