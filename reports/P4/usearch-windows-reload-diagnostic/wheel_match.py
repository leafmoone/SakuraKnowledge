"""Download official exact platform wheel as evidence only; never install."""
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path
D = Path(__file__).resolve().parent
ROOT = D.parents[2]
api = 'https://pypi.org/pypi/usearch/2.26.2/json'
metadata = json.loads(urllib.request.urlopen(api).read())
items = [x for x in metadata['urls'] if x['filename'] == 'usearch-2.26.2-cp314-cp314-win_amd64.whl']
assert len(items) == 1
item = items[0]
data = urllib.request.urlopen(item['url']).read()
assert hashlib.sha256(data).hexdigest() == item['digests']['sha256']
p = D / item['filename']
with p.open('xb') as f:
    f.write(data)
with zipfile.ZipFile(p) as z:
    n = 'usearch/compiled.cp314-win_amd64.pyd'
    official = hashlib.sha256(z.read(n)).hexdigest()
    local = hashlib.sha256((ROOT/'.venv-p4-ann/Lib/site-packages'/n).read_bytes()).hexdigest()
    assert official == local
    record = z.read('usearch-2.26.2.dist-info/RECORD').decode()
j = {'api':api, 'url':item['url'], 'filename':item['filename'], 'wheel_bytes':len(data),
     'wheel_sha256':hashlib.sha256(data).hexdigest(), 'native_sha256':local,
     'LOCAL_BINARY_MATCH':'OFFICIAL_PLATFORM_WHEEL_NATIVE_BYTES_MATCH',
     'source_build_correspondence':'Version-tag source only; no reproducible-build proof or wheel build attestation',
     'native_record':[line for line in record.splitlines() if n in line]}
with (D/'wheel-match.json').open('x',encoding='utf8') as f:
    json.dump(j,f,indent=2)
print(json.dumps(j))
