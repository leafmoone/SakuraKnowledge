"""Four-file raw adapter; declared inventory is the complete read boundary."""
import json
from pathlib import Path


class MultiAdapter:
    adapter_id = 'example-four-file-json'
    adapter_version = '1'

    def input_inventory(self, path):
        return [{'path': name, 'role': name.removesuffix('.json')} for name in
                ['subjects.json', 'characters.json', 'relations.json', 'metadata.json']]

    def inspect(self, path):
        return json.loads((Path(path) / 'metadata.json').read_bytes())

    def source_metadata(self, path):
        return json.loads((Path(path) / 'metadata.json').read_bytes())['source']

    def iter_records(self, path):
        path = Path(path)
        for filename, kind in [('subjects.json', 'subject'), ('characters.json', 'character')]:
            for item in json.loads((path / filename).read_bytes()):
                yield {'key': {'kind': kind, 'namespace': 'demo.' + kind, 'value': item['id']},
                       'status': 'source_backed', 'aliases': [{'text': item['name'], 'status': 'source_backed'}],
                       'documents': [{'title': item['name'], 'original': item['description'], 'status': item.get('text_status', 'source_backed')}],
                       'evidence_id': filename + ':' + item['id']}
        for item in json.loads((path / 'relations.json').read_bytes()):
            yield {'record_type': 'link', 'src': {'kind': 'character', 'namespace': 'demo.character', 'value': item['character']},
                   'dst': {'kind': 'subject', 'namespace': 'demo.subject', 'value': item['subject']},
                   'relation': 'character_of', 'verification_status': item['status'],
                   'method': 'declared_fixture_fact', 'evidence_id': 'relations:' + item['character']}
