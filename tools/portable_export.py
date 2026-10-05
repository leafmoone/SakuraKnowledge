"""Create new, runtime-only SQLite assets without writing to the source."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

EXCLUDED = frozenset({"occurrences", "source_counts", "unresolved_records"})
RAW_FIELDS = ("raw_attributes", "raw_subject_categories", "raw_cv_names", "raw_gender")
MAPPING_FIELDS = ("entry_key", "document_id", "chunk_id", "source_id", "evidence_id")


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def projection(expression, fields):
    """Keep missing keys missing and preserve JSON scalar lexemes (including big ints).

    The -> operator returns JSON, unlike json_extract's numeric conversion. Using
    those fragments also preserves booleans, arrays, objects and explicit null.
    """
    parts = []
    for name in fields:
        path = "'$." + name + "'"
        prefix = json.dumps(name) + ':'
        parts.append(
            f"CASE WHEN json_type({expression},{path}) IS NULL THEN '' "
            f"ELSE '{prefix}' || ({expression} -> {path}) || ',' END"
        )
    return "'{' || rtrim(" + " || ".join(parts) + ", ',') || '}'"


def document_payload(expression):
    return f"CASE WHEN {expression} IS NULL THEN NULL ELSE {projection(expression, ('search_text_truncated', 'text_provenance'))} END"


def evidence_payload(expression):
    nested = f"({expression} -> '$.raw')"
    return (
        f"CASE WHEN {expression} IS NULL THEN NULL "
        f"WHEN json_type({expression},'$.raw') IS NULL THEN {projection(expression, RAW_FIELDS)} "
        f"WHEN json_type({expression},'$.raw')='object' THEN "
        f"'{{\"raw\":' || ({projection(nested, RAW_FIELDS)}) || '}}' "
        f"ELSE '{{\"raw\":' || {nested} || '}}' END"
    )


def checked(condition, message):
    if not condition:
        raise ValueError(message)


def verify(conn, tables, fts_tables=()):
    checked(conn.execute('PRAGMA main.integrity_check').fetchall() == [('ok',)],
            'output integrity_check failed')
    checked(not conn.execute('PRAGMA main.foreign_key_check').fetchall(),
            'output foreign_key_check failed')
    counts = {}
    for name in tables:
        table = quote(name)
        count = conn.execute(f'SELECT count(*) FROM main.{table}').fetchone()[0]
        expected = conn.execute(f'SELECT count(*) FROM old.{table}').fetchone()[0]
        checked(count == expected, f'row count mismatch: {name}')
        counts[name] = count
    for name in fts_tables:
        table = quote(name)
        for left, right in [('main', 'old'), ('old', 'main')]:
            different = conn.execute(
                f'SELECT rowid FROM {left}.{table} EXCEPT '
                f'SELECT rowid FROM {right}.{table} LIMIT 1').fetchone()
            checked(different is None, f'FTS rowid mismatch: {name}')
    return counts


def _export(source, output, mapping):
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    # Exclusive reservation prevents sqlite3.connect from overwriting an asset.
    with output.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(output, uri=True)) as conn:
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.execute('PRAGMA cache_size=-16384')
            temp = output.parent / 'sqlite-temp'
            temp.mkdir(exist_ok=True)
            conn.execute("PRAGMA temp_store_directory='" + str(temp).replace("'", "''") + "'")
            conn.execute('ATTACH DATABASE ? AS old', (source.as_uri() + '?mode=ro',))
            conn.execute('BEGIN')
            if mapping:
                n, low, high = conn.execute('SELECT count(*),min(position),max(position) FROM old.chunks').fetchone()
                checked(n == 0 or (low == 0 and high == n - 1), 'mapping positions must be contiguous from zero')
                conn.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY,chunk_id TEXT NOT NULL,document_id TEXT NOT NULL,kind TEXT NOT NULL,namespace TEXT NOT NULL,value TEXT NOT NULL,source_id TEXT NOT NULL,evidence_id TEXT NOT NULL)')
                conn.execute("INSERT INTO chunks SELECT position, json_extract(metadata,'$.chunk_id'),json_extract(metadata,'$.document_id'),json_extract(metadata,'$.entry_key.kind'),json_extract(metadata,'$.entry_key.namespace'),json_extract(metadata,'$.entry_key.value'),json_extract(metadata,'$.source_id'),json_extract(metadata,'$.evidence_id') FROM old.chunks")
                tables, fts = ['chunks'], []
                source_positions = conn.execute('SELECT count(*),min(position),max(position) FROM old.chunks').fetchone()
                n, low, high = source_positions
                checked(n == 0 or (low == 0 and high == n - 1), 'mapping positions must be contiguous from zero')
            else:
                schema = conn.execute(
                    "SELECT type,name,tbl_name,sql FROM old.sqlite_master "
                    "WHERE sql IS NOT NULL ORDER BY rowid").fetchall()
                tables = [name for kind, name, _, _ in schema
                          if kind == 'table' and name not in EXCLUDED and not name.startswith('sqlite_')]
                fts = [name for kind, name, _, sql in schema
                       if kind == 'table' and name in tables and sql.lstrip().upper().startswith('CREATE VIRTUAL TABLE')]
                shadows = {row[1] for row in conn.execute('PRAGMA old.table_list') if row[2] == 'shadow'}
                for kind, name, _, sql in schema:
                    if kind == 'table' and name in tables and name not in shadows:
                        conn.execute(sql)
                # Copy FTS shadow pages verbatim, not through the virtual table:
                # rebuilding FTS would change segment structure and BM25 statistics.
                for name in tables:
                    if name in fts:
                        continue
                    table = quote(name)
                    columns = [r[1] for r in conn.execute(f'PRAGMA old.table_xinfo({table})') if r[6] == 0]
                    without_rowid = next(r[4] for r in conn.execute('PRAGMA old.table_list') if r[1] == name)
                    if not without_rowid and not {'rowid', '_rowid_', 'oid'}.intersection(columns):
                        columns.insert(0, 'rowid')
                    selected = []
                    for col in columns:
                        expr = quote(col)
                        if col == 'payload' and name == 'documents':
                            expr = document_payload(expr)
                        elif col == 'payload' and name == 'entry_evidence':
                            expr = evidence_payload(expr)
                        selected.append(expr)
                    if name in shadows:
                        conn.execute(f'DELETE FROM main.{table}')
                    conn.execute(f'INSERT INTO main.{table} ({",".join(map(quote, columns))}) '
                                 f'SELECT {",".join(selected)} FROM old.{table}')
                for kind, name, owner, sql in schema:
                    if kind in ('index', 'trigger', 'view') and owner not in EXCLUDED:
                        conn.execute(sql)
                internal = {r[0] for r in conn.execute("SELECT name FROM old.sqlite_master WHERE name LIKE 'sqlite_%'")}
                if 'sqlite_sequence' in internal:
                    conn.execute('DELETE FROM main.sqlite_sequence')
                    conn.execute('INSERT INTO main.sqlite_sequence SELECT * FROM old.sqlite_sequence WHERE name NOT IN (?,?,?)', tuple(sorted(EXCLUDED)))
                if 'sqlite_stat1' in internal:
                    conn.execute('ANALYZE main')
                    conn.execute('DELETE FROM main.sqlite_stat1')
                    conn.execute('INSERT INTO main.sqlite_stat1 SELECT * FROM old.sqlite_stat1 WHERE tbl NOT IN (?,?,?)', tuple(sorted(EXCLUDED)))
            conn.commit()
            conn.execute('VACUUM main')
            counts = verify(conn, tables, fts)
            return {'output': str(output), 'row_counts': counts, 'integrity': 'ok',
                    'foreign_keys': 'ok', 'fts_rowids': 'ok'}
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def export_db(source, output):
    return _export(source, output, mapping=False)


def export_mapping(source, output):
    return _export(source, output, mapping=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest='command', required=True)
    for name in ('export-db', 'export-mapping'):
        sub = subcommands.add_parser(name)
        sub.add_argument('--source', type=Path, required=True)
        sub.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    action = export_db if args.command == 'export-db' else export_mapping
    print(json.dumps(action(args.source, args.output), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
