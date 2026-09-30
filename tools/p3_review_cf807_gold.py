"""Freeze revised55real cases from existing raw/input evidence, never resolver output."""
import hashlib
import json
from pathlib import Path

from p3_evidence import save

from sakura_knowledge.storage import digest


def main():
    oldpath=Path('reports/P3/real-gold-cases.json')
    original=json.loads(oldpath.read_text(encoding='utf-8'))
    cases=original['cases']
    acquisition=json.loads(Path('reports/P3/native-acquisition.json').read_text(encoding='utf-8'))
    raw=next(r for r in acquisition['records'] if r['role']=='tags_and_wiki')
    assert digest(raw['raw_path'])==raw['sha256']
    tags={t['name']:t for t in json.loads(Path(raw['raw_path']).read_text(encoding='utf-8'))}
    compilation=json.loads(Path('reports/P3/v2-input-compilation.json').read_text(encoding='utf-8'))
    compatible={x['tag']:x for x in compilation['compatible_wiki_links']}
    quarantines={x['tag']:x for x in compilation['wiki_conflicts_quarantined']}
    def key(value,kind='tag',namespace='danbooru.tag'):
        return {'kind':kind,'namespace':namespace,'value':value}
    def add(query,expected,**options):
        cases.append(dict(id=f'G{len(cases)+1:02}',query=query,expected=expected,**options))
    queue=[json.loads(line) for line in Path('reports/P3/v2-candidates.jsonl').read_text(encoding='utf-8').splitlines()]
    candidate=next(x for x in queue if x['src']==key('265','subject','bangumi.subject')
                   and x['dst']==key('neon_genesis_evangelion'))
    add('265',{'status':'entity_found_tag_unmapped','tag_key':None,'descriptions_empty':True},
        kind='subject',namespace='bangumi.subject',exact=True,
        source_expectation={'candidate_id':candidate['candidate_id'],'candidate_status':candidate['status'],
                            'queue_sha256':digest('reports/P3/v2-candidates.jsonl'),'dst':candidate['dst']})
    # Every source-backed character alias match from the immutable selected inputs,
    # not from runtime lookup or the compiled resolver table.
    matches=[]
    for path in Path('build/p3-inputs-v2').glob('pilot-*.jsonl'):
        for text in path.read_text(encoding='utf-8').splitlines():
            row=json.loads(text);k=row['key']
            if k['kind']=='character' and (k['value']=='初音未来' or any(a.get('text')=='初音未来' and a.get('status')=='source_backed' for a in row.get('aliases',[]))):
                matches.append(k)
    matches=sorted(matches,key=lambda k:tuple(k[n] for n in ('kind','namespace','value')))
    assert len(matches)==4 and all(k['namespace']=='moegirl.character' for k in matches)
    add('初音未来',{'status':'entity_ambiguous','tag_key':None,'candidates':matches,'descriptions_empty':True},kind='character')
    extension=json.loads(Path('reports/P3/alias-acquisition.json').read_text(encoding='utf-8'))
    for name in ('haruhi_suzumiya','soryu_asuka_langley'):
        scope=next(r for r in extension['records'] if r.get('tag_scope')==name)
        aliases=json.loads(Path(scope['raw_path']).read_text(encoding='utf-8'))
        # Raw retired/deleted alias endpoints do not create native identity, even
        # though a Wiki multilingual-name spelling separately exists.
        assert aliases and all(a['status']!='active' for a in aliases) and name not in tags
        add(name,{'status':'canonical_unknown','tag_key':None,'descriptions_empty':True,
                  'unresolved_reasons':[{'name':name,'matched_by':'official_alias','reason':'missing_native_terminal'}],
                  'evidence_assertions':[{'role':'canonical_scope','evidence_id':'scope:'+name,'raw_sha256':scope['sha256']}]},
            source_expectation={'scope_raw_sha256':scope['sha256'],'inactive_alias_ids':[a['id'] for a in aliases]})
    add('ijichi_nijika',{'status':'resolved','tag_key':key('ijichi_nijika'),'matched_by':'native_exact'})
    for case in cases:
        expected=case['expected'];target=expected.get('tag_key')
        if not target:continue
        name=target['value']
        if name in quarantines:
            conflict=quarantines[name]
            expected['descriptions_empty']=True
            expected.pop('description',None)
            expected['evidence_assertions']=[{'role':'wiki_association_quarantined','tag_key':key(name),
                'reason':conflict['reason'],'old_updated_at':conflict['old_updated_at'],
                'live_updated_at':conflict['new_updated_at'],'raw_sha256':raw['sha256']}]
            case['source_expectation']={'quarantine_report_sha256':digest('reports/P3/v2-input-compilation.json'),'wiki_id':conflict['wiki_id']}
        elif name in compatible:
            wiki=tags[name]['wiki_page'];wkey=key(str(wiki['id']),'page','danbooru.wiki')
            bodysha=hashlib.sha256(wiki['body'].encode('utf-8')).hexdigest()
            expected['description']=True
            expected['evidence_assertions']=[{'role':'wiki_tag_link','tag_key':key(name),'wiki_key':wkey,
                'tag_id':tags[name]['id'],'wiki_id':wiki['id'],'raw_sha256':raw['sha256']},
                {'role':'wiki_cut_compatibility','tag_key':key(name),'wiki_key':wkey,
                 'old_updated_at':wiki['updated_at'],'live_updated_at':wiki['updated_at'],'body_sha256':bodysha},
                {'role':'wiki_association_edge','src':wkey,'dst':key(name)},
                {'role':'description','wiki_key':wkey,'tag_key':key(name)}]
    assert len(cases)==55
    save('reports/P3/review-cf807-real-gold.json',dict(original,cases=cases,
         protocol='55 raw/input expected cases declared before repaired runtime acceptance; existing50preserved in oldfile',
         parent_gold_sha256=digest(oldpath),review_baseline='cf807c1a5179ce4b451b9a85870b6684d2dccaf3',
         added_real_coverage=['candidate-only actualBGM265','entity_ambiguous fourcharacterkeys',
                              'two missing native terminals','two changedWiki explicitemptydescriptions+quarantineproof'],
         new_upstream_GETs=0,verified_entity_tag_positives=0))
    print(json.dumps({'cases':55,'verified_entity_tag_positive':0,'network':False}))


if __name__=='__main__':main()
