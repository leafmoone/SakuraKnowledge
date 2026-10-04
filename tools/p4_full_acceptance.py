"""Read-only FULL acceptance checks; never load artifacts or run inference."""
import hashlib
import json
import re
from contextlib import closing, contextmanager
from pathlib import Path, PureWindowsPath

from tools import p4_rust_pilot as pilot
from tools.p4_full_preflight import (
    CONFIG,
    ROOT,
    require,
    validate_contract,
)

PACK_SCHEMA = 'p4-rust-semantic-full-pack-v1'
CANONICAL_PATH = 'configs/p4-full-semantic-v1.json'
ARTIFACTS = {'model', 'external_data', 'tokenizer', 'ort_dll', 'index', 'mapping', 'corpus'}


def runtime_contract(declaration, rows):
    encoder, runtime = declaration['encoder'], declaration['runtime']
    return {'schema': 'p4-full-semantic-contract-v1', **runtime,
            **{key: encoder[key] for key in ('revision', 'dimension', 'pooling', 'normalize',
                                            'query_prefix', 'dtype')},
            'output': 'embeddings', 'ann': {'rows': rows, **{key: declaration['ann'][key]
            for key in ('metric', 'dtype', 'connectivity', 'expansion_add', 'expansion_search',
                        'chunk_depth', 'entry_depth')}},
            **declaration['hybrid'], 'full_chunk_count': rows}


def _absolute(path):
    # Path.absolute() on Windows normalizes away traversed symlink/junction components.
    path = Path(path)
    require(not path.drive or path.is_absolute(), 'drive-relative path forbidden')
    return path if path.is_absolute() else Path.cwd() / path


def _safe_name(name):
    require(isinstance(name, str) and name and '\x00' not in name, 'binding path required')
    windows = PureWindowsPath(name)
    require(not windows.drive or windows.is_absolute(), 'drive-relative path forbidden')
    require(all(':' not in part for part in windows.parts[1:] if windows.drive) and
            (windows.drive or ':' not in name), 'alternate stream path forbidden')


def _no_links(path):
    for part in (path, *path.parents):
        require(not part.is_symlink() and
                not (hasattr(part, 'is_junction') and part.is_junction()),
                'inventory symlink/junction forbidden')


def _controlled_path(path, root):
    """Allow relative parent traversal only when the final file remains in ROOT."""
    path, root = _absolute(path), _absolute(root)
    _no_links(path)
    _no_links(root)
    resolved = path.resolve(strict=True)
    _no_links(resolved)
    require(resolved.is_relative_to(root.resolve(strict=True)) and resolved.is_file(),
            'inventory path escape or non-file')
    return resolved


def _binding(record):
    require(isinstance(record, dict) and set(record) == {'path', 'size', 'sha256'},
            'file binding required')
    _safe_name(record['path'])
    require(type(record['size']) is int and record['size'] > 0, 'positive binding size required')
    require(isinstance(record['sha256'], str) and
            re.fullmatch('[0-9a-f]{64}', record['sha256']), 'binding SHA256 required')


def approved_full_dll():
    """Return the independently configured current ORT DLL binding."""
    try:
        path = _controlled_path(ROOT / 'configs/p4-current-assets.json', ROOT)
        data = json.loads(path.read_bytes())
        record = data['ort_dll']
        _binding(record)
        resolved = Path(record['path']).expanduser()
        require(resolved.is_absolute(), 'current ORT DLL exact path required')
        _no_links(resolved)
        resolved = resolved.resolve(strict=True)
        _no_links(resolved)
        require(resolved.is_file(), 'approved ORT DLL missing')
        # Content verification belongs to the session, not path authority checks.
        return {'path': str(resolved), 'size': record['size'], 'sha256': record['sha256']}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f'BLOCKED: approved external ORT DLL binding unavailable: {exc}') from exc


def _approved_dll_path():
    return Path(approved_full_dll()['path'])


