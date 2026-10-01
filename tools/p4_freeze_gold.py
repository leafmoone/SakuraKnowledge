"""Create exclusive DRAFT gold from directly inspected source documents, not hits.

Requires the parent's whole-file PASS receipt. Does not freeze/commit the result.
No model, network, retrieval ranking, or database writes.
"""
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'build/p3-full-authorized-retry1/knowledge.sqlite'
SEED = 'p4-gold-source-inspection-v1'

# Hash-preselected first twenty per available family, then directly read by author.
# Fields: document ID, inspected original language, same-language paraphrase,
# description translation (first fifteen per family used).
AUTHORED = [
(755558,'ja','助けてもらった主人公を大魔法使いだと思い、秘書のようについてくる内気なサキュバス。','A shy succubus treats her rescuer as a great wizard and acts as his unsolicited secretary.'),
(649507,'ja','子供の父親をめぐる告白で別れを告げられ、潔白のためDNA検査を決める斎。','After a paternity revelation and an abrupt breakup, Itsuki decides on a DNA test to prove his innocence.'),
(538967,'ja','雷で命を落とした工作好きの男が異世界で地球の製造技術を閲覧する能力を得る話。','A hobbyist maker dies in a lightning strike and gains access to Earth manufacturing knowledge in another world.'),
(940004,'en','Which American animation writer co-created Gargoyles and published Rain of the Ghosts in 2013?','哪位美国动画编剧参与创作了Gargoyles，并在2013年出版小说Rain of the Ghosts？'),
(89355,'ja','高校野球の準々決勝前、先輩から夏を譲れと言われた選手が、仲間の騎手になる夢を耳にする巻。','A baseball player is asked to give up his summer by a former senior and overhears a teammate planning to become a jockey.'),
(136234,'ja','魔理沙とアリスを主題にした、七曲と小説で夏を描くLapis mossの第二弾。','The second Lapis moss novel-and-CD release tells a summer story about Marisa and Alice through seven songs.'),
(216,'zh','夏末少女接连从废楼坠亡，两仪式以能看见死线的眼睛调查其中关联。','At summer’s end, Shiki investigates apparently unrelated girls jumping from a ruined building, using eyes that see lines of death.'),
(334063,'ja','交際一周年が近い秘密の社内カップルが、同僚とのキャンプで関係を公表したくなる巻。','A secret workplace couple approaches their first anniversary and considers telling colleagues during a camping trip.'),
(785252,'ja','十五歳で修士課程に在籍し、ザイファのAIを使った導力ドローンを研究する銀髪の少年。','A silver-haired fifteen-year-old master’s student researches orbal drones using Xipha AI.'),
(662262,'en','A mouse-controlled first-person 2D action game in Estalia where the player assists the saint Clarisse.','在只有女性的异世界Estalia帮助圣女Clarisse，以鼠标操作攻击、防御和闪避的第一人称二维动作游戏。'),
(543100,'zh','复员军人广能昌三在狱中结识若杉宽，出狱后加入山守组卷入帮派争斗。','A demobilized soldier befriends Wakasugi in prison, joins Yamamori’s gang after release, and becomes entangled in gang warfare.'),
(450048,'ja','明代最後の暗殺者の復讐が、現代横浜の少女の遺伝子に残る記憶として描かれる第二巻。','A Ming-era assassin’s revenge survives as ancestral memories in a modern Yokohama girl undergoing treatment.'),
(279865,'zh','大小姐出钱组建高校电竞战队，经理还把自己的青梅竹马拉进队伍的故事。','A wealthy young woman funds a college esports team, and its manager recruits his childhood friend to fill the roster.'),
(952195,'zh','出生群马、毕业多摩美术大学，以写实又梦幻的少女油画知名的白日会画家。','A Gunma-born Tama Art University graduate and Hakujitsukai painter known for realistic yet dreamlike oil portraits of girls.'),
(620931,'ja','隣国でパン屋を営む元公爵令嬢が殺人事件を解いたため、王位を狙う第二王子に謎を持ち込まれる。','A former duke’s daughter runs a bakery abroad, solves a murder, and attracts a second prince who brings her mysteries to advance his claim to the throne.'),
(187379,'ja','Old SchoolとRaveをテーマに、Remo-conをゲストに迎えたwavformeのコンピレーション。',''),
(806574,'ja','姉の深雪とは別の大学に通い、同窓会で晴彦と再会した十八歳のボーイッシュな少女。',''),
(254472,'ja','自殺を禁じる新法ができた日本で、死を望む人をどんな手段でも救う執行者の物語。',''),
(84485,'ja','ルパンとコナンの映画用新曲を二枚のCDに収めた、大野雄二と大野克夫の共同サントラ。',''),
(155034,'ja','学校一の美男子が突然スカートで登校し、ヨーコは親しくなるほど彼への恋心を強める。',''),
(2912335,'en','The outfit worn by Fate’s Ibuki Douji at her third ascension.','Fate中伊吹童子第三次灵基再临时穿着的服装。'),
(2978292,'en','The American perpetrator named Micah Xavier Johnson in the Dallas police shooting account.','达拉斯警察枪击事件条目中名为Micah Xavier Johnson的美国行凶者。'),
(2874017,'en','Handheld poles used by a skier for control and gaining momentum.','滑雪时手持、帮助控制方向或增加动力的杆子。'),
(2715988,'en','A dark clothing style drawing on Victorian and Elizabethan looks, often using black, lace and rich contrasting colors.','借鉴维多利亚和伊丽莎白时代元素，以黑色、蕾丝及鲜艳深色对比为特点的阴郁服饰风格。'),
(2861876,'en','An extinct Ordovician jawless fish whose awkward Helsinki museum reconstruction became an internet meme.','因赫尔辛基自然史博物馆复原模型在网上走红的奥陶纪无颌鱼类。'),
(2825804,'en','A dress decorated with laces or ribbons crossing over one another.','绑带、细绳或缎带交叉穿系的连衣裙。'),
(2905289,'en','A Hitoka hitomoku Synthesizer V song featuring the SV version of Kasane Teto.','Hitoka hitomoku创作、由Synthesizer V版本重音Teto演唱的歌曲。'),
(2962022,'en','Sitting in the space between another person’s spread legs rather than directly on their lap.','不是直接坐在大腿上，而是坐在另一个人张开的双腿之间。'),
(2887887,'en','The Final Gear character with short curls, aqua eyes, a burger hair ornament and blue roller skates.','Final Gear中短卷发、水色眼睛、戴汉堡发饰并穿蓝色轮滑鞋的角色。'),
(2733127,'en','The Tales of the Abyss monster tamer raised by Ligers who resents Anise over Ion.','深渊传说中被Liger养大、因Ion而怨恨Anise的驯兽师。'),
(2798945,'en','Red-colored sleeves that are detached or contrast with the rest of the outfit.','红色袖子，须是独立袖套或与衣服其余部分颜色不同。'),
(2751418,'en','Nyorori’s nineteen-year-old original pink-haired girl with a side ponytail and purple eyes.','Nyorori创作的十九岁原创女孩，粉色侧马尾、紫色眼睛。'),
(2843752,'en','Special Week’s main-story finale skin whose star fragments require Goddess Statues.','特别周主线故事终章登场、需用女神像购买升星碎片的特殊服装。'),
(2777726,'en','National Pokédex 538: a bulky red humanoid Fighting-type wearing a white martial arts uniform and black belt.','全国图鉴538号，红色皮肤、体型粗壮、穿白色道服系黑带的格斗属性宝可梦。'),
(2866018,'en','A Splatoon roller weapon styled after a soda cup and drinking straw.','外形像汽水杯和吸管的Splatoon滚筒类主武器。'),
(2732392,'en','A business financially supports a team in return for its logo being displayed on clothing or equipment.',''),
(2851730,'en','Azur Lane Chao Ho’s official alternate costume called Frolicking Flowers Verse II.',''),
(2809403,'en','The US airborne division nicknamed Screaming Eagles that painted playing-card symbols on helmets for D-Day.',''),
(2718256,'en','An M de Pink game with characters Karasawa Mika and Igarashi Kasumi.',''),
(2915584,'en','The independent virtual YouTuber with the channel handle kanade_biscotte.',''),
]
PAIRS = [
(2874017,2874015,'skiing equipment', 'Equipment used for skiing; poles and boards are distinct eligible examples.'),
(2874015,2874016,'gear attached at a skier’s feet','Boards and boots both participate in the described ski binding arrangement.'),
(2825804,2813176,'clothing with crisscross lacing','Dress and skirt both explicitly have crossing laces.'),
(2825804,2733157,'crossing patterns on clothing','Laced dress and X-shaped halter are two explicit constructions.'),
(2962022,2723901,'sitting close to another person’s legs','Between-legs and on-lap are distinct positions, not equivalent identities.'),
(2962022,2743005,'between legs','A seated person and the general object/body-part placement both support this underspecified phrase.'),
(2798945,2798946,'colored detached sleeves','Red and blue sleeves each permit detached sleeves.'),
(2777726,2777727,'male Fighting Pokémon with a black belt','Throh and Sawk each explicitly satisfy these properties.'),
(2715988,2964630,'goth clothing styles','General goth and military goth are a broad category and subtype, both acceptable for this broad query.'),
(2732392,2719194,'brands displayed in advertising','Paid sponsorship and product placement both concern displayed brands; neither implies the other identity.'),
]


