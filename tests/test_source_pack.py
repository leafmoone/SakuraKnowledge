import json
import sqlite3
import struct

import pytest

from tools.source_pack import binding, build, build_database, finalize_manifest, list_sources


@pytest.fixture
def inputs(tmp_path):
    mother, mapping = tmp_path / 'mother.sqlite', tmp_path / 'original.sqlite'
    with sqlite3.connect(mother) as c:
        c.executescript('''
        CREATE TABLE sources(source_id TEXT PRIMARY KEY,metadata TEXT NOT NULL);
        CREATE TABLE entries(id INTEGER PRIMARY KEY,kind TEXT,namespace TEXT,value TEXT,type TEXT,locator TEXT,conflicted INTEGER NOT NULL DEFAULT 0,UNIQUE(kind,namespace,value));
        CREATE TABLE entry_evidence(id INTEGER PRIMARY KEY,entry_id INTEGER REFERENCES entries,source_id TEXT REFERENCES sources,evidence_id TEXT,status TEXT,type TEXT,locator TEXT,payload TEXT);
        CREATE TABLE aliases(id INTEGER PRIMARY KEY,entry_id INTEGER REFERENCES entries,text TEXT,language TEXT,type TEXT,status TEXT,source_id TEXT REFERENCES sources,evidence_id TEXT,payload TEXT);
        CREATE TABLE documents(id INTEGER PRIMARY KEY,entry_id INTEGER REFERENCES entries,title TEXT,original TEXT,search_text TEXT,language TEXT,status TEXT,source_id TEXT REFERENCES sources,evidence_id TEXT,payload TEXT);
        CREATE TABLE links(id INTEGER PRIMARY KEY,src INTEGER REFERENCES entries,dst INTEGER REFERENCES entries,relation TEXT,source_id TEXT REFERENCES sources,evidence_id TEXT,method TEXT,verification_status TEXT,payload TEXT);
        CREATE TABLE tag_resolutions(id INTEGER PRIMARY KEY,name TEXT,target INTEGER REFERENCES entries,matched_by TEXT,canonical_status TEXT,category INTEGER,source_id TEXT REFERENCES sources,evidence_id TEXT,payload TEXT);
        CREATE TABLE build_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE occurrences(id INTEGER);
        CREATE TABLE source_counts(id INTEGER);
        CREATE TABLE unresolved_records(id INTEGER);
        CREATE VIRTUAL TABLE search_fts USING fts5(text,document_id UNINDEXED,entry_id UNINDEXED);
        CREATE INDEX document_entry ON documents(entry_id,status);
        ''')
        for sid, provider in [('d1', 'danbooru'), ('d2', 'danbooru'), ('b', 'bangumi'),
                              ('m', 'moegirl'), ('map', 'mapping'), ('t', 'tag_wiki')]:
            c.execute('INSERT INTO sources VALUES(?,?)', (sid, json.dumps({'provider': provider})))
        for eid, kind, ns, value in [(1, 'tag', 'danbooru.tag', 'a'), (2, 'character', 'bangumi.character', '2'),
                                     (3, 'episode', 'bangumi.episode', '3')]:
            c.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,0)', (eid, kind, ns, value, 'global', 'foreign-locator'))
        for vid, eid, sid, status in [(1, 1, 'd1', 'source_backed'), (2, 2, 'b', 'source_backed'),
                                       (3, 3, 'b', 'source_backed'), (4, 1, 't', 'draft')]:
            c.execute('INSERT INTO entry_evidence VALUES(?,?,?,?,?,?,?,?)',
                      (vid, eid, sid, 'proof', status, 'native', sid + '-locator', '{"raw":{"raw_gender":"x","secret":"drop"}}'))
        for did, eid, sid, status in [(10, 1, 'd1', 'source_backed'), (11, 1, 'd2', 'generated_from_evidence'),
                                      (12, 1, 'd1', 'draft'), (20, 2, 'b', 'source_backed'),
                                      (30, 3, 'b', 'source_backed')]:
            c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (did, eid, 'title', 'original', 'original indexed text', 'en', status, sid, 'proof', '{"search_text_truncated":false,"secret":4}'))
            c.execute('INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES(?,?,?,?)',
                      (did + 100, 'actual stored FTS text', did, eid))
        c.execute("INSERT INTO aliases VALUES(1,1,'alias','en','name','draft','d2','proof','{}')")
        c.execute("INSERT INTO links VALUES(1,1,2,'candidate','d2','proof','name','candidate','{}')")
        c.execute("INSERT INTO links VALUES(2,2,1,'candidate','map','proof','name','candidate','{}')")
        c.execute("INSERT INTO tag_resolutions VALUES(1,'a',1,'exact','canonical',0,'d2','proof','{}')")
        c.execute("INSERT INTO tag_resolutions VALUES(2,'b',2,'exact','unknown',0,'t','proof','{}')")
        c.executemany('INSERT INTO build_meta VALUES(?,?)', [('snapshot', 'original-identity'), ('contract_version', '2'),
                                                           ('p3_resolver_version', '1'), ('search_text_version', '2'), ('index_episodes', 'false')])
    with sqlite3.connect(mapping) as c:
        c.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY,metadata TEXT NOT NULL,fulltext TEXT)')
        for position, did, kind, ns, value, sid in [(0, 20, 'character', 'bangumi.character', '2', 'b'),
                                                  (1, 10, 'tag', 'danbooru.tag', 'a', 'd1'),
                                                  (2, 12, 'tag', 'danbooru.tag', 'a', 'd1'),
                                                  (3, 11, 'tag', 'danbooru.tag', 'a', 'd2'),
                                                  (4, 30, 'episode', 'bangumi.episode', '3', 'b'),
                                                  (5, 10, 'tag', 'danbooru.tag', 'a', 't')]:
            c.execute('INSERT INTO chunks VALUES(?,?,?)', (position, json.dumps({'chunk_id': 'chunk-' + str(position),
                      'document_id': did, 'entry_key': {'kind': kind, 'namespace': ns, 'value': value},
                      'source_id': sid, 'evidence_id': 'proof'}), 'DO NOT EXPORT'))
    return mother, mapping


