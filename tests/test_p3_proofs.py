"""Additional independent contract boundaries and full-JSON offline oracle checks."""
import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from test_p3_resolver import fixture, key, run
from test_rust_repair import binary as rust_binary_fixture

binary=rust_binary_fixture
spec=importlib.util.spec_from_file_location('p3oracle',Path(__file__).parents[1]/'tools/p3_resolver_oracle.py')
oracle=importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def edge(conn,target,status):
    source=conn.execute("SELECT id FROM entries WHERE value='hero'").fetchone()[0]
    dst=conn.execute('SELECT id FROM entries WHERE value=?',(target,)).fetchone()[0]
    conn.execute('INSERT INTO links(src,dst,relation,source_id,evidence_id,method,verification_status,payload) VALUES(?,?,\'entity_tag\',\'fixture-v1\',\'edge\',\'explicit-id-rule\',?,\'{}\')',(source,dst,status))


@pytest.mark.parametrize('status',['candidate','conflict'])
def test_candidate_conflict_not_resolved(binary,tmp_path,status):
    db,_=fixture(tmp_path)
    conn=sqlite3.connect(db);edge(conn,'A_(original!)',status);conn.commit();conn.close()
    got=run(binary,db,'hero','--key','--kind','character','--namespace','fixture.character')
    assert got['status']=='entity_found_tag_unmapped' and got['tag_key'] is None
    assert got==oracle.result(db,'hero',kind='character',namespace='fixture.character',exact=True)


def test_verified_actual_link_and_multi_target_limit(binary,tmp_path):
    db,_=fixture(tmp_path)
    conn=sqlite3.connect(db);edge(conn,'A_(original!)','verified');conn.commit();conn.close()
    got=run(binary,db,'hero','--key','--kind','character','--namespace','fixture.character')
    assert got['status']=='resolved' and got['tag_key']==key('A_(original!)')
    assert got['evidence_chain'][0]['role']=='entity_tag'
    assert got==oracle.result(db,'hero',kind='character',namespace='fixture.character',exact=True)
    conn=sqlite3.connect(db)
    conn.execute("UPDATE tag_resolutions SET canonical_status='canonical' WHERE name='partial'")
    conn.execute("INSERT INTO tag_resolutions SELECT NULL,'B',target,'native_exact','canonical',3,source_id,evidence_id,payload FROM tag_resolutions WHERE name='partial'")
    edge(conn,'B','verified');conn.commit();conn.close()
    for limit in (1,100):
        actual=run(binary,db,'hero','--key','--kind','character','--namespace','fixture.character','--limit',str(limit))
        assert actual['status']=='tag_ambiguous' and actual['tag_key'] is None
        assert actual==oracle.result(db,'hero',kind='character',namespace='fixture.character',exact=True,limit=limit)


def test_retraction_rebuild_not_stale_verified(binary,tmp_path):
    db,_=fixture(tmp_path)
    conn=sqlite3.connect(db);edge(conn,'A_(original!)','verified');conn.commit();conn.close()
    assert run(binary,db,'hero')['status']=='resolved'
    # Synthetic un-published test DB only: represents new decision input's result.
    conn=sqlite3.connect(db);conn.execute('DELETE FROM links');conn.commit();conn.close()
    assert run(binary,db,'hero')['status']=='entity_found_tag_unmapped'


@pytest.mark.parametrize('query',['A_(original!)','alias','中文甲','same','cycle','partial','absent','shared_entity'])
def test_full_json_independent_oracle(binary,tmp_path,query):
    db,_=fixture(tmp_path)
    assert run(binary,db,query)==oracle.result(db,query)


def test_essential_proof_response_cap_fail_not_truncate_identity(binary,tmp_path):
    db,_=fixture(tmp_path)
    conn=sqlite3.connect(db)
    conn.execute("UPDATE tag_resolutions SET payload=? WHERE name='A_(original!)'",
                 (json.dumps({'evidence_chain':[{'identity':'s'*600000}]}),))
    conn.commit();conn.close()
    proc=subprocess.run([str(binary),'resolve-tag',str(db),'A_(original!)'],capture_output=True,timeout=15,check=False)
    assert proc.returncode==2 and not proc.stdout
    assert json.loads(proc.stderr)['message']=='response_budget_exceeded'


def test_schema_missing_projection_fails_closed(binary,tmp_path):
    db,_=fixture(tmp_path)
    conn=sqlite3.connect(db);conn.execute('DROP TABLE tag_resolutions');conn.commit();conn.close()
    proc=subprocess.run([str(binary),'resolve-tag',str(db),'alias'],capture_output=True,timeout=15,check=False)
    assert proc.returncode==2 and not proc.stdout


def test_inbound_absent_capability_explicit_error(binary,tmp_path):
    db,_=fixture(tmp_path)
    conn=sqlite3.connect(db);conn.execute('DROP INDEX link_dst');conn.commit();conn.close()
    proc=subprocess.run([str(binary),'related',str(db),'tag','danbooru.tag','A_(original!)','--direction','in'],
                        capture_output=True,timeout=15,check=False)
    assert proc.returncode==2 and not proc.stdout
    assert json.loads(proc.stderr)['message']=='p3_inverse_capability_absent'
