"""Experimental, source-bound sample CAS/codec; never a production migration.

Original TEXT columns become content references only in a create-new experimental
DB. FTS retains its original persistent searchable text, rowids and configuration.
No mother DB, ANN/model, upstream processor, or production Core is used or written.
"""
import argparse
import hashlib
import json
import random
import re
import sqlite3
import time
import zlib
from collections import Counter
from contextlib import closing
from pathlib import Path

VERSION = 'bangumi-compact-sample-v1'
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_SEGMENTS = 128
TABLES = ('sources', 'entries', 'entry_evidence', 'aliases', 'documents', 'links',
          'build_meta', 'tag_resolutions')
CONTENT_FIELDS = {'sources': ('metadata',), 'entry_evidence': ('payload',),
                  'aliases': ('payload',), 'documents': ('original', 'payload', 'search_text'),
                  'links': ('payload',), 'tag_resolutions': ('payload',)}
CAS_SCHEMA = """
CREATE TABLE compact_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE content_blobs(id INTEGER PRIMARY KEY,digest TEXT NOT NULL UNIQUE,
 codec TEXT NOT NULL,codec_version INTEGER NOT NULL,uncompressed_bytes INTEGER NOT NULL,
 data BLOB NOT NULL);
CREATE TABLE content_refs(id INTEGER PRIMARY KEY,digest TEXT NOT NULL,
 uncompressed_bytes INTEGER NOT NULL,segments TEXT NOT NULL);
CREATE INDEX content_refs_digest ON content_refs(digest,uncompressed_bytes);
CREATE TABLE compact_search_refs(document_id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL,target_id INTEGER NOT NULL);
"""


def digest_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def small_binding(path):
    path = Path(path)
    return {'path': path.as_posix(), 'bytes': path.stat().st_size,
            'sha256': digest_bytes(path.read_bytes())}


def readonly(path, seconds=60):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA cache_size=-8192')
    conn.execute('PRAGMA temp_store=MEMORY')
    deadline = time.perf_counter() + seconds
    conn.set_progress_handler(lambda: time.perf_counter() > deadline, 2000)
    return conn


