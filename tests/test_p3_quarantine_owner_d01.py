"""Quarantine owner is its reference key, not a native alias's terminal target."""
import hashlib
import json
import sys
from itertools import pairwise
from pathlib import Path

import pytest
from test_core import manifest
from test_p3_resolver import expected, key, run
from test_p3_review_cf807 import tool
from test_rust_repair import binary as rust_binary_fixture

from sakura_knowledge.storage import build

binary=rust_binary_fixture
PATHS=[('A',False),('B',False),('C',False),('A',True),('B',True),('C',True),
       ('heroA',True),('heroB',True),('heroC',True)]


def owner_fixture(tmp_path,monkeypatch,reverse=False):
    monkeypatch.chdir(tmp_path)
    reports=Path('reports/P3');reports.mkdir(parents=True)
    old=Path('build/real-full-7afe7fb');old.mkdir(parents=True)
    pages=[{'key':key(str(wid),'page','danbooru.wiki'),'status':'source_backed',
            'documents':[{'title':name,'original':'Body '+name,'status':'source_backed'}],
            'raw':{'raw_page_metadata':{'id':wid,'title':name,'updated_at':'old-'+name,'other_names':[]}}}
           for name,wid in [('A',9),('C',19)]]
    oldbytes=(''.join(json.dumps(p)+'\n' for p in pages)).encode('utf-8')
    (old/'wiki.jsonl').write_bytes(oldbytes);oldsha=hashlib.sha256(oldbytes).hexdigest()
    (old/'manifest.json').write_text(json.dumps({'sources':[{'source_id':'old-owner-wiki','provider':'danbooru',
                                'path':'wiki.jsonl','local_sha256':oldsha}]}),encoding='utf-8')
    def raw(name,value,role,**extras):
        path=reports/(name+'.raw');data=json.dumps(value).encode('utf-8');path.write_bytes(data)
        return dict(role=role,status='FROZEN',raw_path=str(path),sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data),fetched_at_utc='owner-fetch',**extras)
    tags=[{'id':tid,'name':name,'category':4,'is_deprecated':False,'wiki_page':{'id':wid,'title':name,
           'body':'Body '+name,'updated_at':'new-'+name,'is_deleted':False,'other_names':[]}}
          for name,tid,wid in [('A',1,9),('C',3,19)]]
    if reverse:tags.reverse()
    tagraw=raw('tags',tags,'tags_and_wiki');records=[tagraw]
    scopes={}
    for name,edges in [('A',[]),('B',[{'id':2,'antecedent_name':'B','consequent_name':'C','status':'active'}]),
                       ('C',[{'id':3,'antecedent_name':'C','consequent_name':'A','status':'active'}])]:
        scopes[name]=raw(name,edges,'outgoing_alias_scope',tag_scope=name)
    records.extend(scopes[n] for n in (('C','B','A') if reverse else ('A','B','C')))
    (reports/'native-acquisition.json').write_text(json.dumps({'status':'SCOPED_COMPLETE','records':records}),encoding='utf-8')
    (reports/'alias-acquisition.json').write_text(json.dumps({'status':'SCOPED_COMPLETE','records':[]}),encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['compiler','--out','compiled']);tool('p3_compile_inputs').main()
    projections=[json.loads(t) for t in Path('compiled/native.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(r.get('relation')=='wiki_tag' for r in projections)
    assert not any(r.get('matched_by')=='wiki_name' for r in projections)
    sid='danbooru-native-scoped-'+tagraw['sha256'][:12]
    def proof(role,r,eid,**extra):
        return dict(role=role,source_id=sid,evidence_id=eid,raw_path=r['raw_path'],raw_sha256=r['sha256'],
                    fetched_at_utc='owner-fetch',**extra)
    quarantines={name:proof('wiki_association_quarantined',tagraw,'wiki-quarantine:'+str(wid),
        wiki_key=key(str(wid),'page','danbooru.wiki'),tag_key=key(name),reason='mixed_cut_version_conflict',
        old_source_id='old-owner-wiki',old_input_sha256=oldsha,old_line=line,
        old_updated_at='old-'+name,live_updated_at='new-'+name)
        for name,wid,line in [('A',9,1),('C',19,2)]}
    chains={}
    for name,path in [('A',['A']),('B',['B','C','A']),('C',['C','A'])]:
        chain=[proof('native_identity',tagraw,'native:1',tag_id=1)]
        for start,end in pairwise(path):
            aid=2 if start=='B' else 3
            chain.append(proof('official_alias_step',scopes[start],'official_alias:'+str(aid),alias_id=aid,
                               antecedent_name=start,consequent_name=end,upstream_status='active'))
        for step in path:
            chain.append(proof('canonical_scope',scopes[step],'scope:'+step,name=step,
                               coverage='scoped_complete',active_alias_ids=[] if step=='A' else [2 if step=='B' else 3]))
        # Native transit C retains its own observed C/Wiki19 origin proof locally.
        # It must also receive actual terminal A/Wiki9, never spread C to A or B.
        if name=='C':chain.append(quarantines['C'])
        chain.append(quarantines['A']);chains[name]=chain
    entities=[{'key':key('B'),'status':'source_backed'}]
    links=[]
    for name in ('heroA','heroB','heroC'):
        dst=name[-1];entities.append({'key':key(name,'character','fixture.character'),'status':'source_backed'})
        links.append({'record_type':'link','src':key(name,'character','fixture.character'),'dst':key(dst),
            'relation':'entity_tag','method':'explicit_cross_source_link','verification_status':'verified',
            'evidence_refs':[{'role':'cross_source_id_link','src':key(name,'character','fixture.character'),
                'dst':key(dst),'source_id':'fixture-v1','evidence_id':'cross:'+name,'raw_sha256':'c'*64}]})
    builder=tmp_path/'builder';builder.mkdir();path=manifest(builder,pages+entities+projections+links)
    value=json.loads(path.read_text());value['p3_resolver_version']='1';path.write_text(json.dumps(value))
    receipt=build(path,builder/'published');assert receipt['verification']['ok']
    sh=value['sources'][0]['local_sha256']
    eids={link['src']['value']:f'fixture-v1:{sh}:line:{len(pages)+len(entities)+len(projections)+i+1}'
          for i,link in enumerate(links)}
    return builder/'published/knowledge.sqlite',receipt['snapshot'],chains,links,projections,eids


def owner_expected(snapshot,name,exact,chains,links,eids):
    entity=name.startswith('hero');endpoint=name[-1] if entity else name
    kind='character' if entity else 'tag';namespace='fixture.character' if entity else 'danbooru.tag'
    want=expected(snapshot,name,'resolved',tag='A',canonical='canonical',
                  matched='entity_tag' if entity else 'official_alias' if name=='B' else 'native_exact',
                  source=key(name,kind,namespace) if exact else None)
    want['evidence_chain']=list(chains[endpoint])
    if entity:
        link=next(r for r in links if r['src']['value']==name)
        want['evidence_chain'].append({'role':'entity_tag','source_id':'fixture-v1','evidence_id':eids[name],'link':link})
    return want,kind,namespace


@pytest.mark.parametrize('name,exact',PATHS)
@pytest.mark.parametrize('reverse',[False,True])
def test_native_alias_quarantine_owner_full_json(binary,tmp_path,monkeypatch,name,exact,reverse):
    db,snapshot,chains,links,projections,eids=owner_fixture(tmp_path,monkeypatch,reverse)
    want,kind,namespace=owner_expected(snapshot,name,exact,chains,links,eids)
    args=['--key','--kind',kind,'--namespace',namespace] if exact else []
    assert run(binary,db,name,*args)==want
    assert tool('p3_resolver_oracle').result(db,name,kind=kind if exact else None,
                namespace=namespace if exact else None,exact=exact)==want
    for spelling in ('A','B','C'):
        projection=next(r for r in projections if r.get('record_type')=='tag_resolution' and r['name']==spelling)
        assert projection['target']==key('A') and projection['evidence_chain']==chains[spelling]
