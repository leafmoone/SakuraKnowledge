"""Explicit example adapter: raw demo facts, no SQL/runtime knowledge."""
import json
from pathlib import Path


class DemoAdapter:
    adapter_id = 'example-demo-json'
    adapter_version = '1'

    def inspect(self, path):
        return {'namespaces': ['demo.subject', 'demo.character'], 'rows': len(json.loads(Path(path).read_bytes())['items'])}

    def source_metadata(self, path):
        return {'source_id': 'demo-frozen-1', 'provider': 'demo', 'repo': 'local://demo-fixture',
                'dataset_role': 'fixture', 'asset_name': Path(path).name, 'importer_version': 'demo-1'}

    def iter_records(self, path):
        for item in json.loads(Path(path).read_bytes())['items']:
            key = {'kind': item['type'], 'namespace': 'demo.' + item['type'], 'value': item['id']}
            yield {'key': key, 'status': 'source_backed', 'aliases': [{'text': item['name'], 'status': 'source_backed'}],
                   'documents': [{'title': item['name'], 'original': item['description'], 'status': item.get('text_status', 'source_backed')}],
                   'evidence_id': 'demo:item:' + item['id']}
        for relation in json.loads(Path(path).read_bytes())['relations']:
            yield {'record_type': 'link', 'src': {'kind': 'character', 'namespace': 'demo.character', 'value': relation['character']},
                   'dst': {'kind': 'subject', 'namespace': 'demo.subject', 'value': relation['subject']},
                   'relation': 'character_of', 'verification_status': relation['status'],
                   'method': 'demo_native_fact' if relation['status'] == 'verified' else 'demo_candidate',
                   'evidence_id': 'demo:relation:' + relation['character']}
