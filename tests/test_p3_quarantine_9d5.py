"""Independent raw->compiler->normal builder->full JSON quarantine counterexample."""
import hashlib
import json
import sys
from pathlib import Path

import pytest
from test_core import manifest
from test_p3_resolver import expected, key, run
from test_p3_review_cf807 import tool
from test_rust_repair import binary as rust_binary_fixture

from sakura_knowledge.storage import build

binary=rust_binary_fixture


def conflict_fixture(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    reports=Path('reports/P3');reports.mkdir(parents=True)
    old=Path('build/real-full-7afe7fb');old.mkdir(parents=True)
    page={'key':key('9','page','danbooru.wiki'),'status':'source_backed',
          'documents':[{'title':'C','original':'Unchanged source body','status':'source_backed'}],
          'raw':{'raw_page_metadata':{'id':9,'title':'C','updated_at':'old-cut','other_names':['丙']}}}
    oldbytes=(json.dumps(page,ensure_ascii=False)+'\n').encode('utf-8')
    (old/'wiki.jsonl').write_bytes(oldbytes)
    oldsha=hashlib.sha256(oldbytes).hexdigest()
    (old/'manifest.json').write_text(json.dumps({'sources':[{'source_id':'old-wiki','provider':'danbooru',
                                         'path':'wiki.jsonl','local_sha256':oldsha}]}),encoding='utf-8')
    def raw(name,value,role,**extras):
        path=reports/(name+'.raw')
        data=json.dumps(value,ensure_ascii=False).encode('utf-8');path.write_bytes(data)
        return dict(role=role,status='FROZEN',raw_path=str(path),sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data),fetched_at_utc='fetch-cut',**extras)
    tags=[{'id':3,'name':'C','category':4,'is_deprecated':False,'wiki_page':{
        'id':9,'title':'C','body':'Unchanged source body','updated_at':'new-cut',
        'is_deleted':False,'other_names':['丙']}}]
    tagraw=raw('tags',tags,'tags_and_wiki');records=[tagraw]
    for name,edges in [('A',[{'id':1,'antecedent_name':'A','consequent_name':'B','status':'active'}]),
                       ('B',[{'id':2,'antecedent_name':'B','consequent_name':'C','status':'active'}]),('C',[])]:
        records.append(raw(name,edges,'outgoing_alias_scope',tag_scope=name))
    (reports/'native-acquisition.json').write_text(json.dumps({'status':'SCOPED_COMPLETE','records':records}),encoding='utf-8')
    (reports/'alias-acquisition.json').write_text(json.dumps({'status':'SCOPED_COMPLETE','records':[]}),encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['compile','--out','compiled'])
    tool('p3_compile_inputs').main()
    rows=[json.loads(line) for line in Path('compiled/native.jsonl').read_text(encoding='utf-8').splitlines()]
    assert not any(r.get('relation')=='wiki_tag' for r in rows)
    assert not any(r.get('matched_by')=='wiki_name' for r in rows)
    sid='danbooru-native-scoped-'+tagraw['sha256'][:12]
    def proof(role,r,eid,**extra):
        return dict(role=role,source_id=sid,evidence_id=eid,raw_path=r['raw_path'],raw_sha256=r['sha256'],
                    fetched_at_utc='fetch-cut',**extra)
    quarantine=proof('wiki_association_quarantined',tagraw,'wiki-quarantine:9',wiki_key=key('9','page','danbooru.wiki'),
                     tag_key=key('C'),reason='mixed_cut_version_conflict',old_source_id='old-wiki',
                     old_input_sha256=oldsha,old_line=1,old_updated_at='old-cut',live_updated_at='new-cut')
    chains={}
    for name,index in [('A',0),('B',1),('C',2)]:
        chain=[proof('native_identity',tagraw,'native:3',tag_id=3)]
        for step in range(index,2):
            edge=('A','B','C')[step:step+2]
            chain.append(proof('official_alias_step',records[step+1],f'official_alias:{step+1}',
                               alias_id=step+1,antecedent_name=edge[0],consequent_name=edge[1],upstream_status='active'))
        for step in range(index,3):
            scope=('A','B','C')[step]
            chain.append(proof('canonical_scope',records[step+1],'scope:'+scope,name=scope,
                               coverage='scoped_complete',active_alias_ids=[step+1] if step<2 else []))
        chain.append(quarantine)
        chains[name]=chain
    # Alias endpoints exist as typed identities for explicit/verified-key paths;
    # all terminal assessments remain real compiler output, never hand patched.
    entities=[{'key':key(name),'status':'source_backed'} for name in ('A','B')]
    links=[]
    for name,dst in [('heroA','A'),('heroC','C')]:
        entities.append({'key':key(name,'character','fixture.character'),'status':'source_backed'})
        links.append({'record_type':'link','src':key(name,'character','fixture.character'),'dst':key(dst),
                      'relation':'entity_tag','method':'explicit_cross_source_link','verification_status':'verified',
                      'evidence_id':'bound:'+name,'evidence_refs':[{'role':'cross_source_id_link',
                        'src':key(name,'character','fixture.character'),'dst':key(dst),'source_id':'fixture-v1',
                        'evidence_id':'cross:'+name,'raw_sha256':'b'*64}]})
    builder=tmp_path/'builder';builder.mkdir()
    path=manifest(builder,[page]+entities+rows+links)
    value=json.loads(path.read_text(encoding='utf-8'));value['p3_resolver_version']='1'
    path.write_text(json.dumps(value),encoding='utf-8')
    published=builder/'published';receipt=build(path,published)
    assert receipt['verification']['ok']
    source_hash=value['sources'][0]['local_sha256']
    link_eids={link['src']['value']:f'fixture-v1:{source_hash}:line:{1+len(entities)+len(rows)+i+1}'
               for i,link in enumerate(links)}
    return published/'knowledge.sqlite',receipt['snapshot'],chains,links,rows,link_eids


@pytest.mark.parametrize('name,exact',[('A',False),('B',False),('C',False),
                                      ('A',True),('B',True),('C',True),('heroA',True),('heroC',True)])
def test_quarantine_exact_chain_survives_every_canonical_path(binary,tmp_path,monkeypatch,name,exact):
    db,snapshot,chains,links,rows,link_eids=conflict_fixture(tmp_path,monkeypatch)
    entity=name.startswith('hero')
    terminal_input=name[-1] if entity else name
    kind='character' if entity else 'tag';namespace='fixture.character' if entity else 'danbooru.tag'
    source=key(name,kind,namespace) if exact else None
    matched='entity_tag' if entity else 'native_exact' if name=='C' else 'official_alias'
    want=expected(snapshot,name,'resolved',tag='C',matched=matched,canonical='canonical',source=source)
    want['evidence_chain']=list(chains[terminal_input])
    if entity:
        link=next(r for r in links if r['src']['value']==name)
        want['evidence_chain'].append({'role':'entity_tag','source_id':'fixture-v1',
                                      'evidence_id':link_eids[name],'link':link})
    args=['--key','--kind',kind,'--namespace',namespace] if exact else []
    # Full independent expected: exact hash/source/keys/reason/unequal cuts, all
    # directed steps/scopes, docs=[], no compatible edge/placeholder role.
    assert run(binary,db,name,*args)==want
    oracle=tool('p3_resolver_oracle').result(db,name,kind=kind if exact else None,
                                          namespace=namespace if exact else None,exact=exact)
    assert oracle==want
    projection=next(r for r in rows if r.get('record_type')=='tag_resolution' and r['name']==terminal_input)
    assert projection['evidence_chain']==chains[terminal_input]
