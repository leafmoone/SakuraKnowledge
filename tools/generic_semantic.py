"""Explicit semantic workspace and create-new, manifest-last runtime publication."""
import argparse
import json
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

from tools import p4_chunks
from tools.normalized_source import validate
from tools.source_pack import binding


def _disjoint(paths):
    resolved = [Path(p).resolve() for p in paths]
    for i, left in enumerate(resolved):
        for right in resolved[i + 1:]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError('input/output/workspace path collision')


def _write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def prepare(pack, model, output, index_builder, encoder=None, tokenizer=None, index_inspector=None,
            workspace=None, resume_workspace=False, keep_workspace=False):
    import numpy as np
    pack, model, output = Path(pack).resolve(), Path(model).resolve(), Path(output).resolve()
    workspace = Path(workspace).resolve() if workspace else output.with_name(output.name + '.semantic-work')
    _disjoint([pack, model, output, workspace])
    if output.exists():
        raise FileExistsError(f'output already exists: {output}')
    if resume_workspace:
        if not workspace.is_dir():
            raise ValueError('resume workspace missing')
    elif workspace.exists():
        raise FileExistsError(f'workspace already exists: {workspace}')
    validate(pack)
    manifest = json.loads((pack / 'manifest.json').read_bytes())
    contract = json.loads((model / 'manifest.json').read_bytes())
    if contract.get('revision') != '5617a9f61b028005a4858fdac845db406aefb181':
        raise ValueError('unsupported frozen model revision')
    synthetic = encoder is not None
    if not synthetic:
        if contract.get('schema') != 'sakura-shared-model-v1' or contract.get('model_id') != 'bge-m3':
            raise ValueError('unsupported_model_contract')
        for field, expected in {'dimension': 1024, 'pooling': 'cls', 'normalize': True, 'query_prefix': '', 'dtype': 'float32', 'output': 'embeddings'}.items():
            if contract['contract'].get(field) != expected:
                raise ValueError('frozen encoder contract mismatch')
        for item in [contract['artifacts']['model'], contract['artifacts']['tokenizer'], *contract['artifacts']['external_data']]:
            if Path(item['path']).name != item['path'] or binding(model / item['path']) != {k: item[k] for k in ('path', 'sha256', 'size')}:
                raise ValueError('frozen model artifact binding mismatch')
    tokenizer_path = model / contract.get('artifacts', {}).get('tokenizer', {}).get('path', 'tokenizer.json')
    if index_inspector is None:
        index_inspector = Path(index_builder).with_name('inspect_i8' + Path(index_builder).suffix)
    params = {'version': p4_chunks.VERSION, 'max_tokens': 384, 'overlap_tokens': 64,
              'passage_prefix': '', 'dimension': 1024, 'metric': 'cos', 'dtype': 'i8',
              'connectivity': 16, 'expansion_add': 256, 'expansion_search': 2048,
              'chunk_depth': 512, 'entry_depth': 100}
    inputs = {'pack_manifest': binding(pack / 'manifest.json'), 'pack_artifacts': manifest['artifacts'],
              'model_manifest': binding(model / 'manifest.json'), 'tokenizer': binding(tokenizer_path),
              'parameters': params, 'synthetic_test_encoder': synthetic}
    if not resume_workspace:
        workspace.mkdir(parents=True, exist_ok=False)
    state_path = workspace / 'workspace.json'
    try:
        if resume_workspace:
            state = json.loads(state_path.read_bytes())
            if state['inputs'] != inputs or not state.get('ready'):
                raise ValueError('workspace input/parameter binding mismatch or incomplete')
            for item in state['artifacts'].values():
                if Path(item['path']).name != item['path'] or binding(workspace / item['path']) != item:
                    raise ValueError('workspace artifact binding mismatch')
            vectors = np.load(workspace / 'vectors.npy', mmap_mode='r', allow_pickle=False)
            _vectors(vectors, state['rows'])
        else:
            _write(state_path, {'inputs': inputs, 'ready': False})
            if tokenizer is None:
                from tokenizers import Tokenizer
                tokenizer = Tokenizer.from_file(str(tokenizer_path))
            chunks = []
            with closing(sqlite3.connect((pack / 'knowledge.sqlite').as_uri() + '?mode=ro', uri=True)) as conn:
                for row in conn.execute("SELECT d.id,d.entry_id,d.title,d.original,e.kind,e.namespace,e.value,d.source_id,d.evidence_id FROM documents d JOIN entries e ON e.id=d.entry_id WHERE e.conflicted=0 AND e.kind!='episode' AND d.status IN ('source_backed','generated_from_evidence') AND EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed') ORDER BY d.id"):
                    doc = {'document_id': row[0], 'entry_id': row[1], 'title': row[2], 'original': row[3], 'entry_key': dict(zip(['kind', 'namespace', 'value'], row[4:7])), 'source_id': row[7], 'evidence_id': row[8]}
                    chunks.extend(p4_chunks.project_document(doc, tokenizer, base_snapshot_sha256=manifest['artifacts']['snapshot']['sha256'], tokenizer_inventory_sha256=inputs['tokenizer']['sha256'], passage_prefix='', max_sequence_tokens=512))
            if not chunks:
                raise ValueError('empty trusted semantic corpus')
            with closing(sqlite3.connect(workspace / 'mapping.sqlite')) as conn:
                conn.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY,original_position INTEGER NOT NULL UNIQUE,chunk_id TEXT NOT NULL UNIQUE,document_id INTEGER NOT NULL,kind TEXT NOT NULL,namespace TEXT NOT NULL,value TEXT NOT NULL,source_id TEXT NOT NULL,evidence_id TEXT NOT NULL)')
                for i, chunk in enumerate(chunks):
                    k = chunk['entry_key']
                    conn.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?)', (i, i, chunk['chunk_id'], chunk['document_id'], k['kind'], k['namespace'], k['value'], chunk['source_id'], chunk['evidence_id']))
                conn.commit()
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
            vectors = encoder([c['text'] for c in chunks])
            _vectors(vectors, len(chunks))
            np.save(workspace / 'vectors.npy', vectors)
            result = subprocess.run([str(index_builder), str(workspace / 'vectors.npy'), str(workspace / 'vectors.i8.usearch')], capture_output=True, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors='replace'))
            state = {'inputs': inputs, 'ready': True, 'rows': len(chunks), 'native_build': json.loads(result.stdout),
                     'artifacts': {name: binding(workspace / name) for name in ['vectors.npy', 'mapping.sqlite', 'vectors.i8.usearch']}}
            _write(state_path, state)
        result = subprocess.run([str(index_inspector), str(workspace / 'vectors.i8.usearch'), str(state['rows'])], capture_output=True, check=False)
        if result.returncode or json.loads(result.stdout).get('validation') != 'PASS':
            raise ValueError('workspace native index validation')
        staging = workspace / 'runtime-staging'
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        for role in ['snapshot', 'lexical_membership']:
            shutil.copy2(pack / manifest['artifacts'][role]['path'], staging / manifest['artifacts'][role]['path'])
        for name in ['mapping.sqlite', 'vectors.i8.usearch']:
            shutil.copy2(workspace / name, staging / name)
        manifest['distribution_closed_set'] = True
        manifest['text_projection'] = {**params, 'tokenizer_sha256': inputs['tokenizer']['sha256'], 'model_revision': contract['revision'], 'synthetic_test_encoder': synthetic}
        manifest['capabilities'] = ['structured', 'lexical', 'semantic']
        manifest['requires_model'] = 'bge-m3'
        manifest['semantic'] = {k: v for k, v in params.items() if k in ['dimension', 'metric', 'dtype', 'connectivity', 'expansion_add', 'expansion_search', 'chunk_depth', 'entry_depth']}
        manifest['semantic']['rows'] = state['rows']
        for role, filename in [('snapshot', 'knowledge.sqlite'), ('mapping', 'mapping.sqlite'), ('index', 'vectors.i8.usearch')]:
            manifest['artifacts'][role] = binding(staging / filename)
        manifest['artifacts']['snapshot']['identity'] = 'knowledge.sqlite'
        _write(staging / 'manifest.json', manifest)
        validate(staging, index_inspector)
        _publish(staging, output)
        validation = validate(output, index_inspector)
        workspace_bytes = sum(p.stat().st_size for p in workspace.rglob('*') if p.is_file())
        # Release the Windows read-only NPY mapping before optional workspace cleanup.
        del vectors
        if not keep_workspace:
            shutil.rmtree(workspace)
        return {'rows': state['rows'], 'native_build': state['native_build'], 'validation': validation,
                'manifest': str(output / 'manifest.json'), 'workspace': str(workspace),
                'workspace_kept': keep_workspace, 'workspace_bytes': workspace_bytes}
    except Exception as exc:
        raise RuntimeError(f'semantic preparation failed; workspace preserved at {workspace}: {exc}') from exc