def checked_text(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_TEXT_BYTES:
        raise ValueError('invalid or excessive content bytes')
    raw.decode('utf-8', errors='strict')
    return raw


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('invalid content length/reference/count')
    return value


def decode_blob(codec, version, expected, digest, data):
    integer(version, 1)
    integer(expected)
    if version != 1 or expected > MAX_TEXT_BYTES or not isinstance(data, bytes):
        raise ValueError('unsupported codec/length')
    if len(data) > MAX_TEXT_BYTES * 2 or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('invalid digest/stored bytes')
    if codec == 'identity':
        raw = data
    elif codec == 'zlib':
        try:
            stream = zlib.decompressobj()
            raw = stream.decompress(data, expected + 1)
        except zlib.error as error:
            raise ValueError('malformed compressed stream') from error
        if not stream.eof or stream.unused_data or stream.unconsumed_tail:
            raise ValueError('truncated, trailing, or excessive compressed stream')
    else:
        raise ValueError('unknown codec')
    if len(raw) != expected or digest_bytes(raw) != digest:
        raise ValueError('content length/hash mismatch')
    return checked_text(raw)


class ContentStore:
    def __init__(self, conn, compress=True):
        self.conn = conn
        self.compress = compress
        self.counters = Counter()

    def put(self, raw):
        raw = checked_text(raw)
        digest = digest_bytes(raw)
        prior = self.conn.execute('SELECT id,codec,codec_version,uncompressed_bytes,digest,data '
                                  'FROM content_blobs WHERE digest=?', (digest,)).fetchone()
        if prior:
            if decode_blob(*prior[1:]) != raw:
                raise ValueError('content hash collision')
            self.counters['reused_blob_references'] += 1
            return prior[0]
        compressed = zlib.compress(raw, level=6) if self.compress else raw
        codec, data = ('zlib', compressed) if self.compress and len(compressed) < len(raw) else ('identity', raw)
        cursor = self.conn.execute('INSERT INTO content_blobs(digest,codec,codec_version,uncompressed_bytes,data) '
                                   'VALUES(?,?,1,?,?)', (digest, codec, len(raw), data))
        self.counters['new_blobs'] += 1
        return cursor.lastrowid

    def get_blob(self, ref):
        row = self.conn.execute('SELECT codec,codec_version,uncompressed_bytes,digest,data '
                                'FROM content_blobs WHERE id=?', (integer(ref, 1),)).fetchone()
        if row is None:
            raise ValueError('missing content blob')
        return decode_blob(*row)

    def add_ref(self, raw, bodies=()):
        """Canonical JSON-string token substitution, preserving all other bytes.

        Noncanonical escape spellings fall back unchanged to a whole-payload blob.
        Transform refs point at the same *unescaped UTF-8 body* as documents.original.
        Unknown keys, duplicate keys, order and whitespace are never reserialized.
        """
        raw = checked_text(raw)
        replacements = canonical_body_tokens(raw, bodies)
        parts, last = [], 0
        for start, end, body in replacements:
            if start > last:
                parts.append({'blob': self.put(raw[last:start]), 'transform': 'raw'})
            parts.append({'blob': self.put(body), 'transform': 'json_string'})
            last = end
        if last < len(raw) or not parts:
            parts.append({'blob': self.put(raw[last:]), 'transform': 'raw'})
        if len(parts) > MAX_SEGMENTS:
            parts = [{'blob': self.put(raw), 'transform': 'raw'}]
        self.counters['json_body_tokens_referenced'] += len(replacements) if len(parts) > 1 else 0
        segments = json.dumps(parts, separators=(',', ':'))
        digest = digest_bytes(raw)
        previous = self.conn.execute('SELECT id FROM content_refs WHERE digest=? AND uncompressed_bytes=? '
                                     'AND segments=? LIMIT 1', (digest, len(raw), segments)).fetchone()
        if previous:
            return previous[0]
        return self.conn.execute('INSERT INTO content_refs(digest,uncompressed_bytes,segments) VALUES(?,?,?)',
                                 (digest, len(raw), segments)).lastrowid

    def get_ref(self, ref):
        row = self.conn.execute('SELECT digest,uncompressed_bytes,segments FROM content_refs WHERE id=?',
                                (integer(ref, 1),)).fetchone()
        if row is None:
            raise ValueError('missing content reference')
        digest, expected, encoded = row
        integer(expected)
        if expected > MAX_TEXT_BYTES or not isinstance(encoded, str) or len(encoded) > 65536:
            raise ValueError('excessive content recipe')
        parts = json.loads(encoded)
        if not isinstance(parts, list) or not parts or len(parts) > MAX_SEGMENTS:
            raise ValueError('invalid content recipe segments')
        result = bytearray()
        for part in parts:
            if not isinstance(part, dict) or set(part) != {'blob', 'transform'}:
                raise ValueError('invalid recipe segment')
            chunk = self.get_blob(part['blob'])
            if part['transform'] == 'json_string':
                chunk = json.dumps(chunk.decode('utf-8'), ensure_ascii=False).encode('utf-8')
            elif part['transform'] != 'raw':
                raise ValueError('unknown recipe transform')
            if len(result) + len(chunk) > expected:
                raise ValueError('excessive recipe output')
            result.extend(chunk)
        raw = bytes(result)
        if len(raw) != expected or digest_bytes(raw) != digest:
            raise ValueError('recipe length/hash mismatch')
        return checked_text(raw)


def canonical_body_tokens(raw, bodies):
    bodies = set(bodies)
    if not bodies:
        return []
    text = raw.decode('utf-8')
    try:
        json.loads(text)  # Invalid/non-JSON payload is stored verbatim, not parsed away.
    except (ValueError, RecursionError):
        return []
    decoder = json.JSONDecoder()
    tokens, i = [], 0
    while i < len(text):
        if text[i] != '"':
            i += 1
            continue
        value, end = decoder.raw_decode(text, i)
        after = end
        while after < len(text) and text[after].isspace():
            after += 1
        if after < len(text) and text[after] == ':' and value in ('summary', 'original', 'description'):
            start = after + 1
            while start < len(text) and text[start].isspace():
                start += 1
            if start < len(text) and text[start] == '"':
                body, stop = decoder.raw_decode(text, start)
                try:
                    body_raw = body.encode('utf-8')
                except UnicodeEncodeError:
                    i = stop
                    continue  # Escaped lone surrogates: exact whole-payload fallback.
                token = text[start:stop].encode('utf-8')
                if len(body_raw) >= 64 and body_raw in bodies and token == json.dumps(body, ensure_ascii=False).encode('utf-8'):
                    tokens.append((len(text[:start].encode('utf-8')), len(text[:stop].encode('utf-8')), body_raw))
                i = stop
                continue
        i = end
    return tokens


def columns(conn, table):
    return [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]


def selected_rows(conn, table, ids):
    if table in ('sources', 'build_meta'):
        return conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
    result = []
    for ref in sorted(ids):
        result.extend(conn.execute(f'SELECT * FROM {table} WHERE id=?', (integer(ref, 1),)).fetchall())
    return result


def freeze_pool(pack, output):
    """One covering typed-key index pass, no payloads/FTS/dbstat or source rehash."""
    pack, output = Path(pack), Path(output)
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads((pack / 'manifest.json').read_bytes())
    declared = manifest['artifacts']['snapshot']
    db = pack / declared['path']
    if manifest['pack_id'] != 'bangumi' or db.stat().st_size != declared['size']:
        raise ValueError('unexpected source pack size/binding')
    started = time.perf_counter()
    groups, rngs = {}, {}
    with closing(readonly(db, seconds=120)) as conn:
        for kind, namespace, value, eid in conn.execute('SELECT kind,namespace,value,id FROM entries ORDER BY kind,namespace,value'):
            if kind not in groups:
                groups[kind] = {'count': 0, 'min_id': eid, 'max_id': eid, 'reservoir': []}
                rngs[kind] = random.Random('bangumi-compact-v1:' + kind)
            group = groups[kind]
            group['count'] += 1
            group['min_id'], group['max_id'] = min(group['min_id'], eid), max(group['max_id'], eid)
            if len(group['reservoir']) < 768:
                group['reservoir'].append(eid)
            else:
                at = rngs[kind].randrange(group['count'])
                if at < 768:
                    group['reservoir'][at] = eid
    report = {'elapsed_seconds': time.perf_counter() - started,
              'method': 'one covering typed-key index pass; deterministic per-kind reservoir768; no full payload/FTS/dbstat scan',
              'seed_prefix': 'bangumi-compact-v1:', 'groups': groups,
              'source_manifest': small_binding(pack / 'manifest.json'), 'source_snapshot_declared': declared,
              'source_snapshot_hash_reread': False, 'physical_disk_bytes_read': 'UNKNOWN'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    return report


def freeze_selection(pack, pool, output):
    pack, output = Path(pack), Path(output)
    if output.exists():
        raise FileExistsError(output)
    source_manifest = json.loads((pack / 'manifest.json').read_bytes())
    declared = source_manifest['artifacts']['snapshot']
    db = pack / declared['path']
    if source_manifest['pack_id'] != 'bangumi' or db.stat().st_size != declared['size']:
        raise ValueError('unexpected source pack/binding size')
    candidates = json.loads(Path(pool).read_bytes())
    if candidates.get('source_manifest', small_binding(pack / 'manifest.json')) != small_binding(pack / 'manifest.json'):
        raise ValueError('candidate source manifest changed')
    picked, feature_report = set(), {}
    started = time.perf_counter()
    with closing(readonly(db)) as conn:
        if sorted(row[0] for row in conn.execute('SELECT source_id FROM sources')) != sorted(source_manifest['source_ids']):
            raise ValueError('source owner declaration mismatch')
        if conn.execute('SELECT id FROM tag_resolutions LIMIT 1').fetchone() is not None:
            raise ValueError('nonempty tag projection requires explicit sample closure')
        for kind, group in sorted(candidates['groups'].items()):
            features = []
            for eid in group['reservoir']:
                row = conn.execute('SELECT coalesce(max(length(CAST(original AS BLOB))),0),count(*) '
                                   'FROM documents WHERE entry_id=?', (eid,)).fetchone()
                aliases = conn.execute('SELECT count(*) FROM aliases WHERE entry_id=?', (eid,)).fetchone()[0]
                features.append((eid, row[0], row[1], aliases))
            uniform = random.Random('bangumi-compact-selected-v1:' + kind).sample(features, min(128, len(features)))
            long = sorted(features, key=lambda r: (-r[1], r[0]))[:16]
            empty = [r for r in features if r[1] == 0][:16]
            short = sorted((r for r in features if r[1] > 0), key=lambda r: (r[1], r[0]))[:16]
            many = sorted(features, key=lambda r: (-r[2], -r[3], r[0]))[:16]
            picked.update(row[0] for row in uniform + long + empty + short + many)
            feature_report[kind] = {'candidate_count': len(features), 'uniform': len(uniform),
                                    'max_candidate_original_bytes': max(r[1] for r in features),
                                    'empty_candidate_count': sum(r[1] == 0 for r in features),
                                    'max_candidate_documents': max(r[2] for r in features),
                                    'max_candidate_aliases': max(r[3] for r in features),
                                    'selectors': 'uniform + longest16 + shortest_nonempty16 + empty16 + multidoc/alias16'}
        last = conn.execute('SELECT id FROM links ORDER BY id DESC LIMIT 1').fetchone()[0]
        link_rows = []
        for slot in range(512):
            target = 1 + slot * (last - 1) // 511
            row = conn.execute('SELECT id,src,dst,relation,verification_status FROM links WHERE id>=? ORDER BY id LIMIT 1',
                               (target,)).fetchone()
            if row:
                link_rows.append(row)
                picked.update(row[1:3])
        table_ids = {'entries': sorted(picked), 'links': sorted({r[0] for r in link_rows}), 'tag_resolutions': []}
        for table in ('documents', 'entry_evidence', 'aliases'):
            table_ids[table] = sorted({row[0] for eid in sorted(picked)
                                      for row in conn.execute(f'SELECT id FROM {table} WHERE entry_id=?', (eid,))})
        # One metadata-only FTS pass preserves *all* selected document occurrences,
        # including duplicate rows and arbitrary rowids. Never infer rowid=docid.
        fts_rows, fts_scanned = [], 0
        selected_documents = set(table_ids['documents'])
        fts_started = time.perf_counter()
        for row in conn.execute('SELECT rowid,document_id,entry_id FROM search_fts ORDER BY rowid'):
            fts_scanned += 1
            if row[1] in selected_documents:
                if row[2] not in picked:
                    raise ValueError('selected FTS entry closure missing')
                fts_rows.append(row)
        fts_metadata_seconds = time.perf_counter() - fts_started
        schema = conn.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        storage = {key: conn.execute('PRAGMA ' + key).fetchone()[0]
                   for key in ('page_size', 'page_count', 'freelist_count')}
        fts_config = conn.execute('SELECT k,v FROM search_fts_config ORDER BY k').fetchall()
    selection = {'version': VERSION, 'source_pack': pack.as_posix(),
                 'source_manifest': small_binding(pack / 'manifest.json'),
                 'source_snapshot_declared': declared, 'source_snapshot_bytes_verified': db.stat().st_size,
                 'source_snapshot_hash_reread': False, 'source_stat': {'mtime_ns': db.stat().st_mtime_ns},
                 'candidate_pool_binding': small_binding(pool), 'index_only_pass_seconds': candidates['elapsed_seconds'],
                 'selection_probe_seconds': time.perf_counter() - started,
                 'table_ids': table_ids, 'fts_metadata': fts_rows, 'fts_config': fts_config,
                 'features': feature_report, 'sample_link_statuses': dict(Counter(r[4] for r in link_rows)),
                 'sample_link_relations': dict(Counter(r[3] for r in link_rows)), 'schema': schema,
                 'storage_light': storage, 'full_dbstat_or_payload_scan': 'NOT_RUN',
                 'method': 'deterministic typed-key index reservoir + bounded feature probes; 512 evenly spaced link PK seeks and endpoint closure',
                 'FTS_scope': 'one full FTS metadata pass; all occurrences for selected documents, not full-library rank validation',
                 'fts_metadata_rows_scanned': fts_scanned, 'fts_metadata_seconds': fts_metadata_seconds,
                 'unresolved_scope': 'sealed source pack has no unresolved_records table; no upstream raw records read'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(selection, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    return selection


def extract_sample(selection, baseline):
    baseline = Path(baseline)
    if baseline.exists():
        raise FileExistsError(baseline)
    source_path = Path(selection['source_pack']) / selection['source_snapshot_declared']['path']
    source_stat = source_path.stat()
    if (source_stat.st_size != selection['source_snapshot_bytes_verified'] or
            source_stat.st_mtime_ns != selection['source_stat']['mtime_ns'] or
            small_binding(Path(selection['source_pack']) / 'manifest.json') != selection['source_manifest']):
        raise ValueError('frozen source binding changed')
    started = time.perf_counter()
    baseline.touch(exist_ok=False)  # Exclusive reservation, never open an old DB for writing.
    with closing(readonly(source_path)) as source, closing(sqlite3.connect(baseline)) as target:
        target.execute('PRAGMA foreign_keys=ON')
        target.execute('PRAGMA journal_mode=DELETE')
        for name, typ, sql in selection['schema']:
            if typ == 'table' and name in TABLES:
                target.execute(sql)
        fts_sql = next(row[2] for row in selection['schema'] if row[0] == 'search_fts')
        target.execute(fts_sql)
        for table in TABLES:
            rows = selected_rows(source, table, selection['table_ids'].get(table, ()))
            marks = ','.join('?' for _ in columns(source, table))
            target.executemany(f'INSERT INTO {table} VALUES({marks})', rows)
        for rowid, did, eid in selection['fts_metadata']:
            row = source.execute('SELECT rowid,text,document_id,entry_id FROM search_fts WHERE rowid=?', (rowid,)).fetchone()
            if row is None or row[2:] != (did, eid):
                raise ValueError('frozen FTS metadata changed')
            target.execute('INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES(?,?,?,?)', row)
        for key, value in selection['fts_config']:
            if key != 'version':
                target.execute('INSERT INTO search_fts(search_fts,rank) VALUES(?,?)', (key, value))
        for name, typ, sql in selection['schema']:
            if typ == 'index' and sql:
                target.execute(sql)
        target.commit()
        if target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('baseline sample reference closure')
    if source_path.stat().st_size != source_stat.st_size or source_path.stat().st_mtime_ns != source_stat.st_mtime_ns:
        raise ValueError('source stat changed during sample extraction')
    return {'read_and_sample_build_seconds': time.perf_counter() - started, 'bytes': baseline.stat().st_size,
            'source_stat_before_after_equal': True, 'actual_physical_disk_bytes_read': 'UNKNOWN'}


def build_compact(baseline, output, compress=True):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    output.touch(exist_ok=False)
    with closing(readonly(baseline)) as source, closing(sqlite3.connect(output)) as target:
        schema = source.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        target.execute('PRAGMA foreign_keys=ON')
        target.executescript(CAS_SCHEMA)
        target.execute('INSERT INTO compact_meta VALUES(?,?)', ('format', VERSION))
        for name, typ, sql in schema:
            if typ == 'table' and name in TABLES:
                # All identity/proof/index columns stay unchanged; only designated
                # TEXT body/payload columns are experiment-only integer recipe refs.
                for field in CONTENT_FIELDS.get(name, ()):
                    sql = re.sub(r'\b' + field + r' TEXT\b', field + ' INTEGER', sql)
                target.execute(sql)
        fts_sql = next(row[2] for row in schema if row[0] == 'search_fts')
        target.execute(fts_sql)
        target.executemany('INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES(?,?,?,?)',
                           source.execute('SELECT rowid,text,document_id,entry_id FROM search_fts ORDER BY rowid'))
        for key, value in source.execute('SELECT k,v FROM search_fts_config ORDER BY k'):
            if key != 'version':
                target.execute('INSERT INTO search_fts(search_fts,rank) VALUES(?,?)', (key, value))
        fts_by_document = {}
        for rowid, text, did, eid in source.execute('SELECT rowid,text,document_id,entry_id FROM search_fts ORDER BY rowid'):
            fts_by_document.setdefault(did, []).append((rowid, text, eid))
        store = ContentStore(target, compress)
        bodies = {row[0].encode('utf-8') for row in source.execute('SELECT original FROM documents WHERE original IS NOT NULL')}
        measurements = Counter()
        for table in TABLES:
            cols = columns(source, table)
            fields = set(CONTENT_FIELDS.get(table, ()))
            insert = f'INSERT INTO {table} VALUES(' + ','.join('?' for _ in cols) + ')'
            for row in source.execute(f'SELECT * FROM {table} ORDER BY 1'):
                values = list(row)
                for i, field in enumerate(cols):
                    if field not in fields or values[i] is None:
                        continue
                    raw = values[i].encode('utf-8')
                    measurements[table + '.' + field + '.original_bytes'] += len(raw)
                    if table == 'documents' and field == 'search_text':
                        did = row[cols.index('id')]
                        occurrences = fts_by_document.get(did, [])
                        fts = occurrences[0] if len(occurrences) == 1 else None
                        if fts and fts[2] == row[cols.index('entry_id')] and fts[1].encode('utf-8') == raw:
                            target.execute('INSERT INTO compact_search_refs VALUES(?,?,?)', (did, 'fts', fts[0]))
                            values[i] = None
                            measurements['search_text_refs_to_existing_FTS'] += 1
                            continue
                        ref = store.add_ref(raw)
                        target.execute('INSERT INTO compact_search_refs VALUES(?,?,?)', (did, 'content', ref))
                        values[i] = None
                    else:
                        values[i] = store.add_ref(raw, bodies if field == 'payload' else ())
                target.execute(insert, values)
        for name, typ, sql in schema:
            if typ == 'index' and sql:
                target.execute(sql)
        target.execute("INSERT INTO search_fts(search_fts) VALUES('integrity-check')")
        target.commit()
        if target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('compact metadata FK closure')
        for codec, count, original, stored in target.execute('SELECT codec,count(*),sum(uncompressed_bytes),sum(length(data)) FROM content_blobs GROUP BY codec'):
            measurements['codec.' + codec + '.blobs'] = count
            measurements['codec.' + codec + '.uncompressed_bytes'] = original
            measurements['codec.' + codec + '.stored_bytes'] = stored
        measurements.update(store.counters)
    return {'build_seconds': time.perf_counter() - started, 'bytes': output.stat().st_size,
            'measurements': dict(measurements), 'compression': 'zlib level6 with smaller-only guard' if compress else 'identity-only CAS'}


def materialize(conn, table, row):
    cols = columns(conn, table)
    values = list(row)
    store = ContentStore(conn)
    for field in CONTENT_FIELDS.get(table, ()):
        i = cols.index(field)
        if table == 'documents' and field == 'search_text':
            did = row[cols.index('id')]
            ref = conn.execute('SELECT kind,target_id FROM compact_search_refs WHERE document_id=?', (did,)).fetchone()
            if ref is None:
                if values[i] is not None:
                    raise ValueError('unbound compact search field')
                continue  # Preserve SQL NULL, rather than replacing it with empty text.
            kind, target = ref
            integer(target, 1)
            if kind == 'fts':
                fts = conn.execute('SELECT text,document_id,entry_id FROM search_fts WHERE rowid=?', (target,)).fetchone()
                if fts is None or fts[1:] != (did, row[cols.index('entry_id')]):
                    raise ValueError('missing or mismatched FTS reference')
                values[i] = fts[0]
            elif kind == 'content':
                values[i] = store.get_ref(target).decode('utf-8')
            else:
                raise ValueError('invalid compact search reference kind')
        elif values[i] is not None:
            values[i] = store.get_ref(values[i]).decode('utf-8')
    return tuple(values)


def fts_ranking(conn, query):
    # Identical sample corpus, persisted tokenization and original rowid tie order.
    return conn.execute("SELECT rowid,document_id,entry_id,bm25(search_fts) FROM search_fts "
                        "WHERE search_fts MATCH ? ORDER BY bm25(search_fts),rowid LIMIT 100", (query,)).fetchall()


def search_materialized(conn, query, compact=False):
    rows = conn.execute("SELECT f.rowid,d.id,e.id,e.kind,e.namespace,e.value,bm25(search_fts) "
                        "FROM search_fts f JOIN documents d ON d.id=f.document_id "
                        "JOIN entries e ON e.id=f.entry_id WHERE search_fts MATCH ? AND e.conflicted=0 "
                        "AND d.status IN ('source_backed','generated_from_evidence') "
                        "AND EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed') "
                        "ORDER BY bm25(search_fts),e.kind,e.namespace,e.value,f.rowid LIMIT 100", (query,)).fetchall()
    hits = []
    for rowid, did, eid, kind, namespace, value, score in rows:
        doc = conn.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
        if compact:
            doc = materialize(conn, 'documents', doc)
        hits.append({'rowid': rowid, 'document_id': did, 'entry_id': eid,
                     'key': (kind, namespace, value), 'score': score, 'document': doc,
                     'citation': (doc[7], doc[8])})
    return hits


def validate_pair(baseline, compact):
    started = time.perf_counter()
    counts, status_counts = {}, {}
    with closing(readonly(baseline)) as source, closing(readonly(compact)) as target:
        if target.execute("SELECT value FROM compact_meta WHERE key='format'").fetchone() != (VERSION,):
            raise ValueError('unsupported compact format')
        for table in TABLES:
            expected = source.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
            restored = [materialize(target, table, row) for row in target.execute(f'SELECT * FROM {table} ORDER BY 1')]
            if (expected != restored or len(expected) != len(restored) or
                    any(type(a) is not type(b) for left, right in zip(expected, restored) for a, b in zip(left, right))):
                raise ValueError('exact typed/UTF-8 row roundtrip failed: ' + table)
            counts[table] = len(expected)
            cols = columns(source, table)
            field = 'status' if 'status' in cols else 'verification_status' if 'verification_status' in cols else None
            if field:
                status_counts[table] = dict(Counter(row[cols.index(field)] for row in expected))
        oldfts = source.execute('SELECT rowid,text,document_id,entry_id FROM search_fts ORDER BY rowid').fetchall()
        if oldfts != target.execute('SELECT rowid,text,document_id,entry_id FROM search_fts ORDER BY rowid').fetchall():
            raise ValueError('FTS row content/id/multiplicity mismatch')
        if source.execute('SELECT * FROM search_fts_config ORDER BY k').fetchall() != target.execute('SELECT * FROM search_fts_config ORDER BY k').fetchall():
            raise ValueError('FTS configuration mismatch')
        terms = sorted({text.split()[0] for _, text, _, _ in oldfts if text.split()})
        selected_terms = random.Random('bangumi-compact-fts-gold-v1').sample(terms, min(48, len(terms)))
        for term in selected_terms:
            query = '"' + term.replace('"', '""') + '"'
            if fts_ranking(source, query) != fts_ranking(target, query):
                raise ValueError('sample FTS ranking/score mismatch')
            if search_materialized(source, query) != search_materialized(target, query, compact=True):
                raise ValueError('sample trusted retrieval/key/full text/citation mismatch')
        if target.execute('PRAGMA integrity_check').fetchone() != ('ok',) or target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('compact sample integrity/reference failure')
    return {'status': 'PASS', 'rows': counts, 'status_counts': status_counts, 'fts_rows': len(oldfts),
            'sample_fts_queries': len(selected_terms), 'exact_row_bytes_types': True,
            'exact_FTS_rowids_text_metadata_multiplicity_rank_scores': True,
            'exact_trusted_sample_results_document_keys_fulltext_citations': True,
            'FTS_ref_hash_scope': 'FTS referenced text is verified by baseline roundtrip/artifact binding, not per-read CAS hash',
            'seconds': time.perf_counter() - started,
            'scope': 'same frozen sample; NOT full-library retrieval/ANN/identity promotion validation'}


def benchmark_pair(baseline, compact):
    """Same complete rows, including ref lookups, decoding, UTF-8/hash verification."""
    report = {}
    with closing(readonly(baseline)) as conn:
        terms = sorted({row[0].split()[0] for row in conn.execute('SELECT text FROM search_fts') if row[0].split()})
    queries = ['"' + term.replace('"', '""') + '"' for term in random.Random('bangumi-compact-fts-gold-v1').sample(terms, min(48, len(terms)))]
    for label, path in (('baseline', baseline), ('compact', compact)):
        start = time.perf_counter()
        with closing(readonly(path)) as conn:
            opened = time.perf_counter()
            passes = []
            for _ in range(4):
                stage = time.perf_counter()
                byte_count, count = 0, 0
                for table in TABLES:
                    for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1'):
                        values = materialize(conn, table, row) if label == 'compact' else row
                        count += 1
                        byte_count += sum(len(value.encode('utf-8')) for value in values if isinstance(value, str))
                passes.append({'ms': (time.perf_counter() - stage) * 1000, 'rows': count, 'text_bytes': byte_count})
            query_passes = []
            for _ in range(3):
                stage = time.perf_counter()
                hits = sum(len(search_materialized(conn, query, compact=label == 'compact')) for query in queries)
                query_passes.append({'ms': (time.perf_counter() - stage) * 1000, 'queries': len(queries), 'hits': hits})
            report[label] = {'open_ms': (opened - start) * 1000, 'first_pass': passes[0], 'warm_passes': passes[1:],
                             'FTS_select_and_materialize_passes': query_passes}
    report['cache_scope'] = 'first connection/pass, OS cache NOT flushed; warm includes decompress/hash/ref lookups, no decoded-content cache'
    return report


def optional_dbstat(conn):
    try:
        return {'status': 'PASS', 'pages': conn.execute('SELECT name,sum(pgsize) FROM dbstat GROUP BY name ORDER BY name').fetchall()}
    except sqlite3.OperationalError as error:
        if str(error) != 'no such table: dbstat':
            raise
        return {'status': 'NOT_AVAILABLE', 'reason': 'this SQLite build does not expose dbstat',
                'sqlite_version': sqlite3.sqlite_version, 'full_physical_file_bytes_still_measured': True}


def run_sample(selection_path, output):
    selection_path, output = Path(selection_path), Path(output)
    if output.exists():
        raise FileExistsError(output)
    selection = json.loads(selection_path.read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    baseline, dedup, compact = (output / name for name in ('baseline.sqlite', 'cas-identity.sqlite', 'cas-zlib.sqlite'))
    report = {'version': VERSION, 'status': 'FAIL', 'selection': small_binding(selection_path),
              'source_mutated': False, 'production_runtime_compatible': False,
              'full9GB_compact_database': 'NOT_RUN', 'model_ANN_queries_or_builds': 'NOT_RUN'}
    try:
        report['baseline'] = extract_sample(selection, baseline)
        report['dedup_only'] = build_compact(baseline, dedup, compress=False)
        report['compressed'] = build_compact(baseline, compact, compress=True)
        report['dedup_validation'] = validate_pair(baseline, dedup)
        report['compressed_validation'] = validate_pair(baseline, compact)
        report['latency'] = benchmark_pair(baseline, compact)
        with closing(readonly(baseline)) as conn:
            raw_payloads = conn.execute('SELECT payload FROM entry_evidence').fetchall()
            report['actual_entry_evidence_raw_empty_count'] = sum(json.loads(row[0]).get('raw') == {} for row in raw_payloads)
            report['actual_entry_evidence_count'] = len(raw_payloads)
            # Table accounting is for these small experimental files, not the9GB source.
            report['baseline_dbstat'] = optional_dbstat(conn)
        with closing(readonly(compact)) as conn:
            report['compact_dbstat'] = optional_dbstat(conn)
        report['sample_physical_reduction_fraction'] = 1 - compact.stat().st_size / baseline.stat().st_size
        report['assets'] = [small_binding(path) for path in (baseline, dedup, compact)]
        report['status'] = 'PASS'
    except (ValueError, TypeError, OSError, sqlite3.Error) as error:
        report['error'] = repr(error)
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('pool', 'freeze', 'sample'))
    parser.add_argument('--pack')
    parser.add_argument('--pool')
    parser.add_argument('--selection')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'pool':
        result = freeze_pool(args.pack, args.output)
        print(json.dumps({'groups': {key: group['count'] for key, group in result['groups'].items()},
                          'seconds': result['elapsed_seconds']}))
    elif args.command == 'freeze':
        result = freeze_selection(args.pack, args.pool, args.output)
        print(json.dumps({'frozen_entries': len(result['table_ids']['entries']),
                          'FTS_rows': len(result['fts_metadata']), 'seconds': result['selection_probe_seconds']}))
    else:
        result = run_sample(args.selection, args.output)
        print(json.dumps({key: result[key] for key in ('status', 'baseline', 'dedup_only', 'compressed', 'sample_physical_reduction_fraction')}))


if __name__ == '__main__':
    main()
