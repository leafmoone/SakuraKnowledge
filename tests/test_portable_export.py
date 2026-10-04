import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from sakura_knowledge.api import Knowledge
from sakura_knowledge.response import source_observations
from sakura_knowledge.storage import SCHEMA
from tools import portable_export as export


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def runtime_db(tmp_path):
    source = tmp_path / 'knowledge.sqlite'
    with sqlite3.connect(source) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO sources VALUES ('s','{}')")
        db.executemany('INSERT INTO build_meta VALUES (?,?)', [('contract_version', '2'), ('search_text_version', '2'), ('snapshot', 'tiny')])
        db.execute("INSERT INTO entries(id,kind,namespace,value) VALUES (7,'character','bangumi.character','Hero')")
        payloads = [
            {'raw_attributes': None, 'raw_cv_names': [], 'ignored': 'large'},
            {'raw': {'raw_gender': False, 'raw_attributes': {'nested': [1, None, True]}, 'ignored': 'large'}, 'raw_gender': 'shadowed'},
            {'raw': None, 'raw_gender': 'shadowed'},
            {'raw': [], 'raw_gender': 'shadowed'},
            {'raw': {}, 'raw_attributes': 'shadowed'},
            {'ignored': 'large'},
            {'raw_subject_categories': 18446744073709551615},
        ]
        for i, payload in enumerate(payloads, 1):
            db.execute("INSERT INTO entry_evidence(id,entry_id,source_id,evidence_id,status,payload) VALUES (?,7,'s',?,'source_backed',?)", (i, str(i), json.dumps(payload)))
        for i, payload in enumerate([{}, {'search_text_truncated': None}, {'search_text_truncated': False}, {'search_text_truncated': True}, None], 1):
            db.execute("INSERT INTO documents(id,entry_id,title,original,search_text,status,source_id,evidence_id,payload) VALUES (?,7,'Hero','hero story','hero story','source_backed','s',?,?)", (i, str(i), None if payload is None else json.dumps({**payload, 'ignored': 'large'})))
            db.execute('INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES (?,?,?,7)', (i * 13, 'hero story', i))
        db.execute("INSERT INTO links VALUES (17,7,7,'related','s','1','test','source_backed','{\"raw\":{\"anything\":[1]}}')")
        db.execute("INSERT INTO occurrences(entry_id,source_id) VALUES (7,'s')")
        db.execute("INSERT INTO unresolved_records VALUES ('s',1,'{}')")
        db.execute("INSERT INTO source_counts VALUES ('s',1,1,0,0,0,0,'{}')")
        db.execute('ANALYZE')
    return source


def observations(db):
    db.row_factory = sqlite3.Row
    proofs = [dict(r) for r in db.execute('SELECT source_id,evidence_id,status,payload FROM entry_evidence ORDER BY id')]
    return source_observations(proofs)


def test_runtime_export_preserves_logical_outputs(runtime_db, tmp_path):
    target = tmp_path / 'runtime.sqlite'
    before = digest(runtime_db)
    report = export.export_db(runtime_db, target)
    assert report['integrity'] == 'ok'
    assert digest(runtime_db) == before
    with sqlite3.connect(runtime_db) as old, sqlite3.connect(target) as new:
        assert observations(old) == observations(new)
        old.row_factory = new.row_factory = None
        schemas = lambda c: c.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT IN ('occurrences','unresolved_records','source_counts') ORDER BY name").fetchall()
        assert schemas(old) == schemas(new)
        for name, in old.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if name in export.EXCLUDED or name in ('documents', 'entry_evidence', 'sqlite_stat1'):
                continue
            assert new.execute(f'SELECT * FROM {export.quote(name)}').fetchall() == old.execute(f'SELECT * FROM {export.quote(name)}').fetchall()
        stats = "SELECT * FROM sqlite_stat1 WHERE tbl NOT IN ('occurrences','unresolved_records','source_counts') ORDER BY tbl,idx"
        assert new.execute(stats).fetchall() == old.execute(stats).fetchall()
        query = "SELECT rowid,bm25(search_fts) FROM search_fts WHERE search_fts MATCH 'hero' ORDER BY rowid"
        assert old.execute(query).fetchall() == new.execute(query).fetchall()
        assert [json.loads(r[0]) if r[0] is not None else None for r in new.execute('SELECT payload FROM documents ORDER BY id')] == [{}, {'search_text_truncated': None}, {'search_text_truncated': False}, {'search_text_truncated': True}, None]
        payloads = [json.loads(r[0]) for r in new.execute('SELECT payload FROM entry_evidence ORDER BY id')]
        assert payloads[2:6] == [{'raw': None}, {'raw': []}, {'raw': {}}, {}]
        assert payloads[-1]['raw_subject_categories'] == 18446744073709551615
        assert not export.EXCLUDED.intersection(r[0] for r in new.execute("SELECT name FROM sqlite_master"))
    with Knowledge(runtime_db) as old, Knowledge(target) as new:
        for method, args in [('lookup', ('Hero',)), ('search', ('hero',)), ('ask', ('Hero',))]:
            assert getattr(old, method)(*args) == getattr(new, method)(*args)
    with pytest.raises(FileExistsError):
        export.export_db(runtime_db, target)
    assert digest(runtime_db) == before


def test_mapping_cli_only_runtime_fields(tmp_path):
    source, target = tmp_path / 'full.sqlite', tmp_path / 'mapping.sqlite'
    metadata = {'entry_key': {'kind': 'character', 'namespace': 'bangumi.character', 'value': 'Hero'}, 'document_id': 7, 'chunk_id': 'c', 'source_id': 's', 'evidence_id': 'e', 'entry_id': 17, 'text': 'large body'}
    with sqlite3.connect(source) as db:
        db.executescript('CREATE TABLE chunks(position INTEGER PRIMARY KEY, metadata TEXT NOT NULL, text TEXT); CREATE TABLE projection(position INTEGER PRIMARY KEY,row_json TEXT);')
        db.execute('INSERT INTO chunks VALUES (0,?,?)', (json.dumps(metadata), 'body'))
        db.execute("INSERT INTO projection VALUES (0,'{\"text\":\"body\"}')")
    before = digest(source)
    result = subprocess.run([sys.executable, str(Path(export.__file__)), 'export-mapping', '--source', str(source), '--output', str(target)], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['row_counts'] == {'chunks': 1}
    assert digest(source) == before
    with sqlite3.connect(target) as db:
        assert [r[1] for r in db.execute('PRAGMA table_info(chunks)')] == ['position','chunk_id','document_id','kind','namespace','value','source_id','evidence_id']
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [('chunks',)]
        assert db.execute('SELECT * FROM chunks WHERE position=0').fetchone() == (0,'c','7','character','bangumi.character','Hero','s','e')
    with pytest.raises(FileExistsError):
        export.export_mapping(source, target)


def test_failure_removes_partial_output(tmp_path):
    source, target = tmp_path / 'invalid.sqlite', tmp_path / 'mapping.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY, metadata TEXT)')
        db.execute("INSERT INTO chunks VALUES (9,'{}')")
    with pytest.raises(ValueError, match='contiguous'):
        export.export_mapping(source, target)
    assert not target.exists()
