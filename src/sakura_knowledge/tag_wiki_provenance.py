"""Reconstruct narrow text proofs from frozen source bytes; never identity proofs."""
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

VERSION = 'tag-wiki-text-proof-v1'
MIN_CHARACTERS = 24
MIN_WORDS = 4


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def whitespace(text):
    return re.sub(r'\s+', ' ', text).strip()


class ProofRejected(ValueError):
    pass


def verify_text_proof(text, body, proof):
    if proof.get('version') != VERSION or digest(body) != proof.get('wiki_body_sha256') or digest(text) != proof.get('trusted_text_sha256'):
        raise ProofRejected('proof_hash_mismatch')
    normalized = whitespace(body)
    method = proof.get('method')
    if method == 'whitespace_prefix':
        valid = normalized.startswith(text)
    elif method == 'whitespace_contiguous_excerpt':
        valid = text in normalized
    else:
        raise ProofRejected('proof_method_invalid')
    if not valid:
        raise ProofRejected('text_not_derivable')
    return True


def derive(record, wiki, candidates):
    """Status, confidence and model labels play no role in acceptance."""
    ids = sorted({int(x['wiki_id']) for x in candidates})
    if not ids:
        raise ProofRejected('no_tag_evidence')
    if len(ids) != 1:
        raise ProofRejected('multiple_wiki_candidates')
    if wiki is None or wiki['wiki_id'] != ids[0]:
        raise ProofRejected('missing_wiki')
    if wiki['is_deleted']:
        raise ProofRejected('deleted_wiki')
    body = wiki['body']
    if not isinstance(body, str) or not body.strip():
        raise ProofRejected('empty_wiki')
    if record['table'] == 'full_annotation_cache':
        try:
            obj = json.loads(record['text'])
        except (ValueError, TypeError) as error:
            raise ProofRejected('json_parse') from error
        if not isinstance(obj, dict) or obj.get('tag_key') != record['tag_key']:
            raise ProofRejected('json_schema')
        fields = [(name, obj.get(name)) for name in ('short_summary', 'detailed_description')]
    else:
        fields = [('semantic_summary', record['text'])]
    normalized = whitespace(body)
    accepted = []
    for field, value in fields:
        if not isinstance(value, str) or not value.strip():
            continue
        # Only whitespace collapsing is permitted; no case/punctuation/fuzzy match.
        text = whitespace(value)
        if normalized.startswith(text):
            method = 'whitespace_prefix'
        elif text in normalized:
            method = 'whitespace_contiguous_excerpt'
        else:
            continue
        if len(text) < MIN_CHARACTERS or len(re.findall(r'\w+', text)) < MIN_WORDS:
            continue
        accepted.append((len(text), field, text, method))
    if not accepted:
        values = [whitespace(v) for _, v in fields if isinstance(v, str)]
        if any(v and v in normalized for v in values):
            raise ProofRejected('too_short')
        raise ProofRejected('text_not_derivable')
    _, field, text, method = max(accepted)
    return text, {'version': VERSION, 'method': method, 'field': field,
                  'tag_key': {'kind': 'tag', 'namespace': 'local.tag_aggregate', 'value': record['tag_key']},
                  'raw_table': record['table'], 'raw_locator': record['locator'],
                  'raw_status': record['status'],
                  'wiki_key': {'kind': 'page', 'namespace': 'danbooru.wiki', 'value': str(ids[0])},
                  'wiki_body_sha256': digest(body), 'trusted_text_sha256': digest(text),
                  'candidate_wiki_ids': ids,
                  'history': 'reconstructed_from_frozen_bytes; producer_revision_unknown'}


def records(conn):
    for table, column in [('full_annotation_cache', 'result_json'), ('annotations', 'semantic_summary')]:
        for key, tag, status, text in conn.execute(f'SELECT cache_key,tag_key,status,{column} FROM {table} ORDER BY cache_key'):
            yield {'table': table, 'locator': 'cache_key:' + key, 'tag_key': tag,
                   'status': status, 'text': text}


class Auditor:
    def __init__(self, tag_path, dan_path):
        self.tag = sqlite3.connect(Path(tag_path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
        self.tag.row_factory = sqlite3.Row
        self.dan = sqlite3.connect(Path(dan_path).resolve().as_uri() + '?mode=ro', uri=True)
        self.dan.row_factory = sqlite3.Row
        self.counts = Counter()
        self.statuses = Counter()
        self.methods = Counter()
        self.seen = set()

    def close(self):
        self.tag.close()
        self.dan.close()

    def prove(self, record):
        self.statuses[record['table'] + ':' + record['status']] += 1
        candidates = [dict(r) for r in self.tag.execute('SELECT wiki_id,match_type,matched_text FROM tag_evidence WHERE tag_key=?', (record['tag_key'],))]
        ids = {r['wiki_id'] for r in candidates}
        wiki = self.tag.execute('SELECT wiki_id,title,body,is_deleted FROM wiki_pages WHERE wiki_id=?', (next(iter(ids)),)).fetchone() if len(ids) == 1 else None
        try:
            text, proof = derive(record, wiki, candidates)
            rows = self.dan.execute("SELECT d.id,d.source_id,d.evidence_id,d.original,e.id FROM entries e JOIN documents d ON d.entry_id=e.id WHERE e.kind='page' AND e.namespace='danbooru.wiki' AND e.value=? AND e.conflicted=0 AND d.status='source_backed' AND EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed')", (proof['wiki_key']['value'],)).fetchall()
            matches = [r for r in rows if r['original'] == wiki['body']]
            if len(matches) != 1:
                raise ProofRejected('danbooru_source_body_mismatch')
            row = matches[0]
            proof.update({'wiki_source_id': row['source_id'], 'wiki_evidence_id': row['evidence_id'], 'wiki_document_id': row['id']})
            dedup = (record['tag_key'], proof['trusted_text_sha256'])
            if dedup in self.seen:
                raise ProofRejected('duplicate_text')
            self.seen.add(dedup)
            self.counts['proved'] += 1
            self.methods[proof['method']] += 1
            return text, proof
        except ProofRejected as error:
            self.counts[str(error)] += 1
            return None
