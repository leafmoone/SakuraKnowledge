"""Offline native tag graph assessment and builder projection; not a runtime API."""
from collections import defaultdict

RULE_VERSION = 'danbooru-native-1'
P3_SCHEMA = '''
CREATE TABLE tag_resolutions(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
 target INTEGER REFERENCES entries, matched_by TEXT NOT NULL,
 canonical_status TEXT NOT NULL, category INTEGER, source_id TEXT REFERENCES sources,
 evidence_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX tag_resolution_name ON tag_resolutions(name,matched_by);
CREATE INDEX tag_resolution_target ON tag_resolutions(target);
CREATE INDEX link_dst ON links(dst,relation,verification_status);
'''


def assess(tags, aliases, covered_names, max_chain=16):
    """Caller supplies frozen raw native records and proven per-name outgoing scope.

    No title/score/generated string enters the native identity set. Invalid graph
    outcomes preserve the observed spelling but never fabricate a terminal.
    """
    native, outgoing = defaultdict(list), defaultdict(list)
    for tag in tags:
        if not isinstance(tag.get('name'),str) or not tag['name']:
            raise ValueError('native tag name required')
        if type(tag.get('id')) is not int or type(tag.get('category')) is not int:
            raise ValueError('native tag numeric id/category required')
        native[tag['name']].append(tag)
    for alias in aliases:
        if not isinstance(alias.get('antecedent_name'),str) or not isinstance(alias.get('consequent_name'),str):
            raise TypeError('official alias endpoints required')
        outgoing[alias['antecedent_name']].append(alias)
    result = {}
    for name in sorted(set(native)|set(outgoing)):
        current, visited, chain, reason = name, set(), [], None
        while True:
            if current in visited:
                reason = 'alias_cycle'
                break
            visited.add(current)
            if current not in covered_names:
                reason = 'alias_scope_partial'
                break
            edges = outgoing[current]
            by_id = defaultdict(list)
            for edge in edges:
                by_id[edge.get('id')].append(edge)
            if any(any(item != group[0] for item in group) for group in by_id.values()):
                reason = 'alias_source_conflict'
                break
            if any(x.get('status') not in {'active','deleted','retired'} for x in edges):
                reason = 'alias_status_unknown'
                break
            active = {x['id']:x for x in edges if x.get('status') == 'active'}
            if len(active) > 1:
                reason = 'multiple_active_aliases'
                break
            if active:
                if len(chain) >= max_chain:
                    reason = 'alias_chain_limit'
                    break
                edge = next(iter(active.values()))
                chain.append(edge['id'])
                current = edge['consequent_name']
                continue
            if not native[current]:
                reason = 'missing_native_terminal'
            elif len(native[current]) != 1:
                reason = 'native_conflict'
            elif native[current][0].get('is_deprecated') is True:
                reason = 'deprecated_terminal'
            elif native[current][0].get('is_deprecated') is not False:
                reason = 'lifecycle_unknown'
            break
        result[name] = {'terminal':None if reason else current,
                        'canonical_status':'unknown' if reason else 'canonical',
                        'reason':reason,'chain':chain,
                        'category':None if reason else native[current][0]['category']}
    return result


def insert_projection(conn, record, source, fallback):
    """Builder-only import after real endpoints. Does not assert native identities."""
    import json

    from .storage import entry_id
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='tag_resolutions' AND type='table'").fetchone():
        raise ValueError('P3 projection capability not enabled')
    if record.get('status') != 'source_backed' or record.get('rule_version') != RULE_VERSION:
        raise ValueError('tag resolution must be source-backed compiled rule v1')
    if record.get('matched_by') not in {'native_exact','official_alias','wiki_name'}:
        raise ValueError('unknown native lookup proof role')
    if record.get('canonical_status') not in {'canonical','unknown'}:
        raise ValueError('invalid canonical status')
    if not isinstance(record.get('name'),str) or not record['name']:
        raise ValueError('lookup name required')
    target = None
    if record.get('target') is not None:
        key = record['target']
        if key['kind'] != 'tag' or key['namespace'] != 'danbooru.tag':
            raise ValueError('projection target must be typed native tag')
        target = entry_id(conn,key)
        if target is None:
            raise ValueError('projection native endpoint missing')
    proof = record.get('evidence_chain')
    if not isinstance(proof,list) or not proof:
        raise ValueError('source proof chain required')
    if record['canonical_status'] == 'canonical':
        if target is None or type(record.get('category')) is not int:
            raise ValueError('canonical target and category required')
        if not {'native_identity','canonical_scope'} <= {x.get('role') for x in proof}:
            raise ValueError('native identity/canonical scope proofs required')
    for ref in proof:
        if not all(ref.get(k) for k in ('role','source_id','evidence_id','raw_sha256')):
            raise ValueError('missing bound proof reference')
    conn.execute('INSERT INTO tag_resolutions(name,target,matched_by,canonical_status,category,source_id,evidence_id,payload) VALUES(?,?,?,?,?,?,?,?)',
                 (record['name'],target,record['matched_by'],record['canonical_status'],record.get('category'),
                  source['source_id'],record.get('evidence_id',fallback),json.dumps(record,ensure_ascii=False)))
    return 'accepted'


def verify_projection(conn):
    """Publication gate: no canonical projection over untrusted/conflicted identities."""
    row = conn.execute("SELECT value FROM build_meta WHERE key='p3_resolver_version'").fetchone()
    if row is None:
        return
    if row[0] != '1':
        raise ValueError('unsupported P3 projection version')
    bad = conn.execute("SELECT count(*) FROM tag_resolutions r JOIN entries e ON e.id=r.target "
                       "WHERE e.kind!='tag' OR e.namespace!='danbooru.tag' OR e.conflicted!=0 OR "
                       "NOT EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed')").fetchone()[0]
    if bad:
        raise ValueError('P3 projection has untrusted native endpoint')
    for row in conn.execute('SELECT payload FROM tag_resolutions'):
        record = json_load(row[0])
        # Import validation owns graph compilation; gate preserves original proof.
        if record.get('rule_version') != RULE_VERSION or not record.get('evidence_chain'):
            raise ValueError('P3 projection proof invalid')


def json_load(text):
    import json
    return json.loads(text)
