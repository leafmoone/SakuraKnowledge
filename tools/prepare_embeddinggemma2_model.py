"""Prepare the pinned community EmbeddingGemma 2 FP32 graph for text-only use.

Requires onnx 1.20.1 only during preparation; no downloads or index changes occur.
Supply existing pinned ONNX/tokenizer files and explicit ORT 1.24.1 libraries.
The resulting model is separate from BGE and does not activate semantic packs.
"""
import argparse
import hashlib
import json
from pathlib import Path

from tools.model_artifacts import (
    ArtifactSpec, checked_source, copy_verified, encoder_contract, runtime_bindings,
)

REPOSITORY = 'onnx-community/embeddinggemma-2-ONNX'
REVISION = 'daa72c51243991dfcaf9f9137d2c573d8f7790c0'
REFERENCE_REVISION = '914f7f89142e33e77833254d9c9b90c3cef7303b'
SOURCE_MODEL: ArtifactSpec = {
    'size': 421421,
    'sha256': 'bc47de15f81208a5c99e5ab10f746d5e33b51ea228b7dc0bef9c133a94f1c1c3',
}
SOURCE_TENSOR: ArtifactSpec = {
    'size': 1084170240,
    'sha256': '9fd452bfc6916e5a92f080f8dada35598ca4512b21c65897d4c5974d5f9630a2',
}
TOKENIZER: ArtifactSpec = {
    'size': 32170510,
    'sha256': '4d777ef5bdc1aa36227abdfb77c3e49e7b9c892d16e1b6bda41c393504828be4',
}


def text_graph(graph_bytes: bytes) -> bytes:
    import onnx
    from onnx.external_data_helper import _get_all_tensors

    model = onnx.load_model_from_string(graph_bytes)
    if [v.name for v in model.graph.input] != [
        'input_ids', 'attention_mask', 'image_features', 'video_features', 'audio_features',
    ] or [v.name for v in model.graph.output] != ['last_hidden_state', 'sentence_embedding']:
        raise ValueError('unexpected pinned EmbeddingGemma 2 graph interface')
    locations = {
        dict((entry.key, entry.value) for entry in tensor.external_data).get('location')
        for tensor in _get_all_tensors(model) if tensor.external_data
    }
    if locations != {'model.onnx_data'}:
        raise ValueError('unexpected upstream external tensor locations')

    # Google forward replaces multimodal placeholders with PAD before text lookup.
    # With no media, bypass only the feature-merging branch, not the text encoder.
    nodes = [node for node in model.graph.node
             if not node.name.startswith('/model/multimodal_merge/')]
    lookup = next(node for node in nodes if node.name == '/model/embed_tokens/Gather')
    lookup.input[1] = 'sakura_text_ids'
    masks = [onnx.helper.make_node('Equal', ['input_ids', f'/model/constants/INT64/{token}'],
                                  [f'sakura_{kind}_mask'])
             for kind, token in [('image', 258880), ('video', 258884), ('audio', 258881)]]
    masks += [
        onnx.helper.make_node('Or', ['sakura_image_mask', 'sakura_video_mask'], ['sakura_visual_mask']),
        onnx.helper.make_node('Or', ['sakura_visual_mask', 'sakura_audio_mask'], ['sakura_media_mask']),
        onnx.helper.make_node('Where', ['sakura_media_mask', '/model/constants/INT64/0', 'input_ids'],
                              ['sakura_text_ids']),
    ]
    nodes[nodes.index(lookup):nodes.index(lookup)] = masks
    merged = '/model/multimodal_merge/Reshape_embeds/output_0'
    for node in nodes:
        for index, name in enumerate(node.input):
            if name == merged:
                node.input[index] = lookup.output[0]
            elif name.startswith('/model/multimodal_merge/'):
                raise ValueError('unexpected remaining multimodal branch consumer')
    del model.graph.node[:]
    model.graph.node.extend(nodes)
    del model.graph.input[2:]
    used = {name for node in nodes for name in node.input}
    retained = [value for value in model.graph.initializer if value.name in used]
    del model.graph.initializer[:]
    model.graph.initializer.extend(retained)

    # The existing output already includes mask-aware mean pooling and L2 norm.
    final = model.graph.node[-1]
    if final.op_type != 'Div' or list(final.output) != ['sentence_embedding']:
        raise ValueError('unexpected upstream normalized mean output')
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
    return model.SerializeToString()


