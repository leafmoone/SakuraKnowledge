"""Read-only scoped P3 audit of explicitly known handoff/cache assets, not a machine scan."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    root = Path('D:/dataset/danbooru_wiki')
    cache = Path('build/source-cache')
    items = []
    named = [root/'handoff/file_manifest.json', root/'handoff/dataset_inventory.json',
             root/'outputs/download_manifest.json', root/'outputs/manifest.json',
             root/'outputs/tag_wiki.sqlite', cache/'tag_wiki-frozen.sqlite',
             root/'raw/danbooru_wiki/wiki/danbooru_wiki.parquet',
             root/'raw/danbooru_wiki/wiki/danbooru_wiki_links.parquet',
             root/'outputs/all_tags.parquet', root/'outputs/per_source_tag_counts.parquet']
    for path in named:
        item = {'path': str(path.resolve()), 'exists': path.exists()}
        if path.exists():
            item['bytes'] = path.stat().st_size
            # Nonfrozen live SQLite is schema-observation only, never ingest it.
            if path.name != 'tag_wiki.sqlite':
                item['sha256'] = sha(path)
            if path.suffix == '.sqlite':
                conn = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
                try:
                    tables = [x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                    item['schema'] = {t: [list(x) for x in conn.execute('PRAGMA table_info("'+t.replace('"','""')+'")')]
                                      for t in tables}
                    item['native_tags'] = [t for t in tables if t == 'tags' and {'id','name','category'} <=
                                           {x[1] for x in item['schema'][t]}]
                    item['native_aliases'] = [t for t in tables if {'antecedent_name','consequent_name','status'} <=
                                              {x[1] for x in item['schema'][t]}]
                    if path.parent == cache:
                        item['rows'] = {t: conn.execute('SELECT count(*) FROM "'+t+'"').fetchone()[0]
                                        for t in ('wiki_pages','tag_aliases','tag_evidence') if t in tables}
                finally:
                    conn.close()
            if path.suffix == '.parquet':
                import pyarrow.parquet as pq
                data = pq.ParquetFile(path)
                item['schema'] = str(data.schema_arrow)
                item['rows'] = data.metadata.num_rows
                cols = set(data.schema_arrow.names)
                item['native_tags_schema'] = {'id','name','category','post_count'} <= cols
                item['native_alias_schema'] = {'antecedent_name','consequent_name','status'} <= cols
        items.append(item)
    frozen = Path('build/real-full-7afe7fb/manifest.json')
    manifest = json.loads(frozen.read_text(encoding='utf-8'))
    normalized = []
    for src in manifest['sources']:
        path = (frozen.parent/src['path']).resolve()
        actual = sha(path)
        normalized.append({'source_id':src['source_id'],'path':str(path),'bytes':path.stat().st_size,
                           'sha256':actual,'locked_sha256':src['local_sha256'],
                           'unchanged':actual == src['local_sha256']})
    if not all(x['unchanged'] for x in normalized):
        raise ValueError('existing normalized input hash mismatch')
    usage = shutil.disk_usage(Path.cwd())
    result = {'inspected_at_utc':datetime.now(UTC).isoformat(),'scope':'explicit handoff lists and known cache/assets only',
              'inputs':items,'existing_normalized':normalized,'disk':{'free_bytes':usage.free,'total_bytes':usage.total},
              'native_evidence_local':any(x.get('native_tags') or x.get('native_tags_schema') or
                                          x.get('native_aliases') or x.get('native_alias_schema') for x in items),
              'limitations':['Known scoped files only; not a universal filesystem absence claim',
                             'Live SQLite schema read-only, not frozen input or source fact verification']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x',encoding='utf-8',newline='\n') as output:
        json.dump(result,output,ensure_ascii=False,indent=2)
    print(json.dumps({'native_evidence_local':result['native_evidence_local'],'free_bytes':usage.free,
                      'existing_inputs_unchanged':True,'files':len(items)}))


if __name__ == '__main__':
    main()
