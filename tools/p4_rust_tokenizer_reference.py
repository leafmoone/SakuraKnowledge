"""Create authorized token-ID reference; never load a model or run embedding."""
import hashlib
import importlib.metadata
from pathlib import Path

from tools import p4_exact_pilot as pilot


def main():
    output = pilot.local('reports/P4/rust-tokenizer-reference-v1.json')
    pilot.require(not output.exists(), 'reference exists')
    job_path = pilot.local('configs/p4-cpu-native-b-v2.json')
    job = pilot.load(job_path)
    model, contract, manifest, cases = pilot.prepare(job)
    pilot.require(importlib.metadata.version('tokenizers') == '0.22.2', 'tokenizers version')
    directory = pilot.local(model['asset_directory'])
    tokenizer_path = directory / 'tokenizer.json'
    before = {str(p): pilot.sha(p) for p in (job_path, tokenizer_path, pilot.local(job['gold']))}
    raw, wrapper = pilot.frozen_tokenizers(directory)
    records = []
    for case in sorted(cases, key=lambda c: c['case_id']):
        text = case['query']
        encoding = raw.encode(text)
        actual = wrapper(text, add_special_tokens=True, truncation=False, padding=False)
        pilot.require(encoding.ids == actual['input_ids'] and
                      encoding.attention_mask == actual['attention_mask'], 'Python ID mismatch')
        pilot.require(len(encoding.ids) <= contract['max_sequence_tokens'], 'token budget')
        records.append({'case_id': case['case_id'], 'query': text,
                        'query_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                        'input_ids': encoding.ids, 'attention_mask': encoding.attention_mask,
                        'token_count': len(encoding.ids)})
    pilot.require(len(records) == 120, '120 cases required')
    pilot.require(pilot.prepare(job) == (model, contract, manifest, cases), 'inputs changed')
    for path, digest in before.items():
        pilot.bound(Path(path), digest)
    pilot.save(output, {'schema': 'p4-rust-tokenizer-reference-v1', 'status': 'PASS',
                        'embedding_executed': False, 'model_loaded': False,
                        'tokenizers_version': '0.22.2', 'tokenizer_sha256': pilot.sha(tokenizer_path),
                        'input_sha256': before, 'cases': records})


if __name__ == '__main__':
    main()
