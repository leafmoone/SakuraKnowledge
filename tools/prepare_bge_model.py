r"""Prepare the pinned BGE-M3 ONNX graph's existing normalized CLS output offline.

Requires onnx 1.20.1 for preparation only; no model/runtime downloads occur.
Example (all inputs must already be present locally)::

    python -m tools.prepare_bge_model --onnx-directory assets/bge-m3/onnx \
        --tokenizer assets/bge-m3/tokenizer.json --output model/bge-m3 \
        --ort-library linux-x86_64=bin/libonnxruntime.so.1.24.1

The new output is a shared-model directory, not an ANN/source-pack rebuild.
Place each bound runtime as a regular file with its declared basename in the
configured bin_directory. Repeat --ort-library to bind both supported platforms.
"""
import argparse
import hashlib
import json
from pathlib import Path

REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
SOURCE_MODEL = {
    'size': 724923,
    'sha256': 'f84251230831afb359ab26d9fd37d5936d4d9bb5d1d5410e66442f630f24435b',
}
SOURCE_TENSOR = {
    'size': 2266820608,
    'sha256': '1eebfb28493f67bba03ce0ef64bfdc7fc5a3bd9d7493f818bb1d78cd798416b4',
}
ROOT_TOKENIZER = {
    'size': 17098108,
    'sha256': '21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08',
}
RUNTIMES = {
    'linux-x86_64': {
        'size': 22044576,
        'sha256': 'e5a7e3646718d8f1f8f52c8fcb770fe229ab44305caf3ea702d558e6e426c9aa',
    },
    'windows-x86_64': {
        'size': 15355936,
        'sha256': '4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847',
    },
}


def _checked_source(path, expected):
    if not path.is_file() or path.stat().st_size != expected['size']:
        raise ValueError(f'wrong or missing source size: {path.name}')


def _copy_verified(source, destination, expected):
    """Copy and hash in one pass; never share mutable tensor inodes with input."""
    _checked_source(source, expected)
    sha = hashlib.sha256()
    size = 0
    with source.open('rb') as src, destination.open('xb') as dst:
        while block := src.read(8 * 1024 * 1024):
            size += len(block)
            sha.update(block)
            dst.write(block)
    if size != expected['size'] or sha.hexdigest() != expected['sha256']:
        raise ValueError(f'source binding mismatch: {source.name}; output remains incomplete')
    return {'path': destination.name, **expected}


def _runtime_bindings(libraries):
    if not libraries:
        raise ValueError('at least one explicit ORT library is required')
    bindings = {}
    for platform, path in libraries.items():
        if platform not in RUNTIMES:
            raise ValueError(f'unsupported ORT platform: {platform}')
        path = Path(path)
        if path.is_symlink() or ':' in path.name or '\\' in path.name:
            raise ValueError('ORT library must be a regular file with a portable basename')
        expected = RUNTIMES[platform]
        _checked_source(path, expected)
        with path.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        if sha != expected['sha256']:
            raise ValueError(f'ORT 1.24.1 library binding mismatch: {platform}')
        if any(b['path'] == path.name for b in bindings.values()):
            raise ValueError('platform runtimes require distinct basenames')
        bindings[platform] = {'path': path.name, **expected}
    return bindings


