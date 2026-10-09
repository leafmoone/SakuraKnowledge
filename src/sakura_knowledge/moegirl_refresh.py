"""Frozen local Moegirl refresh: exact partial templates, historical fields separated."""
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from .adapters import MOEGIRL_FILES, iter_moegirl, iter_moegirl_mappings
from .model import EntryKey

RAW_FILES = ('extra_info', 'extra_info.outcomes', 'extra_info.missing', 'attrs', 'subjects')
MAPPING_FILES = ('bgm2moegirl', 'moegirl2bgm', 'bgm_info', 'bgm_redirects_full')
VERSION = 'moegirl-frozen-template-v1'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def pointer(value):
    return value.replace('~', '~0').replace('/', '~1')


def category_observations(tree, allowed):
    """Keep native category paths as raw observations, not typed works or relations."""
    result = {}
    def walk(node, stack, locator):
        if not isinstance(node, dict) or not isinstance(node.get('pages'), list) or not isinstance(node.get('subcategories'), list):
            raise TypeError('invalid frozen category tree')
        if 'name' in node and (not isinstance(node['name'], str) or not node['name']):
            raise ValueError('invalid category title')
        if any(not isinstance(page, dict) or not isinstance(page.get('name'), str) for page in node['pages']):
            raise ValueError('invalid category page')
        stack = stack + ([node['name']] if 'name' in node else [])
        for i, page in enumerate(node['pages']):
            if page['name'] in allowed:
                result.setdefault(page['name'], []).append({'categories': stack,
                    'page_url': page.get('url'), 'locator': locator + '/pages/' + str(i)})
        for i, child in enumerate(node['subcategories']):
            walk(child, stack, locator + '/subcategories/' + str(i))
    walk(tree, [], '#')
    return result


