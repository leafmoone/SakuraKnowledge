"""Optional P3 atomic builder integration; no Python production runtime additions."""
import json
import sqlite3

import pytest
from test_core import manifest

from sakura_knowledge.model import EntryKey
from sakura_knowledge.storage import build


def rows(status='source_backed', namespace='danbooru.tag'):
    key = EntryKey('tag',namespace,'native').as_dict()
    native={'key':key,'status':status,'raw':{'id':7,'name':'native','category':4,'is_deprecated':False}}
    proof=[{'role':role,'source_id':'fixture-v1','evidence_id':'raw:7','raw_sha256':'a'*64}
           for role in ('native_identity','canonical_scope')]
    projection={'record_type':'tag_resolution','name':'native','target':key,
                'matched_by':'native_exact','canonical_status':'canonical','category':4,
                'rule_version':'danbooru-native-1','status':'source_backed','evidence_chain':proof}
    return [native,projection]


def p3_manifest(tmp_path,records,enabled=True):
    path=manifest(tmp_path,records)
    value=json.loads(path.read_text())
    if enabled:
        value['p3_resolver_version']='1'
    path.write_text(json.dumps(value),encoding='utf-8')
    return path


def test_projection_atomic_and_accounted(tmp_path):
    path=p3_manifest(tmp_path,rows())
    output=tmp_path/'new-p3'
    build(path,output)
    conn=sqlite3.connect(output/'knowledge.sqlite')
    assert conn.execute('SELECT count(*) FROM tag_resolutions').fetchone()[0]==1
    assert conn.execute('SELECT input,accepted,rejected FROM source_counts').fetchone()==(2,2,0)
    assert conn.execute("SELECT value FROM build_meta WHERE key='p3_resolver_version'").fetchone()[0]=='1'
    assert conn.execute("SELECT count(*) FROM pragma_index_info('link_dst')").fetchone()[0]==3
    conn.close()
    with pytest.raises(FileExistsError):
        build(path,output)


@pytest.mark.parametrize('status,namespace',[
    ('generated_from_evidence','danbooru.tag'),('source_backed','local.tag_aggregate')])
def test_projection_never_promotes_generated_or_aggregate(tmp_path,status,namespace):
    path=p3_manifest(tmp_path,rows(status,namespace))
    output=tmp_path/'bad-p3'
    with pytest.raises(ValueError):
        build(path,output)
    assert not output.exists()


def test_old_manifest_cannot_silently_publish_new_record(tmp_path):
    path=p3_manifest(tmp_path,rows(),False)
    output=tmp_path/'no-capability'
    with pytest.raises(ValueError):
        build(path,output)
    assert not output.exists()
