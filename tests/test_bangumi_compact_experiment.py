"""Synthetic compact-storage checks; not real Bangumi/full-library validation."""
import hashlib
import json
import sqlite3
import zlib
from contextlib import closing

import pytest

from sakura_knowledge.native_tags import P3_SCHEMA
from sakura_knowledge.storage import SCHEMA
from tools import bangumi_compact_experiment as compact


@pytest.fixture
def baseline(tmp_path):
    path = tmp_path / 'baseline.sqlite'
    body = 'A long alpha original: 日本語😀\\ quote"\n' * 24
    payload = ('{ "unknown":[9,8], "raw":{"summary":' + json.dumps(body, ensure_ascii=False)
               + '}, "duplicate":1, "duplicate":2, "opaque":"\\u65e5" }')
    escaped = json.dumps({'summary': body, 'unknown': ['keep', 0]}, ensure_ascii=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA + P3_SCHEMA)
        conn.execute('INSERT INTO sources VALUES(?,?)', ('synthetic', '{ "fixture":true }'))
        for eid, kind in ((7, 'subject'), (9, 'person'), (22, 'character'), (31, 'episode')):
            conn.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?)',
                         (eid, kind, 'fixture.' + kind, str(eid), kind, None, 0))
            status = 'no_reference' if eid == 22 else 'source_backed'
            conn.execute('INSERT INTO entry_evidence VALUES(?,?,?,?,?,?,?,?)',
                         (eid * 10, eid, 'synthetic', 'proof:' + str(eid), status, kind, None,
                          payload if eid == 7 else escaped if eid == 9 else '{"raw":{}}'))
        docs = [(100, 7, 'Body', body, 'alpha 日本語', 'source_backed', payload),
                (101, 7, 'Repeated body', body, 'alpha alpha', 'generated_from_evidence', '{"unknown":1}'),
                (102, 9, 'Empty', '', '', 'source_backed', escaped),
                (103, 22, 'Untrusted', 'unknown data', 'alpha', 'no_reference', '{}'),
                (104, 31, 'Episode', None, None, 'no_reference', '{}')]
        for did, eid, title, original, search, status, raw in docs:
            conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (did, eid, title, original, search, None, status, 'synthetic', 'doc:' + str(did), raw))
        # Arbitrary rowids, repeated FTS occurrence and mismatched FTS metadata:
        # preserve the row corpus, but reference only a unique exact closed row.
        conn.executemany('INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES(?,?,?,?)',
                         [(900, 'alpha 日本語', 100, 7), (2, 'alpha alpha', 101, 7),
                          (3, 'alpha alpha', 101, 7), (400, '', 102, 9),
                          (600, 'not identical', 103, 22)])
        conn.execute("INSERT INTO search_fts(search_fts,rank) VALUES('rank','bm25(3.0)')")
        conn.execute('INSERT INTO aliases VALUES(?,?,?,?,?,?,?,?,?)',
                     (999, 7, 'Alias', None, 'name', 'source_backed', 'synthetic', 'alias:999',
                      '{ "unknown":42, "text":"Alias" }'))
        conn.execute('INSERT INTO links VALUES(?,?,?,?,?,?,?,?,?)',
                     (777, 7, 9, 'credit_person', 'synthetic', 'link:777', 'fixture', 'native', payload))
        conn.execute('INSERT INTO build_meta VALUES(?,?)', ('contract_version', '2'))
        conn.commit()
    return path


@pytest.mark.parametrize('compress', [False, True])
def test_complete_exact_roundtrip_same_sample_fts_and_evidence(baseline, tmp_path, compress):
    out = tmp_path / ('compact-' + str(compress) + '.sqlite')
    built = compact.build_compact(baseline, out, compress)
    result = compact.validate_pair(baseline, out)
    assert result['status'] == 'PASS'
    assert result['rows']['entries'] == 4 and result['rows']['documents'] == 5
    assert result['fts_rows'] == 5 and result['sample_fts_queries'] > 0
    assert result['status_counts']['documents']['no_reference'] == 2
    assert built['measurements']['search_text_refs_to_existing_FTS'] == 2
    assert built['measurements']['json_body_tokens_referenced'] >= 2
    with closing(sqlite3.connect(out)) as conn:
        # Same actual unescaped body CAS, not a second escaped-body blob copy.
        with closing(sqlite3.connect(baseline)) as source:
            body = source.execute('SELECT original FROM documents WHERE id=100').fetchone()[0]
        assert conn.execute('SELECT count(*) FROM content_blobs WHERE digest=?',
                            (hashlib.sha256(body.encode()).hexdigest(),)).fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM content_blobs WHERE digest=?',
                            (hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest(),)).fetchone()[0] == 0
        assert conn.execute('SELECT kind FROM compact_search_refs WHERE document_id=101').fetchone() == ('content',)
        assert conn.execute('SELECT kind FROM compact_search_refs WHERE document_id=103').fetchone() == ('content',)
    with pytest.raises(FileExistsError):
        compact.build_compact(baseline, out, compress)