def _artifact_path(path, kind, binding):
    path = _absolute(path)
    _no_links(path)
    resolved = path.resolve(strict=True)
    _no_links(resolved)
    approved = approved_full_dll() if kind == 'ort_dll' else None
    if not resolved.is_relative_to(Path(ROOT).resolve(strict=True)):
        require(kind == 'ort_dll', 'inventory path escape')
        require(resolved == Path(approved['path']), 'unapproved external ORT DLL path')
        require(resolved.is_file(), 'inventory non-file')
        require((binding['size'], binding['sha256']) ==
                (approved['size'], approved['sha256']), 'unpinned ORT DLL')
        return resolved
    if kind == 'ort_dll':
        require((binding['size'], binding['sha256']) ==
                (approved['size'], approved['sha256']), 'unpinned ORT DLL')
    return _controlled_path(path, ROOT)


def _file_state(path):
    stat = path.stat()
    # Hashing and SQLite reads can update access time; it is not a content mutation.
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _verify_file(path, binding):
    before = _file_state(path)
    require(before[2] == binding['size'] and pilot.sha(path) == binding['sha256'],
            'actual file binding mismatch')
    require(_file_state(path) == before, 'file changed during hashing')
    return before


class VerifiedInventory:
    """One acceptance-session verification of each unique content asset."""
    def __init__(self, records):
        self.records = [(Path(path), dict(binding), kind) for path, binding, kind in records]
        self.states = []
        self._verified = {}

    def check(self):
        for original, path, binding, kind, before in self.states:
            require(_artifact_path(original, kind, binding) == path and
                    _file_state(path) == before, 'inventory changed')

    def verify(self, records=None):
        self.check()
        for original, binding, kind in self.records if records is None else records:
            _binding(binding)
            original, binding = Path(original), dict(binding)
            path = _artifact_path(original, kind, binding)
            pin = (binding['size'], binding['sha256'])
            require(path not in self._verified or self._verified[path] == pin,
                    'session file binding mismatch')
            if path not in self._verified:
                before = _verify_file(path, binding)
                self._verified[path] = pin
                self.states.append((original, path, binding, kind, before))
            elif not any(item[0] == original and item[3] == kind for item in self.states):
                self.states.append((original, path, binding, kind, _file_state(path)))
        self.check()
        return self

    def __enter__(self):
        return self.verify()

    def __exit__(self, *_):
        self.check()


class AcceptanceSession:
    """Explicit, caller-owned asset verification cache; never a provenance cache.

    Reuse for one immutable acceptance run. Each validation checks the entire known
    inventory before and after use. Closing checks it once more and forbids reuse.
    A new instance always hashes real bytes again; no process-global cache exists.
    """
    def __init__(self):
        self._inventory = VerifiedInventory([])
        self._closed = False

    @contextmanager
    def guard(self, records):
        require(not self._closed, 'acceptance session closed')
        self._inventory.verify(records)
        try:
            yield
        finally:
            self._inventory.check()

    def close(self):
        if not self._closed:
            self._closed = True
            self._inventory.check()

    def __enter__(self):
        require(not self._closed, 'acceptance session closed')
        self._inventory.check()
        return self

    def __exit__(self, *_):
        self.close()


def _inventory_guard(records, session=None):
    require(session is None or isinstance(session, AcceptanceSession),
            'acceptance session required')
    return (session if session is not None else AcceptanceSession()).guard(records)


def _canonical(contract, experimental_ef2048=False):
    require(type(experimental_ef2048) is bool, 'explicit experiment flag required')
    declaration = validate_contract(contract, expected_expansion_search=2048) if experimental_ef2048 else validate_contract(contract)
    canonical_path = CANONICAL_PATH
    config = CONFIG
    require(Path(config).absolute() == Path(ROOT).absolute() / canonical_path,
            'controlled canonical path required')
    path = _controlled_path(config, ROOT)
    data = path.read_bytes()
    require(json.loads(data) == contract, 'canonical bytes do not contain approved contract')
    binding = {'path': canonical_path, 'size': len(data),
               'sha256': hashlib.sha256(data).hexdigest()}
    return declaration, path, binding


