"""Declared independent expected behavior, not Python production resolver parity."""
import json
import sqlite3
import subprocess

import pytest
from test_core import record
from test_review_f99 import snapshot
from test_rust_repair import binary as rust_binary_fixture

binary = rust_binary_fixture
P3_SCHEMA = '''
CREATE TABLE tag_resolutions(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
 target INTEGER REFERENCES entries, matched_by TEXT NOT NULL,
 canonical_status TEXT NOT NULL, category INTEGER, source_id TEXT REFERENCES sources,
 evidence_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX tag_resolution_name ON tag_resolutions(name,matched_by);
CREATE INDEX tag_resolution_target ON tag_resolutions(target);
CREATE INDEX link_dst ON links(dst,relation,verification_status);
'''


def key(value, kind='tag', namespace='danbooru.tag'):
    return {'kind':kind,'namespace':namespace,'value':value}


def expected(snapshot_id, query, status, tag=None, matched=None, canonical='unknown',
             candidates=None, source=None, warnings=None, category=None):
    return {'contract_version':'2','response_version':'3','resolver_contract_version':'1',
            'snapshot':snapshot_id,'query':query,'requested_namespace':'danbooru.tag',
            'requested_category':category,'source_key':source,'status':status,
            'tag_key':None if tag is None else key(tag),'matched_by':matched,
            'canonical_status':canonical,'evidence_chain':[],'descriptions':[],
            'citations':[],'candidates':candidates or [],'candidates_truncated':False,
            'source_scope':['fixture-v1'],'warnings':warnings or [],'relations':[]}


def fixture(tmp_path):
    records = [record('tag','danbooru.tag', 'A_(original!)'),
               record('tag','danbooru.tag', 'B'),
               record('character','fixture.character','hero'),
               record('character','fixture.character','hero2')]
    db = snapshot(tmp_path, records)
    conn = sqlite3.connect(db)
    conn.executescript(P3_SCHEMA)
    conn.execute("INSERT INTO build_meta VALUES('p3_resolver_version','1')")
    source = conn.execute('SELECT source_id FROM sources LIMIT 1').fetchone()[0]
    for name, value, matched, status, cat in [
        ('A_(original!)','A_(original!)','native_exact','canonical',4),
        ('alias','A_(original!)','official_alias','canonical',4),
        ('中文甲','A_(original!)','wiki_name','canonical',4),
        ('same','A_(original!)','wiki_name','canonical',4),
        ('same','B','wiki_name','canonical',3),
        ('cycle',None,'official_alias','unknown',None),
        ('partial','B','native_exact','unknown',3),
        ('retired',None,'official_alias','unknown',None),
    ]:
        target = conn.execute('SELECT id FROM entries WHERE namespace=? AND value=?',
                              ('danbooru.tag',value)).fetchone() if value else None
        conn.execute('INSERT INTO tag_resolutions(name,target,matched_by,canonical_status,category,source_id,evidence_id,payload) VALUES(?,?,?,?,?,?,?,?)',
                     (name,target[0] if target else None,matched,status,cat,source,'fixture:proof',
                      json.dumps({'evidence_chain':[], 'reason':status})))
    for value in ('hero','hero2'):
        entry = conn.execute('SELECT id FROM entries WHERE value=?',(value,)).fetchone()[0]
        conn.execute("INSERT INTO aliases(entry_id,text,language,type,status,source_id,evidence_id,payload) VALUES(?, 'shared_entity','unknown','name','source_backed',?,'alias','{}')",(entry,source))
    identity = conn.execute("SELECT value FROM build_meta WHERE key='snapshot'").fetchone()[0]
    conn.commit()
    conn.close()
    return db, identity


def run(binary, db, query, *options):
    proc = subprocess.run([str(binary),'resolve-tag',str(db),query,*options],capture_output=True,
                          timeout=15,check=False)
    assert proc.returncode == 0, proc.stderr
    assert not proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize('query,status,tag,matched,canonical',[
    ('A_(original!)','resolved','A_(original!)','native_exact','canonical'),
    ('alias','resolved','A_(original!)','official_alias','canonical'),
    ('中文甲','resolved','A_(original!)','wiki_name','canonical'),
    ('absent','not_found',None,None,'unknown'),
    ('cycle','canonical_unknown',None,None,'unknown'),
    ('partial','canonical_unknown',None,None,'unknown'),
    ('retired','canonical_unknown',None,None,'unknown'),
])
def test_declared_simple_expected(binary,tmp_path,query,status,tag,matched,canonical):
    db, identity = fixture(tmp_path)
    # Every response field is compared. No production Python API is invoked.
    want = expected(identity,query,status,tag,matched,canonical)
    if status == 'canonical_unknown':
        want['warnings'] = ['canonical_evidence_incomplete']
    assert run(binary,db,query) == want


def test_limit_not_uniqueness(binary,tmp_path):
    db,_ = fixture(tmp_path)
    a = run(binary,db,'same','--limit','1')
    b = run(binary,db,'same','--limit','100')
    assert a['status'] == b['status'] == 'tag_ambiguous'
    assert a['tag_key'] is b['tag_key'] is None
    assert len(a['candidates']) == 1 and a['candidates_truncated']
    assert {x['tag_key']['value'] for x in b['candidates']} == {'A_(original!)','B'}


def test_terminal_category(binary,tmp_path):
    db,_ = fixture(tmp_path)
    a = run(binary,db,'same','--category','4')
    assert a['status'] == 'resolved' and a['tag_key'] == key('A_(original!)')
    assert run(binary,db,'alias','--category','3')['status'] == 'not_found'
    assert run(binary,db,'A_(original!)','--category','3')['status'] == 'not_found'


def test_source_constraints_do_not_global_fallback(binary,tmp_path):
    db,_ = fixture(tmp_path)
    assert run(binary,db,'alias','--kind','character','--namespace','fixture.character')['status'] == 'not_found'
    explicit = run(binary,db,'hero','--key','--kind','character','--namespace','fixture.character')
    assert explicit['status'] == 'entity_found_tag_unmapped'
    assert explicit['source_key'] == key('hero','character','fixture.character')
    assert run(binary,db,'shared_entity')['status'] == 'entity_ambiguous'


def test_incoming_uses_actual_edge_and_offline_index(binary,tmp_path):
    db,_ = fixture(tmp_path)
    conn = sqlite3.connect(db)
    src = conn.execute("SELECT id FROM entries WHERE value='hero'").fetchone()[0]
    dst = conn.execute("SELECT id FROM entries WHERE value='A_(original!)'").fetchone()[0]
    conn.execute("INSERT INTO links(src,dst,relation,source_id,evidence_id,method,verification_status,payload) VALUES(?,?,'entity_tag','fixture-v1','edge','explicit-source-link','verified','{}')",(src,dst))
    conn.commit()
    conn.close()
    proc = subprocess.run([str(binary),'related',str(db),'tag','danbooru.tag','A_(original!)',
                           '--direction','in','--kind','character'],capture_output=True,timeout=15,check=False)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out['direction'] == 'in'
    assert out['relations'][0]['src'] == key('hero','character','fixture.character')
    assert out['relations'][0]['dst'] == key('A_(original!)')
    assert out['relations'][0]['evidence_id'] == 'edge'


def test_old_snapshot_unsupported_not_scan(binary,tmp_path):
    db = snapshot(tmp_path,[record('tag','local.tag_aggregate','alias')])
    result = run(binary,db,'alias')
    assert result['status'] == 'unsupported' and result['tag_key'] is None
    assert result['warnings'] == ['p3_resolver_capability_absent']
