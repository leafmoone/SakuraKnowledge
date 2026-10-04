"""Exactly one independent read-only native-buffer probe, not acceptance or recovery."""
import gc
import hashlib
import json
import mmap
import sys
import time
from pathlib import Path
import numpy as np
from usearch.index import Index

D = Path(__file__).resolve().parent
ROOT = D.parents[2]
OUT = ROOT / 'build/p4-full-semantic-v1-retry1'

def save(name, value):
    with (D/name).open('x', encoding='utf8') as f:
        json.dump(value, f, indent=2, allow_nan=False)


def main():
    assert json.loads((D/'tiny-buffer.json').read_bytes())['native_buffer_api'] == 'PASS'
    # Durable one-shot diagnostic claim: never restart after interrupted/failed probe.
    save('full-probe-claim.json', {'pid':__import__('os').getpid(), 'purpose':'one diagnostic buffer view only'})
    report = {'OPEN_PASS':'NOT_RUN','KEY_AUDIT':'NOT_RUN','VECTOR_MAPPING_AUDIT':'NOT_RUN',
              'runtime_qualification':'NOT_RUN','quality_acceptance':'NOT_RUN'}
    start = time.monotonic()
    p = OUT/'vectors.usearch'
    vectors = None
    idx = None
    mm = None
    view = None
    f = None
    try:
        f = p.open('rb')
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        assert len(mm) == 5800312336
        view = memoryview(mm)
        assert view.readonly and view.itemsize == 1 and view.nbytes == len(mm)
        idx = Index(ndim=1024, metric='cos', dtype='f32', connectivity=16,
                    expansion_add=256, expansion_search=128)
        idx._compiled.view_index_from_buffer(view, None)
        assert len(idx) == 1366520
        report['OPEN_PASS'] = 'PASS'
        print('OPEN_PASS=PASS', flush=True)
        keys = np.asarray(idx.keys, dtype=np.uint64)
        assert keys.shape == (1366520,)
        ordered = np.sort(keys)
        assert np.array_equal(ordered, np.arange(1366520, dtype=np.uint64))
        report.update(KEY_AUDIT='PASS', key_count=int(keys.size), key_min=int(ordered[0]),
                      key_max=int(ordered[-1]), duplicate_count=0, missing_count=0,
                      sorted_keys_sha256=hashlib.sha256(ordered.tobytes()).hexdigest())
        del ordered, keys
        print('KEY_AUDIT=PASS', flush=True)
        positions = json.loads((OUT/'sample.json').read_bytes())['positions']
        assert len(positions) == len(set(positions)) == 1200
        vectors = np.load(OUT/'vectors.npy', mmap_mode='r', allow_pickle=False)
        assert vectors.shape == (1366520,1024) and vectors.dtype == np.float32
        maximum = 0.0
        for key in positions:
            got = idx.get(int(key), dtype=np.float32)
            assert got is not None and got.shape == (1024,) and got.dtype == np.float32
            assert np.isfinite(got).all()
            error = float(np.max(np.abs(got - vectors[key])))
            maximum = max(maximum, error)
            assert np.array_equal(got, vectors[key]), 'stored key/vector bytes differ'
        report.update(VECTOR_MAPPING_AUDIT='PASS', sample_count=1200,
                      sample_max_component_error=maximum, stored_vector_mapping='EXACT_FP32_EQUAL')
        print('VECTOR_MAPPING_AUDIT=PASS', flush=True)
    except BaseException as error:
        report.update(error_type=type(error).__name__, error_message=str(error))
        raise
    finally:
        # Release every native reference before releasing exporter/mapping.
        if idx is not None:
            idx.reset()
            del idx
            gc.collect()
        if vectors is not None:
            vectors._mmap.close()
            del vectors
        if view is not None:
            view.release()
        if mm is not None:
            mm.close()
        if f is not None:
            f.close()
        report['elapsed_seconds'] = time.monotonic() - start
        report['lifetime_release'] = 'index reset/delete/gc before view.release/mmap.close'
        save('full-buffer-probe.json', report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
