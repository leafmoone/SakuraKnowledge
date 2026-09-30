"""Bind immutable repaired receipt blobs; --verify checks final pushed closed set."""
import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

from p3_evidence import save, verify

BASE='cf807c1a5179ce4b451b9a85870b6684d2dccaf3'
SOURCE='7393d601a6d95432f41da243395ed5d3e0a2fda1'
MAIN='894dc6a73bfd42f18cc7648e8ab7481aae211ab1'
OUT=Path('reports/P3/review-cf807-committed-byte-binding.json')


def git(*args):return subprocess.check_output(['git',*args])


def inventory(commit):
    files=git('ls-tree','-r','--name-only',commit,'reports/P3').decode().splitlines()
    rows=[];refs={};embedded=0
    def walk(v):
        nonlocal embedded
        if isinstance(v,dict):
            if {'path','bytes','sha256'}<=v.keys() and str(v['path']).startswith('reports/P3/raw/'):
                verify(v);refs[v['path']]=dict(v)
            elif {'raw_path','bytes','sha256'}<=v.keys():
                ref={'path':v['raw_path'],'bytes':v['bytes'],'sha256':v['sha256']};verify(ref);refs[ref['path']]=ref
            for stream in ('stdout','stderr'):
                if stream+'_base64' in v:
                    assert hashlib.sha256(base64.b64decode(v[stream+'_base64'])).hexdigest()==v[stream+'_sha256']
                    embedded+=1
            for child in v.values():walk(child)
        elif isinstance(v,list):
            for child in v:walk(child)
    for path in files:
        data=git('show',commit+':'+path)
        exact=Path(path).read_bytes()==data
        if path.endswith(('.json','.jsonl')):assert exact,path
        rows.append({'path':path,'commit':commit,'blob_oid':git('rev-parse',commit+':'+path).decode().strip(),
                     'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'worktree_byte_match':exact})
        if path.endswith('.json'):walk(json.loads(data))
        elif path.endswith('.jsonl'):
            for line in data.splitlines():walk(json.loads(line))
    return rows,refs,embedded


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    head=git('rev-parse','HEAD').decode().strip();rows,refs,streams=inventory(head)
    assert git('diff','--name-only',SOURCE,head,'--','src','rust').strip()==b''
    assert git('diff','--name-only',BASE,head,'--','reports/P1','reports/P2','src/sakura_knowledge',
               'tools/parity_cases.py','tools/parity_repair_expected.py').strip()==b''
    historical=git('ls-tree','-r','--name-only',BASE,'reports/P3').decode().splitlines()
    for path in historical:assert git('rev-parse',BASE+':'+path)==git('rev-parse',head+':'+path),path
    assert git('rev-parse','main').decode().strip()==MAIN
    summary={'status':'VERIFIED','HEAD':head,'source_artifact_commit':SOURCE,'overall_P3':'BLOCKED/NOT_READY',
             'code_review_state':'WAITING_REVIEW','committed_files_verified':len(rows),
             'exact_JSON_JSONL':sum(r['path'].endswith(('.json','.jsonl')) for r in rows),
             'unique_raw_verified':len(refs),'embedded_streams_verified':streams,
             'historical_P3_files_unchanged':len(historical),'main':MAIN,'fullcandidate_attempts':0}
    if args.verify:
        binding=json.loads(git('show',head+':'+str(OUT).replace('\\','/')))
        for r in binding['files']:
            data=git('show',head+':'+r['path'])
            assert len(data)==r['bytes'] and hashlib.sha256(data).hexdigest()==r['sha256']
            assert git('rev-parse',head+':'+r['path']).decode().strip()==r['blob_oid']
        remote=dict(line.split()[::-1] for line in git('ls-remote','origin','refs/heads/dev','refs/heads/main').decode().splitlines())
        assert remote['refs/heads/dev']==head and remote['refs/heads/main']==MAIN
        assert git('status','--porcelain').strip()==b''
        summary.update(origin_dev=remote['refs/heads/dev'],origin_main=remote['refs/heads/main'],working_tree='CLEAN',
                       evidence_commit=binding['evidence_commit'])
    else:
        save(OUT,dict(summary,evidence_commit=head,files=rows,raw_inventory=list(refs.values()),
                      binding_boundary='Exact immutable parent receipt blobs; newbinding cannot selfhash futurecommit. --verify finalhead includes closedset+self and actualremote.',
                      EOL='JSONJSONL byteverbatim; Markdown checkout differences truthfully listed',
                      historical_base=BASE))
    print(json.dumps(summary))


if __name__=='__main__':main()