def _vectors(vectors, rows):
    import numpy as np
    if vectors.shape != (rows, 1024) or vectors.dtype != np.float32 or not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError('invalid frozen encoder vectors')


def _publish(staging, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=output.name + '.publish-', dir=output.parent))
    try:
        for path in staging.iterdir():
            if path.name != 'manifest.json':
                shutil.copy2(path, pending / path.name)
        shutil.copy2(staging / 'manifest.json', pending / 'manifest.json')
        # Same-volume directory rename: no discoverable final manifest until complete.
        if output.exists():
            raise FileExistsError(f'output already exists: {output}')
        pending.rename(output)
    finally:
        if pending.exists():
            shutil.rmtree(pending)


def main():
    p = argparse.ArgumentParser()
    for name in ['pack', 'model', 'output', 'index-builder']:
        p.add_argument('--' + name, required=True)
    p.add_argument('--index-inspector')
    p.add_argument('--workspace')
    p.add_argument('--resume-workspace', action='store_true')
    p.add_argument('--keep-workspace', action='store_true')
    a = p.parse_args()
    print(json.dumps(prepare(a.pack, a.model, a.output, a.index_builder, index_inspector=a.index_inspector,
                             workspace=a.workspace, resume_workspace=a.resume_workspace, keep_workspace=a.keep_workspace)))


if __name__ == '__main__':
    main()
