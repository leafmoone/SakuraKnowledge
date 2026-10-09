"""Small readonly typed multiset comparison for SQLite tables with nullable keys."""
import itertools


def typed_rows(connection, table, schema='main'):
    quote = lambda name: '"' + name.replace('"', '""') + '"'
    columns = [row[1] for row in connection.execute('PRAGMA ' + quote(schema) + '.table_info(' + quote(table) + ')')]
    if not columns:
        raise ValueError('comparison table missing')
    expressions = [part for column in columns for part in (quote(column) + ' COLLATE BINARY', 'typeof(' + quote(column) + ')')]
    grouped = ','.join(expressions)
    return connection.execute('SELECT ' + grouped + ',count(*) FROM ' + quote(schema) + '.' + quote(table)
                              + ' GROUP BY ' + grouped + ' ORDER BY ' + grouped)


def same_multiset(left, right):
    sentinel = object()
    for a, b in itertools.zip_longest(left, right, fillvalue=sentinel):
        if a != b:
            return False
    return True
