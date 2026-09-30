"""New installed wheel and release binary verified from outside source tree."""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from p3_accept_resolver import check, command
from p3_evidence import save, store
from p3_resolver_oracle import result

from sakura_knowledge.storage import digest


def main():
    parser=argparse.ArgumentParser()
    for flag in ('python','bin','wheel','db','gold','out'):
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--source-commit',default='b393581c54d5ac0db76802897220f4818c1eb3c0')
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    records=[]
    with tempfile.TemporaryDirectory(prefix='sknow-p3-artifact-') as directory:
        def capture(argv):
            p=subprocess.run(argv,cwd=directory,capture_output=True,timeout=15,check=False,env=env)
            rec={'argv':argv,'cwd':directory,'exit':p.returncode,'stdout':store(p.stdout),'stderr':store(p.stderr)}
            records.append(rec)
            return p
        code="import json,sys,sakura_knowledge.api as a;from sakura_knowledge.api import Knowledge;print(json.dumps({'file':a.__file__,'runtime_resolve_tag':hasattr(Knowledge,'resolve_tag'),'prefix':sys.prefix,'path':sys.path,'stdout_encoding':sys.stdout.encoding,'utf8_mode':sys.flags.utf8_mode}))"
        p=capture([str(args.python.resolve()),'-X','utf8','-I','-c',code])
        env_record=json.loads(p.stdout) if p.returncode==0 and not p.stderr else None
        environment_pass=env_record is not None and env_record['stdout_encoding'].lower()=='utf-8' and env_record['utf8_mode']==1 and not env_record['runtime_resolve_tag'] and 'site-packages' in env_record['file'] and not any(Path(x).resolve()==root/'src' for x in env_record['path'] if x)
        # Installed Python old public API must have no resolver, and still exactly
        # reproduce ordinary Rust P2 lookup on the same immutable pilot snapshot.
        pair_queries=['hatsune_miku','初音未来','后藤一里','镜音铃','gotoh_hitori','5655','孤独摇滚','Rem']
        pairs=[]
        pycode="import json,sys;from sakura_knowledge.api import Knowledge\nwith Knowledge(sys.argv[1]) as k: print(json.dumps(k.lookup(sys.argv[2]),ensure_ascii=False,separators=(',',':')))"
        for q in pair_queries:
            py=capture([str(args.python.resolve()),'-X','utf8','-I','-c',pycode,str(args.db.resolve()),q])
            rs=capture([str(args.bin.resolve()),'lookup',str(args.db.resolve()),q])
            good=py.returncode==rs.returncode==0 and not py.stderr and not rs.stderr and json.loads(py.stdout)==json.loads(rs.stdout)
            pairs.append({'query':q,'passed':good})
        # Rust-only new resolver: expected/gold and complete independent oracle.
        resolver=[]
        gold=json.loads(args.gold.read_text(encoding='utf-8'))
        for case in gold['cases']:
            p=capture(command(args.bin,args.db,case))
            value=json.loads(p.stdout) if p.returncode==0 and not p.stderr else None
            want=result(args.db,case['query'],**{k:case[k] for k in ('category','kind','namespace','exact','limit') if k in case})
            good=value==want and check(value,case) if value is not None else False
            resolver.append({'case_id':case['id'],'passed':good})
    passed=environment_pass and all(x['passed'] for x in pairs+resolver)
    save(args.out,{'status':'PASS' if passed else 'FAIL','source_commit':args.source_commit,
                   'environment':env_record,'source_external_verified':environment_pass,'pairs':pairs,'resolver_cases':resolver,
                   'processes':records,'retries':0,
                   'artifacts': [{'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path)} for path in (args.wheel,args.bin,args.db)],
                   'coverage':'pilot only; candidate full is BLOCKED/NOT_RUN','Python_public_resolver_added':False})
    print(json.dumps({'status':'PASS' if passed else 'FAIL','P2pairs':len(pairs),'Rustresolver':len(resolver),'external':environment_pass}))
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
