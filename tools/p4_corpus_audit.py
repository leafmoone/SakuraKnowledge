"""Read-only P4 coverage gate; no text promotion, embeddings or source writes."""
import json
import sqlite3

from p4_snapshot_check import EXPECTED_BYTES, EXPECTED_SHA256, RELATIVE, ROOT, binding, sidecars


def main():
    db = ROOT / RELATIVE
    before = sidecars(db)
    actual = binding(db)
    if actual['bytes'] != EXPECTED_BYTES or actual['sha256'] != EXPECTED_SHA256:
        raise ValueError('snapshot binding mismatch')
    if any(before[s].get('bytes', 0) for s in ('-wal', '-journal')):
        raise ValueError('nonempty source transaction sidecar')
    conn = sqlite3.connect(db.as_uri() + '?mode=ro&immutable=1', uri=True)
    conn.execute('PRAGMA query_only=ON')
    try:
        documents = conn.execute(
            'SELECT source_id,status,count(*) FROM documents GROUP BY source_id,status').fetchall()
        trusted = conn.execute('''SELECT d.source_id,e.kind,e.namespace,count(DISTINCT d.id)
            FROM search_fts f CROSS JOIN documents d ON d.id=f.document_id
            CROSS JOIN entries e ON e.id=d.entry_id
            WHERE f.entry_id=e.id AND e.conflicted=0 AND e.kind!='episode'
            AND d.status IN ('source_backed','generated_from_evidence')
            AND EXISTS(SELECT 1 FROM entry_evidence v
                       WHERE v.entry_id=e.id AND v.status='source_backed')
            GROUP BY d.source_id,e.kind,e.namespace''').fetchall()
        policy = conn.execute("SELECT value FROM build_meta WHERE key='index_episodes'").fetchone()
    finally:
        conn.close()
    after = sidecars(db)
    if before != after or db.stat().st_mtime_ns != actual['mtime_ns']:
        raise ValueError('source metadata changed during audit')
    missing = []
    for family, prefix in [('bangumi', 'bangumi'), ('moegirl', 'moegirl'),
                           ('danbooru', 'danbooru'), ('local_tag', 'tag_wiki')]:
        if not any(row[0].startswith(prefix) and row[3] for row in trusted):
            missing.append(family)
    result = {'snapshot': {'path': RELATIVE, **actual}, 'index_episodes': policy,
              'documents_by_source_status': documents,
              'trusted_fts_by_source_kind_namespace': trusted,
              'required_source_families_missing': missing,
              'coverage_gate': 'BLOCKED' if missing else 'PASS',
              'sidecars_unchanged': before == after,
              'semantic_execution': 'NOT_RUN',
              'limitation': 'Stored document status is authoritative; embedded payload claims '
                            'do not upgrade trust. No snapshot mutation or rebuild authorized.'}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
