"""Explicit create-new semantic preparation, reusing frozen chunk and native I8 builders."""
import argparse
import json
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

from tools import p4_chunks
from tools.normalized_source import validate
from tools.source_pack import binding


def prepare(pack, model, output, index_builder, encoder=None, tokenizer=None, index_inspector=None):
    import numpy as np
    pack, model, output = Path(pack), Path(model), Path(output)
    validate(pack)
    manifest = json.loads((pack / 'manifest.json').read_bytes())
    contract = json.loads((model / 'manifest.json').read_bytes())
    if contract.get('revision') != '5617a9f61b028005a4858fdac845db406aefb181':
        raise ValueError('unsupported frozen model revision')
    if encoder is None:
        if contract.get('schema') != 'sakura-shared-model-v1' or contract.get('model_id') != 'bge-m3':
            raise ValueError('unsupported_model_contract')
        for field, expected in {'dimension': 1024, 'pooling': 'cls', 'normalize': True, 'query_prefix': '', 'dtype': 'float32', 'output': 'embeddings'}.items():
            if contract['contract'].get(field) != expected:
                raise ValueError('frozen encoder contract mismatch')
        for item in [contract['artifacts']['model'], contract['artifacts']['tokenizer'], *contract['artifacts']['external_data']]:
            if Path(item['path']).name != item['path'] or binding(model / item['path']) != {k: item[k] for k in ('path', 'sha256', 'size')}:
                raise ValueError('frozen model artifact binding mismatch')
    tokenizer_path = model / contract.get('artifacts', {}).get('tokenizer', {}).get('path', 'tokenizer.json')
    if tokenizer is None:
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
    if encoder is None:
        import onnxruntime as ort
        session = ort.InferenceSession(str(model / contract['artifacts']['model']['path']), providers=['CPUExecutionProvider'])
        def encoder(texts):
            outputs = []
            for text in texts:
                encoded = tokenizer.encode(text)
                if len(encoded.ids) > 512:
                    raise ValueError('chunk exceeds frozen model context')
                ids = np.asarray([encoded.ids], dtype=np.int64)
                outputs.append(session.run(['embeddings'], {'input_ids': ids, 'attention_mask': np.ones_like(ids)})[0][0])
            return np.asarray(outputs, dtype=np.float32)
    output.mkdir(parents=True, exist_ok=False)
    for role in ['snapshot', 'lexical_membership']:
        shutil.copy2(pack / manifest['artifacts'][role]['path'], output / manifest['artifacts'][role]['path'])
    chunks = []
    snapshot = binding(output / 'knowledge.sqlite')
    with closing(sqlite3.connect((pack / 'knowledge.sqlite').resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        for row in conn.execute("SELECT d.id,d.entry_id,d.title,d.original,e.kind,e.namespace,e.value,d.source_id,d.evidence_id FROM documents d JOIN entries e ON e.id=d.entry_id WHERE e.conflicted=0 AND e.kind!='episode' AND d.status IN ('source_backed','generated_from_evidence') AND EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed') ORDER BY d.id"):
            doc = {'document_id': row[0], 'entry_id': row[1], 'title': row[2], 'original': row[3], 'entry_key': dict(zip(['kind', 'namespace', 'value'], row[4:7])), 'source_id': row[7], 'evidence_id': row[8]}
            chunks.extend(p4_chunks.project_document(doc, tokenizer, base_snapshot_sha256=snapshot['sha256'], tokenizer_inventory_sha256=binding(tokenizer_path)['sha256'], passage_prefix='', max_sequence_tokens=512))
    if not chunks:
        raise ValueError('empty trusted semantic corpus')
    with closing(sqlite3.connect(output / 'mapping.sqlite')) as conn:
        conn.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY,original_position INTEGER NOT NULL UNIQUE,chunk_id TEXT NOT NULL UNIQUE,document_id INTEGER NOT NULL,kind TEXT NOT NULL,namespace TEXT NOT NULL,value TEXT NOT NULL,source_id TEXT NOT NULL,evidence_id TEXT NOT NULL)')
        for i, chunk in enumerate(chunks):
            k = chunk['entry_key']
            conn.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?)', (i, i, chunk['chunk_id'], chunk['document_id'], k['kind'], k['namespace'], k['value'], chunk['source_id'], chunk['evidence_id']))
        conn.commit()
    vectors = encoder([c['text'] for c in chunks])
    if vectors.shape != (len(chunks), 1024) or vectors.dtype != np.float32 or not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError('invalid frozen encoder vectors')
    np.save(output / 'vectors.npy', vectors)
    result = subprocess.run([str(index_builder), str(output / 'vectors.npy'), str(output / 'vectors.i8.usearch')], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    manifest['text_projection'] = {'version': p4_chunks.VERSION, 'max_tokens': 384, 'overlap_tokens': 64, 'passage_prefix': '', 'tokenizer_sha256': binding(tokenizer_path)['sha256'], 'model_revision': contract['revision'], 'synthetic_test_encoder': contract.get('schema') != 'sakura-shared-model-v1'}
    manifest['capabilities'] = ['structured', 'lexical', 'semantic']
    manifest['requires_model'] = 'bge-m3'
    manifest['semantic'] = {'rows': len(chunks), 'dimension': 1024, 'metric': 'cos', 'dtype': 'i8', 'connectivity': 16, 'expansion_add': 256, 'expansion_search': 2048, 'chunk_depth': 512, 'entry_depth': 100}
    for role, filename in [('snapshot', 'knowledge.sqlite'), ('mapping', 'mapping.sqlite'), ('index', 'vectors.i8.usearch')]:
        manifest['artifacts'][role] = binding(output / filename)
    manifest['artifacts']['snapshot']['identity'] = 'knowledge.sqlite'
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if index_inspector is None:
        index_inspector = Path(index_builder).with_name('inspect_i8' + Path(index_builder).suffix)
    validation = validate(output, index_inspector)
    return {'rows': len(chunks), 'native_build': json.loads(result.stdout), 'validation': validation, 'manifest': str(output / 'manifest.json')}


def main():
    p = argparse.ArgumentParser()
    for name in ['pack', 'model', 'output', 'index-builder']:
        p.add_argument('--' + name, required=True)
    p.add_argument('--index-inspector')
    a = p.parse_args()
    print(json.dumps(prepare(a.pack, a.model, a.output, a.index_builder, index_inspector=a.index_inspector)))


if __name__ == '__main__':
    main()