def connect():
    if Path(str(DB) + '-journal').exists():
        raise ValueError('rollback journal present')
    wal = Path(str(DB) + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('nonempty WAL')
    c = sqlite3.connect(DB.as_uri() + '?mode=ro&immutable=1', uri=True)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    return c


def build():
    receipt = json.loads((ROOT / 'reports/P4/initial-snapshot-check.json').read_text(encoding='utf-8'))
    baseline = json.loads(receipt['stdout'])
    assert receipt['status'] == baseline['status'] == 'PASS'
    assert DB.stat().st_size == baseline['bytes']
    assert DB.stat().st_mtime_ns == baseline['mtime_ns']
    before = DB.stat()
    c = connect()
    ids = {r[0] for r in AUTHORED} | {x for a,b,_,_ in PAIRS for x in (a,b)}
    docs = {}
    for did in sorted(ids):
        row = c.execute('''SELECT d.*,e.kind,e.namespace,e.value,e.conflicted FROM documents d
            JOIN entries e ON e.id=d.entry_id WHERE d.id=?''', (did,)).fetchone()
        assert row and not row['conflicted'] and row['kind'] != 'episode'
        assert row['status'] in ('source_backed','generated_from_evidence')
        identity = c.execute("SELECT source_id,evidence_id FROM entry_evidence WHERE entry_id=? AND status='source_backed' ORDER BY id LIMIT 1", (row['entry_id'],)).fetchone()
        assert identity
        docs[did] = dict(row)
        docs[did]['identity_evidence'] = dict(identity)
    # Membership-only scan; no MATCH, ranking or retrieval results.
    members = set()
    for row in c.execute('SELECT document_id,entry_id FROM search_fts'):
        did = int(row[0])
        if did in docs and int(row[1]) == docs[did]['entry_id']:
            members.add(did)
    assert members == ids
    langs = {r[0]:r[1] for r in AUTHORED}
    def anchor(did):
        d = docs[did]
        text = d['original']
        return {'document_id': did, 'entry_id': d['entry_id'],
                'entry_key': {k: d[k] for k in ('kind', 'namespace', 'value')},
                'source_id': d['source_id'], 'evidence_id': d['evidence_id'],
                'identity_evidence': d['identity_evidence'], 'title': d['title'],
                'source_language': langs.get(did, 'en'), 'stored_language': d['language'],
                'language_uncertainty': 'Author-inferred from inspected passage; stored language is null; titles/markup may mix languages.',
                'excerpt': text[:min(650, len(text))], 'excerpt_field': 'original', 'excerpt_start': 0,
                'document_text_sha256': hashlib.sha256((d['title']+'\n'+text).encode('utf-8')).hexdigest(),
                'original_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
    cases = []
    def add(subset, query, qlang, targets, negatives=(), **extra):
        assert query and not set(targets) & set(negatives)
        cases.append(dict(case_id=f'P4-{len(cases)+1:03d}', subset=subset, query=query,
                          query_language=qlang, accepted_targets=[anchor(i) for i in targets],
                          candidate_hard_negative_document_ids=list(negatives), **extra))
    hard = {}
    for a,b,_,reason in PAIRS:
        hard.setdefault(a,[]).append(b)
        hard.setdefault(b,[]).append(a)
    chosen = AUTHORED[:15] + AUTHORED[20:35]
    for did,lang,_,_ in chosen:
        title = docs[did]['title']
        qlang = 'ja' if any('\u3040' <= x <= '\u30ff' for x in title) else ('zh' if any('\u4e00' <= x <= '\u9fff' for x in title) else 'en')
        add('lexical', title, qlang, [did], hard.get(did,()), query_language_uncertainty='Script-based for names; Latin names may not be English.')
    for did,lang,query,_ in AUTHORED:
        add('semantic',query,lang,[did],hard.get(did,()))
    for did,lang,_,query in chosen:
        add('crosslingual',query,'en' if lang in ('zh','ja') else 'zh',[did],hard.get(did,()),translation_basis='Original description, not title-only translation.')
    for a,b,query,reason in PAIRS:
        add('ambiguous/negative',query,'en',[a,b],case_type='source_supported_ambiguity',label_reason=reason,accepted_set_scope='Two explicitly inspected supported targets; not a claim of exhaustive corpus relevance.')
    negatives = [
        ('en','Show the current balance of my private checking account.'),
        ('en','Track my unprovided parcel number and give its live GPS location.'),
        ('en','What is tomorrow’s exact closing price for my unnamed stock?'),
        ('en','Identify the fictional entry with UUID P4-NOIDENTITY-6f3b8d2a.'),
        ('zh','请读取我未提供的私人病历并给出今天的化验结果。'),
        ('zh','查询我家此刻智能电表的实时读数。'),
        ('zh','找出标识符P4-虚构对象-91ac7e对应的已验证人物。'),
        ('ja','私の未公開の銀行口座の現在残高を教えてください。'),
        ('ja','番号を提示していない私の荷物の現在位置を特定してください。'),
        ('ja','P4-架空識別子-c0842fに対応する検証済み作品を断定してください。'),
    ]
    for lang,query in negatives:
        add('ambiguous/negative',query,lang,[],case_type='constructed_no_identity',
            label_reason='Constructed private/live/unprovided-data request or invented identifier, not a supplied source identity. No exhaustive no-relevant-document claim.',
            expected_behavior='Do not assert a verified identity from semantic proximity; related topical candidates may occur.',ranking_metrics='N/A')
    counts = dict(Counter(x['subset'] for x in cases))
    assert counts == {'lexical':30,'semantic':40,'crosslingual':30,'ambiguous/negative':20}
    report = {'schema_version': 'p4-source-gold-v1', 'status': 'DRAFT_PRE_EMBEDDING',
        'base_snapshot_sha256': baseline['sha256'], 'base_snapshot_bytes': baseline['bytes'],
        'baseline_receipt': 'reports/P4/initial-snapshot-check.json',
        'document_text_hash_contract': 'SHA256(UTF8(title + LF + original)); no normalization',
        'subset_counts': counts, 'selection': {'seed': SEED,
            'rule': 'Distinct trusted FTS-member documents with original length 120..6000 and no U+FFFD in title/original; first 20 per available source family by ascending SHA256(seed + colon + decimal document_id).',
            'deliberate_additions': 'Ten related Danbooru documents selected through direct inspection of source cross-references for ambiguity and hard negatives.',
            'reuse': '30 lexical and 30 description translations reuse targets from 40 semantic cases; cases are not independent entity samples.'},
        'limitations': [
            'Engineering gold authored by an implementation agent from inspected source passages, NOT full human source-fact review. Parent review/hash/commit required before freeze.',
            'Coverage blocker: this snapshot has no Moegirl documents. Local tag documents are only no_reference or unverified_draft at document.status, even when embedded JSON claims source_backed. They are excluded, never promoted. Therefore required Moegirl/local-tag trusted target coverage is unavailable.',
            'All document.language fields inspected are null; language labels are inferred, mixed scripts and proper-name ambiguity remain.',
            'Only original prefixes through 1100 characters were inspected during authoring; anchors retain up to 650 characters, not entire copyrighted documents.',
            'Candidate hard negatives are related topics, not universally proven irrelevant; broad queries can make them relevant. No retrieval runs used.',
            'Accepted sets are source-supported engineering choices, not exhaustive judgments over millions of documents.',
            'Receipt hash is inherited from the immediately preceding parent whole-file check; this authoring command checks size/mtime and sidecars, not a fresh whole hash.',
            'No embeddings, vector queries, model downloads or retrieval-ranked selections executed. Queries must not change after embedding measurements.'
        ],
        'candidate_hard_negatives': [{'document_id': b, 'anchor': anchor(b),
                                     'related_target_document_id': a, 'inspection_reason': reason}
                                    for a,b,_,reason in PAIRS],
        'cases': cases}
    c.close()
    after = DB.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    out = ROOT / 'reports/P4/retrieval-gold.json'
    with out.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps({'status':report['status'],'counts':counts,'documents':sorted(ids),'output':str(out)},ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    build()