def _snapshot(contract):
    spec = contract['snapshot']
    _binding(spec)
    name = Path(spec['path'])
    require(not name.is_absolute() and '..' not in name.parts, 'snapshot path escape')
    return _controlled_path(Path(ROOT) / name, ROOT), spec


def _verify_existing_roles(records):
    assets = json.loads((ROOT / 'configs/p4-current-assets.json').read_bytes())
    export = _controlled_path(ROOT / assets['export_manifest']['path'], ROOT)
    exported = json.loads(export.read_bytes())['files']
    for path, record, role in records:
        resolved = _artifact_path(path, role, record)
        if role == 'lexical_membership':
            continue
        if role in ('index', 'mapping', 'corpus'):
            expected = assets['existing_full_assets'][role]
            expected_path = ROOT / expected['path']
        elif role == 'tokenizer':
            expected = next(r for r in assets['model']['obtained_inventory'] if r['path'] == 'tokenizer.json')
            expected_path = ROOT / assets['model']['assetdirectory'] / 'tokenizer.json'
        elif role in ('model', 'external_data'):
            expected = next((r for r in exported if
                             _controlled_path(export.parent / r['path'], ROOT) == resolved), None)
            require(expected is not None, 'unknown existing export resource')
            require((role == 'model') == (expected['path'] == 'model.onnx'), 'existing export role mismatch')
            expected_path = export.parent / expected['path']
        else:
            require(role == 'ort_dll', 'unknown existing asset role')
            expected = assets['ort_dll']
            expected_path = Path(expected['path'])
        pin = {key: expected[key] for key in ('path', 'size', 'sha256')}
        require(resolved == _artifact_path(expected_path, role, pin) and
                (record['size'], record['sha256']) == (expected['size'], expected['sha256']),
                'existing product role binding mismatch')


def _verify_inventory(artifacts, pack_root, *, expected_dll, prepared=False):
    """Bindings are relative to the pack, but containment authority is Knowledge ROOT."""
    require(isinstance(artifacts, dict) and set(artifacts) == (ARTIFACTS | {'lexical_membership'} if prepared else ARTIFACTS),
            'exact FULL artifact inventory required (no sidecar)')
    external = artifacts['external_data']
    require(isinstance(external, list) and external, 'nonempty external_data required')
    root = _absolute(pack_root)
    _no_links(root)
    require(root.resolve(strict=True).is_relative_to(Path(ROOT).resolve(strict=True)) and
            root.is_dir(), 'controlled pack root required')
    records, seen = [], set()
    inventory = [(key, artifacts[key]) for key in sorted(set(artifacts) - {'external_data'})]
    inventory.extend(('external_data', binding) for binding in external)
    for kind, binding in inventory:
        _binding(binding)
        name = Path(binding['path'])
        if kind == 'lexical_membership':
            require(name.as_posix() == 'lexical-membership.sqlite', 'local prepared membership required')
        require(not name.is_absolute() or kind == 'ort_dll', 'inventory path escape')
        path = _artifact_path(root / name, kind, binding)
        require(path not in seen, 'duplicate inventory path')
        seen.add(path)
        # Keep traversed components for subsequent session safety checks.
        records.append((root / name, binding, kind))
    dll = artifacts['ort_dll']
    require((dll['size'], dll['sha256']) == expected_dll, 'unpinned ORT DLL')
    return records


