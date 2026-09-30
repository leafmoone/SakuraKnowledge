"""Single authorized read-only metadata/EXPLAIN diagnostic, never run S02."""
import json
import re
import sqlite3
from pathlib import Path

from p3_evidence import save, store

ROOT = Path(__file__).resolve().parents[1]
RAW = Path('reports/P3/close-raw')
OUT = ROOT / 'reports/P3/close-diagnosis.json'


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    source = (ROOT / 'rust/src/search.rs').read_text(encoding='utf-8')
    sql = re.search(r'pub const SQL: &str = "(.*?)";', source, re.DOTALL).group(1)
    sql = sql.replace('search_fts.rank AS score', 'bm25(search_fts) AS score')
    sql = sql.replace('ORDER BY search_fts.rank', 'ORDER BY score,e.kind,e.namespace,e.value,search_fts.rowid')
    sql = sql.replace('FROM search_fts JOIN documents d ON d.id=search_fts.document_id\nJOIN entries e ON e.id=search_fts.entry_id',
                      'FROM search_fts CROSS JOIN entries e ON e.id=search_fts.entry_id\nCROSS JOIN documents d ON d.id=search_fts.document_id')
    db = ROOT / 'build/p3-full-authorized-retry1/knowledge.sqlite'
    conn = sqlite3.connect(db.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        meta = conn.execute("SELECT value FROM build_meta WHERE key='index_episodes'").fetchone()
        compiled = '"one" OR "piece"'
        plan = conn.execute('EXPLAIN QUERY PLAN ' + sql, (compiled, 'episode', None)).fetchall()
    finally:
        conn.close()
    report = {'status': 'PASS' if meta == ('false',) else 'STOP', 'index_episodes': meta,
              'metadata_sql': "SELECT value FROM build_meta WHERE key='index_episodes'",
              'filtered_sql': sql, 'compiled': compiled, 'parameters': [compiled, 'episode', None],
              'query_plan': plan, 'query_executed': False, 'mode': 'ro&immutable=1',
              'builder_contract': 'src/sakura_knowledge/storage.py:281-282 excludes episode FTS unless index_episodes true',
              'limitations': 'EXPLAIN is not elapsed execution or complete root-cause measurement'}
    report['raw'] = store(json.dumps(report, ensure_ascii=False).encode('utf-8'), root=RAW)
    save(OUT, report)
    print(json.dumps(report))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
