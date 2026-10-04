"""Tiny native-buffer lifetime prerequisite. Writes only in this diagnostic directory."""
import gc
import json
import mmap
from pathlib import Path
import numpy as np
from usearch.index import Index

D = Path(__file__).resolve().parent
kw = dict(ndim=4, metric='cos', dtype='f32', connectivity=16, expansion_add=256, expansion_search=128)
p = D / 'tiny.usearch'
i = Index(**kw)
assert callable(getattr(i._compiled, 'view_index_from_buffer', None))
i.add(np.array([0, 1], dtype=np.uint64), np.array([[1,0,0,0],[0,1,0,0]], dtype=np.float32), threads=1, copy=True)
with p.open('xb'):
    pass
i.save(str(p))
i.reset()
del i
gc.collect()
with p.open('rb') as f:
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    view = memoryview(mm)
    j = Index(**kw)
    try:
        j._compiled.view_index_from_buffer(view, None)
        assert len(j) == 2 and sorted(j.keys) == [0,1]
        assert np.array_equal(j.get(0, dtype=np.float32), np.array([1,0,0,0], dtype=np.float32))
    finally:
        j.reset()
        del j
        gc.collect()
        view.release()
        mm.close()
with (D/'tiny-buffer.json').open('x', encoding='utf8') as f:
    json.dump({'native_buffer_api':'PASS', 'read_only_mmap':'PASS', 'key_vector_check':'PASS',
               'lifetime':'index.reset/delete/gc before memoryview.release/mmap.close PASS',
               'full_probe':'NOT_RUN'}, f)
print('TINY_READONLY_BUFFER_LIFETIME=PASS')