def validate_full_manifest(manifest, contract, *, pack_root, session=None, experimental_ef2048=False):
    """Verify actual FULL inventory; optionally reuse a caller-owned session.

    Synthetic tests patch authorities, not product facts, and are not actual FULL
    acceptance. Standalone callers get fresh content verification on every call.
    """
    declaration, canonical, canonical_binding = _canonical(contract, experimental_ef2048)
    require(manifest.get('canonical_contract') == {'schema': contract['schema'],
            **canonical_binding}, 'canonical binding mismatch')
    require(manifest.get('schema') == PACK_SCHEMA and manifest.get('object_type') == 'runtime_pack',
            'FULL pack object/schema required')
    require(manifest.get('declarative_contract') == declaration, 'FULL declaration required')
    snapshot, spec = _snapshot(contract)
    ref = manifest.get('snapshot', {})
    require(ref.get('identity') == spec['path'] and ref.get('size') == spec['size'] and
            ref.get('sha256') == spec['sha256'], 'snapshot binding mismatch')
    _safe_name(ref.get('path'))
    require(_controlled_path(Path(pack_root) / ref['path'], ROOT) == snapshot,
            'controlled snapshot path mismatch')
    rows = manifest.get('full_chunk_count')
    require(type(rows) is int and 0 < rows <= 2**63-1, 'dynamic full_chunk_count required')
    require(manifest.get('contract') == runtime_contract(declaration, rows), 'runtime projection mismatch')
    require('lexical_metadata' not in manifest and 'full_declaration' not in manifest,
            'FULL pilot sidecar/metadata forbidden')
    approved_dll = approved_full_dll()
    prepared = manifest.get('pack_version') == 'p4-full-prepared-lexical-v1'
    records = _verify_inventory(manifest.get('artifacts'), pack_root,
                                expected_dll=(approved_dll['size'], approved_dll['sha256']), prepared=prepared)
    if manifest.get('pack_version') in ('p4-full-existing-assets-v1', 'p4-full-prepared-lexical-v1'):
        _verify_existing_roles(records)
    with _inventory_guard([(canonical, canonical_binding, 'canonical'),
                           (snapshot, spec, 'snapshot'), *records], session):
        if prepared:
            validate_prepared_membership(Path(pack_root) / 'lexical-membership.sqlite', manifest)
        return rows


def validate_prepared_membership(path, manifest):
    import sqlite3
    from contextlib import closing
    declaration = manifest.get('lexical_membership', {})
    snapshot = manifest['snapshot']
    require(set(declaration) == {'version', 'snapshot_sha256', 'snapshot_size', 'rows'} and
            declaration['version'] == 'p4-full-membership-v1' and
            declaration['snapshot_sha256'] == snapshot['sha256'] and
            declaration['snapshot_size'] == snapshot['size'] and
            type(declaration['rows']) is int and declaration['rows'] > 0,
            'membership metadata mismatch: run explicit prepare-lexical')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        require(conn.execute('PRAGMA integrity_check').fetchall() == [('ok',)],
                'membership corrupt: run explicit prepare-lexical')
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        require(tables == [('members',), ('meta',)], 'membership schema mismatch')
        expected = {'version': declaration['version'], 'snapshot_sha256': snapshot['sha256'],
                    'snapshot_size': str(snapshot['size']), 'rows': str(declaration['rows'])}
        require(conn.execute('PRAGMA table_info(meta)').fetchall() ==
                [(0, 'key', 'TEXT', 0, None, 1), (1, 'value', 'TEXT', 1, None, 0)],
                'membership meta schema mismatch')
        metadata = conn.execute('SELECT key,value FROM meta').fetchall()
        require(len(metadata) == 4 and dict(metadata) == expected, 'membership metadata mismatch')
        require(conn.execute('PRAGMA table_info(members)').fetchall() ==
                [(0, 'fts_rowid', 'INTEGER', 0, None, 1), (1, 'entry_id', 'INTEGER', 1, None, 0),
                 (2, 'document_id', 'INTEGER', 1, None, 0)], 'membership schema mismatch')
        count, bad = conn.execute("SELECT count(*),coalesce(sum(typeof(fts_rowid)!='integer' OR "
                                 "typeof(entry_id)!='integer' OR typeof(document_id)!='integer'),0) FROM members").fetchone()
        require(count == declaration['rows'] and bad == 0, 'membership rows mismatch')
    return count


