"""Explicit semantic workspace and create-new, manifest-last runtime publication."""
from __future__ import annotations
import argparse
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from sakura_knowledge.storage import _publish_new_directory
from tools import semantic_chunks
from tools.normalized_source import validate, validate_source
from tools.model_artifacts import encoder_contract, verified_model
from tools.source_pack import binding


if TYPE_CHECKING:
    from tools.gemma_cuda import GemmaCudaEncoder


def _disjoint(paths):
    resolved = [Path(p).resolve() for p in paths]
    for i, left in enumerate(resolved):
        for right in resolved[i + 1:]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError('input/output/workspace path collision')


def _write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def _checkpoint(path, state):
    # A failed/interrupted state update must leave the last complete stage readable.
    fd, temporary = tempfile.mkstemp(prefix='.workspace-', suffix='.json', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _check_destination(output: Path, workspace: Path, resume_workspace: bool) -> None:
    if output.exists():
        raise FileExistsError(f'output already exists: {output}')
    if resume_workspace:
        if not workspace.is_dir():
            raise ValueError('resume workspace missing')
    elif workspace.exists():
        raise FileExistsError(f'workspace already exists: {workspace}')


def prepare(pack, model, output, index_builder, encoder=None, tokenizer=None, index_inspector=None,
            workspace=None, resume_workspace=False, keep_workspace=False, batch_size=1, *, cuda_encoder: GemmaCudaEncoder | None):
    import numpy as np
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError('batch_size must be a positive integer')
    pack, model, output = Path(pack).resolve(), Path(model).resolve(), Path(output).resolve()
    workspace = Path(workspace).resolve() if workspace else output.with_name(output.name + '.semantic-work')
    _disjoint([pack, model, output, workspace])
    _check_destination(output, workspace, resume_workspace)
    if index_inspector is None:
        index_inspector = Path(index_builder).with_name('inspect_i8' + Path(index_builder).suffix)
    validate_source(pack)
    manifest = json.loads((pack / 'manifest.json').read_bytes())
    if cuda_encoder is not None and (encoder is not None or model != cuda_encoder.prepared):
        raise ValueError('CUDA encoder must use its verified prepared model, not a test encoder')
    contract = (cuda_encoder.contract if cuda_encoder is not None else
                json.loads((model / 'manifest.json').read_bytes()) if encoder is not None else verified_model(model))
    synthetic = encoder is not None
    model_id = contract.get('model_id', 'bge-m3') if synthetic else contract.get('model_id')
    frozen = encoder_contract(model_id)
    if contract.get('revision') != frozen['revision']:
        raise ValueError('unsupported frozen model revision')
    tokenizer_path = model / contract.get('artifacts', {}).get('tokenizer', {}).get('path', 'tokenizer.json')
    params = {'version': semantic_chunks.VERSION, 'max_tokens': 384, 'overlap_tokens': 64,
              'passage_prefix': '', 'dimension': frozen['dimension'], 'metric': 'cos', 'dtype': 'i8',
              'connectivity': 16, 'expansion_add': 256, 'expansion_search': 2048,
              'chunk_depth': 512, 'entry_depth': 100}
    if model_id == 'embeddinggemma-2':
        params.update(document_template=frozen['document_template'], untitled_document=frozen['untitled_document'],
                      document_text='canonical_title_and_original', max_sequence_tokens=512)
    build = {'batch_size': batch_size}
    if cuda_encoder is not None:
        build['document_encoder'] = cuda_encoder.provenance
    inputs = {'pack_manifest': binding(pack / 'manifest.json'), 'pack_artifacts': manifest['artifacts'],
              'model_manifest': cuda_encoder.manifest_binding if cuda_encoder is not None else binding(model / 'manifest.json'),
              'tokenizer': contract['artifacts']['tokenizer'] if not synthetic else binding(tokenizer_path),
              'parameters': params, 'build': build,
              'synthetic_test_encoder': synthetic}
    if not resume_workspace:
        workspace.mkdir(parents=True, exist_ok=False)
    state_path = workspace / 'workspace.json'
    try:
        if resume_workspace:
            state = json.loads(state_path.read_bytes())
            # Ready workspaces written before stage checkpoints remain resumable.
            stage = state.get('stage', 'ready' if state.get('ready') is True else None)
            if (state['inputs'] != inputs or stage not in ('encoded', 'ready')
                    or state.get('ready') is not (stage == 'ready')):
                raise ValueError('workspace input/parameter binding mismatch or incomplete')
            names = {'vectors.npy', 'mapping.sqlite'}
            if stage == 'ready':
                names.add('vectors.i8.usearch')
            if (type(state.get('rows')) is not int or state['rows'] < 1
                    or set(state['artifacts']) != names):
                raise ValueError('workspace incomplete artifact state')
            for name, item in state['artifacts'].items():
                if (Path(item['path']).name != item['path']
                        or (name != 'vectors.i8.usearch' and item['path'] != name)
                        or binding(workspace / item['path']) != item):
                    raise ValueError('workspace artifact binding mismatch')
            vectors = np.load(workspace / 'vectors.npy', mmap_mode='r', allow_pickle=False)
            try:
                _vectors(vectors, state['rows'], params['dimension'])
            finally:
                # Release the Windows NPY mapping before publication or workspace cleanup.
                del vectors
        else:
            _checkpoint(state_path, {'inputs': inputs, 'stage': 'encoding', 'ready': False})
            if tokenizer is None:
                from tokenizers import Tokenizer
                tokenizer = Tokenizer.from_file(str(tokenizer_path))
            rows = _encode_corpus(pack, model, workspace, manifest, contract, inputs,
                                  tokenizer, encoder, batch_size, cuda_encoder)
            # _encode_corpus owns the ORT session and releases it before ANN construction.
            state = {'inputs': inputs, 'stage': 'encoded', 'ready': False, 'rows': rows,
                     'artifacts': {name: binding(workspace / name) for name in ['vectors.npy', 'mapping.sqlite']}}
            _checkpoint(state_path, state)
        if not state['ready']:
            # Each attempt gets a new path: a failed builder can leave a partial index.
            # Ignore unrecorded attempts instead of overwriting or deleting their bytes.
            with tempfile.NamedTemporaryFile(prefix='vectors-', suffix='.i8.usearch', dir=workspace) as reserved:
                index_path = Path(reserved.name)
            result = subprocess.run([str(index_builder), str(workspace / 'vectors.npy'), str(index_path)], capture_output=True, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors='replace'))
            state = {**state, 'stage': 'ready', 'ready': True, 'native_build': json.loads(result.stdout),
                     'artifacts': {**state['artifacts'], 'vectors.i8.usearch': binding(index_path)}}
            _checkpoint(state_path, state)
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=output.name + '.publish-', dir=output.parent))
        try:
            for role in ['snapshot', 'lexical_membership']:
                shutil.copy2(pack / manifest['artifacts'][role]['path'], staging / manifest['artifacts'][role]['path'])
            for name in ['mapping.sqlite', 'vectors.i8.usearch']:
                shutil.copy2(workspace / state['artifacts'][name]['path'], staging / name)
            manifest['distribution_closed_set'] = True
            manifest['text_projection'] = {**params, 'tokenizer_sha256': inputs['tokenizer']['sha256'], 'model_revision': contract['revision'], 'synthetic_test_encoder': synthetic}
            manifest['semantic_build'] = build
            manifest['capabilities'] = ['structured', 'lexical', 'semantic']
            manifest['requires_model'] = model_id
            manifest['semantic'] = {k: v for k, v in params.items() if k in ['dimension', 'metric', 'dtype', 'connectivity', 'expansion_add', 'expansion_search', 'chunk_depth', 'entry_depth']}
            manifest['semantic']['rows'] = state['rows']
            for role, filename in [('mapping', 'mapping.sqlite'), ('index', 'vectors.i8.usearch')]:
                manifest['artifacts'][role] = {**state['artifacts'][filename], 'path': filename}
            manifest['artifacts']['snapshot']['identity'] = 'knowledge.sqlite'
            _write(staging / 'manifest.json', manifest)
            # Verify the final bytes and complete proof/key closure once, before publication.
            validation = validate(staging, index_inspector)
            _publish_new_directory(staging, output)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        workspace_bytes = sum(p.stat().st_size for p in workspace.rglob('*') if p.is_file())
        if not keep_workspace:
            shutil.rmtree(workspace)
        return {'rows': state['rows'], 'native_build': state['native_build'], 'validation': validation,
                'manifest': str(output / 'manifest.json'), 'workspace': str(workspace),
                'workspace_kept': keep_workspace, 'workspace_bytes': workspace_bytes,
                'document_encoding': cuda_encoder.statistics() if cuda_encoder is not None and not resume_workspace else None}
    except Exception as exc:
        raise RuntimeError(f'semantic preparation failed; workspace preserved at {workspace}: {exc}') from exc


