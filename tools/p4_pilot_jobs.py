"""Bind completed pre-embedding artifacts into explicit offline pilot jobs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open('xb') as f:
        f.write((json.dumps(data, sort_keys=True, indent=2) + '\n').encode())


def main():
    gold = ROOT / 'reports/P4/retrieval-gold.json'
    corpus = ROOT / 'build/p4/continuation-pilot-v1.jsonl'
    summary = ROOT / 'reports/P4/model-freeze-summary.json'
    report = json.loads((ROOT / 'reports/P4/continuation-pilot-manifest.json').read_bytes())
    if sha(corpus) != report['corpus_sha256'] or report['selected_count'] != 50000:
        raise ValueError('pilot binding mismatch')
    if sha(gold) != 'ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba':
        raise ValueError('gold binding mismatch')
    for label in ('a', 'b'):
        prefix = f'build/p4/continuation-chunks-{label}-v1'
        manifest_path = ROOT / prefix / 'manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        if manifest['document_count'] != 50000 or manifest['corpus_sha256'] != sha(corpus):
            raise ValueError('chunk corpus mismatch')
        if sha(ROOT / prefix / 'chunks.jsonl') != manifest['chunks_sha256']:
            raise ValueError('chunk bytes mismatch')
        job = {'model': label, 'device': 'cuda', 'threads': 8, 'batch_size': 8,
               'summary': str(summary.relative_to(ROOT)).replace('\\', '/'),
               'summary_sha256': sha(summary),
               'corpus': str(corpus.relative_to(ROOT)).replace('\\', '/'),
               'corpus_sha256': sha(corpus), 'chunks': prefix + '/chunks.jsonl',
               'chunks_manifest': prefix + '/manifest.json',
               'chunks_manifest_sha256': sha(manifest_path),
               'gold': 'reports/P4/retrieval-gold.json', 'gold_sha256': sha(gold),
               'authorization': f'reports/P4/continuation-embedding-auth-{label}.json',
               'index': f'build/p4/continuation-dense-{label}-v1',
               'output': f'build/p4/continuation-dense-{label}-build.json'}
        auth = {key: job[key] for key in ('gold_sha256', 'corpus_sha256',
                                         'summary_sha256', 'chunks_manifest_sha256')}
        auth.update(authorized=True, gold_status='FROZEN_PRE_EMBEDDING',
                    chunks_sha256=manifest['chunks_sha256'],
                    scope='Offline exact-dense pilot only; no ANN/runtime/FULL authorization',
                    requested_bulk_device='cuda', dtype='float32',
                    cpu_qualification='separate required measurements')
        save(ROOT / job['authorization'], auth)
        save(ROOT / f'configs/p4-pilot-job-{label}.json', job)
        save(ROOT / f'reports/P4/continuation-chunks-{label}-manifest.json', manifest)
        print(json.dumps({'model': label, 'chunks': manifest['chunk_count'],
                          'job': f'configs/p4-pilot-job-{label}.json'}))


if __name__ == '__main__':
    main()