def prepare(onnx_directory, tokenizer, output, ort_libraries):
    import onnx
    from onnx.external_data_helper import _get_all_tensors

    source = Path(onnx_directory).resolve()
    tokenizer = Path(tokenizer).resolve()
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    resolved_output = output.resolve()
    if resolved_output.is_relative_to(source) or resolved_output.is_relative_to(tokenizer.parent):
        raise ValueError('output must be separate from the upstream input directories')
    graph_path = source / 'model.onnx'
    tensor_path = source / 'model.onnx_data'
    _checked_source(graph_path, SOURCE_MODEL)
    _checked_source(tensor_path, SOURCE_TENSOR)
    _checked_source(tokenizer, ROOT_TOKENIZER)
    graph_bytes = graph_path.read_bytes()
    if hashlib.sha256(graph_bytes).hexdigest() != SOURCE_MODEL['sha256']:
        raise ValueError('pinned upstream ONNX graph binding mismatch')
    libraries = _runtime_bindings(ort_libraries)
    model = onnx.load_model_from_string(graph_bytes)
    if [v.name for v in model.graph.input] != ['input_ids', 'attention_mask']:
        raise ValueError('unexpected upstream graph inputs')
    if [v.name for v in model.graph.output] != ['token_embeddings', 'sentence_embedding']:
        raise ValueError('unexpected upstream graph outputs')
    locations = {
        dict((entry.key, entry.value) for entry in tensor.external_data).get('location')
        for tensor in _get_all_tensors(model) if tensor.external_data
    }
    if locations != {'model.onnx_data'}:
        raise ValueError('unexpected upstream external tensor locations')
    # The pinned graph already gathers token zero then L2-normalizes it.
    # Change only the public output list and the final tensor's name.
    final = model.graph.node[-1]
    if final.op_type != 'Div' or list(final.output) != ['sentence_embedding']:
        raise ValueError('unexpected upstream normalized CLS output')
    if any('sentence_embedding' in node.input for node in model.graph.node):
        raise ValueError('sentence_embedding unexpectedly has graph consumers')
    selected = onnx.ValueInfoProto()
    selected.CopyFrom(model.graph.output[1])
    selected.name = 'embeddings'
    final.output[0] = 'embeddings'
    del model.graph.output[:]
    model.graph.output.append(selected)
    for value in model.graph.value_info:
        if value.name == 'sentence_embedding':
            value.name = 'embeddings'
    prepared_bytes = model.SerializeToString()

    output.mkdir(parents=True, exist_ok=False)
    token_binding = _copy_verified(tokenizer, output / 'tokenizer.json', ROOT_TOKENIZER)
    tensor_binding = _copy_verified(tensor_path, output / 'model.onnx_data', SOURCE_TENSOR)
    with (output / 'model.onnx').open('xb') as stream:
        stream.write(prepared_bytes)
    onnx.checker.check_model(str(output / 'model.onnx'), full_check=False)
    manifest = {
        'schema': 'sakura-shared-model-v1', 'model_id': 'bge-m3', 'version': '1',
        'revision': REVISION,
        'contract': {
            'revision': REVISION, 'dimension': 1024, 'pooling': 'cls', 'normalize': True,
            'query_prefix': '', 'dtype': 'float32', 'output': 'embeddings',
            'provider': 'CPUExecutionProvider', 'ort_version': '1.24.1',
            'intra_threads': 8, 'inter_threads': 1, 'sequential': True,
        },
        'artifacts': {
            'model': {'path': 'model.onnx', 'size': len(prepared_bytes),
                      'sha256': hashlib.sha256(prepared_bytes).hexdigest()},
            'tokenizer': token_binding, 'external_data': [tensor_binding],
        },
        'ort_libraries': libraries,
        'provenance': {
            'repository': 'BAAI/bge-m3', 'revision': REVISION,
            'source_model': {'path': 'onnx/model.onnx', **SOURCE_MODEL},
            'source_tokenizer': {'path': 'tokenizer.json', **ROOT_TOKENIZER},
            'adaptation': 'Select existing normalized CLS sentence_embedding and rename to '
                          'embeddings; no weights, operators, pooling or normalization changed.',
            'tokenizer_runtime': 'Self-contained root tokenizer.json; no added prefix, padding '
                                 'or truncation.',
            'historical_export_identity': 'Not established. This is a derived pinned official '
                                          'ONNX artifact, not the historical custom export.',
        },
    }
    if libraries.get('windows-x86_64', {}).get('path') == 'onnxruntime.dll':
        manifest['ort_dll'] = dict(RUNTIMES['windows-x86_64'])
    # An interrupted/failed preparation never leaves an activatable manifest.
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--onnx-directory', required=True)
    parser.add_argument('--tokenizer', required=True,
                        help='Pinned repository-root tokenizer.json, not onnx/tokenizer.json')
    parser.add_argument('--output', required=True, help='New shared-model directory')
    parser.add_argument('--ort-library', action='append', required=True, metavar='PLATFORM=FILE')
    args = parser.parse_args()
    libraries = {}
    for item in args.ort_library:
        platform, separator, path = item.partition('=')
        if not separator or not path or platform in libraries:
            parser.error('--ort-library requires distinct PLATFORM=FILE entries')
        libraries[platform] = path
    manifest = prepare(args.onnx_directory, args.tokenizer, args.output, libraries)
    print(json.dumps({'model_directory': str(Path(args.output)),
                      'model': manifest['artifacts']['model'],
                      'ort_libraries': manifest['ort_libraries']}, indent=2))


if __name__ == '__main__':
    main()