def _document_chunks(pack, manifest, tokenizer, tokenizer_sha256, parameters):
    # Projection still owns one document at a time, never the complete corpus.
    with closing(sqlite3.connect((pack / 'knowledge.sqlite').as_uri() + '?mode=ro', uri=True)) as conn:
        for row in conn.execute("SELECT d.id,d.entry_id,d.title,d.original,e.kind,e.namespace,e.value,d.source_id,d.evidence_id FROM documents d JOIN entries e ON e.id=d.entry_id WHERE e.conflicted=0 AND e.kind!='episode' AND d.status IN ('source_backed','generated_from_evidence') AND EXISTS(SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed') ORDER BY d.id"):
            doc = {'document_id': row[0], 'entry_id': row[1], 'title': row[2], 'original': row[3], 'entry_key': dict(zip(['kind', 'namespace', 'value'], row[4:7])), 'source_id': row[7], 'evidence_id': row[8]}
            prefix = ''
            if 'document_template' in parameters:
                title = (doc['title'] or '').replace('\r\n', '\n').replace('\r', '\n')
                prefix = parameters['document_template'].format(title=title or parameters['untitled_document'], text='')
            try:
                chunks = semantic_chunks.project_document(
                    doc, tokenizer, base_snapshot_sha256=manifest['artifacts']['snapshot']['sha256'],
                    tokenizer_inventory_sha256=tokenizer_sha256, passage_prefix=prefix,
                    max_sequence_tokens=parameters.get('max_sequence_tokens', 512))
            except semantic_chunks.ChunkError as exc:
                raise semantic_chunks.ChunkError(f"document {doc['document_id']}: {exc}") from exc
            for chunk in chunks:
                # Keep canonical source spans/IDs; only the encoder receives the task prompt.
                yield {**chunk, 'encoding_text': prefix + chunk['text']}


