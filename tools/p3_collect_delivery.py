"""Validate source/artifact/receipt bytes and assemble an explicitly BLOCKED delivery."""
import base64
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from p3_evidence import save, verify

from sakura_knowledge.storage import digest

SOURCE='b393581c54d5ac0db76802897220f4818c1eb3c0'


def main():
    root=Path('reports/P3')
    checks={}
    for name in ('pytest','ruff','diff','fmt','rust-test','clippy','release'):
        r=json.loads((root/('check-'+name+'.json')).read_text(encoding='utf-8'))
        if r['exit']!=0 or r['head']!=SOURCE:raise ValueError('check not passed on fixedsource')
        checks[name]={'path':str(root/('check-'+name+'.json')),'exit':r['exit'],'sha256':digest(root/('check-'+name+'.json'))}
    gate=json.loads((root/'full-candidate-gate.json').read_text(encoding='utf-8'))
    old=json.loads((root/'old151.json').read_text(encoding='utf-8'))
    real=json.loads((root/'real-pilot-acceptance-final.json').read_text(encoding='utf-8'))
    perf=json.loads((root/'resolver-performance.json').read_text(encoding='utf-8'))
    art=json.loads((root/'artifact-cli-utf8.json').read_text(encoding='utf-8'))
    if gate['attempts']!=0 or gate['status']!='BLOCKED':raise ValueError('fullbuild state unexpected')
    if old['summary']['passed']!=151 or real['passed']!=50 or perf['status']!='PASS' or art['status']!='PASS':raise ValueError('missing validation')
    wheel=Path('dist/p3-b393581/sakura_knowledge-0.2.0-py3-none-any.whl')
    matched=[]
    with zipfile.ZipFile(wheel) as zipped:
        for name in zipped.namelist():
            if name.startswith('sakura_knowledge/') and name.endswith('.py'):
                blob=subprocess.check_output(['git','show',SOURCE+':src/'+name])
                contents=zipped.read(name)
                export=(Path('dist/p3-b393581/source/src')/name).read_bytes()
                if contents!=export or contents.replace(b'\r\n',b'\n')!=blob.replace(b'\r\n',b'\n'):
                    raise ValueError('wheel source beyond documented archive EOL transform diverges')
                matched.append({'module':name,'committed_blob_sha256':hashlib.sha256(blob).hexdigest(),
                                'committed_bytes':len(blob),'wheel_export_sha256':hashlib.sha256(contents).hexdigest(),
                                'wheel_export_bytes':len(contents),'byte_exact_git_blob':contents==blob,
                                'exact_export_match':True,'eol_normalized_git_blob_match':True})
    if subprocess.check_output(['git','diff','--name-only',SOURCE,'--','src','rust']).strip():
        raise ValueError('production source changed after artifact freeze')
    files=[wheel,Path('dist/p3-b393581/source/rust/target/release/sknow-rs.exe'),
           Path('dist/p3-b393581/source/rust/target/release/examples/bench_resolver.exe'),
           Path('build/p3-pilot-v2/knowledge.sqlite'),Path('build/p3-inputs-v2/pilot-manifest.json'),
           Path('build/p3-inputs-v2/candidate-manifest.json'),Path('build/p3-inputs-v2/native.jsonl')]
    artifacts=[{'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size} for p in files]
    refs={};embedded=0
    def walk(v):
        nonlocal embedded
        if isinstance(v,dict):
            if {'path','bytes','sha256'}<=v.keys() and str(v['path']).startswith('reports/P3/raw/'):
                verify(v);refs[v['path']]=dict(v)
            elif {'raw_path','bytes','sha256'}<=v.keys():
                ref={'path':v['raw_path'],'bytes':v['bytes'],'sha256':v['sha256']}
                verify(ref);refs[ref['path']]=ref
            for stream in ('stdout','stderr'):
                if stream+'_base64' in v:
                    b=base64.b64decode(v[stream+'_base64'])
                    if hashlib.sha256(b).hexdigest()!=v[stream+'_sha256']:raise ValueError('embedded command raw mismatch')
                    embedded+=1
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    for p in sorted(root.glob('*.json')):
        walk(json.loads(p.read_text(encoding='utf-8')))
    save(root/'coverage_summary.json',{'overall':'NOT_READY','full_candidate':'BLOCKED/NOT_RUN','full_build_attempts':0,
         'native_tag_identities':30,'official_active_alias_graphs':1,'official_inactive_alias_records':3,
         'wiki_tag_links':28,'wiki_changed_versions_quarantined':2,'native_name_assessments':352,
         'pilot_entries':451,'pilot_fts_documents':222,'pilot_input_records':874,'pilot_accepted_records':874,
         'candidate_decisions':100,'verified_entity_tag':0,'human_verified':0,
         'gold_queries':50,'positive_denominator':38,'positive_correct':38,'chinese_script_positive_denominator':15,
         'nonresolved_denominator':12,'nonresolved_correct':12,'wrong_resolved_tag':0,
         'full_source_recall':'NOT_MEASURED','description_claim':'source text only, bounded compatibleWiki',
         'gaps':['Real source-backed cross-source mapping ID/link evidence is missing',
                 'No actual human verification; agent candidate decisions never count as human',
                 'Old and new source cuts remain distinct; new30tag native scope only',
                 'Full candidate resolver performance and RSS NOT_RUN because build blocked']})
    save(root/'artifact-manifest.json',{'source_commit':SOURCE,'build_origin':'new git archive of fixed committed source; no relabeling P2 outputs',
                                       'wheel_source_modules_verified':matched,'artifacts':artifacts,
                                       'source_export_note':'Git archive export used observed CRLF for12Python modules. Wheel matches exact export; each committedGitblob separately hashed; only LF/CRLF transform permitted. No byte-exactGitblob claim for these12modules.',
                                       'old_snapshot_immutable':gate['old_snapshot'],
                                       'artifact_external_utf8_environment':art['environment']})
    save(root/'delivery.json',{'status':'BLOCKED','overall_P3':'NOT_READY','source_commit':SOURCE,
         'full_candidate':{'status':'NOT_RUN','attempts':0,'gate_receipt':'reports/P3/full-candidate-gate.json'},
         'blocker':gate['blocker'],'checks':checks,'old151_summary':old['summary'],
         'real50':{k:real[k] for k in ('status','attempted','passed','positive_denominator','positive_correct','nonresolved_denominator','nonresolved_correct','wrong_resolved')},
         'performance':{'status':perf['status'],'measured':perf['measured'],'warmups':perf['warmups'],'retries':0,'scope':'PILOT_ONLY',
                        'max_reused_p95_s':max(x['p95_s'] for x in perf['summary'] if x['mode']=='reused_connection'),
                        'max_cli_p95_s':max(x['p95_s'] for x in perf['summary'] if x['mode']=='independent_cli')},
         'artifact_external':{'P2_pairs':8,'Rust_resolver_fullJSON_expected':50,'ABC_pairs':10,'UTF8_verified':True},
         'artifacts':artifacts,'verified_raw_unique_files':len(refs),'embedded_command_streams_verified':embedded,
         'raw_inventory':list(refs.values()),'raw_policy':'Official source/query streams once local byhash;small command receipts embedded; all historical P1P2 immutable',
         'superseded_receipts':{'input-compilation.json':'INVALID_COVERAGE nested raw metadata schema lookup bug, v2 separate replacement',
              'real-pilot-acceptance.json':'FAIL49/50; correct aliasidentity lackedWiki description, fixedruntime; unchanged gold',
              'artifact-cli-command.json':'FAIL exit1 UTF8 fixture setup: isolated Python ignoredenv; explicit-Xutf8 verified in new receipt'},
         'limitations':['No P3 acceptance or mainmerge authorized','Linux/Pi/Pool/dbstat/full human facts remain NOT_RUN',
                        'No verifiedentitytag source positive, no fullcandidate build or fullcandidate RSS/perf',
                        'Native collection is finite mixed-cut, no full live refresh','Rawsource license unknown/local-only'],
         'required_unblock':'Provide genuine explicit cross-source ID/link evidence or actual scoped human decisions; replay/compile a new pilot before full gates',
         'remote_bound_commit':'Read final commit binding and git ls-remote after normal push; no self-referential SHA fabricated'})
    print(json.dumps({'status':'BLOCKED','checks':len(checks),'rawfiles_verified':len(refs),'wheel_modules_verified':len(matched),'artifacts':len(artifacts)}))


if __name__=='__main__':main()
