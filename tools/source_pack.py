"""Read-only source-family projections; never builds vectors or runs the full job."""
import argparse
import hashlib
import json
import sqlite3
import struct
from contextlib import closing
from pathlib import Path

try:
    from .portable_export import checked, document_payload, evidence_payload, quote
except ImportError:
    from portable_export import checked, document_payload, evidence_payload, quote

FAMILIES = {'danbooru': 'danbooru', 'bangumi': 'bangumi',
            'moegirl': 'moegirl', 'mapping': 'moegirl', 'tag_wiki': 'tag-wiki'}
TABLES = ('sources', 'entries', 'entry_evidence', 'aliases', 'documents', 'links',
          'tag_resolutions', 'build_meta', 'search_fts')
TRUST = """e.conflicted=0 AND d.status IN ('source_backed','generated_from_evidence')
 AND length(trim(d.evidence_id))>0
 AND EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id
            AND v.status='source_backed')"""


def readonly(path):
    return sqlite3.connect(Path(path).resolve(strict=True).as_uri() + '?mode=ro', uri=True)


def binding(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': path.name, 'sha256': digest.hexdigest(), 'size': path.stat().st_size}


def source_catalog(conn, counts=False):
    result = []
    for sid, raw in conn.execute('SELECT source_id,metadata FROM sources ORDER BY source_id'):
        metadata = json.loads(raw)
        checked(isinstance(metadata, dict), 'source metadata must be an object: ' + sid)
        family = FAMILIES.get(metadata.get('provider'))
        row = {'source_id': sid, 'family': family or 'unassigned', 'metadata': metadata}
        if counts:
            row['table_counts'] = {
                table: conn.execute(f'SELECT count(*) FROM {quote(table)} WHERE source_id=?', (sid,)).fetchone()[0]
                for table in ('sources', 'entry_evidence', 'aliases', 'documents', 'links', 'tag_resolutions')}
        result.append(row)
    return result


def list_sources(mother):
    with closing(readonly(mother)) as conn:
        return {'sources': source_catalog(conn, counts=True)}


def reserve(path):
    with Path(path).open('xb'):
        pass


def build_database(mother, output, source_ids):
    """Clone the actual runtime schema, retaining globally stable original IDs."""
    output = Path(output)
    reserve(output)
    try:
        with closing(sqlite3.connect(output, uri=True)) as conn:
            conn.execute("PRAGMA temp_store_directory='" + str(output.parent).replace("'", "''") + "'")
            conn.execute('PRAGMA cache_size=-16384')
            conn.execute('ATTACH DATABASE ? AS old', (Path(mother).resolve(strict=True).as_uri() + '?mode=ro',))
            conn.execute('CREATE TEMP TABLE selected(source_id TEXT PRIMARY KEY)')
            conn.executemany('INSERT INTO selected VALUES(?)', ((sid,) for sid in source_ids))
            schema = conn.execute('SELECT type,name,tbl_name,sql FROM old.sqlite_master WHERE sql IS NOT NULL ORDER BY rowid').fetchall()
            definitions = {name: sql for kind, name, _, sql in schema if kind == 'table'}
            checked(set(TABLES) <= definitions.keys(), 'mother lacks required runtime tables')
            for name in TABLES:
                conn.execute(definitions[name])
            conn.execute('INSERT INTO sources SELECT s.* FROM old.sources s JOIN selected USING(source_id)')
            for table in ('entry_evidence', 'aliases', 'documents', 'links', 'tag_resolutions', 'build_meta'):
                cols = [r[1] for r in conn.execute(f'PRAGMA old.table_info({quote(table)})')]
                exprs = []
                for col in cols:
                    expr = 's.' + quote(col)
                    if col == 'payload' and table == 'documents':
                        expr = document_payload(expr)
                    elif col == 'payload' and table == 'entry_evidence':
                        expr = evidence_payload(expr)
                    exprs.append(expr)
                where = '' if table == 'build_meta' else ' WHERE s.source_id IN (SELECT source_id FROM selected)'
                conn.execute(f'INSERT INTO {quote(table)} SELECT {",".join(exprs)} FROM old.{quote(table)} s{where}')
            # Build indexes before per-entry proof lookup; full inputs have millions of rows.
            for kind, _, owner, sql in schema:
                if kind == 'index' and owner in TABLES:
                    conn.execute(sql)
            conn.execute('CREATE INDEX IF NOT EXISTS source_pack_evidence_entry ON entry_evidence(entry_id,status)')
            conn.execute('CREATE TEMP TABLE needed(id INTEGER PRIMARY KEY)')
            for table, column in (('entry_evidence', 'entry_id'), ('aliases', 'entry_id'),
                                  ('documents', 'entry_id'), ('links', 'src'), ('links', 'dst'),
                                  ('tag_resolutions', 'target')):
                conn.execute(f'INSERT OR IGNORE INTO needed SELECT {column} FROM {table} WHERE {column} IS NOT NULL')
            # Endpoint-only rows carry identity, not another family's proof or locator.
            conn.execute("""INSERT INTO entries SELECT e.id,e.kind,e.namespace,e.value,
                (SELECT v.type FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed' ORDER BY v.id LIMIT 1),
                (SELECT v.locator FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed' ORDER BY v.id LIMIT 1),
                e.conflicted FROM old.entries e JOIN needed n ON n.id=e.id""")
            conn.execute(f"""INSERT INTO search_fts(rowid,text,document_id,entry_id)
                SELECT f.rowid,f.text,f.document_id,f.entry_id FROM old.search_fts f
                JOIN documents d ON d.id=f.document_id JOIN entries e ON e.id=d.entry_id
                WHERE f.entry_id=e.id AND {TRUST}""")
            conn.execute("INSERT INTO search_fts(search_fts) VALUES('integrity-check')")
            checked(not conn.execute('PRAGMA foreign_key_check').fetchall(), 'source foreign keys failed')
            conn.commit()
            checked(conn.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'source integrity failed')
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return binding(output)


def build_mapping(mapping, snapshot, output, positions):
    """Local ANN key equals position; original_position selects the unchanged NPY row."""
    output, positions = Path(output), Path(positions)
    reserve(output)
    created_positions = False
    try:
        with positions.open('xb') as stream, closing(sqlite3.connect(output, uri=True)) as conn:
            created_positions = True
            conn.execute('ATTACH DATABASE ? AS old', (Path(mapping).resolve(strict=True).as_uri() + '?mode=ro',))
            conn.execute('ATTACH DATABASE ? AS selected', (Path(snapshot).resolve(strict=True).as_uri() + '?mode=ro',))
            conn.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY, original_position INTEGER NOT NULL UNIQUE, chunk_id TEXT NOT NULL UNIQUE, document_id INTEGER NOT NULL, kind TEXT NOT NULL, namespace TEXT NOT NULL, value TEXT NOT NULL, source_id TEXT NOT NULL, evidence_id TEXT NOT NULL)')
            # Ownership must resolve to the actual selected document AND typed entry.
            with closing(conn.execute(f"""SELECT c.position,
                json_extract(c.metadata,'$.chunk_id'), d.id,e.kind,e.namespace,e.value,d.source_id,d.evidence_id
                FROM old.chunks c JOIN selected.documents d ON d.id=json_extract(c.metadata,'$.document_id')
                JOIN selected.entries e ON e.id=d.entry_id
                WHERE json_extract(c.metadata,'$.source_id')=d.source_id
                AND json_extract(c.metadata,'$.evidence_id')=d.evidence_id
                AND json_extract(c.metadata,'$.entry_key.kind')=e.kind
                AND json_extract(c.metadata,'$.entry_key.namespace')=e.namespace
                AND json_extract(c.metadata,'$.entry_key.value')=e.value
                AND {TRUST.replace('FROM entry_evidence', 'FROM selected.entry_evidence')}
                ORDER BY c.position""")) as rows:
                count = 0
                for row in rows:
                    checked(type(row[0]) is int and row[0] >= 0, 'invalid original position')
                    conn.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?)', (count, *row))
                    stream.write(struct.pack('<Q', row[0]))
                    count += 1
            conn.commit()
    except BaseException:
        output.unlink(missing_ok=True)
        if created_positions:
            positions.unlink(missing_ok=True)
        raise
    return {'rows': count, 'mapping': binding(output), 'positions': binding(positions)}