def _batch_inputs(texts, tokenizer, pad_id, max_tokens):
    import numpy as np
    encoded = [tokenizer.encode(text) for text in texts]
    if any(not item.ids or len(item.ids) > max_tokens for item in encoded):
        raise ValueError('chunk exceeds frozen model context or is empty')
    ids = np.full((len(encoded), max(len(item.ids) for item in encoded)), pad_id, dtype=np.int64)
    attention = np.zeros_like(ids)
    for i, item in enumerate(encoded):
        ids[i, :len(item.ids)] = item.ids
        attention[i, :len(item.ids)] = item.attention_mask
    return {'input_ids': ids, 'attention_mask': attention}


def _encode_corpus(pack, model, workspace, manifest, contract, inputs, tokenizer, encoder, batch_size, cuda_encoder):
    import numpy as np
    session = None
    if encoder is None:
        pad_id = tokenizer.token_to_id('<pad>')
        expected_pad = 0 if contract['model_id'] == 'embeddinggemma-2' else 1
        if pad_id != expected_pad:
            raise ValueError('frozen tokenizer padding token mismatch')
        if cuda_encoder is not None:
            cuda_encoder.begin_source()
            encode_inputs = cuda_encoder.encode
        else:
            import onnxruntime as ort
            if ort.__version__ != contract['contract']['ort_version']:
                raise ValueError('frozen ORT version mismatch')
            options = ort.SessionOptions()
            options.intra_op_num_threads = 8
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            session = ort.InferenceSession(str(model / contract['artifacts']['model']['path']),
                                           sess_options=options, providers=['CPUExecutionProvider'])
            encode_inputs = lambda batch: session.run(['embeddings'], batch)[0]
        encoder = lambda texts: encode_inputs(_batch_inputs(
            texts, tokenizer, pad_id, inputs['parameters'].get('max_sequence_tokens', 512)))
    dimension = inputs['parameters']['dimension']
    rows = 0
    try:
        with closing(sqlite3.connect(workspace / 'mapping.sqlite')) as conn, (workspace / 'vectors.npy').open('xb') as stream:
            # NumPy reserves growth-axis digits in its standard header. Finalize it
            # in place after streaming, producing the same bytes as np.save.
            header = _npy_header(0, dimension)
            stream.write(header)
            conn.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY,original_position INTEGER NOT NULL UNIQUE,chunk_id TEXT NOT NULL UNIQUE,document_id INTEGER NOT NULL,kind TEXT NOT NULL,namespace TEXT NOT NULL,value TEXT NOT NULL,source_id TEXT NOT NULL,evidence_id TEXT NOT NULL)')
            batch = []
            def flush():
                nonlocal rows
                vectors = encoder([chunk['encoding_text'] for chunk in batch])
                _vectors(vectors, len(batch), dimension)
                np.asarray(vectors, order='C').tofile(stream)
                for chunk in batch:
                    key = chunk['entry_key']
                    conn.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?)',
                                 (rows, rows, chunk['chunk_id'], chunk['document_id'],
                                  key['kind'], key['namespace'], key['value'], chunk['source_id'], chunk['evidence_id']))
                    rows += 1
                batch.clear()
            for chunk in _document_chunks(pack, manifest, tokenizer, inputs['tokenizer']['sha256'], inputs['parameters']):
                batch.append(chunk)
                if len(batch) == batch_size:
                    flush()
            if batch:
                flush()
            if not rows:
                raise ValueError('empty trusted semantic corpus')
            final_header = _npy_header(rows, dimension)
            if len(final_header) != len(header):
                raise ValueError('NPY header growth exceeds reserved space')
            stream.seek(0)
            stream.write(final_header)
            conn.commit()
    finally:
        # Release this source's ORT session; the explicit CUDA owner spans serial sources.
        encoder = None
        session = None
    if cuda_encoder is not None:
        cuda_encoder.end_source()
    return rows


