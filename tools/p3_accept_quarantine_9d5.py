"""One raw compiler/normal-builder fixture, eight independent full-JSON paths."""
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
from test_p3_quarantine_9d5 import conflict_fixture
from test_p3_resolver import expected, key


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bin',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    binary=args.bin.resolve();output=args.out.resolve();root=Path.cwd();rawroot=root/'reports/P3/raw'
    if output.exists():raise FileExistsError(output)
    records=[]
    with tempfile.TemporaryDirectory(prefix='sknow-quarantine-9d5-') as directory,pytest.MonkeyPatch.context() as patch:
        db,snapshot,chains,links,projections,eids=conflict_fixture(Path(directory),patch)
        files=[{'fixture_path':p.relative_to(directory).as_posix(),'raw':store(p.read_bytes(),rawroot)}
               for p in sorted(Path(directory).rglob('*')) if p.is_file() and p.suffix in ('.raw','.json','.jsonl')]
        for name,exact in [('A',False),('B',False),('C',False),('A',True),('B',True),('C',True),('heroA',True),('heroC',True)]:
            entity=name.startswith('hero');endpoint=name[-1] if entity else name
            kind='character' if entity else 'tag';namespace='fixture.character' if entity else 'danbooru.tag'
            want=expected(snapshot,name,'resolved',tag='C',canonical='canonical',
                          matched='entity_tag' if entity else 'native_exact' if name=='C' else 'official_alias',
                          source=key(name,kind,namespace) if exact else None)
            want['evidence_chain']=list(chains[endpoint])
            if entity:
                link=next(r for r in links if r['src']['value']==name)
                want['evidence_chain'].append({'role':'entity_tag','source_id':'fixture-v1','evidence_id':eids[name],'link':link})
            argv=[str(binary),'resolve-tag',str(db),name]
            if exact:argv+=['--key','--kind',kind,'--namespace',namespace]
            process=subprocess.run(argv,capture_output=True,timeout=15,check=False,
                                   env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'))
            value=json.loads(process.stdout) if process.returncode==0 and not process.stderr else None
            oracle=result(db,name,kind=kind if exact else None,namespace=namespace if exact else None,exact=exact)
            records.append({'name':name,'exact':exact,'argv':argv,'exit':process.returncode,
                            'stdout':store(process.stdout,rawroot),'stderr':store(process.stderr,rawroot),
                            'expected':store(json.dumps(want,ensure_ascii=False,separators=(',',':')).encode('utf-8'),rawroot),
                            'oracle':store(json.dumps(oracle,ensure_ascii=False,separators=(',',':')).encode('utf-8'),rawroot),
                            'independent_fullJSON':value==want,'oracle_fullJSON':value==oracle,
                            'passed':value==want==oracle,'retries':0})
    # Restore cwd before writing portable byhash references. Fixture URLs/paths are
    # observations only; actual fixture bytes are frozen once at repositoryrawroot.
    def portable(v):
        if isinstance(v,dict):
            if {'path','bytes','sha256'}<=v.keys():v['path']=Path(v['path']).relative_to(root).as_posix()
            for x in v.values():portable(x)
        elif isinstance(v,list):
            for x in v:portable(x)
    portable(records);portable(files)
    passed=sum(r['passed'] for r in records)
    save(output,{'status':'PASS' if passed==8 else 'FAIL','attempted':8,'passed':passed,'retries':0,
                 'snapshot':snapshot,'normal_builder_atomic_verified':True,'fixture_files':files,
                 'compiled_projections':projections,'records':records,
                 'expected_origin':'hardcoded raw IDs/keypairs/source SHA/step endpoints/scopes/cut old-cut!=new-cut, not resolver-derived',
                 'real_source_positive':False,'upstream_GETs':0,'fullcandidate_attempts':0})
    print(json.dumps({'status':'PASS' if passed==8 else 'FAIL','passed':passed,'attempted':8,'retries':0}))
    return 0 if passed==8 else 1


if __name__=='__main__':raise SystemExit(main())
