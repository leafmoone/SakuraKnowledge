"""Independent exact-template check against frozen JSON, not the adapter/prover."""
import argparse
import hashlib
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

from tools.source_pack import binding


def verify(pack, frozen):
    start = time.monotonic()
    pack, frozen = Path(pack), Path(frozen)
    raw_path, index_path = frozen / 'moegirl/extra_info.json', frozen / 'moegirl/char_index.json'
    raw_binding, index_binding = binding(raw_path), binding(index_path)
    raw, index = json.loads(raw_path.read_bytes()), json.loads(index_path.read_bytes())
    expected = {(name, i) for name, values in raw.items() for i, text in enumerate(values) if isinstance(text, str) and text.strip()}
    observation_bindings = {name: binding(frozen / 'moegirl' / (name + '.json')) for name in ('attrs', 'subjects', 'extra_info.outcomes')}
    outcomes = json.loads((frozen / 'moegirl/extra_info.outcomes.json').read_bytes())
    indexed_names = set(index)
    category_expected = {}
    for file, field in [('attrs', 'current_attr_category_paths'), ('subjects', 'current_subject_category_paths')]:
        tree = json.loads((frozen / 'moegirl' / (file + '.json')).read_bytes())
        queue = [(tree, '#', [])]
        expected_paths = {}
        while queue:
            node, locator, parents = queue.pop()
            categories = parents + ([node['name']] if 'name' in node else [])
            for i, page in enumerate(node['pages']):
                if page['name'] in indexed_names:
                    expected_paths.setdefault(page['name'], []).append({'categories': categories, 'page_url': page.get('url'), 'locator': locator + '/pages/' + str(i)})
            queue.extend((child, locator + '/subcategories/' + str(i), categories) for i, child in reversed(list(enumerate(node['subcategories']))))
        category_expected[field] = expected_paths
    seen = set()
    identity_positions = {name: i for i, name in enumerate(index)}
    conn = sqlite3.connect((pack / 'knowledge.sqlite').resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    counts = Counter()
    try:
        sources = {sid: json.loads(payload) for sid, payload in conn.execute('SELECT source_id,metadata FROM sources')}
        for did, sid, eid, status, original, payload, kind, namespace, name, entry_id in conn.execute('SELECT d.id,d.source_id,d.evidence_id,d.status,d.original,d.payload,e.kind,e.namespace,e.value,e.id FROM documents d JOIN entries e ON e.id=d.entry_id ORDER BY d.id'):
            proof = json.loads(payload).get('text_provenance')
            if not isinstance(proof, dict) or proof.get('version') != 'moegirl-frozen-template-v1' or proof.get('method') != 'frozen_template_exact':
                raise ValueError('template proof method/version missing')
            position = proof.get('template_index')
            if type(position) is not int or position < 0 or (name, position) not in expected:
                raise ValueError('raw template record locator missing')
            identity_position = identity_positions[name]
            if proof['identity_index_locator'] != 'moegirl/char_index.json#/' + str(identity_position):
                raise ValueError('identity index locator mismatch')
            raw_locator = 'moegirl/extra_info.json#/' + name.replace('~', '~0').replace('/', '~1') + '/' + str(position)
            if proof['raw_locator'] != raw_locator or proof['raw_title'] != name or index[identity_position] != name:
                raise ValueError('template/index locator binding mismatch')
            if kind != 'character' or namespace != 'moegirl.character' or status != 'source_backed' or proof['raw_source_id'] != sid or eid != sid + ':' + raw_locator:
                raise ValueError('source/evidence/typed closure mismatch')
            if original != raw[name][position] or proof['trusted_text_sha256'] != hashlib.sha256(original.encode('utf-8')).hexdigest():
                raise ValueError('exact frozen text/hash mismatch')
            if proof['raw_file_sha256'] != raw_binding['sha256'] or proof['identity_index_sha256'] != index_binding['sha256']:
                raise ValueError('frozen file binding mismatch')
            owned = {item['path']: item for item in sources[sid]['owned_input_inventory']}
            if owned['moegirl/extra_info.json']['sha256'] != raw_binding['sha256'] or owned['moegirl/char_index.json']['sha256'] != index_binding['sha256']:
                raise ValueError('source input inventory mismatch')
            if not conn.execute("SELECT 1 FROM entry_evidence WHERE entry_id=? AND status='source_backed' AND source_id!=?", (entry_id, sid)).fetchone():
                raise ValueError('template cannot independently create identity')
            if (name, position) in seen:
                raise ValueError('duplicate raw projection locator')
            seen.add((name, position)); counts['exact_template_documents'] += 1
        if seen != expected:
            raise ValueError('frozen template coverage incomplete')
        current_sources = {sid for sid, meta in sources.items() if meta.get('conversion_spec_version') == 'moegirl-frozen-template-v1'}
        if len(current_sources) != 1:
            raise ValueError('exactly one current raw source required')
        current_source = next(iter(current_sources))
        observation_owned = {item['path']: item for item in sources[current_source]['owned_input_inventory']}
        for name, saved in observation_bindings.items():
            declared = observation_owned.get('moegirl/' + name + '.json')
            if not declared or declared['sha256'] != saved['sha256'] or declared['size'] != saved['size']:
                raise ValueError('category/state source-owned frozen file binding mismatch')
        observed_titles = set()
        for kind, namespace, name, status, payload in conn.execute('SELECT e.kind,e.namespace,e.value,v.status,v.payload FROM entry_evidence v JOIN entries e ON e.id=v.entry_id WHERE v.source_id=?', (current_source,)):
            observation = json.loads(payload)['raw']
            state = 'template_present' if raw.get(name) else 'empty_template_list' if name in raw else outcomes[name]['status']
            if name in observed_titles or (kind, namespace) != ('character', 'moegirl.character') or observation['current_template_state'] != state or observation['source_outcome'] != outcomes.get(name):
                raise ValueError('current raw-state source/typed observation mismatch')
            if status != ('source_backed' if state == 'template_present' else 'no_reference'):
                raise ValueError('missing/empty/skipped cannot create current identity evidence')
            for field, expected_paths in category_expected.items():
                if observation[field] != expected_paths.get(name, []):
                    raise ValueError('current native category path/file/page locator mismatch')
                counts[field] += len(observation[field])
            observed_titles.add(name); counts['current_state_' + state] += 1
        if observed_titles != set(index):
            raise ValueError('current category/state index coverage incomplete')
        result = {'status': 'PASS', 'documents': len(seen), 'record_titles': len({n for n, _ in seen}),
                  'raw_records': len(raw), 'empty_lists': sum(not v for v in raw.values()),
                  'classification': dict(counts), 'seconds': time.monotonic() - start,
                  'identity_basis': 'independent historical source-backed entry evidence',
                  'scope': 'partial frozen templates; not full page or authenticated producer revision'}
    finally:
        conn.close()
    if any(binding(frozen / 'moegirl' / (name + '.json')) != saved for name, saved in observation_bindings.items()):
        raise ValueError('frozen category/state input changed while independently verifying')
    if binding(raw_path) != raw_binding or binding(index_path) != index_binding:
        raise ValueError('frozen input changed while independently verifying')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pack', required=True)
    parser.add_argument('--frozen', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    with output.open('x', encoding='utf-8') as stream:
        result = verify(args.pack, args.frozen)
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