def _npy_header(rows, dimension):
    import numpy as np
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, {
        'descr': np.lib.format.dtype_to_descr(np.dtype(np.float32)),
        'fortran_order': False, 'shape': (rows, dimension)})
    return stream.getvalue()


def _vectors(vectors, rows, dimension):
    import numpy as np
    if vectors.shape != (rows, dimension) or vectors.dtype != np.float32:
        raise ValueError('invalid frozen encoder vectors')
    # Keep resume validation bounded even when vectors is a very large NPY mmap.
    for start in range(0, rows, 256):
        block = vectors[start:start + 256]
        if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block, axis=1), 1, atol=1e-4):
            raise ValueError('invalid frozen encoder vectors')


def main():
    p = argparse.ArgumentParser()
    for name in ['pack', 'output']:
        p.add_argument('--' + name, required=True, action='append')
    for name in ['model', 'index-builder']:
        p.add_argument('--' + name, required=True)
    p.add_argument('--index-inspector')
    p.add_argument('--workspace', action='append')
    p.add_argument('--resume-workspace', action='store_true')
    p.add_argument('--keep-workspace', action='store_true')
    p.add_argument('--batch-size', type=int, help='maximum encoder batch size; CPU defaults to 1')
    p.add_argument('--cuda-model', type=Path, help='fixed local Google checkpoint; enables CUDA document encoding')
    p.add_argument('--device', help='explicit CUDA device, for example cuda:0')
    a = p.parse_args()
    if len(a.pack) != len(a.output) or (a.workspace and len(a.workspace) != len(a.pack)):
        p.error('supply equal counts of --pack, --output and optional --workspace')
    if a.cuda_model is not None and (not a.device or a.batch_size is None):
        p.error('--cuda-model requires explicit --device and --batch-size')
    if a.device and a.cuda_model is None:
        p.error('--device requires --cuda-model')
    workspaces = a.workspace or [str(Path(output).with_name(Path(output).name + '.semantic-work')) for output in a.output]
    _disjoint([*a.pack, *a.output, *workspaces, a.model, *([a.cuda_model] if a.cuda_model is not None else [])])
    if a.batch_size is not None and a.batch_size < 1:
        p.error('--batch-size must be positive')
    for output, workspace in zip(a.output, workspaces):
        _check_destination(Path(output).resolve(), Path(workspace).resolve(), a.resume_workspace)
    cuda_encoder = None
    tokenizer = None
    if a.cuda_model is not None:
        from tools.gemma_cuda import GemmaCudaEncoder
        cuda_encoder = GemmaCudaEncoder(Path(a.model), a.cuda_model, a.device)
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(Path(a.model) / cuda_encoder.contract['artifacts']['tokenizer']['path']))
    try:
        for pack, output, workspace in zip(a.pack, a.output, workspaces):
            print(json.dumps(prepare(
                pack, a.model, output, a.index_builder, index_inspector=a.index_inspector,
                workspace=workspace, resume_workspace=a.resume_workspace,
                keep_workspace=a.keep_workspace, batch_size=a.batch_size if a.batch_size is not None else 1,
                tokenizer=tokenizer, cuda_encoder=cuda_encoder)), flush=True)
    finally:
        if cuda_encoder is not None:
            cuda_encoder.close()


if __name__ == '__main__':
    main()
