"""Full-candidate decision gate, never launches/retries the one-time full build."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from p3_evidence import save

from sakura_knowledge.storage import digest
from sakura_knowledge.tag_decisions import replay


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    mainsha=subprocess.check_output(['git','rev-parse','main'],text=True).strip()
    status=subprocess.check_output(['git','status','--porcelain'],text=True)
    manifest=Path('build/p3-inputs-v2/candidate-manifest.json')
    value=json.loads(manifest.read_text(encoding='utf-8'))
    inputs=[]
    for source in value['sources']:
        path=Path(source['path'])
        if not path.is_absolute():path=manifest.parent/path
        observed=digest(path)
        inputs.append({'source_id':source['source_id'],'path':str(path),'expected':source['local_sha256'],
                       'observed':observed,'unchanged':observed==source['local_sha256']})
    decisions=[json.loads(x) for x in Path('reports/P3/v2-decisions.jsonl').read_text(encoding='utf-8').splitlines()]
    verified=replay(decisions)
    acquisition=json.loads(Path('reports/P3/alias-acquisition.json').read_text(encoding='utf-8'))
    compilation=json.loads(Path('reports/P3/v2-input-compilation.json').read_text(encoding='utf-8'))
    old=Path('build/snapshot-full-20bf5b3/knowledge.sqlite')
    old_sha=digest(old)
    acceptance=json.loads(Path('reports/P3/real-pilot-acceptance-final.json').read_text(encoding='utf-8'))
    free=shutil.disk_usage(old.parent).free
    gates={'code_sha_clean':not status,'main_unchanged':mainsha=='894dc6a73bfd42f18cc7648e8ab7481aae211ab1',
           'frozen_inputs_all_sha':all(x['unchanged'] for x in inputs),
           'old_snapshot_unchanged':old_sha=='4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073',
           'disk_100GiB_budget':free>100*1024**3,
           'official_budget':acquisition['status']=='SCOPED_COMPLETE' and acquisition['requests_including_prior_docs']<=200
                             and acquisition['cumulative_collector_bytes']+acquisition['documentation_byte_reserve']<=268435456,
           'realpilot_acceptance':acceptance['status']=='PASS',
           'native_real_positive':compilation['native_tags']>0,
           'wiki_real_positive':len(compilation['compatible_wiki_links'])>0,
           'necessary_verified_entity_tag_real_positive':bool(verified)}
    ready=all(gates.values())
    save(args.out,{'status':'READY' if ready else 'BLOCKED','fixed_code_sha':head,'main_sha':mainsha,
                  'candidate_build':'NOT_RUN','attempts':0,'gates':gates,'inputs':inputs,
                  'old_snapshot':{'path':str(old),'bytes':old.stat().st_size,'sha256':old_sha},'free_bytes':free,
                  'decisions_verified':len(verified),'decision_count':len(decisions),
                  'manifest':{'path':str(manifest),'sha256':digest(manifest)},
                  'blocker':'No real explicit cross-source ID/link evidence or actual human verification for necessary entity_tag positive. Name-only queue remains candidate; no runtime confidence promotion.',
                  'overall_P3':'NOT_READY, pilot/code evidence only, not P3 acceptance',
                  'future_action':'Supply source-backed cross-source ID/link evidence or genuine human decision, replay+new pilot; do not automatically perform/retry full build'})
    print(json.dumps({'status':'READY' if ready else 'BLOCKED','gates':gates,'attempts':0,'free_bytes':free}))


if __name__=='__main__':main()