def prepare(onnx_directory: Path, tokenizer: Path, output: Path,
            ort_libraries: dict[str, Path]) -> dict[str, object]:
    source, tokenizer = onnx_directory.resolve(), tokenizer.resolve()
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if output.resolve().is_relative_to(source) or output.resolve().is_relative_to(tokenizer.parent):
        raise ValueError('output must be separate from the upstream input directories')
    graph_path, tensor_path = source / 'model.onnx', source / 'model.onnx_data'
    for path, expected in [(graph_path, SOURCE_MODEL), (tensor_path, SOURCE_TENSOR), (tokenizer, TOKENIZER)]:
        checked_source(path, expected)
    graph_bytes = graph_path.read_bytes()
    if hashlib.sha256(graph_bytes).hexdigest() != SOURCE_MODEL['sha256']:
        raise ValueError('pinned community ONNX graph binding mismatch')
    libraries = runtime_bindings(ort_libraries)
    prepared_bytes = text_graph(graph_bytes)

    output.mkdir(parents=True, exist_ok=False)
    token_binding = copy_verified(tokenizer, output / 'tokenizer.json', TOKENIZER)
    tensor_binding = copy_verified(tensor_path, output / 'model.onnx_data', SOURCE_TENSOR)
    with (output / 'model.onnx').open('xb') as stream:
        stream.write(prepared_bytes)
    # This pinned graph uses ORT's default-domain SimplifiedLayerNormalization,
    # absent from the ONNX 1.20.1 checker schema; validate execution with ORT 1.24.1.
    notices = Path(__file__).resolve().parents[1] / 'docs/licenses'
    for source_name, target_name in [('EmbeddingGemma2-LICENSE', 'LICENSE'),
                                     ('EmbeddingGemma2-NOTICE', 'NOTICE')]:
        with (output / target_name).open('xb') as stream:
            stream.write((notices / source_name).read_bytes())
    manifest: dict[str, object] = {
        'schema': 'sakura-shared-model-v1', 'model_id': 'embeddinggemma-2', 'version': '1',
        'revision': REVISION,
        'contract': encoder_contract('embeddinggemma-2'),
        'artifacts': {
            'model': {'path': 'model.onnx', 'size': len(prepared_bytes),
                      'sha256': hashlib.sha256(prepared_bytes).hexdigest()},
            'tokenizer': token_binding, 'external_data': [tensor_binding],
        },
        'ort_libraries': libraries,
        'provenance': {
            'repository': REPOSITORY, 'revision': REVISION, 'license': 'Apache-2.0',
            'license_files': ['LICENSE', 'NOTICE'],
            'reference_repository': 'google/embeddinggemma-2',
            'reference_revision': REFERENCE_REVISION,
            'source_model': {'path': 'onnx/model.onnx', **SOURCE_MODEL},
            'source_external_data': {'path': 'onnx/model.onnx_data', **SOURCE_TENSOR},
            'source_tokenizer': {'path': 'tokenizer.json', **TOKENIZER},
            'checkpoint_relation': 'All 413 reference text tensors correspond exactly after '
                'the export graph\'s transposes, concatenations, sqrt(512) embedding scaling '
                'and last-layer scalar folding into RMS epsilon. The exporter does not declare '
                'a base commit; this is checked text-weight correspondence, not an upstream '
                'revision declaration or verification of image/audio towers.',
            'adaptation': 'Map media placeholder IDs to PAD as in Google text-only forward; '
                'remove the media-feature merge branch; select existing mask-aware mean/L2 '
                'sentence_embedding as embeddings. Preserve all external tensor bytes.',
            'precision': 'Pinned FP32 export only; float16 is not supported.',
        },
    }
    # Publish the manifest last, so failed preparation cannot activate a partial model.
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--onnx-directory', required=True, type=Path)
    parser.add_argument('--tokenizer', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--ort-library', action='append', required=True, metavar='PLATFORM=FILE')
    args = parser.parse_args()
    libraries: dict[str, Path] = {}
    for item in args.ort_library:
        platform, separator, path = item.partition('=')
        if not separator or not path or platform in libraries:
            parser.error('--ort-library requires distinct PLATFORM=FILE entries')
        libraries[platform] = Path(path)
    manifest = prepare(args.onnx_directory, args.tokenizer, args.output, libraries)
    print(json.dumps({'model_directory': str(args.output), 'artifacts': manifest['artifacts']}, indent=2))


if __name__ == '__main__':
    main()
