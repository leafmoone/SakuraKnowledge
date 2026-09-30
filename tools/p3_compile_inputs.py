"""Offline frozen native/Wiki ETL and conflict-preserving pilot selection."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sakura_knowledge.native_tags import RULE_VERSION, assess
from sakura_knowledge.storage import REQUIRED_SOURCE, digest


def key(kind,namespace,value):
    return {'kind':kind,'namespace':namespace,'value':str(value)}


def dump(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)


def lines(path,records):
    with path.open('x',encoding='utf-8',newline='\n') as f:
        for r in records:
            f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')


def load_raw(receipt):
    path=Path(receipt['raw_path'])
    b=path.read_bytes()
    if digest(path)!=receipt['sha256'] or len(b)!=receipt['bytes']:
        raise ValueError('frozen acquisition raw mismatch')
    return json.loads(b)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--receipt-prefix',default='')
    args=parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    args.out.mkdir(parents=True)
    acquisition=json.loads(Path('reports/P3/native-acquisition.json').read_text())
    extension=json.loads(Path('reports/P3/alias-acquisition.json').read_text())
    if acquisition['status']!='SCOPED_COMPLETE' or extension['status']!='SCOPED_COMPLETE':
        raise ValueError('scoped native acquisition incomplete')
    tagreceipt=next(x for x in acquisition['records'] if x['role']=='tags_and_wiki')
    tags=load_raw(tagreceipt)
    source_id='danbooru-native-scoped-'+tagreceipt['sha256'][:12]
    scopes={};aliases=[];alias_refs={}
    for r in acquisition['records']+extension['records']:
        if r['role']=='outgoing_alias_scope' and r['status']=='FROZEN':
            scopes[r['tag_scope']]=r
            for a in load_raw(r):
                aliases.append(a)
                alias_refs[a['id']]=r
    assessments=assess(tags,aliases,set(scopes))
    aliases_by_id={a['id']:a for a in aliases}
    tags_by_name={t['name']:t for t in tags}
    native_records=[]
    lookup=[]
    wiki_ids=set()
    candidates=[]
    for t in sorted(tags,key=lambda t:t['name']):
        native_records.append({'key':key('tag','danbooru.tag',t['name']),'status':'source_backed',
                               'evidence_id':'native:'+str(t['id']),'raw_native':{k:v for k,v in t.items() if k!='wiki_page'},
                               'raw_reference':{'path':tagreceipt['raw_path'],'sha256':tagreceipt['sha256'],
                                                'record_id':t['id']},'source_cut':tagreceipt['fetched_at_utc']})
    def proof(role,r,eid,**extra):
        return dict(role=role,source_id=source_id,evidence_id=eid,raw_path=r['raw_path'],
                    raw_sha256=r['sha256'],fetched_at_utc=r['fetched_at_utc'],**extra)
    for name,a in assessments.items():
        terminal=a['terminal']
        target=tags_by_name.get(terminal)
        chain=[]
        if target:
            chain.append(proof('native_identity',tagreceipt,'native:'+str(target['id']),tag_id=target['id']))
        path=[name]
        for aid in a['chain']:
            edge=aliases_by_id[aid]
            chain.append(proof('official_alias_step',alias_refs[aid],'official_alias:'+str(aid),alias_id=aid,
                               antecedent_name=edge['antecedent_name'],consequent_name=edge['consequent_name'],
                               upstream_status=edge['status']))
            path.append(edge['consequent_name'])
        for step in dict.fromkeys(path):
            if step in scopes:
                chain.append(proof('canonical_scope',scopes[step],'scope:'+step,name=step,
                                   coverage='scoped_complete',active_alias_ids=[e['id'] for e in load_raw(scopes[step]) if e['status']=='active']))
        if not chain:
            chain=[proof('canonical_scope',tagreceipt,'unknown:'+name,coverage='partial')]
        matched='native_exact' if name in tags_by_name else 'official_alias'
        record={'record_type':'tag_resolution','name':name,
                'target':key('tag','danbooru.tag',terminal) if terminal else None,
                'matched_by':matched,'canonical_status':a['canonical_status'],'category':a['category'],
                'reason':a['reason'],'rule_version':RULE_VERSION,'status':'source_backed',
                'evidence_id':'assessment:'+name,'evidence_chain':chain}
        lookup.append(record)
    # New live Wiki evidence is allowed only if explicit embedded association and
    # old frozen page metadata/body/other_names are exactly compatible. No rewrites.
    old_manifest=Path('build/real-full-7afe7fb/manifest.json')
    original=json.loads(old_manifest.read_text())
    danbooru_source=next(s for s in original['sources'] if s['provider']=='danbooru')
    old_wiki_path=(old_manifest.parent/danbooru_source['path']).resolve()
    old_pages={};old_lines={}
    live_wikis={str(t['wiki_page']['id']):t for t in tags if isinstance(t.get('wiki_page'),dict)}
    with old_wiki_path.open(encoding='utf-8') as stream:
        for line_no,text in enumerate(stream,1):
            row=json.loads(text)
            if row.get('key',{}).get('namespace')=='danbooru.wiki' and row['key']['value'] in live_wikis:
                old_pages[row['key']['value']]=row
                old_lines[row['key']['value']]=line_no
    compatible=[];conflicts=[]
    for wid,t in live_wikis.items():
        wiki=t['wiki_page'];old=old_pages.get(wid);native=next(x for x in lookup if x['name']==t['name'])
        reason=None
        if wiki.get('is_deleted') is not False or wiki.get('title')!=t['name']:
            reason='live_wiki_association_invalid'
        elif old is None or not old.get('documents'):
            reason='old_wiki_missing'
        else:
            meta=old.get('raw',{}).get('raw_page_metadata',{})
            if meta.get('updated_at')!=wiki.get('updated_at') or meta.get('other_names')!=wiki.get('other_names'):
                reason='mixed_cut_version_conflict'
            elif old['documents'][0]['original']!=wiki.get('body',''):
                reason='mixed_cut_body_conflict'
        if reason:
            native['evidence_chain']=native['evidence_chain']+[proof('wiki_association_quarantined',tagreceipt,
                'wiki-quarantine:'+wid,wiki_key=key('page','danbooru.wiki',wid),tag_key=key('tag','danbooru.tag',t['name']),
                reason=reason,old_source_id=danbooru_source['source_id'],old_input_sha256=danbooru_source['local_sha256'],
                old_line=old_lines.get(wid),old_updated_at=old.get('raw',{}).get('raw_page_metadata',{}).get('updated_at') if old else None,
                live_updated_at=wiki.get('updated_at'))]
            conflicts.append({'tag':t['name'],'wiki_id':wid,'reason':reason,
                              'old_updated_at':old.get('raw',{}).get('raw_page_metadata',{}).get('updated_at') if old else None,
                              'new_updated_at':wiki.get('updated_at')})
            continue
        if native['canonical_status']!='canonical':
            conflicts.append({'tag':t['name'],'wiki_id':wid,'reason':'canonical_unknown'})
            continue
        wiki_ids.add(wid);compatible.append({'tag':t['name'],'wiki_id':wid,'updated_at':wiki['updated_at']})
        wkey=key('page','danbooru.wiki',wid)
        tkey=key('tag','danbooru.tag',t['name'])
        association=proof('wiki_tag_link',tagreceipt,'wiki:'+wid,wiki_id=wiki['id'],tag_id=t['id'],
                          wiki_key=wkey,tag_key=tkey,association='official embedded tag.wiki_page')
        body_sha=hashlib.sha256(wiki['body'].encode('utf-8')).hexdigest()
        names_sha=hashlib.sha256(json.dumps(wiki['other_names'],ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
        compatibility=proof('wiki_cut_compatibility',tagreceipt,'wiki-cut:'+wid,wiki_key=wkey,tag_key=tkey,
                            old_source_id=danbooru_source['source_id'],old_input_sha256=danbooru_source['local_sha256'],
                            old_path=str(old_wiki_path),old_line=old_lines[wid],
                            old_evidence_id=old.get('evidence_id',f"{danbooru_source['source_id']}:{danbooru_source['local_sha256']}:line:{old_lines[wid]}"),
                            old_updated_at=meta['updated_at'],live_updated_at=wiki['updated_at'],
                            body_sha256=body_sha,old_body_sha256=body_sha,live_body_sha256=body_sha,
                            old_other_names_sha256=names_sha,live_other_names_sha256=names_sha,
                            rule='exact body+updated_at+other_names; no live overwrite')
        description_refs=[association,compatibility]
        native_records.append({'record_type':'link','src':wkey,'dst':tkey,
                               'relation':'wiki_tag','method':'official-embedded-association-compatible-cut-v1',
                               'verification_status':'native','evidence_refs':description_refs})
        native['evidence_chain']=native['evidence_chain']+description_refs
        native['wiki_key']=wkey
        for text in wiki.get('other_names',[]):
            if not isinstance(text,str) or not text:
                continue
            reference=proof('multilingual_name',tagreceipt,'wiki:'+wid,wiki_id=wiki['id'],language='unknown',text=text)
            lookup.append({**native,'name':text,'matched_by':'wiki_name','evidence_id':'wiki:'+wid+':name:'+text,
                           'evidence_chain':native['evidence_chain']+[reference]})
    all_records=native_records+lookup
    lines(args.out/'native.jsonl',all_records)
    # Preserve every old record whose full identity or source-backed alias matches
    # any selected title/multilingual name. No favorable-only entity sampling.
    name_set={x['name'] for x in lookup}|{t['name'] for t in tags}
    selected=set();counts=Counter();selected_records=[];old_sources=[]
    for s in original['sources']:
        path=(old_manifest.parent/s['path']).resolve()
        if digest(path)!=s['local_sha256']:
            raise ValueError('old normalized inputs changed')
        filename='pilot-'+s['provider']+'-'+s['source_id'][:12]+'.jsonl'
        chosen=[]
        with path.open(encoding='utf-8') as stream:
            for line_no,text in enumerate(stream,1):
                row=json.loads(text);k=row.get('key')
                if not k:
                    continue
                match=k['value'] in name_set or (k['namespace']=='danbooru.wiki' and k['value'] in wiki_ids)
                match=match or any(a.get('status')=='source_backed' and a.get('text') in name_set for a in row.get('aliases',[]))
                if match:
                    chosen.append(row);selected.add(tuple(k[x] for x in ('kind','namespace','value')))
                    counts[k['namespace']]+=1;selected_records.append({'source_id':s['source_id'],'line':line_no,'key':k})
                    if k['namespace'].startswith(('bangumi.','moegirl.')) and len(candidates)<100:
                        matching=[t for t in tags if any(a.get('text') in t['wiki_page'].get('other_names',[]) for a in row.get('aliases',[]))]
                        for t in matching:
                            if len(candidates)>=100:break
                            candidates.append({'candidate_id':f'candidate:{len(candidates)+1}','src':k,
                                               'dst':key('tag','danbooru.tag',t['name']),'relation':'entity_tag',
                                               'status':'candidate','reason':'shared_source_name_only_not_identity',
                                               'evidence_refs':[{'source_id':s['source_id'],'input_sha256':s['local_sha256'],'line':line_no},
                                                                proof('native_identity',tagreceipt,'native:'+str(t['id']))]})
        if chosen:
            lines(args.out/filename,chosen)
            meta=dict(s,path=filename,local_sha256=digest(args.out/filename),dataset_role='p3_conflict_preserving_pilot_subset',
                      counts={'normalized_records':len(chosen)},source_references=[{'original_input_sha256':s['local_sha256'],'original_source_id':s['source_id']}])
            old_sources.append(meta)
    source=dict.fromkeys(REQUIRED_SOURCE)
    source.update(source_id=source_id,provider='danbooru',dataset_role='scoped_native_tags_aliases_verified_wiki_projection',
                  repo='https://danbooru.donmai.us',path='native.jsonl',adapter='contract-jsonl-v1',
                  asset_name='official scoped metadata',local_sha256=digest(args.out/'native.jsonl'),
                  fetched_at_utc=tagreceipt['fetched_at_utc'],exported_at=datetime.now(UTC).isoformat(),
                  schema_version=RULE_VERSION,refresh_status='scoped_complete mixed-source dates; not full live refresh',
                  counts={'normalized_records':len(all_records),'native_tags':len(tags),'aliases_observed':len(aliases)},
                  input_file_inventory=[{'path':r['raw_path'],'sha256':r['sha256'],'bytes':r['bytes']} for r in acquisition['records']+extension['records']],
                  source_references=['reports/P3/native-acquisition.json','reports/P3/alias-acquisition.json'],
                  importer_version=RULE_VERSION,code_license='MIT (SakuraKnowledge); upstream rules separate',
                  data_license='unknown; local-only raw/metadata; no unrestricted redistribution claim')
    full_sources=[dict(s,path=str((old_manifest.parent/s['path']).resolve())) for s in original['sources']]
    dump(args.out/'pilot-manifest.json',{'p3_resolver_version':'1','sources':old_sources+[source]})
    dump(args.out/'candidate-manifest.json',dict(original,p3_resolver_version='1',sources=full_sources+[source]))
    prefix=args.receipt_prefix
    lines(Path('reports/P3/'+prefix+'candidates.jsonl'),candidates)
    lines(Path('reports/P3/'+prefix+'decisions.jsonl'),[{'decision_id':'decision:'+x['candidate_id'],'src':x['src'],'dst':x['dst'],
        'relation':'entity_tag','decision':'candidate','method':'shared-source-name-insufficient','rule_version':RULE_VERSION,
        'evidence_refs':x['evidence_refs'],'reviewer_kind':'execution_agent','reviewer_id':'swe_2',
        'time':datetime.now(UTC).isoformat(),'supersedes':None} for x in candidates])
    report={'status':'FROZEN','native_source_id':source_id,'native_tags':len(tags),'official_alias_records':len(aliases),
            'assessments':assessments,'compatible_wiki_links':compatible,'wiki_conflicts_quarantined':conflicts,
            'pilot_namespace_record_counts':dict(counts),'pilot_selected_records':selected_records,
            'cross_source_candidates':len(candidates),'cross_source_verified':0,'human_verified':0,
            'native_input':{'path':str(args.out/'native.jsonl'),'sha256':digest(args.out/'native.jsonl')},
            'description_policy':'Original compatible old documents only; no body duplication',
            'limitations':['No cross-source ID evidence found in name-only candidates, no verified mapping fabricated',
                           'Mixed Wiki versions quarantined; no live old-source refresh',
                           'Name language remains unknown; Chinese-script tests not a universal translation label']}
    dump(Path('reports/P3/'+prefix+'source_manifest.json'),source)
    dump(Path('reports/P3/'+prefix+'input-compilation.json'),report)
    print(json.dumps({k:v for k,v in report.items() if k in ['native_tags','official_alias_records','cross_source_candidates','cross_source_verified','pilot_namespace_record_counts']}))


if __name__=='__main__':
    main()
