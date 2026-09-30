"""Bind exact committed STOP evidence for the sole timed-out formal attempt."""
import argparse
import hashlib
import json
from pathlib import Path

from p3_evidence import save
from p3_full_candidate import IMPLEMENTATION, P3_BASE
from p3_full_stop_audit import BASE, BUILD_SHA
from p3_review_cf807_bind import git, inventory

OUT=Path('reports/P3/full-authorized-committed-byte-binding.json')


def main():
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');args=p.parse_args()
    head=git('rev-parse','HEAD').decode().strip();rows,refs,streams=inventory(head)
    assert not git('diff','--name-only',IMPLEMENTATION,head,'--','src','rust','tools/p3_compile_inputs.py',
                   'tools/p3_accept_quarantine_owner_d01.py','tests/test_p3_quarantine_owner_d01.py').strip()
    assert not git('diff','--name-only',BASE,head,'--','reports/P1','reports/P2','src','rust','tools/parity_cases.py','tools/parity_repair_expected.py').strip()
    assert not git('diff','--name-only',BUILD_SHA,head,'--','tools/p3_full_candidate.py','tools/p3_freeze_gate.py','tests/test_p3_full_candidate.py').strip()
    oldfiles=git('ls-tree','-r','--name-only',BASE,'reports/P3').decode().splitlines()
    for path in oldfiles:assert git('rev-parse',BASE+':'+path)==git('rev-parse',head+':'+path)
    assert git('rev-parse','main').decode().strip()==P3_BASE
    delivery=json.loads(git('show',head+':reports/P3/full-authorized-delivery.json'))
    assert delivery['P3']=='NOT_READY' and delivery['attempts']==1 and delivery['build']=='FAIL_HOST_TIMEOUT'
    summary={'status':'VERIFIED_STOP_EVIDENCE','HEAD':head,'P3_BASE':P3_BASE,'IMPLEMENTATION':IMPLEMENTATION,
        'FULL_BUILD_SHA':BUILD_SHA,'overall_P3':'NOT_READY','code_review':'WAITING_REVIEW',
        'fullcandidate_attempts':1,'fullcandidate_maximum':1,'build':'FAIL_HOST_TIMEOUT',
        'committed_files_verified':len(rows),'exact_JSON_JSONL':sum(r['path'].endswith(('.json','.jsonl')) for r in rows),
        'unique_raw_verified':len(refs),'embedded_streams_verified':streams,'historical_P3_unchanged':len(oldfiles),
        'source_publicPython_Rust_P1P2_old151_unchanged':True,'main':P3_BASE}
    if args.verify:
        binding=json.loads(git('show',head+':'+OUT.as_posix()))
        for r in binding['files']:
            data=git('show',head+':'+r['path'])
            assert len(data)==r['bytes'] and hashlib.sha256(data).hexdigest()==r['sha256']
            assert git('rev-parse',head+':'+r['path']).decode().strip()==r['blob_oid']
        finalpaths={r['path'] for r in rows};parents={r['path'] for r in binding['files']}
        assert finalpaths==parents|{OUT.as_posix()}
        remote=dict(line.split()[::-1] for line in git('ls-remote','origin','refs/heads/dev','refs/heads/main').decode().splitlines())
        assert remote['refs/heads/dev']==head and remote['refs/heads/main']==P3_BASE
        assert not git('status','--porcelain').strip()
        summary.update(origin_dev=remote['refs/heads/dev'],origin_main=remote['refs/heads/main'],working_tree='CLEAN',evidence_commit=binding['evidence_commit'])
    else:
        save(OUT,dict(summary,evidence_commit=head,files=rows,raw_inventory=list(refs.values()),
            boundary='parent immutable blob OID/SHA/size incl failure; verify finalclosedset adds only binding itself; no selfhash claim',
            EOL='JSON/JSONL exactbytes; markdown checkout differences explicitly listed',historical_base=BASE))
    print(json.dumps(summary))


if __name__=='__main__':main()
