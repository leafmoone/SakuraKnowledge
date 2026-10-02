"""Read-only FULL acceptance checks; never load artifacts or run inference.

implementation_origin=clean_room_reimplementation_after_untracked_source_loss
recovered_original_source=false
reference_sources=committed Rust pilot 471829, approved FULL requirements/P3 snapshot,
committed pilot tokenizer/chunk/ANN/runtime. This is not recovered original source.
"""
import hashlib
import json
import re
from contextlib import closing, contextmanager
from pathlib import Path

from tools import p4_rust_pilot as pilot
from tools.p4_full_preflight import (
    CONFIG,
    IMPLEMENTATION,
    PINNED_JOBS,
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


def _no_links(path):
    for part in (path, *path.parents):
        require(not part.is_symlink() and
                not (hasattr(part, 'is_junction') and part.is_junction()),
                'inventory symlink/junction forbidden')


def _controlled_path(path, root):
    """Allow relative parent traversal only when the final file remains in ROOT."""
    path, root = Path(path).absolute(), Path(root).absolute()
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
    require(isinstance(record['path'], str) and record['path'], 'binding path required')
    require(type(record['size']) is int and record['size'] > 0, 'positive binding size required')
    require(isinstance(record['sha256'], str) and
            re.fullmatch('[0-9a-f]{64}', record['sha256']), 'binding SHA256 required')


def _approved_dll_path():
    """Only the existing pack authenticated by the pinned pilot job grants authority."""
    try:
        job_name = 'configs/p4-rust-pilot-v1.json'
        job_path = _controlled_path(Path(ROOT) / job_name, ROOT)
        job_bytes = job_path.read_bytes()
        require(hashlib.sha256(job_bytes).hexdigest() == PINNED_JOBS[job_name],
                'unapproved pilot configuration')
        job = json.loads(job_bytes)
        require(job['manifest'] == pilot.PACK, 'unapproved pilot pack path')
        pack_path = _controlled_path(Path(ROOT) / pilot.PACK, ROOT)
        pack_bytes = pack_path.read_bytes()
        require(hashlib.sha256(pack_bytes).hexdigest() == job['frozen_sha256'][pilot.PACK],
                'unapproved pilot pack hash')
        record = json.loads(pack_bytes)['artifacts']['ort_dll']
        _binding(record)
        require((record['size'], record['sha256']) == (pilot.DLL_SIZE, pilot.DLL_SHA),
                'unpinned approved ORT DLL')
        path = (pack_path.parent / record['path']).absolute()
        _no_links(path)
        resolved = path.resolve(strict=True)
        _no_links(resolved)
        require(resolved.is_file(), 'approved ORT DLL missing')
        return resolved
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('BLOCKED: approved external ORT DLL binding unavailable') from exc


def _artifact_path(path, kind, binding):
    path = Path(path).absolute()
    _no_links(path)
    resolved = path.resolve(strict=True)
    _no_links(resolved)
    if kind == 'ort_dll':
        require((binding['size'], binding['sha256']) == (pilot.DLL_SIZE, pilot.DLL_SHA),
                'unpinned ORT DLL')
    if not resolved.is_relative_to(Path(ROOT).resolve(strict=True)):
        require(kind == 'ort_dll', 'inventory path escape')
        require(resolved == _approved_dll_path(), 'unapproved external ORT DLL path')
        require(resolved.is_file(), 'inventory non-file')
        return resolved
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


@contextmanager
def _inventory_guard(records):
    """Stream hashes before and after use; recheck ROOT/kind-specific authority."""
    states = [(path, binding, kind, _verify_file(_artifact_path(path, kind, binding), binding))
              for path, binding, kind in records]
    try:
        yield
    finally:
        for path, binding, kind, before in states:
            require(_artifact_path(path, kind, binding) == path and _file_state(path) == before,
                    'inventory changed')
            _verify_file(path, binding)


def _canonical(contract):
    declaration = validate_contract(contract)
    require(Path(CONFIG).absolute() == Path(ROOT).absolute() / CANONICAL_PATH,
            'controlled canonical path required')
    path = _controlled_path(CONFIG, ROOT)
    data = path.read_bytes()
    require(json.loads(data) == contract, 'canonical bytes do not contain approved contract')
    binding = {'path': CANONICAL_PATH, 'size': len(data),
               'sha256': hashlib.sha256(data).hexdigest()}
    return declaration, path, binding


def _snapshot(contract):
    spec = contract['snapshot']
    _binding(spec)
    name = Path(spec['path'])
    require(not name.is_absolute() and '..' not in name.parts, 'snapshot path escape')
    return _controlled_path(Path(ROOT) / name, ROOT), spec


def _verify_inventory(artifacts, pack_root, *, expected_dll):
    """Bindings are relative to the pack, but containment authority is Knowledge ROOT."""
    require(isinstance(artifacts, dict) and set(artifacts) == ARTIFACTS,
            'exact FULL artifact inventory required (no sidecar)')
    external = artifacts['external_data']
    require(isinstance(external, list) and external, 'nonempty external_data required')
    root = Path(pack_root).absolute()
    _no_links(root)
    require(root.resolve(strict=True).is_relative_to(Path(ROOT).resolve(strict=True)) and
            root.is_dir(), 'controlled pack root required')
    records, seen = [], set()
    inventory = [(key, artifacts[key]) for key in sorted(ARTIFACTS - {'external_data'})]
    inventory.extend(('external_data', binding) for binding in external)
    for kind, binding in inventory:
        _binding(binding)
        name = Path(binding['path'])
        require(not name.is_absolute() or kind == 'ort_dll', 'inventory path escape')
        path = _artifact_path(root / name, kind, binding)
        require(path not in seen, 'duplicate inventory path')
        seen.add(path)
        records.append((path, binding, kind))
    dll = artifacts['ort_dll']
    require((dll['size'], dll['sha256']) == expected_dll, 'unpinned ORT DLL')
    return records


def validate_full_manifest(manifest, contract, *, pack_root):
    """Complete inventory verification, including actual approved snapshot bytes.

    This is intentionally expensive for FULL. Synthetic tests patch authorities,
    not the product facts, and must not be reported as actual FULL acceptance.
    """
    declaration, canonical, canonical_binding = _canonical(contract)
    require(manifest.get('canonical_contract') == {'schema': contract['schema'],
            **canonical_binding}, 'canonical binding mismatch')
    require(manifest.get('schema') == PACK_SCHEMA and manifest.get('object_type') == 'runtime_pack',
            'FULL pack object/schema required')
    require(manifest.get('declarative_contract') == declaration, 'FULL declaration required')
    require(manifest.get('implementation_origin') == IMPLEMENTATION and
            manifest.get('recovered_original_source') is False, 'clean-room provenance required')
    snapshot, spec = _snapshot(contract)
    ref = manifest.get('snapshot', {})
    require(ref.get('identity') == spec['path'] and ref.get('size') == spec['size'] and
            ref.get('sha256') == spec['sha256'], 'snapshot binding mismatch')
    require(isinstance(ref.get('path'), str) and
            _controlled_path(Path(pack_root) / ref['path'], ROOT) == snapshot,
            'controlled snapshot path mismatch')
    rows = manifest.get('full_chunk_count')
    require(type(rows) is int and 0 < rows <= 2**63-1, 'dynamic full_chunk_count required')
    require(manifest.get('contract') == runtime_contract(declaration, rows), 'runtime projection mismatch')
    require('lexical_metadata' not in manifest and 'full_declaration' not in manifest,
            'FULL pilot sidecar/metadata forbidden')
    records = _verify_inventory(manifest.get('artifacts'), pack_root,
                                expected_dll=(pilot.DLL_SIZE, pilot.DLL_SHA))
    with _inventory_guard([(canonical, canonical_binding, 'canonical'),
                           (snapshot, spec, 'snapshot'), *records]):
        return rows


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


def validate_response(response, *, snapshot_conn=None):
    """Complete response check. Caller owns the connection; it is never closed here."""
    count = validate_response_structure(response)
    require(snapshot_conn is not None, 'controlled readonly snapshot connection required')
    contract = json.loads(Path(CONFIG).read_bytes())
    _, canonical, canonical_binding = _canonical(contract)
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
                           (snapshot, spec, 'snapshot')]):
        _verify_response_snapshot(response, snapshot_conn)
    return count
