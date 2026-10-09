import sqlite3

from tools.sqlite_multiset import same_multiset, typed_rows


def test_nocase_column_does_not_hide_distinct_source_bytes():
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE a(v TEXT COLLATE NOCASE)'); c.execute('CREATE TABLE b(v TEXT COLLATE NOCASE)')
    c.executemany('INSERT INTO a VALUES(?)', [('A',), ('A',), ('a',)])
    c.executemany('INSERT INTO b VALUES(?)', [('A',), ('a',), ('a',)])
    assert not same_multiset(typed_rows(c, 'a'), typed_rows(c, 'b'))
    c.close()


def test_counts_and_distinct_sets_do_not_prove_multiplicity():
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE a(v TEXT)'); c.execute('CREATE TABLE b(v TEXT)')
    c.executemany('INSERT INTO a VALUES(?)', [('a',), ('a',), ('b',)])
    c.executemany('INSERT INTO b VALUES(?)', [('a',), ('b',), ('b',)])
    assert c.execute('SELECT count(*) FROM a').fetchone() == c.execute('SELECT count(*) FROM b').fetchone()
    assert c.execute('SELECT v FROM a EXCEPT SELECT v FROM b').fetchall() == []
    assert not same_multiset(typed_rows(c, 'a'), typed_rows(c, 'b'))
    c.close()


def test_typed_binary_rows_preserve_nulls_and_duplicate_counts():
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE a(v)'); c.execute('CREATE TABLE b(v)')
    c.executemany('INSERT INTO a VALUES(?)', [(None,), (None,), (1,), ('x',)])
    c.executemany('INSERT INTO b VALUES(?)', [(None,), (1.0,), (None,), ('x',)])
    assert not same_multiset(typed_rows(c, 'a'), typed_rows(c, 'b'))
    c.execute('DELETE FROM b'); c.execute('INSERT INTO b SELECT * FROM a')
    assert same_multiset(typed_rows(c, 'a'), typed_rows(c, 'b'))
    c.close()