def build_membership(snapshot, output):
    output = Path(output)
    snapshot_binding = binding(snapshot)
    with closing(readonly(snapshot)) as src:
        identity = src.execute("SELECT value FROM build_meta WHERE key='snapshot'").fetchone()
        checked(identity is not None, 'missing snapshot identity')
    reserve(output)
    try:
        with closing(sqlite3.connect(output, uri=True)) as conn:
            conn.execute('ATTACH DATABASE ? AS selected', (Path(snapshot).resolve(strict=True).as_uri() + '?mode=ro',))
            conn.execute('CREATE TABLE members(fts_rowid INTEGER PRIMARY KEY,entry_id INTEGER NOT NULL,document_id INTEGER NOT NULL)')
            conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            conn.execute('INSERT INTO members SELECT rowid,entry_id,document_id FROM selected.search_fts')
            count = conn.execute('SELECT count(*) FROM members').fetchone()[0]
            meta = {'version': 'p4-full-membership-v1', 'snapshot_sha256': snapshot_binding['sha256'],
                    'snapshot_size': str(snapshot_binding['size']), 'snapshot_identity': 'knowledge.sqlite', 'rows': str(count)}
            conn.executemany('INSERT INTO meta VALUES(?,?)', meta.items())
            conn.commit()
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {**meta, 'rows': count, 'snapshot_size': snapshot_binding['size']}


