SELECT e.id,e.kind,e.namespace,e.value,bm25(search_fts),
d.title,substr(d.original,1,4000),length(d.original)>4000,d.source_id,d.evidence_id
FROM search_fts JOIN documents d ON d.id=search_fts.document_id
JOIN entries e ON e.id=search_fts.entry_id WHERE search_fts MATCH ?1
AND e.conflicted=0 AND d.status IN ('generated_from_evidence','source_backed')
AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status IN ('source_backed'))
AND (?2 IS NULL OR e.kind=?2) AND (?3 IS NULL OR e.namespace=?3)
ORDER BY bm25(search_fts),e.kind,e.namespace,e.value,search_fts.rowid LIMIT 10001
