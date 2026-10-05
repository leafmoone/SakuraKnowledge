"""Readonly full proof audit and create-new tag-wiki text candidate."""
import argparse
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from sakura_knowledge.model import search_text
from sakura_knowledge.tag_wiki_provenance import VERSION, Auditor, records
from tools.source_pack import binding, build_membership


def audit(tag_path, dan_pack, output):
    output = Path(output)
    if output.exists() or output.with_suffix('.proofs.jsonl').exists():
        raise FileExistsError(output)
    checker = Auditor(tag_path, Path(dan_pack) / 'knowledge.sqlite')
    total = 0
    try:
        with output.with_suffix('.proofs.jsonl').open('x', encoding='utf-8') as stream:
            for record in records(checker.tag):
                total += 1
                result = checker.prove(record)
                if result:
                    text, proof = result
                    stream.write(json.dumps({'text': text, 'text_provenance': proof}, ensure_ascii=False) + '\n')
        result = {'schema': VERSION, 'records': total, 'raw_statuses': dict(checker.statuses),
                  'classification': dict(checker.counts), 'methods': dict(checker.methods),
                  'minimum_information': {'characters': 24, 'words': 4},
                  'input_mode': 'readonly_frozen_reconstructed_proof', 'identity_promotions': 0}
        with output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        checker.close()


def build(base_pack, tag_path, dan_pack, output):
    base, output = Path(base_pack), Path(output)
    output.mkdir(exist_ok=False, parents=True)
    target = output / 'knowledge.sqlite'
    shutil.copy2(base / 'knowledge.sqlite', target)
    checker = Auditor(tag_path, Path(dan_pack) / 'knowledge.sqlite')
    count = 0
    try:
        with closing(sqlite3.connect(target, uri=True)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute("PRAGMA temp_store_directory='" + str(output.resolve()).replace("'", "''") + "'")
            for record in records(checker.tag):
                result = checker.prove(record)
                if result is None:
                    continue
                text, proof = result
                row = conn.execute("SELECT e.id,v.source_id,v.evidence_id FROM entries e JOIN entry_evidence v ON v.entry_id=e.id WHERE e.kind='tag' AND e.namespace='local.tag_aggregate' AND e.value=? AND e.conflicted=0 AND v.status='source_backed' ORDER BY v.id LIMIT 1", (record['tag_key'],)).fetchone()
                if row is None:
                    checker.counts['tag_identity_missing'] += 1
                    continue
                eid, sid, ref = row
                proof.update({'tag_source_id': sid, 'tag_evidence_id': ref})
                payload = json.dumps({'text_provenance': proof, 'search_text_truncated': False}, ensure_ascii=False)
                index_text = search_text(record['tag_key'] + ' ' + text)
                cur = conn.execute('INSERT INTO documents(entry_id,title,original,search_text,language,status,source_id,evidence_id,payload) VALUES(?,?,?,?,?,?,?,?,?)', (eid, record['tag_key'], text, index_text, 'en', 'generated_from_evidence', sid, ref, payload))
                conn.execute('INSERT INTO search_fts(text,document_id,entry_id) VALUES(?,?,?)', (index_text, cur.lastrowid, eid))
                count += 1
            conn.commit()
            conn.execute('ATTACH DATABASE ? AS old', (base.joinpath('knowledge.sqlite').resolve().as_uri() + '?mode=ro',))
            for table in ['entries', 'entry_evidence', 'aliases', 'links', 'tag_resolutions', 'sources']:
                for left, right in [('main', 'old'), ('old', 'main')]:
                    if conn.execute(f'SELECT * FROM {left}.{table} EXCEPT SELECT * FROM {right}.{table} LIMIT 1').fetchone():
                        raise ValueError('identity table changed: ' + table)
            if conn.execute('SELECT * FROM old.documents EXCEPT SELECT * FROM main.documents LIMIT 1').fetchone():
                raise ValueError('old document changed')
            if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('candidate database checks failed')
            if conn.execute("SELECT 1 FROM search_fts f JOIN documents d ON d.id=f.document_id WHERE f.entry_id!=d.entry_id OR f.text!=d.search_text OR d.status NOT IN ('source_backed','generated_from_evidence') LIMIT 1").fetchone():
                raise ValueError('FTS closure failed')
        manifest = json.loads((base / 'manifest.json').read_bytes())
        manifest['lexical_membership'] = build_membership(target, output / 'lexical-membership.sqlite')
        manifest['artifacts']['lexical_membership'] = binding(output / 'lexical-membership.sqlite')
        manifest['version'] = '2-text-proof-v1'
        manifest['trusted_fts_documents'] = count
        manifest['lexical_mode'] = 'trusted_documents_and_identity'
        manifest['artifacts']['snapshot'] = {**binding(target), 'identity': 'knowledge.sqlite'}
        manifest['text_provenance'] = {'version': VERSION, 'new_documents': count, 'identity_tables_unchanged': True, 'classification': dict(checker.counts)}
        with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'new_documents': count, 'manifest': str(output / 'manifest.json'), 'classification': dict(checker.counts)}))
    finally:
        checker.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['audit', 'build'])
    parser.add_argument('--tag-wiki', required=True)
    parser.add_argument('--danbooru-pack', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--base-pack')
    args = parser.parse_args()
    if args.command == 'audit':
        audit(args.tag_wiki, args.danbooru_pack, args.output)
    else:
        if not args.base_pack:
            parser.error('--base-pack required for build')
        build(args.base_pack, args.tag_wiki, args.danbooru_pack, args.output)


if __name__ == '__main__':
    main()
