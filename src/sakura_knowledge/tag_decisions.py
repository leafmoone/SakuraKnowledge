"""Offline replayable entity_tag decision validation, never runtime confidence promotion."""
from .model import EntryKey

FIELDS={'decision_id','src','dst','relation','decision','method','rule_version',
        'evidence_refs','reviewer_kind','reviewer_id','time','supersedes'}


def replay(decisions):
    seen={};active={}
    for d in decisions:
        if FIELDS-d.keys():
            raise ValueError('decision fields missing')
        ident=d['decision_id']
        if not isinstance(ident,str) or not ident or ident in seen:
            raise ValueError('duplicate/invalid decision ID')
        src,dst=EntryKey(**d['src']),EntryKey(**d['dst'])
        if d['relation']!='entity_tag' or dst.kind!='tag' or dst.namespace!='danbooru.tag':
            raise ValueError('typed entity_tag target required')
        if d['decision'] not in {'candidate','rejected','verified','revoked'}:
            raise ValueError('unknown decision')
        if d['reviewer_kind'] not in {'execution_agent','human','rule_validator'}:
            raise ValueError('unknown reviewer kind')
        if not all(d[k] for k in ('reviewer_id','time','rule_version','method')):
            raise ValueError('decision provenance required')
        if d['method']=='human_verified' and d['reviewer_kind']!='human':
            raise ValueError('agent self-review cannot be human_verified')
        if not isinstance(d['evidence_refs'],list):
            raise TypeError('decision evidence refs must be list')
        if d['decision']=='verified':
            if d['method']=='human_verified':
                if not d['evidence_refs']:
                    raise ValueError('human review requires cited scope/evidence')
            elif d['method']=='explicit_cross_source_link':
                refs=d['evidence_refs']
                if not any(r.get('role')=='cross_source_id_link' and r.get('src')==d['src']
                           and r.get('dst')==d['dst'] and r.get('raw_sha256')
                           and r.get('source_id') and r.get('evidence_id') for r in refs):
                    raise ValueError('deterministic mapping requires exact bound source ID/link evidence')
            else:
                raise ValueError('name/score/context/candidate is not verified identity evidence')
        supersedes=d['supersedes']
        pair=(src.parts(),dst.parts())
        if supersedes is not None:
            previous=seen.get(supersedes)
            if previous is None or (previous['src']!=d['src'] or previous['dst']!=d['dst']):
                raise ValueError('invalid decision supersedes')
            if active.get(pair,{}).get('decision_id')!=supersedes:
                raise ValueError('supersedes must point to current decision')
        elif pair in active:
            raise ValueError('replacement decision must explicitly supersede')
        seen[ident]=d;active[pair]=d
    return [d for _,d in sorted(active.items()) if d['decision']=='verified']


def normalized_links(decisions):
    return [{'record_type':'link','src':d['src'],'dst':d['dst'],'relation':'entity_tag',
             'method':d['method'],'verification_status':'verified','decision_id':d['decision_id'],
             'rule_version':d['rule_version'],'evidence_refs':d['evidence_refs'],
             'reviewer_kind':d['reviewer_kind'],'reviewer_id':d['reviewer_id'],'time':d['time']}
            for d in replay(decisions)]
