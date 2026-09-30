"""Independent offline acceptance oracle, never imported by Python production API.

This deliberately materializes small assessment sets and declaratively selects
keys before reading proofs. It does not call Rust or Python Runtime methods, nor
ETL graph assessment. Synthetic hard-coded cases and raw-source gold expectations
provide additional independent checks on compiled projection correctness.
"""
import json
import sqlite3
from pathlib import Path


def result(db, query, *, category=None, kind=None, namespace=None, exact=False, limit=20):
    conn=sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        snapshot=conn.execute("SELECT value FROM build_meta WHERE key='snapshot'").fetchone()[0]
        out={'contract_version':'2','response_version':'3','resolver_contract_version':'1','snapshot':snapshot,
             'query':query,'requested_namespace':'danbooru.tag','requested_category':category,
             'source_key':None,'status':'not_found','tag_key':None,'matched_by':None,'canonical_status':'unknown',
             'evidence_chain':[],'descriptions':[],'citations':[],'candidates':[],'candidates_truncated':False,
             'source_scope':[x[0] for x in conn.execute('SELECT source_id FROM sources ORDER BY source_id')],
             'warnings':[],'relations':[]}
        capability=conn.execute("SELECT value FROM build_meta WHERE key='p3_resolver_version'").fetchone()
        if capability is None or capability[0]!='1':
            return dict(out,status='unsupported',warnings=['p3_resolver_capability_absent'])
        def key(row):
            return {k:row[k] for k in ('kind','namespace','value')}
        def assessments(name,apply_category=True):
            rows=[dict(x) for x in conn.execute('SELECT * FROM tag_resolutions WHERE name=? ORDER BY id',(name,))]
            rows=[r for r in rows if not apply_category or category is None or r['category']==category]
            output=[]
            for r in rows:
                target=conn.execute("SELECT * FROM entries WHERE id=? AND kind='tag' AND namespace='danbooru.tag' AND conflicted=0",
                                    (r['target'],)).fetchone()
                if r['target'] is not None and (target is None or not conn.execute("SELECT 1 FROM entry_evidence WHERE entry_id=? AND status='source_backed'",(r['target'],)).fetchone()):
                    continue
                output.append(dict(r,target_row=target,proof=json.loads(r['payload'])))
            return sorted(output,key=lambda r:({'native_exact':0,'official_alias':1,'wiki_name':2}[r['matched_by']],
                                              r['target_row']['value'] if r['target_row'] else '',r['id']))
        chosen=[]
        if not (kind or namespace or exact):
            chosen=assessments(query)
            native=[x for x in chosen if x['matched_by'] in ('native_exact','official_alias')]
            chosen=native if native else chosen
            if not chosen and category is not None and assessments(query,False):
                return out
        if not chosen:
            identities={}
            for r in conn.execute('SELECT * FROM entries WHERE value=? AND conflicted=0',(query,)):
                identities[r['id']]=r
            if not exact:
                for r in conn.execute("SELECT e.* FROM aliases a JOIN entries e ON e.id=a.entry_id WHERE a.text=? AND a.status='source_backed' AND e.conflicted=0",(query,)):
                    identities[r['id']]=r
            trusted=sorted((r for r in identities.values() if (kind is None or r['kind']==kind)
                            and (namespace is None or r['namespace']==namespace)
                            and conn.execute("SELECT 1 FROM entry_evidence WHERE entry_id=? AND status='source_backed'",(r['id'],)).fetchone()),
                           key=lambda r:(r['kind'],r['namespace'],r['value']))
            if not trusted:
                return out
            if len(trusted)>1:
                return dict(out,status='entity_ambiguous',candidates=[{'entry_key':key(r)} for r in trusted[:limit]],
                            candidates_truncated=len(trusted)>limit)
            source=trusted[0]
            out.update(source_key=key(source),status='entity_found_tag_unmapped')
            if source['kind']=='tag' and source['namespace']=='danbooru.tag':
                chosen=assessments(source['value'])
                if category is not None and not chosen:
                    return dict(out,status='not_found')
            else:
                for link in conn.execute("SELECT l.*,e.value FROM links l JOIN entries e ON e.id=l.dst WHERE l.src=? AND l.relation='entity_tag' AND l.verification_status='verified' AND e.kind='tag' AND e.namespace='danbooru.tag' AND e.conflicted=0 ORDER BY e.value,l.id",(source['id'],)):
                    for r in assessments(link['value']):
                        r['proof']['evidence_chain'].append({'role':'entity_tag','source_id':link['source_id'],
                                                           'evidence_id':link['evidence_id'],'link':json.loads(link['payload'])})
                        r['matched_by']='entity_tag'
                        chosen.append(r)
        if not chosen:
            return out
        if any(r['canonical_status']!='canonical' or r['target_row'] is None for r in chosen):
            return dict(out,status='canonical_unknown',warnings=['canonical_evidence_incomplete'],
                        evidence_chain=[p for r in chosen for p in r['proof']['evidence_chain']])
        names=sorted({r['target_row']['value'] for r in chosen})
        if len(names)>1:
            return dict(out,status='tag_ambiguous',candidates=[{'tag_key':{'kind':'tag','namespace':'danbooru.tag','value':v}}
                                                             for v in names[:limit]],candidates_truncated=len(names)>limit)
        primary=chosen[0]
        chain=[]
        for r in chosen:
            for p in r['proof']['evidence_chain']:
                if p not in chain:
                    chain.append(p)
        out.update(status='resolved',tag_key=key(primary['target_row']),matched_by=primary['matched_by'],
                   canonical_status='canonical',evidence_chain=chain)
        wiki=primary['proof'].get('wiki_key')
        if not wiki:
            native=next((r for r in assessments(names[0]) if r['matched_by']=='native_exact'),None)
            wiki=native['proof'].get('wiki_key') if native else None
        if wiki:
            entry=conn.execute('SELECT id FROM entries WHERE kind=? AND namespace=? AND value=? AND conflicted=0',
                               tuple(wiki[k] for k in ('kind','namespace','value'))).fetchone()
            if entry:
                for r in conn.execute("SELECT * FROM documents WHERE entry_id=? AND status IN ('source_backed','generated_from_evidence') ORDER BY id LIMIT 10",(entry[0],)):
                    doc={'title':r['title'][:256],'original':r['original'][:4000],'response_truncated':len(r['original'])>4000,
                         'search_text_truncated':json.loads(r['payload']).get('search_text_truncated'),
                         'source_id':r['source_id'],'evidence_id':r['evidence_id'],'status':r['status']}
                    if len(r['title'])>256:
                        doc['title_truncated']=True
                    out['descriptions'].append(doc)
        return out
    finally:
        conn.close()