def _key(entry):
    require(isinstance(entry, dict), 'typed key required')
    key = tuple(entry.get(name) for name in ('kind', 'namespace', 'value'))
    require(all(isinstance(value, str) and value.strip() for value in key), 'typed key required')
    require(key[0] != 'episode', 'episode candidate forbidden')
    return key


def _collection(response, name):
    value = response.get(name)
    require(isinstance(value, list) and all(isinstance(item, dict) for item in value),
            f'{name} collection required')
    return value


def validate_response_structure(response):
    """Wire-shape checks only; this does NOT verify snapshot facts or confer PASS."""
    require(response.get('contract_version') == '2' and
            response.get('response_version') == 'p4-semantic-evidence-v1', 'response version mismatch')
    require(response.get('identity_status') == 'not_asserted' and
            response.get('promoted_identities') == [] and 'canonical' in response and
            response['canonical'] is None and 'entity_tag' in response and
            response['entity_tag'] is None, 'identity promotion forbidden')
    require('identity_assertions' not in response, 'non-contract identity_assertions field forbidden')
    seen = set()
    for candidate in _collection(response, 'candidates'):
        key = _key(candidate.get('entry'))
        require(key not in seen, 'duplicate candidate')
        seen.add(key)
        provenance = _collection(candidate, 'provenance')
        pins = _collection(candidate, 'trusted_pins')
        require(provenance or pins, 'retrieval provenance or trusted pin required')
        for proof in provenance:
            hit = proof.get('hit')
            require(isinstance(hit, dict) and _key(hit.get('entry')) == key,
                    'typed provenance mismatch')
            require(all(isinstance(hit.get(name), str) and hit[name].strip()
                        for name in ('document_id', 'source_id', 'evidence_id')),
                    'source/evidence provenance required')
        for pin in pins:
            require(_key(pin.get('entry')) == key and pin.get('match') in ('exact', 'alias'),
                    'typed pin mismatch')
    for name in ('sources', 'evidence', 'documents', 'citations', 'trusted_pins'):
        _collection(response, name)
    return len(seen)


def _rows(conn, sql, parameters=()):
    with closing(conn.execute(sql, parameters)) as cursor:
        return cursor.fetchall()


