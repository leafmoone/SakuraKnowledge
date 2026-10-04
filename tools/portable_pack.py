"""Assemble create-new Windows CPU portable metadata/model files from frozen assets.
DB/mapping exports and I8 build are explicit prerequisites, never query side effects.
"""
import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


def binding(path, root):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return {'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size, 'sha256': digest.hexdigest()}


def assemble(repository, output, index):
    oldroot = repository / 'build/p4-dev-2048-1mib-3ee34e2-v1'
    old = json.loads((oldroot / 'manifest.json').read_bytes())
    config = json.loads((repository / 'configs/p4-full-semantic-v1.json').read_bytes())
    if (output / 'manifest.json').exists():
        raise FileExistsError(output / 'manifest.json')
    for folder in ['bin', 'model', 'licenses']:
        (output / folder).mkdir(exist_ok=True)
    index.rename(output / 'vectors.i8.usearch')
    artifacts = {}
    for role in ['model', 'tokenizer', 'ort_dll']:
        source = (oldroot / old['artifacts'][role]['path']).resolve()
        dest = output / ('bin' if role == 'ort_dll' else 'model') / source.name
        shutil.copyfile(source, dest)
        artifacts[role] = binding(dest, output)
    artifacts['external_data'] = []
    for item in old['artifacts']['external_data']:
        source = (oldroot / item['path']).resolve()
        dest = output / 'model' / source.name
        shutil.copyfile(source, dest)
        artifacts['external_data'].append(binding(dest, output))
    snapshot = binding(output / 'knowledge.sqlite', output)
    snapshot['identity'] = 'knowledge.sqlite'
    shutil.copyfile(oldroot / 'lexical-membership.sqlite', output / 'lexical-membership.sqlite')
    c = sqlite3.connect(output / 'lexical-membership.sqlite')
    print('membership tables', c.execute("select name from sqlite_master where type='table'").fetchall())
    metadata = dict(c.execute('SELECT key,value FROM meta'))
    metadata['snapshot_sha256'] = snapshot['sha256']
    metadata['snapshot_size'] = str(snapshot['size'])
    metadata['snapshot_identity'] = snapshot['identity']
    c.executemany('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)', metadata.items())
    c.commit()
    c.close()
    for role, filename in [('mapping','chunks.sqlite'),('index','vectors.i8.usearch'),('lexical_membership','lexical-membership.sqlite')]:
        artifacts[role] = binding(output / filename, output)
    m = copy.deepcopy(old)
    m['schema'] = 'p4-rust-semantic-portable-pack-v1'
    m['pack_version'] = 'portable-cpu-i8-v1'
    m.pop('canonical_contract', None)
    m['source_snapshot'] = config['snapshot']
    m['snapshot'] = snapshot
    m['artifacts'] = artifacts
    m['contract']['ann']['dtype'] = 'i8'
    m['contract']['ann_storage'] = 'i8'
    m['declarative_contract']['ann']['dtype'] = 'i8'
    m['lexical_membership'].update(snapshot_sha256=snapshot['sha256'],snapshot_size=snapshot['size'],snapshot_identity=snapshot['identity'])
    (output / 'manifest.json').write_text(json.dumps(m, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    for name in ['sknow-rs.exe','semantic_pilot.exe']:
        shutil.copyfile(repository / 'build/p4-usearch-native-fix/rust-target/release' / name,output / 'bin' / name)
    shutil.copyfile(repository / 'scripts/sknow.ps1', output / 'sknow.ps1')
    shutil.copyfile(repository / 'README.md', output / 'README.md')
    for name in ['libstdc++-6.dll','libgcc_s_seh-1.dll','libwinpthread-1.dll']:
        shutil.copyfile(Path('C:/msys64/ucrt64/bin') / name,output / 'bin' / name)
    (output / 'sknow-config.json').write_text(json.dumps({'bin':'bin','database':'knowledge.sqlite','manifest':'manifest.json'}),encoding='utf8')
    for folder,names in [('gcc-libs',['COPYING3','COPYING.RUNTIME','COPYING.LIB']),('libwinpthread',['COPYING'])]:
        for name in names:
            shutil.copyfile(Path('C:/msys64/ucrt64/share/licenses')/folder/name,output/'licenses'/(folder+'-'+name))
    shutil.copyfile(repository / 'vendor/usearch-2.26.2/LICENSE',output / 'licenses/USearch-LICENSE')
    for name in ['BGE-LICENSE','ONNXRuntime-LICENSE']:
        shutil.copyfile(repository/'docs/licenses'/name,output/'licenses'/name)
    known={item['path']:item for item in [snapshot,*[v for k,v in artifacts.items() if k!='external_data'],*artifacts['external_data']]}
    inventory={p.relative_to(output).as_posix():known.get(p.relative_to(output).as_posix()) or binding(p,output) for p in output.rglob('*') if p.is_file() and p.name!='inventory.json'}
    (output/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'snapshot':snapshot,'artifacts':artifacts,'total_bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file())},ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--index',type=Path,required=True)
    p.add_argument('--prepare',action='store_true',help='Create exclusive output, export DB/mapping and build actual I8 before assembly')
    a=p.parse_args()
    if a.prepare:
        import subprocess

        from tools.portable_export import export_db, export_mapping
        a.output.mkdir(parents=True,exist_ok=False)
        export_db(a.repository/'build/p3-full-authorized-retry1/knowledge.sqlite',a.output/'knowledge.sqlite')
        export_mapping(a.repository/'build/p4-full-semantic-v1-retry1/chunks.sqlite',a.output/'chunks.sqlite')
        builder=a.repository/'build/p4-usearch-native-fix/rust-target/release/examples/build_i8.exe'
        subprocess.run([str(builder),str(a.repository/'build/p4-full-semantic-v1-retry1/vectors.npy'),str(a.index)],check=True)
    assemble(a.repository,a.output,a.index)


if __name__ == '__main__':
    main()
