"""Shared offline artifact copying and pinned ORT bindings for model preparation."""
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict


class ArtifactSpec(TypedDict):
    size: int
    sha256: str


class ArtifactBinding(ArtifactSpec):
    path: str


RUNTIMES: dict[str, ArtifactSpec] = {
    'linux-x86_64': {
        'size': 22044576,
        'sha256': 'e5a7e3646718d8f1f8f52c8fcb770fe229ab44305caf3ea702d558e6e426c9aa',
    },
    'windows-x86_64': {
        'size': 15355936,
        'sha256': '4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847',
    },
}


def encoder_contract(model_id: str) -> dict[str, str | int | bool]:
    """The two supported frozen text encoders; not an arbitrary model registry."""
    common = {'normalize': True, 'dtype': 'float32', 'output': 'embeddings',
              'provider': 'CPUExecutionProvider', 'ort_version': '1.24.1',
              'intra_threads': 8, 'inter_threads': 1, 'sequential': True}
    if model_id == 'bge-m3':
        return {**common, 'revision': '5617a9f61b028005a4858fdac845db406aefb181',
                'dimension': 1024, 'pooling': 'cls', 'query_prefix': ''}
    if model_id == 'embeddinggemma-2':
        return {**common, 'revision': 'daa72c51243991dfcaf9f9137d2c573d8f7790c0',
                'dimension': 768, 'pooling': 'mean',
                'query_prefix': 'task: search result | query: ',
                'document_template': 'title: {title} | text: {text}',
                'untitled_document': 'none', 'pad_token_id': 0}
    raise ValueError('unsupported_model_contract')


def checked_source(path: Path, expected: ArtifactSpec) -> None:
    if not path.is_file() or path.stat().st_size != expected['size']:
        raise ValueError(f'wrong or missing source size: {path.name}')


def copy_verified(source: Path, destination: Path, expected: ArtifactSpec) -> ArtifactBinding:
    """Copy and hash in one pass; never share mutable tensor inodes with input."""
    checked_source(source, expected)
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


def runtime_bindings(libraries: Mapping[str, str | Path]) -> dict[str, ArtifactBinding]:
    if not libraries:
        raise ValueError('at least one explicit ORT library is required')
    bindings: dict[str, ArtifactBinding] = {}
    for platform, path in libraries.items():
        if platform not in RUNTIMES:
            raise ValueError(f'unsupported ORT platform: {platform}')
        path = Path(path)
        if path.is_symlink() or ':' in path.name or '\\' in path.name:
            raise ValueError('ORT library must be a regular file with a portable basename')
        expected = RUNTIMES[platform]
        checked_source(path, expected)
        with path.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        if sha != expected['sha256']:
            raise ValueError(f'ORT 1.24.1 library binding mismatch: {platform}')
        if any(b['path'] == path.name for b in bindings.values()):
            raise ValueError('platform runtimes require distinct basenames')
        bindings[platform] = {'path': path.name, **expected}
    return bindings


def verified_model(directory: Path) -> dict:
    """Verify a prepared model once at a read-only build invocation boundary."""
    from tools.source_pack import binding
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    frozen = encoder_contract(manifest.get('model_id'))
    if (manifest.get('schema') != 'sakura-shared-model-v1'
            or manifest.get('revision') != frozen['revision']
            or any(manifest.get('contract', {}).get(k) != v for k, v in frozen.items())):
        raise ValueError('frozen encoder contract mismatch')
    for item in [manifest['artifacts']['model'], manifest['artifacts']['tokenizer'],
                 *manifest['artifacts']['external_data']]:
        if (Path(item['path']).name != item['path']
                or binding(directory / item['path']) != {k: item[k] for k in ('path', 'sha256', 'size')}):
            raise ValueError('frozen model artifact binding mismatch')
    return manifest