def _verify_response_snapshot(response, conn):
    """Resolve active proof closure against an already controlled read-only snapshot."""
    sources = {}
    for source in response['sources']:
        sid = source.get('source_id')
        require(isinstance(sid, str) and sid and sid not in sources, 'invalid/duplicate source')
        rows = _rows(conn, 'SELECT metadata FROM sources WHERE source_id=?', (sid,))
        require(len(rows) == 1 and json.loads(rows[0][0]) == source.get('metadata'),
                'snapshot source mismatch')
        sources[sid] = source
    active_sources, active_documents, active_evidence, active_pins = set(), [], [], []

    def verify_pin(pin, key, eid):
        require(_key(pin.get('entry')) == key and pin in response['trusted_pins'],
                'trusted pin closure mismatch')
        sid, evidence = pin.get('source_id'), pin.get('evidence_id')
        require(sid in sources and isinstance(evidence, str) and evidence.strip(),
                'pin source/evidence required')
        if pin.get('match') == 'exact':
            require(response.get('query') == key[2], 'exact pin query mismatch')
            rows = _rows(conn, "SELECT 1 FROM entry_evidence WHERE entry_id=? AND source_id=? "
                         "AND evidence_id=? AND status='source_backed'", (eid, sid, evidence))
        else:
            require(pin.get('match') == 'alias', 'invalid pin match')
            rows = _rows(conn, "SELECT 1 FROM aliases WHERE entry_id=? AND source_id=? "
                         "AND evidence_id=? AND text=? AND status='source_backed'",
                         (eid, sid, evidence, response.get('query')))
        require(rows, 'untrusted pin evidence')
        active_sources.add(sid)

    def entry_id(key):
        rows = _rows(conn, "SELECT id FROM entries WHERE kind=? AND namespace=? AND value=? "
                     "AND conflicted=0 AND EXISTS (SELECT 1 FROM entry_evidence v JOIN sources s "
                     "ON s.source_id=v.source_id WHERE v.entry_id=entries.id AND v.status='source_backed')",
                     key)
        require(len(rows) == 1, 'untrusted typed entry')
        return rows[0][0]

    for candidate in response['candidates']:
        key = _key(candidate['entry'])
        eid = entry_id(key)
        require(candidate.get('typed_identity') ==
                {'kind': key[0], 'namespace': key[1], 'entry_id': str(eid)},
                'typed identity mismatch')
        for proof in candidate['provenance']:
            hit = proof['hit']
            rows = _rows(conn, "SELECT title,original,status,source_id,evidence_id FROM documents "
                         "WHERE id=? AND entry_id=? AND status IN ('source_backed','generated_from_evidence')",
                         (hit['document_id'], eid))
            require(len(rows) == 1, 'snapshot document missing')
            title, original, status, sid, evidence = rows[0]
            require(sid in sources and (sid, evidence) == (hit['source_id'], hit['evidence_id']),
                    'document evidence mismatch')
            doc = {'document_id': hit['document_id'], 'entry_id': str(eid), 'entry_key': candidate['entry'],
                   'title': title, 'original': original, 'status': status,
                   'source_id': sid, 'evidence_id': evidence}
            ev = {name: doc[name] for name in
                  ('document_id', 'entry_id', 'status', 'source_id', 'evidence_id')}
            require(doc in response['documents'] and ev in response['evidence'] and
                    {name: doc[name] for name in ('document_id', 'source_id', 'evidence_id')}
                    in response['citations'], 'document/evidence/citation closure mismatch')
            active_sources.add(sid)
            if doc not in active_documents:
                active_documents.append(doc)
                active_evidence.append(ev)
        for pin in candidate['trusted_pins']:
            verify_pin(pin, key, eid)
            if pin not in active_pins:
                active_pins.append(pin)
    # Rust retains all trusted pins separately, including candidates beyond the limit.
    for pin in response['trusted_pins']:
        key = _key(pin.get('entry'))
        verify_pin(pin, key, entry_id(key))
        if pin not in active_pins:
            active_pins.append(pin)
    require(set(sources) == active_sources and len(response['documents']) == len(active_documents) and
            len(response['evidence']) == len(active_evidence) and
            len(response['citations']) == len(active_documents) and
            len(response['trusted_pins']) == len(active_pins), 'inactive/duplicate proof collection')


def validate_response(response, *, snapshot_conn=None, session=None, experimental_ef2048=False):
    """Validate every response's provenance; caller owns session and connection."""
    count = validate_response_structure(response)
    require(snapshot_conn is not None, 'controlled readonly snapshot connection required')
    config = CONFIG
    contract = json.loads(Path(config).read_bytes())
    _, canonical, canonical_binding = _canonical(contract, experimental_ef2048)
    snapshot, spec = _snapshot(contract)
    databases = _rows(snapshot_conn, 'PRAGMA database_list')
    require(len(databases) == 1 and databases[0][1] == 'main' and
            _controlled_path(databases[0][2], ROOT) == snapshot and
            _rows(snapshot_conn, 'PRAGMA query_only')[0][0] == 1,
            'controlled readonly snapshot connection required')
    ref = response.get('snapshot', {})
    require(ref.get('identity') == spec['path'] and ref.get('size') == spec['size'] and
            ref.get('sha256') == spec['sha256'], 'response snapshot binding mismatch')
    with _inventory_guard([(canonical, canonical_binding, 'canonical'),
                           (snapshot, spec, 'snapshot')], session):
        _verify_response_snapshot(response, snapshot_conn)
    return count