def test_noncanonical_escape_unknown_keys_exact_and_no_accidental_body_rewrite():
    body = ('line 日本語 "quote"\\\n' * 20).encode()
    raw = json.dumps({'summary': body.decode()}, ensure_ascii=True).encode()
    assert compact.canonical_body_tokens(raw, (body,)) == []
    # JSON string content containing a fake field must not become a field token.
    nested = json.dumps({'literal': '"summary":' + json.dumps(body.decode(), ensure_ascii=False)},
                        ensure_ascii=False).encode()
    assert compact.canonical_body_tokens(nested, (body,)) == []
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.executescript(compact.CAS_SCHEMA)
        store = compact.ContentStore(conn)
        for value in (raw, nested, b'not JSON \n { "unknown":true }', b'', body, b'{"summary":"\\ud800"}'):
            assert store.get_ref(store.add_ref(value, (body,))) == value


@pytest.mark.parametrize('codec,version,length,digest,data', [
    ('unknown', 1, 1, 'a' * 64, b'a'),
    ('identity', 1, -1, 'a' * 64, b'a'),
    ('identity', -1, 1, 'a' * 64, b'a'),
    ('identity', 1, 1, 'a' * 64, b'a'),
    ('identity', 1, 1, hashlib.sha256(b'\xff').hexdigest(), b'\xff'),
    ('zlib', 1, 1, hashlib.sha256(b'a').hexdigest(), zlib.compress(b'a')[:-1]),
    ('zlib', 1, 1, hashlib.sha256(b'a').hexdigest(), zlib.compress(b'a') + b'trailing'),
    ('zlib', 1, 1, hashlib.sha256(b'a').hexdigest(), zlib.compress(b'a' * 100000)),
    ('identity', 1, compact.MAX_TEXT_BYTES + 1, 'a' * 64, b'a'),
])
def test_bad_codec_utf8_hash_length_truncated_and_bomb_fail(codec, version, length, digest, data):
    with pytest.raises(ValueError):
        compact.decode_blob(codec, version, length, digest, data)


def test_small_payload_identity_guard_collision_and_missing_reference(monkeypatch):
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.executescript(compact.CAS_SCHEMA)
        store = compact.ContentStore(conn)
        ref = store.add_ref(b'{}')
        assert conn.execute('SELECT codec FROM content_blobs').fetchone() == ('identity',)
        with pytest.raises(ValueError):
            store.get_ref(999)
        conn.execute('UPDATE content_refs SET segments=? WHERE id=?', ('[{"blob":999,"transform":"raw"}]', ref))
        with pytest.raises(ValueError):
            store.get_ref(ref)
        monkeypatch.setattr(compact, 'digest_bytes', lambda raw: 'a' * 64)
        store.put(b'one')
        with pytest.raises(ValueError, match='collision'):
            store.put(b'two')


@pytest.mark.parametrize('mutation', [
    "UPDATE content_blobs SET data=x'00' WHERE id=(SELECT min(id) FROM content_blobs)",
    "UPDATE content_refs SET uncompressed_bytes=-1 WHERE id=(SELECT min(id) FROM content_refs)",
    "UPDATE content_refs SET segments='[{\"blob\":1,\"transform\":\"UNKNOWN\"}]' WHERE id=1",
    "UPDATE compact_search_refs SET target_id=999999 WHERE kind='fts'",
])
def test_tamper_reference_or_codec_fails_validation(baseline, tmp_path, mutation):
    out = tmp_path / 'compact.sqlite'
    compact.build_compact(baseline, out)
    with closing(sqlite3.connect(out)) as conn:
        conn.execute(mutation)
        conn.commit()
    with pytest.raises((ValueError, UnicodeError)):
        compact.validate_pair(baseline, out)


def test_frozen_selection_preserves_all_fts_occurrences_and_create_new(baseline, tmp_path):
    pack = tmp_path / 'pack'
    pack.mkdir()
    # Keep source bytes unchanged while using a synthetic sealed pack binding.
    import shutil
    shutil.copy2(baseline, pack / 'knowledge.sqlite')
    manifest = {'pack_id': 'bangumi', 'source_ids': ['synthetic'],
                'artifacts': {'snapshot': {'path': 'knowledge.sqlite',
                                          'size': baseline.stat().st_size,
                                          'sha256': compact.small_binding(baseline)['sha256']}}}
    (pack / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    pool, selection = tmp_path / 'pool.json', tmp_path / 'selection.json'
    compact.freeze_pool(pack, pool)
    frozen = compact.freeze_selection(pack, pool, selection)
    assert len(frozen['fts_metadata']) == 5
    assert len({row[1] for row in frozen['fts_metadata']}) == 4
    assert frozen['table_ids']['entries'] == [7, 9, 22, 31]
    sample = tmp_path / 'sample.sqlite'
    compact.extract_sample(frozen, sample)
    with closing(sqlite3.connect(sample)) as conn, closing(sqlite3.connect(baseline)) as source:
        assert conn.execute('SELECT rowid,text,document_id,entry_id FROM search_fts ORDER BY rowid').fetchall() == source.execute('SELECT rowid,text,document_id,entry_id FROM search_fts ORDER BY rowid').fetchall()
    with pytest.raises(FileExistsError):
        compact.freeze_pool(pack, pool)
    with pytest.raises(FileExistsError):
        compact.freeze_selection(pack, pool, selection)
    with pytest.raises(FileExistsError):
        compact.extract_sample(frozen, sample)
    with pytest.raises(FileExistsError):
        compact.run_sample(selection, pack)


def test_missing_optional_dbstat_is_explicit_not_fake_page_measurement():
    class MissingDbstat:
        def execute(self, sql):
            raise sqlite3.OperationalError('no such table: dbstat')
    result = compact.optional_dbstat(MissingDbstat())
    assert result['status'] == 'NOT_AVAILABLE' and 'pages' not in result
