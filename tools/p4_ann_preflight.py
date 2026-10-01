"""Synthetic-only ANN preflight. Run with the isolated ANN backend's Python."""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from tools import p4_ann_v1 as ann


def exercise(Index, directory):
    import numpy as np

    vectors = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
                        [-1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, -1]],
                       dtype=np.float32)
    keys = np.arange(8, dtype=np.uint64)
    kwargs = {'ndim': 4, 'metric': 'cos', 'dtype': 'f32', 'connectivity': 16,
              'expansion_add': 128, 'expansion_search': 32, 'multi': False}
    index = Index(**kwargs)
    index.add(keys, vectors, threads=8, copy=True)
    ann.exact.require(len(index) == 8 and bool(index.contains(keys).all()), 'preflight index keys')
    matches = index.search(vectors[0], count=8, threads=8, exact=False)
    distances = np.asarray(matches.distances)
    ann.exact.require(len(matches.keys) == len(distances) == 8 and
                      set(map(int, matches.keys)) == set(range(8)) and int(matches.keys[0]) == 0 and
                      bool(np.isfinite(distances).all()) and bool((np.diff(distances) >= 0).all()) and
                      abs(float(distances[0])) < 1e-5, 'preflight search results')
    path = directory / 'synthetic.usearch'
    ann.exact.require(not path.exists(), 'preflight index overwrite forbidden')
    index.save(str(path))
    ann.exact.require(path.stat().st_size > 0, 'empty preflight index')
    digest = ann.exact.sha(path)
    loaded = Index(**kwargs)
    loaded.load(str(path))
    ann.exact.require(len(loaded) == 8 and bool(loaded.contains(keys).all()), 'preflight loaded keys')
    return {'checks': {k: 'PASS' for k in ('add', 'keys', 'search', 'save', 'load')},
            'index_bytes': path.stat().st_size, 'index_sha256': digest,
            'diagnostics': ann.diagnostics(index), 'loaded_diagnostics': ann.diagnostics(loaded)}


def run():
    output = ann.exact.local(ann.PREFLIGHT)
    ann.exact.require(not output.exists(), 'preflight exists; overwrite forbidden')
    sources = [ann.exact.local('tools/p4_ann_v1.py'), ann.exact.local('tools/p4_ann_preflight.py')]
    receipt = {'schema': 'p4-ann-preflight-v1', 'status': 'FAIL', 'usearch': ann.POLICY['usearch'],
               'synthetic': {'dimension': 4, 'metric': 'cos', 'dtype': 'f32', 'rows': 8, 'queries': 1},
               'retries': 0, 'real_inputs_read': False}
    try:
        receipt['source_sha256_before'] = ann.snapshot(sources)
        Index = ann.load_backend()
        with tempfile.TemporaryDirectory(prefix='p4-ann-preflight-') as directory:
            receipt.update(exercise(Index, Path(directory)))
        receipt['source_sha256_after'] = ann.snapshot(sources)
        ann.exact.require(receipt['source_sha256_before'] == receipt['source_sha256_after'],
                          'preflight source changed')
        receipt['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 - preserve a failed preflight, never retry.
        receipt['error'] = f'{type(exc).__name__}: {exc}'
    ann.save_new(output, receipt)
    return receipt


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    return int(run()['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
