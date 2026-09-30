"""Small receipts reference content-addressed byte-verbatim raw once, not huge copies."""
import hashlib
import json
from pathlib import Path


def store(data, root=Path('reports/P3/raw')):
    root.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(data).hexdigest()
    path=root/(digest+'.raw')
    if path.exists():
        if path.read_bytes()!=data:
            raise ValueError('raw hash collision/mutated evidence')
    else:
        with path.open('xb') as stream:
            stream.write(data)
    return {'path':path.as_posix(),'sha256':digest,'bytes':len(data)}


def save(path,data):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2)


def verify(ref):
    data=Path(ref['path']).read_bytes()
    if len(data)!=ref['bytes'] or hashlib.sha256(data).hexdigest()!=ref['sha256']:
        raise ValueError('raw receipt mismatch')
    return data