class MoegirlRefreshAdapter:
    adapter_id = 'moegirl-frozen-local-refresh'
    adapter_version = '1'

    def input_inventory(self, path):
        return ([{'path': 'refresh-context.json'}]
                + [{'path': 'moegirl/' + name + '.json'} for name in (*MOEGIRL_FILES, *RAW_FILES)]
                + [{'path': 'bangumi/' + name + '.json'} for name in MAPPING_FILES])

    def _load(self, path):
        from tools.source_inventory import capture
        root = Path(path)
        inventory = capture(self, root)
        context = json.loads((root / 'refresh-context.json').read_bytes())
        if context['schema'] != 'moegirl-refresh-context-v1':
            raise ValueError('refresh context schema')
        actual = {item['path']: item for item in inventory}
        for legacy in context['legacy'].values():
            for item in legacy['owned_inventory']:
                if actual.get(item['path']) != item:
                    raise ValueError('legacy source bytes changed; cannot reuse source_id')
        load = lambda name: json.loads((root / 'moegirl' / (name + '.json')).read_bytes())
        names, extra, outcomes = load('char_index'), load('extra_info'), load('extra_info.outcomes')
        if len(names) != len(set(names)) or set(extra) & set(outcomes) or set(extra) | set(outcomes) != set(names):
            raise ValueError('raw/outcome/character index closure')
        if any(not isinstance(v, list) for v in extra.values()) or any(v.get('status') not in {'missing', 'skipped_by_user'} for v in outcomes.values()):
            raise ValueError('unsupported frozen source shape/status')
        owned = [actual['moegirl/' + n + '.json'] for n in ('char_index', *RAW_FILES)]
        fingerprint = sha(json.dumps(owned, sort_keys=True, separators=(',', ':')))
        sid = 'moegirl-local-templates-' + fingerprint[:12]
        return root, context, inventory, load, names, extra, outcomes, sid

    def source_metadata(self, path):
        _, context, inventory, load, names, extra, outcomes, sid = self._load(path)
        owned = [item for item in inventory if item['path'] in {'moegirl/' + n + '.json' for n in ('char_index', *RAW_FILES)}]
        sources = []
        for group, legacy in context['legacy'].items():
            meta = copy.deepcopy(legacy['source'])
            meta['source_input_sha256'] = meta['local_sha256']
            meta['refresh_scope'] = 'historical_derived_bytes_preserved' if group == 'moegirl' else 'unchanged_mapping_bytes_candidates_only'
            meta['owned_input_inventory'] = legacy['owned_inventory']
            sources.append(meta)
        status = dict(Counter(row['status'] for row in outcomes.values()))
        sources.append({'source_id': sid, 'provider': 'moegirl', 'dataset_role': 'frozen_partial_template_and_category_observations',
            'repo': context['legacy']['moegirl']['source']['repo'], 'asset_name': 'moegirl-local-frozen-templates',
            'upstream_revision': None, 'source_declared_cutoff': None, 'exported_at': None, 'fetched_at_utc': None,
            'importer_version': self.adapter_version, 'conversion_spec_version': VERSION,
            'inspected_at_utc': context.get('inspection_recorded_at_utc'),
            'observed_checkout_revision': context.get('observed_checkout_revision'),
            'checkout_revision_scope': 'observed local checkout; not authenticated producer revision',
            'refresh_status': 'local_frozen_partial_cut; no_live_crawler_run',
            'source_observations': {'character_index': len(names), 'raw_records': len(extra),
                'raw_empty_template_lists': sum(not value for value in extra.values()),
                'outcomes': status, 'missing_work_queue': len(load('extra_info.missing'))},
            'unknown_reasons': {'upstream_revision': 'historical producer revision not authenticated',
                'source_declared_cutoff': 'local frozen bytes, not README date or current live site',
                'per_success_api_receipt': 'raw template fragments omit page revision/full response'},
            'owned_input_inventory': owned,
            'identity_basis': 'existing source-backed char_index typed keys only; no names extracted from templates',
            'text_scope': 'exact frozen crawler-selected partial infobox templates, not full article',
            'historical_metadata': 'extra_processed/CV/gender remain separate historical source; no processor rerun'})
        return sources

    def inspect(self, path):
        _, context, *_ = self._load(path)
        mapping = context['legacy']['mapping']
        count = len(mapping.get('historical_missing_endpoint_lines', []))
        expected = {mapping['source']['source_id']: {'missing_endpoint': count}} if count else {}
        return {'namespaces': ['moegirl.character', 'moegirl.category', 'bangumi.character'],
                'expected_unresolved': expected}

    def iter_records(self, path):
        root, context, inventory, load, names, extra, outcomes, sid = self._load(path)
        bindings = {item['path']: item for item in inventory}
        old_moe = context['legacy']['moegirl']['source']['source_id']
        mapping = context['legacy']['mapping']['source']['source_id']
        historical_sha = context['legacy']['moegirl']['source']['local_sha256']
        historical_seen = set()
        for line, record in enumerate(iter_moegirl(root / 'moegirl'), 1):
            fingerprint = sha(json.dumps(record, sort_keys=True, separators=(',', ':')))
            if fingerprint in historical_seen:
                continue
            historical_seen.add(fingerprint)
            ref = f'{old_moe}:{historical_sha}:line:{line}'
            for alias in record.get('aliases', []):
                alias['evidence_id'] = ref
            yield {**record, 'evidence_id': ref, 'source_id': old_moe,
                   'refresh_scope': 'historical_derived_bytes_preserved'}
        attrs = category_observations(load('attrs'), set(names))
        subjects = category_observations(load('subjects'), set(names))
        for i, name in enumerate(names):
            docs = []
            for position, text in enumerate(extra.get(name, [])):
                if not isinstance(text, str) or not text.strip().startswith('{{') or not text.strip().endswith('}}'):
                    raise ValueError('non-template fragment in frozen extra_info')
                locator = 'moegirl/extra_info.json#/' + pointer(name) + '/' + str(position)
                proof = {'version': VERSION, 'method': 'frozen_template_exact', 'raw_locator': locator,
                    'raw_title': name, 'template_index': position, 'trusted_text_sha256': sha(text),
                    'raw_file_sha256': bindings['moegirl/extra_info.json']['sha256'], 'raw_source_id': sid,
                    'identity_index_sha256': bindings['moegirl/char_index.json']['sha256'],
                    'text_scope': 'partial_crawler_selected_template; not_full_page',
                    'identity_index_locator': 'moegirl/char_index.json#/' + str(i),
                    'history': 'observed_frozen_bytes; historical_producer_revision_unknown'}
                docs.append({'title': name, 'original': text, 'status': 'source_backed',
                    'evidence_id': sid + ':' + locator, 'text_provenance': proof})
            state = 'template_present' if docs else 'empty_template_list' if name in extra else outcomes[name]['status']
            yield {'source_id': sid, 'key': EntryKey('character', 'moegirl.character', name).as_dict(),
                'status': 'source_backed' if docs else 'no_reference', 'aliases': [],
                'evidence_id': sid + ':moegirl/char_index.json#/' + str(i), 'documents': docs,
                'raw': {'current_template_state': state, 'source_outcome': outcomes.get(name),
                    'current_attr_category_paths': attrs.get(name, []), 'current_subject_category_paths': subjects.get(name, []),
                    'category_scope': 'native raw associations; not character_of or tag membership'}}
        links = list(iter_moegirl_mappings(root / 'bangumi'))
        backed = {('character', 'moegirl.character', n) for n in names}
        backed |= {('subject', 'moegirl.category', n) for n in load('subject_index')}
        stubs = set()
        mapping_sha = context['legacy']['mapping']['source']['local_sha256']
        missing_endpoint_lines = set(context['legacy']['mapping'].get('historical_missing_endpoint_lines', []))
        for line, link in enumerate(links, 1):
            original_ref = f'{mapping}:{mapping_sha}:line:{line}'
            link['raw']['original_evidence_id'] = original_ref
            if line in missing_endpoint_lines:
                yield {'source_id': mapping, 'record_type': 'unresolved', 'reason': 'missing_endpoint',
                       'raw': link, 'original_evidence_id': original_ref, 'refresh_scope': 'historical_mapping_unresolved_preserved'}
                continue
            for endpoint in [link['src'], link['dst']]:
                typed = (endpoint['kind'], endpoint['namespace'], endpoint['value'])
                if typed not in backed and typed not in stubs:
                    stubs.add(typed)
                    yield {'source_id': mapping, 'key': endpoint, 'status': 'no_reference',
                        'aliases': [], 'documents': [], 'raw': {'reason': 'candidate_endpoint_stub_not_identity'}}
            yield {**link, 'source_id': mapping}
        # Categories retain historical typed keys only; native current paths above are raw observations.