def test_catalog_actual_metadata_and_counts(inputs):
    rows = list_sources(inputs[0])['sources']
    assert [r['source_id'] for r in rows if r['family'] == 'danbooru'] == ['d1', 'd2']
    assert [r['source_id'] for r in rows if r['family'] == 'moegirl'] == ['m', 'map']
    assert next(r for r in rows if r['source_id'] == 'd2')['table_counts']['tag_resolutions'] == 1


def test_source_projection(inputs, tmp_path):
    before = [binding(p) for p in inputs]
    output = tmp_path / 'pack'
    result = build('danbooru', *inputs, output)
    assert before == [binding(p) for p in inputs]
    with sqlite3.connect(output / 'knowledge.sqlite') as c:
        assert c.execute('SELECT source_id FROM sources ORDER BY source_id').fetchall() == [('d1',), ('d2',)]
        assert c.execute('SELECT id,type,locator FROM entries ORDER BY id').fetchall() == [(1, 'native', 'd1-locator'), (2, None, None)]
        assert c.execute('SELECT entry_id FROM entry_evidence').fetchall() == [(1,)]
        assert c.execute('SELECT status FROM aliases').fetchone() == ('draft',)
        assert c.execute('SELECT verification_status FROM links').fetchone() == ('candidate',)
        assert c.execute('SELECT source_id FROM tag_resolutions').fetchall() == [('d2',)]
        assert c.execute('SELECT rowid,text,document_id FROM search_fts ORDER BY rowid').fetchall() == [(110, 'actual stored FTS text', 10), (111, 'actual stored FTS text', 11)]
        assert c.execute('SELECT count(*) FROM build_meta').fetchone() == (5,)
        assert json.loads(c.execute('SELECT payload FROM entry_evidence').fetchone()[0]) == {'raw': {'raw_gender': 'x'}}
        assert json.loads(c.execute('SELECT payload FROM documents LIMIT 1').fetchone()[0]) == {'search_text_truncated': False}
        assert not c.execute("SELECT name FROM sqlite_master WHERE name IN ('occurrences','source_counts','unresolved_records')").fetchall()
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    with sqlite3.connect(output / 'mapping.sqlite') as c:
        assert c.execute('SELECT position,original_position,document_id FROM chunks').fetchall() == [(0, 1, 10), (1, 3, 11)]
        assert 'fulltext' not in [r[1] for r in c.execute('PRAGMA table_info(chunks)')]
    assert (output / 'positions.u64le').read_bytes() == struct.pack('<QQ', 1, 3)
    with sqlite3.connect(output / 'lexical-membership.sqlite') as c:
        assert c.execute('SELECT * FROM members').fetchall() == [(110, 1, 10), (111, 1, 11)]
        meta = dict(c.execute('SELECT * FROM meta'))
        assert len(meta) == 5
        assert meta['snapshot_sha256'] == binding(output / 'knowledge.sqlite')['sha256']
    assert result['manifest'] is None
    assert not (output / 'manifest.json').exists()  # Never advertise a half-built semantic pack.
    with pytest.raises(FileExistsError):
        build('danbooru', *inputs, output)


def test_episodes_not_silently_removed(inputs, tmp_path):
    build('bangumi', *inputs, tmp_path / 'bgm')
    with sqlite3.connect(tmp_path / 'bgm/knowledge.sqlite') as c:
        assert c.execute('SELECT document_id FROM search_fts ORDER BY rowid').fetchall() == [(20,), (30,)]
    with sqlite3.connect(tmp_path / 'bgm/mapping.sqlite') as c:
        assert c.execute('SELECT original_position FROM chunks ORDER BY position').fetchall() == [(0,), (4,)]


def test_unknown_explicit_error(inputs, tmp_path):
    with sqlite3.connect(inputs[0]) as c:
        c.execute('INSERT INTO sources VALUES(?,?)', ('alien', '{"provider":"alien"}'))
    assert next(r for r in list_sources(inputs[0])['sources'] if r['source_id'] == 'alien')['family'] == 'unassigned'
    with pytest.raises(ValueError, match='unassigned'):
        build('danbooru', *inputs, tmp_path / 'unknown')
    assert not (tmp_path / 'unknown').exists()


def test_exclusive_database_and_finalize(inputs, tmp_path):
    occupied = tmp_path / 'occupied'
    occupied.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        build_database(inputs[0], occupied, ['d1'])
    assert occupied.read_bytes() == b'keep'
    output = tmp_path / 'pack'
    build('danbooru', *inputs, output)
    assert not (output / 'manifest.json').exists()
    (output / 'vectors.i8.usearch').write_bytes(b'prepared-index')
    manifest = finalize_manifest(output, 'danbooru', ['d1', 'd2'], ['danbooru.tag', 'danbooru.wiki'], index_prepared=True)
    assert manifest['artifacts']['index']['path'] == 'vectors.i8.usearch'
    assert manifest['requires_model'] == 'bge-m3'
