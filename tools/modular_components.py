"""Local non-consuming modular component/root assembly; no downloader or archive."""
import argparse
import json
import shutil
from pathlib import Path

from tools.portable_pack import binding


def copy_tree(source, output):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError(output)
    shutil.copytree(source, output)


def make_core(baseline, output):
    baseline, output = Path(baseline), Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    shutil.copytree(baseline / 'bin', output / 'bin')
    shutil.copytree(baseline / 'licenses', output / 'licenses')
    shutil.copy2(Path(__file__).resolve().parents[1] / 'scripts/sknow.ps1', output / 'sknow.ps1')
    (output / 'sknow-config.json').write_text(json.dumps({'packs_directory': 'packs', 'model_directory': 'model', 'bin_directory': 'bin'}, indent=2), encoding='utf-8')


def make_model(baseline, output):
    baseline, output = Path(baseline), Path(output)
    if output.exists():
        raise FileExistsError(output)
    old = json.loads((baseline / 'manifest.json').read_text(encoding='utf-8'))
    root = output / 'model/bge-m3'
    root.mkdir(parents=True)
    artifacts = {}
    for name in ('model', 'tokenizer'):
        source = baseline / old['artifacts'][name]['path']
        shutil.copy2(source, root / source.name)
        artifacts[name] = binding(root / source.name, root)
    artifacts['external_data'] = []
    for item in old['artifacts']['external_data']:
        source = baseline / item['path']
        shutil.copy2(source, root / source.name)
        artifacts['external_data'].append(binding(root / source.name, root))
    manifest = {'schema': 'sakura-shared-model-v1', 'model_id': 'bge-m3', 'version': '1', 'contract': old['contract'], 'revision': old['contract']['revision'], 'artifacts': artifacts, 'ort_dll': {k: v for k, v in old['artifacts']['ort_dll'].items() if k != 'path'}}
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def assemble(core, model, packs, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    stage = output.with_name(output.name + '.assemble-stage')
    if stage.exists():
        raise FileExistsError(stage)
    copy_tree(core, stage)
    try:
        if model:
            shutil.copytree(Path(model) / 'model', stage / 'model')
        for source in packs:
            source = Path(source)
            manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
            pack_id = manifest['pack_id']
            if pack_id not in ('danbooru', 'bangumi', 'moegirl', 'tag-wiki'):
                raise ValueError('unsupported pack_id')
            if manifest.get('schema') is not None and manifest['schema'] != 'sakura-source-pack-v1':
                raise ValueError('unsupported source schema')
            for item in manifest.get('artifacts', {}).values():
                path = Path(item['path'])
                if path.is_absolute() or len(path.parts) != 1:
                    raise ValueError('unsafe source artifact path')
                actual = binding(source / path, source)
                if actual != item and actual != {k: v for k, v in item.items() if k != 'identity'}:
                    raise ValueError('source artifact binding mismatch: ' + str(path))
            destination = stage / 'packs' / manifest['pack_id']
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns('positions.u64le', 'manifest.json'))
            shutil.copy2(source / 'manifest.json', destination / 'manifest.json')
        stage.rename(output)
    except BaseException:
        shutil.rmtree(stage)
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('core', 'model', 'assemble-root'))
    p.add_argument('--baseline')
    p.add_argument('--core')
    p.add_argument('--model')
    p.add_argument('--pack', action='append', default=[])
    p.add_argument('--output', required=True)
    a = p.parse_args()
    if a.command == 'core':
        make_core(a.baseline, a.output)
    elif a.command == 'model':
        make_model(a.baseline, a.output)
    else:
        assemble(a.core, a.model, a.pack, a.output)


if __name__ == '__main__':
    main()
