"""Generic normalized bundles use the established storage importer, never a mother DB."""
import argparse
import importlib
import json
import re
import shutil
import sqlite3
import subprocess
from collections import Counter
from contextlib import closing
from pathlib import Path

from sakura_knowledge import storage
from tools.source_inventory import capture, validate_inventory
from tools.model_artifacts import encoder_contract
from tools.source_pack import binding, build_membership


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) or value in ('.', '..'):
        raise ValueError('unsafe pack_id')
    return value


def normalize(raw, adapter_name, output, pack_id):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    module, symbol = adapter_name.split(':', 1)
    adapter = getattr(importlib.import_module(module), symbol)()
    inventory = capture(adapter, raw)
    source = adapter.source_metadata(raw)
    sources = source if isinstance(source, list) else [source]
    if not sources or any(not isinstance(s, dict) for s in sources):
        raise ValueError('adapter source metadata must be source object or nonempty source list')
    observation = adapter.inspect(raw)
    records = output / 'records.jsonl'
    count = 0
    with records.open('x', encoding='utf-8') as stream:
        for record in adapter.iter_records(raw):
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            count += 1
    if capture(adapter, raw) != inventory:
        raise ValueError('raw input inventory changed')
    manifest = {'schema': 'sakura-normalized-source-v1', 'pack_id': safe_id(pack_id),
                'display_name': pack_id, 'version': '1', 'capabilities': ['structured', 'lexical'],
                'requires_model': None, 'sources': sources, 'namespaces': observation['namespaces'],
                'adapter': {'id': adapter.adapter_id, 'version': adapter.adapter_version},
                'expected_unresolved': observation.get('expected_unresolved', {}),
                'input_inventory': inventory, 'input_digests': inventory, 'inventory_scope': 'all_declared_inputs_shared_by_each_source', 'records': {**binding(records), 'count': count},
                'trust_declarations': 'source-backed identities; generated text never identity; candidate links not verified'}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def build_normalized(bundle, output):
    bundle, output = Path(bundle), Path(output)
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    if manifest['schema'] != 'sakura-normalized-source-v1':
        raise ValueError('normalized schema')
    safe_id(manifest['pack_id'])
    inventory = validate_inventory(manifest.get('input_inventory', manifest.get('input_digests')))
    if 'input_digests' in manifest and validate_inventory(manifest['input_digests']) != inventory:
        raise ValueError('conflicting input inventory')
    declared_ns = manifest['namespaces']
    if not declared_ns or len(declared_ns) != len(set(declared_ns)) or any(not isinstance(n, str) or not n or len(n) > 256 or any(ord(c) < 32 for c in n) for n in declared_ns):
        raise ValueError('normalized namespace declaration')
    artifact = manifest['records']
    if not isinstance(artifact.get('count'), int) or isinstance(artifact['count'], bool) or artifact['count'] < 0:
        raise ValueError('normalized record count')
    if artifact['path'] != 'records.jsonl' or binding(bundle / artifact['path']) != {k: artifact[k] for k in ('path', 'sha256', 'size')}:
        raise ValueError('normalized digest mismatch')
    with (bundle / 'records.jsonl').open('rb') as stream:
        if sum(1 for _ in stream) != artifact['count']:
            raise ValueError('normalized count mismatch')
    owners = [s['source_id'] for s in manifest['sources']]
    if not owners or len(owners) != len(set(owners)):
        raise ValueError('source ownership declaration')
    expected = manifest.get('expected_unresolved', {})
    if not isinstance(expected, dict) or any(owner not in owners or not isinstance(reasons, dict) or not reasons for owner, reasons in expected.items()):
        raise ValueError('unresolved source-account declaration')
    expected_counts = Counter()
    for owner, reasons in expected.items():
        for reason, count in reasons.items():
            if not isinstance(reason, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,127}', reason) or type(count) is not int or count <= 0:
                raise ValueError('unresolved reason/count declaration')
            expected_counts[(owner, reason)] = count
    observed_counts = Counter()
    with (bundle / 'records.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            record = json.loads(line)
            owner = record.get('source_id', owners[0] if len(owners) == 1 else None)
            if owner not in owners:
                raise ValueError('normalized record source ownership missing')
            if record.get('record_type') == 'unresolved':
                observed_counts[(owner, record.get('reason'))] += 1
    if observed_counts != expected_counts:
        raise ValueError('unresolved record source-account mismatch')
    work = output.with_name(output.name + '-import-input')
    work.mkdir(parents=True, exist_ok=False)
    sources = []
    for index, meta in enumerate(manifest['sources']):
        source = {k: None for k in storage.REQUIRED_SOURCE}
        source.update(meta)
        source.update({'path': str((bundle / 'records.jsonl').resolve()), 'adapter': 'contract-jsonl-v1',
                       'local_sha256': artifact['sha256'], 'repo': meta.get('repo', 'local://normalized'),
                       'provider': meta.get('provider', manifest['pack_id']), 'schema_version': 'contract-v2',
                       'counts': {'records': artifact['count']}, 'input_file_inventory': inventory,
                       'source_references': [], 'refresh_status': 'frozen_normalized'})
        if len(manifest['sources']) > 1:
            local_records = work / f'source-{index}.jsonl'
            owner_count = 0
            with (bundle / 'records.jsonl').open(encoding='utf-8') as original, local_records.open('x', encoding='utf-8') as target:
                for line in original:
                    record = json.loads(line)
                    if record.get('source_id') == meta['source_id']:
                        target.write(line)
                        owner_count += 1
                    elif record.get('source_id') not in {s['source_id'] for s in manifest['sources']}:
                        raise ValueError('normalized record source ownership missing')
            source['path'] = str(local_records.resolve())
            source['local_sha256'] = binding(local_records)['sha256']
            source['counts'] = {'records': owner_count}
        sources.append(source)
    importer = work / 'manifest.json'
    importer.write_text(json.dumps({'sources': sources, 'p3_resolver_version': '1',
                                    'allow_unresolved_reasons': sorted({reason for _, reason in expected_counts})}), encoding='utf-8')
    report = storage.build(importer, output)
    for owner in owners:
        if report['counts'][owner]['unresolved'] != sum(count for (sid, _), count in expected_counts.items() if sid == owner):
            raise ValueError('imported unresolved source-account mismatch')
    snapshot = output / 'knowledge.sqlite'
    # This new snapshot is owned by this builder. Never index generated-only identities.
    with closing(sqlite3.connect(snapshot)) as conn:
        conn.execute("DELETE FROM search_fts WHERE NOT EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=search_fts.entry_id AND v.status='source_backed') OR EXISTS(SELECT 1 FROM entries e WHERE e.id=search_fts.entry_id AND e.conflicted!=0)")
        conn.commit()
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.execute('PRAGMA journal_mode=DELETE')
    for name in ['build_report.json', 'sources.lock.json']:
        if (output / name).exists():
            shutil.move(str(output / name), str(work / name))
    for name in ['knowledge.sqlite-wal', 'knowledge.sqlite-shm']:
        (output / name).unlink(missing_ok=True)
    membership = build_membership(snapshot, output / 'lexical-membership.sqlite')
    with closing(sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        namespaces = [r[0] for r in conn.execute('SELECT DISTINCT namespace FROM entries ORDER BY namespace')]
        fts = conn.execute('SELECT count(*) FROM search_fts').fetchone()[0]
    pack = {'schema': 'sakura-source-pack-v1', 'distribution_closed_set': True, 'pack_id': manifest['pack_id'],
            'display_name': manifest['display_name'], 'version': manifest['version'],
            'capabilities': ['structured', 'lexical'], 'requires_model': None,
            'source_ids': [s['source_id'] for s in sources], 'namespaces': namespaces,
            'trusted_fts_documents': fts, 'lexical_mode': 'trusted_documents_and_identity',
            'lexical_membership': membership,
            'artifacts': {'snapshot': {**binding(snapshot), 'identity': 'knowledge.sqlite'},
                          'lexical_membership': binding(output / 'lexical-membership.sqlite')}}
    (output / 'manifest.json').write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding='utf-8')
    return validate(output)


def inspect(pack):
    pack = Path(pack)
    manifest = json.loads((pack / 'manifest.json').read_bytes())
    with closing(sqlite3.connect((pack / 'knowledge.sqlite').resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        counts = {t: conn.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in ['entries', 'documents', 'search_fts', 'links']}
    return {'pack_id': manifest['pack_id'], 'version': manifest['version'], 'capabilities': manifest['capabilities'],
            'source_ids': manifest['source_ids'], 'namespaces': manifest['namespaces'], 'counts': counts,
            'requires_model': manifest['requires_model'], 'actual_bytes': sum(p.stat().st_size for p in pack.rglob('*') if p.is_file())}


def validate(pack, index_inspector=None):
    pack = Path(pack)
    manifest = json.loads((pack / 'manifest.json').read_bytes())
    safe_id(manifest['pack_id'])
    if manifest.get('distribution_closed_set'):
        expected_files = {'manifest.json'} | {item['path'] for item in manifest['artifacts'].values()}
        actual_files = {p.relative_to(pack).as_posix() for p in pack.rglob('*') if p.is_file()}
        if actual_files != expected_files or any(p.is_symlink() for p in pack.rglob('*')):
            raise ValueError('runtime distribution file closed set')
    if manifest.get('schema') != 'sakura-source-pack-v1':
        raise ValueError('source pack schema')
    caps = manifest.get('capabilities', [])
    if len(caps) != len(set(caps)) or not {'structured', 'lexical'} <= set(caps) or set(caps) - {'structured', 'lexical', 'semantic'}:
        raise ValueError('capability contradiction')
    sem = 'semantic' in caps
    if not sem and manifest.get('requires_model') is not None:
        raise ValueError('unsupported_model_contract')
    model_contract = encoder_contract(manifest['requires_model']) if sem else None
    if sem and manifest['requires_model'] == 'embeddinggemma-2':
        projection = manifest.get('text_projection', {})
        if projection.get('model_revision') != model_contract['revision']:
            raise ValueError('source model revision mismatch')
        for field in ['document_template', 'untitled_document']:
            if projection.get(field) != model_contract[field]:
                raise ValueError('source document encoding mismatch')
        if (projection.get('document_text') != 'canonical_title_and_original'
                or projection.get('max_sequence_tokens') != 512):
            raise ValueError('source text projection mismatch')
    required = {'snapshot', 'lexical_membership'} | ({'mapping', 'index'} if sem else set())
    if len({item.get('path') for item in manifest['artifacts'].values()}) != len(manifest['artifacts']):
        raise ValueError('duplicate artifact paths')
    if manifest['artifacts']['snapshot'].get('path') != 'knowledge.sqlite' or manifest['artifacts']['lexical_membership'].get('path') != 'lexical-membership.sqlite':
        raise ValueError('canonical artifact role paths')
    if set(manifest['artifacts']) != required or (not sem and 'semantic' in manifest):
        raise ValueError('artifact capability closed set')
    for field in ['source_ids', 'namespaces']:
        items = manifest[field]
        if not items or len(items) != len(set(items)) or any(not isinstance(s, str) or not s or len(s) > 256 or any(ord(c) < 32 for c in s) for s in items):
            raise ValueError('source/namespace declaration')
    for item in manifest['artifacts'].values():
        if Path(item['path']).name != item['path'] or binding(pack / item['path']) != {k: item[k] for k in ('path', 'sha256', 'size')}:
            raise ValueError('artifact binding mismatch')
    with closing(sqlite3.connect((pack / 'knowledge.sqlite').resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or conn.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('database integrity/FK')
        if {r[0] for r in conn.execute('SELECT source_id FROM sources')} != set(manifest['source_ids']):
            raise ValueError('source ownership mismatch')
        if {r[0] for r in conn.execute('SELECT DISTINCT namespace FROM entries')} != set(manifest['namespaces']):
            raise ValueError('namespace mismatch')
        if conn.execute('SELECT count(*) FROM search_fts').fetchone()[0] != manifest['trusted_fts_documents']:
            raise ValueError('FTS count mismatch')
        if conn.execute("SELECT 1 FROM search_fts f LEFT JOIN documents d ON d.id=f.document_id LEFT JOIN entries e ON e.id=f.entry_id WHERE d.id IS NULL OR e.id IS NULL OR e.conflicted!=0 OR d.entry_id!=f.entry_id OR d.search_text!=f.text OR d.evidence_id='' OR d.status NOT IN ('source_backed','generated_from_evidence') OR NOT EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed') LIMIT 1").fetchone():
            raise ValueError('FTS trust closure')
        conn.execute('ATTACH DATABASE ? AS membership', ((pack / manifest['artifacts']['lexical_membership']['path']).resolve().as_uri() + '?mode=ro',))
        for left, right in [('SELECT rowid,entry_id,document_id FROM search_fts', 'SELECT fts_rowid,entry_id,document_id FROM membership.members'), ('SELECT fts_rowid,entry_id,document_id FROM membership.members', 'SELECT rowid,entry_id,document_id FROM search_fts')]:
            if conn.execute(left + ' EXCEPT ' + right + ' LIMIT 1').fetchone():
                raise ValueError('membership closure')
        meta = dict(conn.execute('SELECT key,value FROM membership.meta'))
        if meta['snapshot_sha256'] != manifest['artifacts']['snapshot']['sha256'] or int(meta['rows']) != manifest['trusted_fts_documents']:
            raise ValueError('membership snapshot binding')
        if sem:
            s = manifest['semantic']
            for field, expected in {'dimension': model_contract['dimension'], 'metric': 'cos', 'dtype': 'i8', 'connectivity': 16, 'expansion_add': 256, 'expansion_search': 2048, 'chunk_depth': 512, 'entry_depth': 100}.items():
                if s.get(field) != expected:
                    raise ValueError('semantic contract mismatch')
            conn.execute('ATTACH DATABASE ? AS mapping', ((pack / manifest['artifacts']['mapping']['path']).resolve().as_uri() + '?mode=ro',))
            count, minimum, maximum = conn.execute('SELECT count(*),min(position),max(position) FROM mapping.chunks').fetchone()
            if count != s['rows'] or minimum != 0 or maximum != count - 1:
                raise ValueError('semantic mapping rows/keys')
            if conn.execute("SELECT 1 FROM mapping.chunks c LEFT JOIN documents d ON d.id=c.document_id LEFT JOIN entries e ON e.id=d.entry_id WHERE d.id IS NULL OR e.id IS NULL OR e.conflicted!=0 OR c.kind!=e.kind OR c.namespace!=e.namespace OR c.value!=e.value OR c.source_id!=d.source_id OR c.evidence_id!=d.evidence_id OR d.status NOT IN ('source_backed','generated_from_evidence') OR NOT EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed') LIMIT 1").fetchone():
                raise ValueError('semantic mapping proof closure')
            if index_inspector is None:
                raise ValueError('semantic validation requires explicit --index-inspector native executable')
            arguments = [str(index_inspector), str(pack / manifest['artifacts']['index']['path']), str(count)]
            if s['dimension'] != 1024:
                arguments.append(str(s['dimension']))
            result = subprocess.run(arguments, capture_output=True, check=False)
            if result.returncode or json.loads(result.stdout).get('validation') != 'PASS':
                raise ValueError('native index contract/keys')
    return {**inspect(pack), 'validation': 'PASS'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['normalize', 'build-normalized', 'inspect', 'validate'])
    p.add_argument('--input', required=True)
    p.add_argument('--output')
    p.add_argument('--adapter')
    p.add_argument('--pack-id')
    p.add_argument('--index-inspector')
    a = p.parse_args()
    if a.command == 'normalize':
        result = normalize(a.input, a.adapter, a.output, a.pack_id)
    elif a.command == 'build-normalized':
        result = build_normalized(a.input, Path(a.output))
    elif a.command == 'validate':
        result = validate(a.input, a.index_inspector)
    else:
        result = inspect(a.input)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
