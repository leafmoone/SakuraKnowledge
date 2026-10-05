"""Assemble a portable pack without consuming inputs or replacing existing files.
DB/mapping exports and I8 build are explicit prerequisites, never query side effects.
"""
import argparse
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path, PurePosixPath

NATIVE_ROOT = Path('C:/msys64/ucrt64')
OLD_ROOT = 'build/p4-dev-2048-1mib-3ee34e2-v1'
PREREQUISITES = {'knowledge.sqlite', 'chunks.sqlite'}


def binding(path, root):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return {'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size, 'sha256': digest.hexdigest()}


def _exists(path):
    return path.exists() or path.is_symlink()


def _file(path):
    if not path.is_file():
        raise FileNotFoundError(path)


def _relative(value):
    if not isinstance(value, str) or not value:
        raise ValueError(f'unsafe pack path: {value!r}')
    path = PurePosixPath(value)
    if ('\\' in value or ':' in value or path.is_absolute() or '..' in path.parts
            or path.as_posix() != value or value == '.'):
        raise ValueError(f'unsafe pack path: {value!r}')
    return path


def _output_preflight(output, prepare=False):
    # Refuse a published pack before even reading the source manifest.
    if _exists(output / 'manifest.json'):
        raise FileExistsError(output / 'manifest.json')
    if prepare and _exists(output):
        raise FileExistsError(output)
    if output.is_symlink() or (_exists(output) and not output.is_dir()):
        raise FileExistsError(output)
    if _exists(output / '.assemble-stage'):
        raise FileExistsError(output / '.assemble-stage')
    if output.exists():
        for path in output.rglob('*'):
            if path.is_symlink() or (path.is_file() and path.relative_to(output).as_posix() not in PREREQUISITES):
                raise FileExistsError(path)
    for parent in output.parents:
        if parent.is_symlink() or (_exists(parent) and not parent.is_dir()):
            raise FileExistsError(parent)


def preflight(repository, output, index, native_root=NATIVE_ROOT, prepare=False):
    repository, output, index, native_root = map(Path, (repository, output, index, native_root))
    _output_preflight(output, prepare)
    if index.resolve().is_relative_to(output.resolve()):
        raise ValueError('index input/build target must be outside the pack output')
    oldroot = repository / OLD_ROOT
    old = json.loads((oldroot / 'manifest.json').read_bytes())
    config = json.loads((repository / 'configs/p4-full-semantic-v1.json').read_bytes())
    resources = {}

    def add(source, destination):
        _relative(destination)
        if destination in resources or destination in PREREQUISITES | {'inventory.json', 'manifest.json', 'sknow-config.json'}:
            raise ValueError(f'duplicate destination: {destination}')
        if source.resolve().is_relative_to(output.resolve()):
            raise ValueError(f'input overlaps output: {source}')
        if prepare and source.resolve() == index.resolve():
            raise ValueError(f'input overlaps index build target: {source}')
        resources[destination] = source

    roles = {}
    for role in ['model', 'tokenizer', 'ort_dll']:
        source = oldroot / old['artifacts'][role]['path']
        destination = ('bin/' if role == 'ort_dll' else 'model/') + source.name
        add(source, destination)
        roles[role] = destination
    roles['external_data'] = []
    for item in old['artifacts']['external_data']:
        source = oldroot / item['path']
        destination = 'model/' + source.name
        add(source, destination)
        roles['external_data'].append(destination)
    add(oldroot / 'lexical-membership.sqlite', 'lexical-membership.sqlite')
    # The new index is an output only in prepare mode.
    resources['vectors.i8.usearch'] = index
    for name in ['sknow-rs.exe', 'semantic_pilot.exe']:
        add(repository / 'build/p4-usearch-native-fix/rust-target/release' / name, 'bin/' + name)
    for name, source in [('sknow.ps1', repository / 'scripts/sknow.ps1'), ('README.md', repository / 'README.md')]:
        add(source, name)
    for name in ['libstdc++-6.dll', 'libgcc_s_seh-1.dll', 'libwinpthread-1.dll']:
        add(native_root / 'bin' / name, 'bin/' + name)
    for folder, names in [('gcc-libs', ['COPYING3', 'COPYING.RUNTIME', 'COPYING.LIB']), ('libwinpthread', ['COPYING'])]:
        for name in names:
            add(native_root / 'share/licenses' / folder / name, 'licenses/' + folder + '-' + name)
    add(repository / 'vendor/usearch-2.26.2/LICENSE', 'licenses/USearch-LICENSE')
    for name in ['BGE-LICENSE', 'ONNXRuntime-LICENSE']:
        add(repository / 'docs/licenses' / name, 'licenses/' + name)
    for destination, source in resources.items():
        if not (prepare and source == index):
            _file(source)
        target = output / destination
        if _exists(target):
            raise FileExistsError(target)
        for parent in target.parents:
            if parent == output.parent:
                break
            if parent.is_symlink() or (_exists(parent) and not parent.is_dir()):
                raise FileExistsError(parent)
    if prepare:
        if _exists(index):
            raise FileExistsError(index)
        for parent in index.parents:
            if _exists(parent) and not parent.is_dir():
                raise FileExistsError(parent)
        for source in [repository / 'build/p3-full-authorized-retry1/knowledge.sqlite',
                       repository / 'build/p4-full-semantic-v1-retry1/chunks.sqlite',
                       repository / 'build/p4-full-semantic-v1-retry1/vectors.npy',
                       repository / 'build/p4-usearch-native-fix/rust-target/release/examples/build_i8.exe']:
            _file(source)
            if source.resolve().is_relative_to(output.resolve()) or source.resolve() == index.resolve():
                raise ValueError(f'prepare input/output collision: {source}')
    else:
        for name in PREREQUISITES:
            _file(output / name)
    return old, config, resources, roles


def _membership(path, snapshot, declaration, update=False):
    # sqlite's transaction context does not close the connection (notably Windows).
    with closing(sqlite3.connect(path)) as connection, connection:
        if update:
            connection.executemany('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)', [
                ('snapshot_sha256', snapshot['sha256']), ('snapshot_size', str(snapshot['size'])),
                ('snapshot_identity', snapshot['identity'])])
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('membership integrity failure')
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        if tables != [('members',), ('meta',)]:
            raise ValueError('membership tables mismatch')
        for table, expected in [('members', [('fts_rowid', 'INTEGER', 0, 1), ('entry_id', 'INTEGER', 1, 0), ('document_id', 'INTEGER', 1, 0)]),
                                ('meta', [('key', 'TEXT', 0, 1), ('value', 'TEXT', 1, 0)])]:
            columns = [(r[1], r[2], r[3], r[5]) for r in connection.execute(f'PRAGMA table_info({table})')]
            if columns != expected:
                raise ValueError('membership columns mismatch')
        expected = {'version': 'p4-full-membership-v1', 'rows': str(declaration['rows']),
                    'snapshot_sha256': snapshot['sha256'], 'snapshot_size': str(snapshot['size']),
                    'snapshot_identity': snapshot['identity']}
        if dict(connection.execute('SELECT key,value FROM meta')) != expected:
            raise ValueError('membership binding mismatch')
        if declaration['version'] != expected['version'] or connection.execute('SELECT count(*) FROM members').fetchone()[0] != declaration['rows']:
            raise ValueError('membership rows/version mismatch')


def validate_pack(root, manifest, inventory, expected_paths):
    """Validate the complete closed file set and every binding before publication."""
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(expected_paths) or set(inventory) != actual:
        raise ValueError('pack file set mismatch')
    for name, item in inventory.items():
        _relative(name)
        path = root / name
        if path.is_symlink() or item != binding(path, root):
            raise ValueError(f'pack binding mismatch: {name}')
    if json.loads((root / 'manifest.json').read_bytes()) != manifest:
        raise ValueError('manifest serialization mismatch')
    if manifest['schema'] != 'p4-rust-semantic-portable-pack-v1' or manifest['pack_version'] != 'portable-cpu-i8-v1':
        raise ValueError('portable manifest schema mismatch')
    artifacts = manifest['artifacts']
    if set(artifacts) != {'model', 'tokenizer', 'ort_dll', 'mapping', 'index', 'lexical_membership', 'external_data'}:
        raise ValueError('artifact roles mismatch')
    for role, name in [('mapping', 'chunks.sqlite'), ('index', 'vectors.i8.usearch'), ('lexical_membership', 'lexical-membership.sqlite')]:
        if artifacts[role]['path'] != name:
            raise ValueError(f'artifact path mismatch: {role}')
    bindings = [manifest['snapshot'], *[v for k, v in artifacts.items() if k != 'external_data'], *artifacts['external_data']]
    paths = []
    for item in bindings:
        name = item['path']
        _relative(name)
        if {k: item[k] for k in ('path', 'size', 'sha256')} != inventory.get(name):
            raise ValueError(f'manifest binding mismatch: {name}')
        paths.append(name)
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate manifest binding')
    snapshot = manifest['snapshot']
    if snapshot['path'] != 'knowledge.sqlite' or snapshot['identity'] != 'knowledge.sqlite':
        raise ValueError('snapshot identity mismatch')
    for key in ('sha256', 'size', 'identity'):
        if manifest['lexical_membership']['snapshot_' + key] != snapshot[key]:
            raise ValueError('membership declaration mismatch')
    if manifest['contract']['ann']['dtype'] != 'i8' or manifest['contract']['ann_storage'] != 'i8' or manifest['declarative_contract']['ann']['dtype'] != 'i8':
        raise ValueError('I8 contract mismatch')
    _membership(root / artifacts['lexical_membership']['path'], snapshot, manifest['lexical_membership'])


def _publish(source, destination):
    # Both paths are on the output volume. A hard link is atomic create-new,
    # unlike rename/replace which may silently clobber an existing destination.
    os.link(source, destination)


def assemble(repository, output, index, native_root=NATIVE_ROOT):
    repository, output, index = map(Path, (repository, output, index))
    old, config, resources, roles = preflight(repository, output, index, native_root)
    output.mkdir(parents=True, exist_ok=True)
    stage = output / '.assemble-stage'
    stage.mkdir(exist_ok=False)
    published = []
    try:
        for name in PREREQUISITES:
            os.link(output / name, stage / name)
        for name, source in resources.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        snapshot = binding(stage / 'knowledge.sqlite', stage)
        snapshot['identity'] = 'knowledge.sqlite'
        manifest = copy.deepcopy(old)
        manifest.update(schema='p4-rust-semantic-portable-pack-v1', pack_version='portable-cpu-i8-v1', source_snapshot=config['snapshot'], snapshot=snapshot)
        manifest.pop('canonical_contract', None)
        manifest['contract']['ann']['dtype'] = 'i8'
        manifest['contract']['ann_storage'] = 'i8'
        manifest['declarative_contract']['ann']['dtype'] = 'i8'
        manifest['lexical_membership'].update(snapshot_sha256=snapshot['sha256'], snapshot_size=snapshot['size'], snapshot_identity=snapshot['identity'])
        _membership(stage / 'lexical-membership.sqlite', snapshot, manifest['lexical_membership'], update=True)
        artifacts = {role: binding(stage / name, stage) for role, name in roles.items() if role != 'external_data'}
        artifacts['external_data'] = [binding(stage / name, stage) for name in roles['external_data']]
        for role, name in [('mapping', 'chunks.sqlite'), ('index', 'vectors.i8.usearch'), ('lexical_membership', 'lexical-membership.sqlite')]:
            artifacts[role] = binding(stage / name, stage)
        manifest['artifacts'] = artifacts
        (stage / 'sknow-config.json').write_text(json.dumps({'bin': 'bin', 'database': 'knowledge.sqlite', 'manifest': 'manifest.json'}), encoding='utf8')
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        inventory = {p.relative_to(stage).as_posix(): binding(p, stage) for p in stage.rglob('*') if p.is_file()}
        validate_pack(stage, manifest, inventory, set(resources) | PREREQUISITES | {'sknow-config.json', 'manifest.json'})
        (stage / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        for name in [*resources, 'sknow-config.json', 'inventory.json', 'manifest.json']:
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _publish(stage / name, target)
            published.append(target)
        result = {'files': len(inventory) + 1, 'total_bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and stage not in p.parents)}
        print(json.dumps(result))
        return result
    except BaseException:
        for path in reversed(published):
            if _exists(path) and os.path.samefile(path, stage / path.relative_to(output)):
                path.unlink()
        raise
    finally:
        shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--native-root', type=Path, default=NATIVE_ROOT)
    parser.add_argument('--prepare', action='store_true', help='Export DB/mapping and build a new external I8 index before assembly')
    args = parser.parse_args()
    if args.prepare:
        preflight(args.repository, args.output, args.index, args.native_root, prepare=True)
        # Create the builder's destination on its requested volume before exports.
        args.index.parent.mkdir(parents=True, exist_ok=True)
        args.output.mkdir(parents=True, exist_ok=False)
        from tools.portable_export import export_db, export_mapping
        export_db(args.repository / 'build/p3-full-authorized-retry1/knowledge.sqlite', args.output / 'knowledge.sqlite')
        export_mapping(args.repository / 'build/p4-full-semantic-v1-retry1/chunks.sqlite', args.output / 'chunks.sqlite')
        builder = args.repository / 'build/p4-usearch-native-fix/rust-target/release/examples/build_i8.exe'
        subprocess.run([str(builder), str(args.repository / 'build/p4-full-semantic-v1-retry1/vectors.npy'), str(args.index)], check=True)
    assemble(args.repository, args.output, args.index, args.native_root)


if __name__ == '__main__':
    main()
