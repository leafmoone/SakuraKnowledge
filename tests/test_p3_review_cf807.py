"""Independent expected counterexamples for the cf807c1 review, normal builder."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_core import manifest
from test_p3_resolver import expected, key, run
from test_rust_repair import binary as rust_binary_fixture

from sakura_knowledge.storage import build

binary = rust_binary_fixture
TOOLS = Path(__file__).parents[1]/'tools'
sys.path.insert(0,str(TOOLS))


def tool(name):
    spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def endpoint_fixture(tmp_path):
    proof=[{'role':role,'source_id':'fixture-v1','evidence_id':'A-proof','raw_sha256':'a'*64}
           for role in ('native_identity','canonical_scope')]
    def projection(name,target,category,matched):
        return {'record_type':'tag_resolution','status':'source_backed','name':name,'target':key(target),
                'matched_by':matched,'canonical_status':'canonical','category':category,
                'rule_version':'danbooru-native-1','evidence_chain':proof,'evidence_id':name+':'+matched}
    link={'record_type':'link','src':key('hero','character','fixture.character'),'dst':key('A'),
          'relation':'entity_tag','method':'explicit_cross_source_link','verification_status':'verified',
          'evidence_refs':[{'role':'cross_source_id_link','src':key('hero','character','fixture.character'),
                            'dst':key('A'),'raw_sha256':'b'*64,'source_id':'fixture-v1','evidence_id':'bound-link'}]}
    rows=[{'key':key('A'),'status':'source_backed'}, {'key':key('B'),'status':'source_backed'},
          {'key':key('hero','character','fixture.character'),'status':'source_backed'},
          projection('A','A',4,'native_exact'),projection('B','B',3,'native_exact'),
          projection('A','B',3,'wiki_name'),link]
    path=manifest(tmp_path,rows)
    value=json.loads(path.read_text(encoding='utf-8'));value['p3_resolver_version']='1'
    path.write_text(json.dumps(value),encoding='utf-8')
    output=tmp_path/'normal-published'
    receipt=build(path,output)
    assert receipt['verification']['ok']
    return output/'knowledge.sqlite',receipt['snapshot'],proof,link


@pytest.mark.parametrize('source',['A','hero'])
@pytest.mark.parametrize('category',[None,3,4])
def test_known_endpoint_not_spelling_query(binary,tmp_path,source,category):
    db,snapshot,proof,link=endpoint_fixture(tmp_path)
    kind='tag' if source=='A' else 'character'
    namespace='danbooru.tag' if source=='A' else 'fixture.character'
    sourcekey=key(source,kind,namespace)
    status=('not_found' if source=='A' else 'entity_found_tag_unmapped') if category==3 else 'resolved'
    want=expected(snapshot,source,status,tag='A' if status=='resolved' else None,
                  matched=('native_exact' if source=='A' else 'entity_tag') if status=='resolved' else None,
                  canonical='canonical' if status=='resolved' else 'unknown',source=sourcekey,category=category)
    if status=='resolved':
        want['evidence_chain']=list(proof)
        if source=='hero':
            # Existing builder's fallback link evidence ID is intentionally bound.
            sid='fixture-v1'
            sourcehash=json.loads((tmp_path/'manifest.json').read_text())['sources'][0]['local_sha256']
            want['evidence_chain'].append({'role':'entity_tag','source_id':sid,
                'evidence_id':f'{sid}:{sourcehash}:line:7','link':link})
    args=['--key','--kind',kind,'--namespace',namespace]
    if category is not None:args.extend(['--category',str(category)])
    assert run(binary,db,source,*args)==want
    assert tool('p3_resolver_oracle').result(db,source,kind=kind,namespace=namespace,exact=True,category=category)==want


def compiler_fixture(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    report=Path('reports/P3');report.mkdir(parents=True)
    old=Path('build/real-full-7afe7fb');old.mkdir(parents=True)
    body='Original Wiki C body'
    old_page={'key':key('9','page','danbooru.wiki'),'status':'source_backed',
              'documents':[{'title':'C','original':body,'status':'source_backed'}],
              'raw':{'raw_page_metadata':{'id':9,'title':'C','updated_at':'cut1','other_names':['中文丙']}}}
    (old/'wiki.jsonl').write_text(json.dumps(old_page,ensure_ascii=False)+'\n',encoding='utf-8')
    oldsha=hashlib.sha256((old/'wiki.jsonl').read_bytes()).hexdigest()
    (old/'manifest.json').write_text(json.dumps({'sources':[{'source_id':'old-wiki','provider':'danbooru','path':'wiki.jsonl','local_sha256':oldsha}]}))
    def raw(name,value,role,**extras):
        path=report/(name+'.raw');path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        return dict(role=role,status='FROZEN',raw_path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    bytes=path.stat().st_size,fetched_at_utc='cut2',**extras)
    tags=[{'id':3,'name':'C','category':4,'is_deprecated':False,'wiki_page':{'id':9,'title':'C','body':body,
            'updated_at':'cut1','is_deleted':False,'other_names':['中文丙']}}]
    records=[raw('tags',tags,'tags_and_wiki')]
    for name,edges in [('A',[{'id':1,'antecedent_name':'A','consequent_name':'B','status':'active'}]),
                       ('B',[{'id':2,'antecedent_name':'B','consequent_name':'C','status':'active'}]),('C',[])]:
        records.append(raw(name,edges,'outgoing_alias_scope',tag_scope=name))
    (report/'native-acquisition.json').write_text(json.dumps({'status':'SCOPED_COMPLETE','records':records}))
    (report/'alias-acquisition.json').write_text(json.dumps({'status':'SCOPED_COMPLETE','records':[]}))
    monkeypatch.setattr(sys,'argv',['compile','--out','compiled'])
    tool('p3_compile_inputs').main()
    return [json.loads(x) for x in Path('compiled/native.jsonl').read_text(encoding='utf-8').splitlines()],oldsha


def test_compiler_every_hop_has_scope_proof(tmp_path,monkeypatch):
    rows,_=compiler_fixture(tmp_path,monkeypatch)
    a=next(r for r in rows if r.get('record_type')=='tag_resolution' and r['name']=='A')
    assert a['target']==key('C')
    scopes=[r['evidence_id'] for r in a['evidence_chain'] if r['role']=='canonical_scope']
    assert scopes==['scope:A','scope:B','scope:C']
    edges=[r for r in a['evidence_chain'] if r['role']=='official_alias_step']
    assert [(r['antecedent_name'],r['consequent_name']) for r in edges]==[('A','B'),('B','C')]


def test_compiler_description_proves_old_and_live_association(tmp_path,monkeypatch):
    rows,oldsha=compiler_fixture(tmp_path,monkeypatch)
    native=next(r for r in rows if r.get('record_type')=='tag_resolution' and r['name']=='C')
    association=next(r for r in native['evidence_chain'] if r['role']=='wiki_tag_link')
    assert association['wiki_key']==key('9','page','danbooru.wiki') and association['tag_key']==key('C')
    compatible=next(r for r in native['evidence_chain'] if r['role']=='wiki_cut_compatibility')
    assert compatible['old_input_sha256']==oldsha
    assert compatible['old_updated_at']==compatible['live_updated_at']=='cut1'
    assert compatible['body_sha256']==hashlib.sha256(b'Original Wiki C body').hexdigest()
    assert compatible['old_source_id']=='old-wiki' and compatible['old_line']==1


def test_runtime_description_association_and_unknown_reason(binary,tmp_path,monkeypatch):
    rows,_=compiler_fixture(tmp_path,monkeypatch)
    old=json.loads(Path('build/real-full-7afe7fb/wiki.jsonl').read_text(encoding='utf-8'))
    missing={'record_type':'tag_resolution','name':'missing','target':None,'status':'source_backed',
             'canonical_status':'unknown','matched_by':'official_alias','category':None,
             'rule_version':'danbooru-native-1','reason':'missing_native_terminal',
             'evidence_chain':[{'role':'canonical_scope','source_id':'fixture-v1','evidence_id':'missing-scope','raw_sha256':'c'*64}]}
    fixture_dir=tmp_path/'builder';fixture_dir.mkdir()
    path=manifest(fixture_dir,[old]+rows+[missing])
    value=json.loads(path.read_text());value['p3_resolver_version']='1';path.write_text(json.dumps(value))
    build(path,fixture_dir/'published')
    db=fixture_dir/'published/knowledge.sqlite'
    for query in ('C','A'):
        value=run(binary,db,query)
        assert value['descriptions'][0]['original']=='Original Wiki C body'
        refs=value['evidence_chain']
        assert any(p['role']=='wiki_tag_link' and p['tag_key']==key('C') and p['wiki_key']==key('9','page','danbooru.wiki') for p in refs)
        assert any(p['role']=='wiki_cut_compatibility' and p['old_updated_at']==p['live_updated_at']=='cut1' for p in refs)
        assert any(p['role']=='wiki_association_edge' and p['dst']==key('C') for p in refs)
        assert any(p['role']=='description' and p['source_id']=='fixture-v1' for p in refs)
        assert value==tool('p3_resolver_oracle').result(db,query)
    unknown=run(binary,db,'missing')
    want=expected(unknown['snapshot'],'missing','canonical_unknown',warnings=['canonical_evidence_incomplete'])
    want['evidence_chain']=missing['evidence_chain']
    want['unresolved_reasons']=[{'name':'missing','matched_by':'official_alias','reason':'missing_native_terminal'}]
    assert unknown==want==tool('p3_resolver_oracle').result(db,'missing')
