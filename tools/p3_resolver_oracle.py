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
             'warnings':[],'relations':[],'unresolved_reasons':[]}
        capability=conn.execute("SELECT value FROM build_meta WHERE key='p3_resolver_version'").fetchone()
        if capability is None or capability[0]!='1':
            return dict(out,status='unsupported',warnings=['p3_resolver_capability_absent'])
        def key(row):
            return {k:row[k] for k in ('kind','namespace','value')}
        def assessments(name,apply_category=True,endpoint=False):
            rows=[dict(x) for x in conn.execute('SELECT * FROM tag_resolutions WHERE name=? ORDER BY id',(name,))]
            if endpoint:
                rows=[r for r in rows if r['matched_by'] in ('native_exact','official_alias')]
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
            endpoint_present=bool(assessments(query,False,True))
            chosen=assessments(query,endpoint=endpoint_present)
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
                chosen=assessments(source['value'],endpoint=True)
                if category is not None and not chosen:
                    return dict(out,status='not_found')
            else:
                for link in conn.execute("SELECT l.*,e.value FROM links l JOIN entries e ON e.id=l.dst WHERE l.src=? AND l.relation='entity_tag' AND l.verification_status='verified' AND e.kind='tag' AND e.namespace='danbooru.tag' AND e.conflicted=0 ORDER BY e.value,l.id",(source['id'],)):
                    for r in assessments(link['value'],endpoint=True):
                        r['proof']['evidence_chain'].append({'role':'entity_tag','source_id':link['source_id'],
                                                           'evidence_id':link['evidence_id'],'link':json.loads(link['payload'])})
                        r['matched_by']='entity_tag'
                        chosen.append(r)
        if not chosen:
            return out
        if any(r['canonical_status']!='canonical' or r['target_row'] is None for r in chosen):
            return dict(out,status='canonical_unknown',warnings=['canonical_evidence_incomplete'],
                        evidence_chain=[p for r in chosen for p in r['proof']['evidence_chain']],
                        unresolved_reasons=[{'name':r['name'],'matched_by':r['matched_by'],
                                             'reason':r['proof'].get('reason') or 'canonical_evidence_incomplete'}
                                            for r in chosen if r['canonical_status']!='canonical' or r['target_row'] is None])
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
        links=list(conn.execute("SELECT l.*,w.kind,w.namespace,w.value FROM links l JOIN entries w ON w.id=l.src WHERE l.dst=? AND l.relation='wiki_tag' AND l.verification_status IN ('native','verified') AND w.conflicted=0 AND w.kind='page' AND w.namespace='danbooru.wiki' ORDER BY w.value,l.id",(primary['target'],)))
        for link in links:
            wiki=key(link)
            refs=json.loads(link['payload']).get('evidence_refs',[])
            associations=[p for p in refs if p.get('role')=='wiki_tag_link' and p.get('wiki_key')==wiki and p.get('tag_key')==out['tag_key']]
            cuts=[p for p in refs if p.get('role')=='wiki_cut_compatibility' and p.get('wiki_key')==wiki and p.get('tag_key')==out['tag_key']]
            def valid_cut(p):
                fields=('old_updated_at','old_source_id','old_input_sha256','raw_sha256','source_id','evidence_id','body_sha256','old_other_names_sha256')
                return (all(isinstance(p.get(k),str) and p[k] for k in fields)
                        and p['old_updated_at']==p.get('live_updated_at')
                        and type(p.get('old_line')) is int and p['old_line']>0
                        and p['body_sha256']==p.get('old_body_sha256')==p.get('live_body_sha256')
                        and p['old_other_names_sha256']==p.get('live_other_names_sha256'))
            if not associations or not any(valid_cut(p) for p in cuts):
                continue
            for r in conn.execute("SELECT * FROM documents WHERE entry_id=? AND status IN ('source_backed','generated_from_evidence') ORDER BY id LIMIT 10",(link['src'],)):
                doc={'title':r['title'][:256],'original':r['original'][:4000],'response_truncated':len(r['original'])>4000,
                     'search_text_truncated':json.loads(r['payload']).get('search_text_truncated'),
                     'source_id':r['source_id'],'evidence_id':r['evidence_id'],'status':r['status']}
                if len(r['title'])>256:
                    doc['title_truncated']=True
                out['descriptions'].append(doc)
            if not out['descriptions']:
                continue
            for p in refs:
                if p not in out['evidence_chain']:
                    out['evidence_chain'].append(p)
            out['evidence_chain'].append({'role':'wiki_association_edge','source_id':link['source_id'],'evidence_id':link['evidence_id'],'src':wiki,'dst':out['tag_key']})
            for doc in out['descriptions']:
                out['evidence_chain'].append({'role':'description','source_id':doc['source_id'],'evidence_id':doc['evidence_id'],'wiki_key':wiki,'tag_key':out['tag_key']})
            break
        return out
    finally:
        conn.close()