def finalize_manifest(output, source, source_ids, namespaces, *, version='1', index_prepared=False):
    """Publish last; already completed DB assets may be finalized without recopying."""
    output = Path(output)
    checked(not (output / 'manifest.json').exists(), 'manifest already exists')
    checked(not index_prepared or source in ('danbooru', 'bangumi'), 'lexical-only source cannot publish ANN')
    artifacts = {key: binding(output / name) for key, name in
                 (('snapshot', 'knowledge.sqlite'), ('lexical_membership', 'lexical-membership.sqlite'))}
    if source in ('danbooru', 'bangumi'):
        artifacts['mapping'] = binding(output / 'mapping.sqlite')
    if index_prepared:
        artifacts['index'] = binding(output / 'vectors.i8.usearch')
    manifest = {'schema': 'sakura-source-pack-v1', 'pack_id': source, 'display_name': source,
                'version': version, 'capabilities': ['structured', 'lexical'] + (['semantic'] if index_prepared else []),
                'source_ids': sorted(source_ids), 'namespaces': sorted(namespaces),
                'requires_model': 'bge-m3' if source in ('danbooru', 'bangumi') else None,
                'artifacts': artifacts}
    with closing(sqlite3.connect(output/'lexical-membership.sqlite')) as conn:
        meta=dict(conn.execute('SELECT key,value FROM meta'))
    manifest['lexical_membership']={**meta,'rows':int(meta['rows']),'snapshot_size':int(meta['snapshot_size'])}
    manifest['artifacts']['snapshot']['identity']='knowledge.sqlite'
    manifest['trusted_fts_documents']=manifest['lexical_membership']['rows']
    manifest['lexical_mode']='exact_alias_only' if source in ('moegirl', 'tag-wiki') else 'trusted_documents_and_identity'
    if index_prepared:
        with closing(readonly(output/'mapping.sqlite')) as conn:
            rows=conn.execute('SELECT count(*) FROM chunks').fetchone()[0]
        manifest['semantic']={'rows':rows,'dimension':1024,'metric':'cos','dtype':'i8','connectivity':16,'expansion_add':256,'expansion_search':2048,'chunk_depth':512,'entry_depth':100}
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    return manifest


def build(source, mother, mapping, output, *, index_prepared=False):
    checked(source in set(FAMILIES.values()), 'unknown source family: ' + source)
    with closing(readonly(mother)) as conn:
        catalog = source_catalog(conn)
    unassigned = [r['source_id'] for r in catalog if r['family'] == 'unassigned']
    checked(not unassigned, 'unassigned source metadata: ' + ', '.join(unassigned))
    source_ids = [r['source_id'] for r in catalog if r['family'] == source]
    checked(bool(source_ids), 'no sources for family: ' + source)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output / 'knowledge.sqlite'
    build_database(mother, snapshot, source_ids)
    projected = build_mapping(mapping, snapshot, output / 'mapping.sqlite', output / 'positions.u64le') if source in ('danbooru', 'bangumi') else {'rows': 0}
    membership = build_membership(snapshot, output / 'lexical-membership.sqlite')
    with closing(readonly(snapshot)) as conn:
        namespaces = [r[0] for r in conn.execute('SELECT DISTINCT namespace FROM entries ORDER BY namespace')]
    manifest = finalize_manifest(output, source, source_ids, namespaces, index_prepared=index_prepared) if source not in ('danbooru', 'bangumi') or index_prepared else None
    return {'manifest': manifest, 'mapping_rows': projected['rows'], 'lexical_membership': membership}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list-sources')
    listing.add_argument('--mother', type=Path, required=True)
    builder = commands.add_parser('build')
    builder.add_argument('--source', required=True)
    for name in ('mother', 'mapping', 'output'):
        builder.add_argument('--' + name, type=Path, required=True)
    builder.add_argument('--index-prepared', action='store_true')
    finalizer = commands.add_parser('finalize')
    finalizer.add_argument('--source', required=True)
    finalizer.add_argument('--output', type=Path, required=True)
    finalizer.add_argument('--index-prepared', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'list-sources':
        result = list_sources(args.mother)
    elif args.command == 'finalize':
        with closing(readonly(args.output/'knowledge.sqlite')) as conn:
            source_ids=[r[0] for r in conn.execute('SELECT source_id FROM sources')]
            namespaces=[r[0] for r in conn.execute('SELECT DISTINCT namespace FROM entries')]
        result=finalize_manifest(args.output,args.source,source_ids,namespaces,index_prepared=args.index_prepared)
    else:
        result=build(args.source, args.mother, args.mapping, args.output, index_prepared=args.index_prepared)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
