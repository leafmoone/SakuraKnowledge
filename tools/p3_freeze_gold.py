"""Predeclare50 raw-source behavior cases without invoking a resolver/oracle."""
import json
from pathlib import Path

from p3_evidence import save

from sakura_knowledge.storage import digest


def main():
    acquisition=json.loads(Path('reports/P3/native-acquisition.json').read_text(encoding='utf-8'))
    raw=next(x for x in acquisition['records'] if x['role']=='tags_and_wiki')
    if digest(raw['raw_path'])!=raw['sha256']:raise ValueError('raw mismatch')
    tags=json.loads(Path(raw['raw_path']).read_text(encoding='utf-8'))
    target=json.loads(Path('reports/P3/target_manifest.json').read_text(encoding='utf-8'))
    compatible={x['tag'] for x in json.loads(Path('reports/P3/v2-input-compilation.json').read_text(encoding='utf-8'))['compatible_wiki_links']}
    by_name={t['name']:t for t in tags}
    cases=[]
    def tagkey(name):return {'kind':'tag','namespace':'danbooru.tag','value':name}
    def add(query,status='resolved',tag=None,matched=None,description=False,**options):
        expected={'status':status,'tag_key':tagkey(tag) if tag else None}
        if matched:expected['matched_by']=matched
        if description:expected['description']=True
        cases.append(dict(id=f'G{len(cases)+1:02}',query=query,expected=expected,**options))
    for t in target['targets'][:20]:
        name=t['title'];assert name in by_name
        add(name,tag=name,matched='native_exact',description=name in compatible)
    chinese=[('后藤一里','gotoh_hitori'),('喜多郁代','kita_ikuyo'),('孤独摇滚','bocchi_the_rock!'),
             ('阿尔托莉雅','artoria_pendragon_(fate)'),('拉姆','ram_(re:zero)'),('雷姆','rem_(re:zero)'),
             ('鹿目圆','kaname_madoka'),('晓美焰','akemi_homura'),('魔法少女小圆','mahou_shoujo_madoka_magica'),
             ('樱初音','sakura_miku'),('远坂凛','tohsaka_rin'),('巡音流歌','megurine_luka'),
             ('镜音连','kagamine_len'),('镜音铃','kagamine_rin'),('初音未来','hatsune_miku')]
    for name,tag in chinese:
        assert tag in compatible and name in by_name[tag]['wiki_page']['other_names']
        add(name,tag=tag,matched='wiki_name',description=True,script_group='Chinese-characters; language field remains unknown')
    add('puella_magi_madoka_magica',tag='mahou_shoujo_madoka_magica',matched='official_alias',description=True)
    for query in ('ぼ喜多','madohomu','镜音リンレン','鏡音','ネギトロ'):
        names=sorted(t['name'] for t in tags if t['name'] in compatible and query in t['wiki_page']['other_names'])
        assert len(names)>1
        add(query,status='tag_ambiguous')
        cases[-1]['expected']['candidates']=[tagkey(n) for n in names]
    add('初音未来',status='entity_found_tag_unmapped',kind='character',namespace='moegirl.character',exact=True)
    add('hatsune_miku',status='entity_found_tag_unmapped',kind='tag',namespace='local.tag_aggregate',exact=True)
    add('puella_magi_madoka_magica',status='not_found',category=4)
    add('5655',status='entity_found_tag_unmapped',kind='page',namespace='danbooru.wiki',exact=True)
    add('hatsune_miku',status='not_found',kind='character',namespace='moegirl.character',exact=True)
    add('151534',status='entity_found_tag_unmapped',kind='page',namespace='danbooru.wiki',exact=True)
    add('konpaku_youmu',tag='konpaku_youmu',matched='native_exact')
    add('hatsune_miku',status='not_found',category=3)
    add('madoka_kaname',tag='kaname_madoka',matched='wiki_name',description=True)
    assert len(cases)==50
    save('reports/P3/real-gold-cases.json',{'protocol':'raw-source behavior frozen before any real resolver acceptance',
         'raw_native_sha256':raw['sha256'],'target_manifest_sha256':digest('reports/P3/target_manifest.json'),
         'cases':cases,'limitations':['50scoped queries, not fullsource recall or universal name ownership',
             '15Chinese-script positive names from officialWiki under proven nativeidentity; not humantranslations',
             '2changed Wiki versions quarantined; native direct stillexists, no oldWiki identity upgrade',
             'No verified entity_tag real positives: cross-source ID/link evidence missing; these remain unmapped',
             'inactive official aliases never redirect; G50 separately resolves via explicit compatibleWiki name'],
         'verified_entity_tag_positives':0,'chinese_positive_denominator':15})
    print(json.dumps({'cases':50,'Chinese_positive':15,'verified_entity_tag_positive':0}))


if __name__=='__main__':main()
