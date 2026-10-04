"""Create-new Rust semantic activation packs and explicit qualification jobs.

Pack/freeze only hash files: no model/session/index loading or inference.
external_data is an array of every exported tensor binding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import sqlite3
import stat
import subprocess
import threading
import time
from pathlib import Path

from tools import p4_ann_v1 as ann

ROOT = Path(__file__).resolve().parents[1]
PACK = 'build/p4/rust-semantic-pilot-v1/manifest.json'
JOB = 'configs/p4-rust-pilot-v1.json'
RAW = 'build/p4/rust-semantic-pilot-v1/qualification'
RECEIPT = 'reports/P4/rust-semantic-pilot-v1.json'
SELECTED = 'M16-Eadd256-ef128'
MAX_BYTES = 524288
REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
_DLL = json.loads((ROOT / 'configs/p4-current-assets.json').read_text(encoding='utf8'))['ort_dll']
DLL_SHA, DLL_SIZE = _DLL['sha256'], _DLL['size']
EXTERNAL_ORT_DLL = Path(_DLL['path'])
LEX_SHA = 'c664b3c81181942d202321fe81448d2cfc4e00ab658b864732e758ce7a1829b3'
POLICY = {'warmups': 2, 'formal': 120, 'retries': 0, 'resident_max_ms': 5000,
          'resident_p95_ms': 1000, 'response_max_bytes': MAX_BYTES,
          'startup_timeout_seconds': 120, 'query_timeout_seconds': 5}
require = ann.exact.require


def fixed_contract():
    return {'lexical_mode': 'pilot_sidecar', 'revision': REVISION, 'dimension': 1024,
            'pooling': 'cls', 'normalize': True, 'query_prefix': '', 'dtype': 'float32',
            'output': 'embeddings', 'provider': 'CPUExecutionProvider', 'ort_version': '1.24.1',
            'intra_threads': 8, 'inter_threads': 1, 'sequential': True,
            'ann': {'rows': 52664, 'metric': 'cos', 'dtype': 'f32', 'connectivity': 16,
                    'expansion_add': 256, 'expansion_search': 128,
                    'chunk_depth': 512, 'entry_depth': 100},
            'bm25_document_depth': 100, 'rrf_k': 60, 'ties': 'kind,namespace,value',
            'pins': 'trusted_exact_alias'}


def local(name):
    path = (ROOT / name).resolve()
    require(path.is_relative_to(ROOT), 'path escapes repository')
    return path


def load(path):
    return ann.selection.parse(Path(path).read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save_new(path, value):
    ann.save_new(Path(path), value)


def read_artifact(name, *, ort_dll=False):
    """Read-only exception for the one authorized, independently pinned DLL."""
    path = (ROOT / name).resolve()
    if path.is_relative_to(ROOT):
        return path
    require(ort_dll and Path(name).is_absolute() and
            Path(name) == EXTERNAL_ORT_DLL and path == EXTERNAL_ORT_DLL,
            'path escapes repository')
    require(path.is_file() and path.stat().st_size == DLL_SIZE and sha(path) == DLL_SHA,
            'unpinned ORT DLL')
    return path


def binding(path, relative_to=ROOT, *, ort_dll=False):
    path = read_artifact(path, ort_dll=ort_dll)
    require(path.is_file() and path.stat().st_size > 0, 'empty/missing artifact')
    # External DLLs must stay absolute: relpath cannot cross Windows drives.
    name = (Path(os.path.relpath(path, relative_to)).as_posix()
            if path.is_relative_to(ROOT) else path.as_posix())
    return {'path': name, 'size': path.stat().st_size, 'sha256': sha(path)}


def verify_binding(record, root=ROOT, *, ort_dll=False):
    path = read_artifact(root / record['path'], ort_dll=ort_dll)
    require(path.stat().st_size == record['size'] and sha(path) == record['sha256'],
            f'artifact changed: {path}')
    return path








def export_artifacts(directory, pack_root, *, verified=None):
    """Inventory only: no ONNX parser/session and no tensor materialization."""
    manifest = load(directory / 'manifest.json')
    records = manifest['files']
    names = [r['path'] for r in records]
    require(len(names) == len(set(names)) and 'model.onnx' in names, 'export inventory')
    result = {}
    external = []
    for record in records:
        raw_path = directory / record['path']
        require(not Path(record['path']).is_absolute() and '..' not in Path(record['path']).parts,
                'external tensor escapes export')
        for component in (raw_path, *raw_path.parents):
            info = component.lstat()
            require(not component.is_symlink() and not component.is_junction() and
                    not (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                    'symlink/reparse/junction export asset')
        path = raw_path.resolve()
        require(path.is_relative_to(directory.resolve()), 'external tensor escapes export')
        if verified is not None:
            verified(path, record)
            ref = {'path': Path(os.path.relpath(path, pack_root)).as_posix(),
                   'size': record['size'], 'sha256': record['sha256']}
        else:
            verify_binding(record, directory)
            ref = {'path': Path(os.path.relpath(path, pack_root)).as_posix(),
                   'size': record['size'], 'sha256': record['sha256']}
        if record['path'] == 'model.onnx':
            result['model'] = ref
        elif record['path'] != 'passage-sample.json':
            external.append(ref)
    require(external, 'missing external tensors')
    # Every existing export file must be accounted for, including all tensor shards.
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    require(actual == set(names) | {'manifest.json'}, 'unlisted export file')
    result['external_data'] = external
    return result


def build_pack(snapshot, ort_dll, output=PACK):
    output = local(output)
    require(not output.exists(), 'pack already exists')
    spec = load(local('configs/p4-current-assets.json'))
    directory = local(spec['export_manifest']['path']).parent
    verify_binding(spec['export_manifest'])
    export_manifest = binding(directory / 'manifest.json', output.parent)
    artifacts = export_artifacts(directory, output.parent)
    for key, record in spec['optional_pilot_artifacts'].items():
        artifacts[key] = binding(verify_binding(record), output.parent)
    artifacts['ort_dll'] = binding(ort_dll, output.parent, ort_dll=True)
    require(artifacts['ort_dll']['sha256'] == spec['ort_dll']['sha256'] and
            artifacts['ort_dll']['size'] == spec['ort_dll']['size'], 'unpinned ORT DLL')
    with sqlite3.connect(local(spec['optional_pilot_artifacts']['lexical']['path']).as_uri() + '?mode=ro', uri=True) as conn:
        metadata = json.loads(conn.execute('SELECT value FROM metadata').fetchone()[0])
    snap = binding(snapshot, output.parent)
    snap['identity'] = local(snapshot).relative_to(ROOT).as_posix()
    for name, record in (('snapshot', snap), ('corpus', artifacts['corpus'])):
        require(all(metadata[name][k] == record[k] for k in ('sha256', 'size')),
                f'lexical {name} binding mismatch')
    value = {'schema': 'p4-rust-semantic-pack-v1', 'pack_version': 'rust-semantic-pilot-v1',
             'snapshot': snap, 'contract': fixed_contract(), 'lexical_metadata': metadata,
             'artifacts': artifacts,
             'export_manifest': export_manifest}
    save_new(output, value)
    return value


def pack_bindings(manifest_path):
    manifest_path = local(manifest_path)
    pack = load(manifest_path)
    require(pack['schema'] == 'p4-rust-semantic-pack-v1' and
            pack['contract'] == fixed_contract(), 'pack contract')
    require(isinstance(pack['artifacts']['external_data'], list) and
            pack['artifacts']['external_data'], 'all external tensors required')
    records = [pack['snapshot'], pack['export_manifest']]
    for name, value in pack['artifacts'].items():
        if name != 'ort_dll':
            records.extend(value if name == 'external_data' else [value])
    paths = [verify_binding(r, manifest_path.parent) for r in records]
    paths.append(verify_binding(pack['artifacts']['ort_dll'], manifest_path.parent, ort_dll=True))
    paths.append(manifest_path)
    return pack, paths


def create_job(binary, output=JOB, manifest=PACK):
    output = local(output)
    require(not output.exists(), 'job already exists')
    pack, _ = pack_bindings(manifest)
    value = {'schema': 'p4-rust-pilot-job-v1', 'manifest': manifest,
             'snapshot': pack['snapshot']['identity'], 'binary': binary,
             'policy': POLICY, 'raw_directory': RAW, 'output': RECEIPT}
    save_new(output, value)
    return value


def validate_job(job):
    require(job['schema'] == 'p4-rust-pilot-job-v1' and job['policy'] == POLICY, 'job contract')
    require(local(job['binary']).is_file(), 'runtime binary missing')
    pack_bindings(job['manifest'])


def source_ids(rows):
    return [(r['entry']['kind'], r['entry']['namespace'], r['entry']['value']) for r in rows]


def fusion_ids(lexical, dense, pins):
    ranks = {}
    for branch in (lexical, dense):
        seen = set()
        for rank, key in enumerate(source_ids(branch), 1):
            if key not in seen:
                ranks[key] = ranks.get(key, 0.0) + 1.0 / (60 + rank)
                seen.add(key)
    pinned = set(source_ids(pins))
    return sorted(set(ranks) | pinned,
                  key=lambda k: (k not in pinned, 0 if k in pinned else -ranks[k], k))[:100]


def validate_response(response, case, lexical):
    require(response['status'] == 'PASS' and response['case_id'] == case['case_id'] and
            response['query'] == case['query'], 'response case/status')
    require(response['identity_status'] == 'not_asserted' and
            response['promoted_identities'] == [] and response['canonical'] is None and
            response['entity_tag'] is None, 'identity promotion')
    require(response['contract'] == fixed_contract(), 'response contract')
    require(response['lexical_hits'] == lexical['raw_hits'] and
            response['trusted_pins'] == lexical['trusted_pins'], 'Rust lexical/pin mismatch')
    expected = fusion_ids(lexical['raw_hits'], response['dense_hits'], lexical['trusted_pins'])
    require(source_ids(response['hybrid']) == expected, 'actual Rust fused IDs mismatch')
    require(source_ids(response['candidates']) == expected, 'actual Rust candidate IDs mismatch')
    require([r['hybrid_rank'] for r in response['hybrid']] == list(range(1, len(expected) + 1)),
            'Rust hybrid ranks')
    timings = response['timings_ms']
    require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in timings.values()),
            'invalid timings')
    require(timings['total'] <= POLICY['resident_max_ms'], 'resident query budget')


def vector_diagnostics(actual, reference):
    require(len(actual) == len(reference) == 1024 and
            all(math.isfinite(float(v)) for v in [*actual, *reference]), 'invalid vectors')
    norm = math.sqrt(sum(float(v) ** 2 for v in actual))
    ref_norm = math.sqrt(sum(float(v) ** 2 for v in reference))
    require(norm > 0 and ref_norm > 0, 'zero vector')
    error = max(abs(float(a) - float(b)) for a, b in zip(actual, reference, strict=True))
    cosine = sum(float(a) * float(b) for a, b in zip(actual, reference, strict=True)) / (norm * ref_norm)
    return {'max_component_error': error, 'norm': norm, 'cosine': cosine,
            'pass': error <= 1e-4 and abs(norm - 1) <= 1e-5 and cosine >= .99999}


class Driver:
    """Bounded line reader on a daemon thread works with Windows subprocess pipes."""
    def __init__(self, command, stderr):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=stderr, cwd=ROOT)
        self.lines = queue.Queue(maxsize=2)
        def reader():
            while True:
                raw = self.process.stdout.readline(MAX_BYTES + 1)
                self.lines.put(raw)
                if not raw or len(raw) > MAX_BYTES:
                    break
        threading.Thread(target=reader, daemon=True).start()

    def receive(self, timeout):
        try:
            raw = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError('Rust response timeout; no retry') from exc
        require(raw and raw.endswith(b'\n') and len(raw) <= MAX_BYTES, 'EOF/oversize JSONL response')
        return ann.selection.parse(raw.decode('utf-8')), len(raw)

    def request(self, case):
        data = {'case_id': case['case_id'], 'query': case['query'], 'limit': 100,
                'include_vector': True}
        self.process.stdin.write((json.dumps(data, ensure_ascii=False) + '\n').encode('utf-8'))
        self.process.stdin.flush()
        return self.receive(POLICY['query_timeout_seconds'])

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        self.process.stdin.close()
        self.process.stdout.close()


def evaluation_inputs():
    """Load ordinary benchmark data; historical selection receipts are not authority."""
    job = load(local('configs/p4-pilot-score-job.json'))
    get = lambda key: load(local(job[key]))
    with local(job['corpus']).open(encoding='utf8') as stream:
        documents = [ann.selection.parse(line) for line in stream if line.strip()]
    bindings = {key: sha(local(job[key])) for key in
                ('gold', 'corpus', 'lexical', 'dense_a', 'dense_b', 'model_summary', 'config')}
    return (get('gold'), documents, get('lexical'), {'a': get('dense_a'), 'b': get('dense_b')},
            get('model_summary'), get('config'), bindings)


def qualify(job, receipt):
    import numpy as np

    inputs = evaluation_inputs()
    cases = sorted(inputs[0]['cases'], key=lambda c: c['case_id'])
    require(len(cases) == 120 and len({c['case_id'] for c in cases}) == 120, '120 unique cases')
    reference = load(local(f'{ann.RETRY_RAW}/{SELECTED}.json'))
    ref_cases = reference['queries']
    require([r['case_id'] for r in ref_cases] == [c['case_id'] for c in cases], 'reference ordering')
    onnx = load(local(ann.INPUTS['ranks']))
    require(onnx['case_order'] == [c['case_id'] for c in cases], 'ONNX vector ordering')
    vectors = np.load(local(ann.INPUTS['queries']), mmap_mode='r', allow_pickle=False)
    require(vectors.shape == (120, 1024), 'ONNX query matrix')
    lexical = ann.score.case_map(inputs[2]['cases'])
    raw = local(job['raw_directory'])
    raw.mkdir(parents=True, exist_ok=False)
    driver = None
    try:
        with (raw / 'stderr.log').open('xb') as stderr:
            start = time.perf_counter()
            driver = Driver([str(local(job['binary'])), str(local(job['snapshot'])),
                             str(local(job['manifest']))], stderr)
            receipt['opened'], _ = driver.receive(POLICY['startup_timeout_seconds'])
            receipt['startup_wall_ms'] = (time.perf_counter() - start) * 1000
            require(receipt['opened']['event'] == 'opened' and
                    receipt['opened']['retries'] == 0, 'driver startup')
            for phase, rows in (('warmups', cases[:2]), ('formal', cases)):
                for i, case in enumerate(rows):
                    row = {'case_id': case['case_id'], 'status': 'FAIL'}
                    receipt[phase].append(row)
                    try:
                        start = time.perf_counter()
                        response, size = driver.request(case)
                        row.update(wall_ms=(time.perf_counter() - start) * 1000, response_bytes=size)
                        save_new(raw / f'{phase}-{case["case_id"]}.json', response)
                        validate_response(response, case, lexical[case['case_id']])
                        row['timings_ms'] = response['timings_ms']
                        require(row['wall_ms'] <= 5000, 'resident wall budget')
                        if phase == 'formal':
                            row['vector'] = vector_diagnostics(response['vector'], vectors[i])
                            row['overlap'] = ann.recall_rows(response['dense_hits'], ref_cases[i]['hits'])
                            require(row['vector']['pass'], 'vector numerical agreement')
                        row['status'] = 'PASS'
                    except Exception as exc:
                        row['error'] = f'{type(exc).__name__}: {exc}'
                        raise  # no retry or replacement of failed samples
            driver.process.stdin.close()
            require(driver.process.wait(timeout=10) == 0, 'driver exit failure')
    finally:
        if driver is not None:
            driver.close()
    actual_cases = []
    for case in cases:
        response = load(raw / f'formal-{case["case_id"]}.json')
        actual_cases.append({**next(c for c in onnx['cases'] if c['case_id'] == case['case_id']),
                             'hits': response['dense_hits']})
    # The frozen scorer reconstructs hybrid; validate_response independently proved
    # those exact ordered IDs were returned by Rust (including pin and tie ordering).
    actual, details = ann.score_cases(inputs, actual_cases)
    baseline, _ = ann.score_cases(inputs, [{**c, 'hits': r['hits']}
                                for c, r in zip(onnx['cases'], ref_cases, strict=True)])
    receipt['quality'] = ann.quality.quality(actual['metrics'], baseline['metrics'])
    receipt['overlap'] = ann.approximation([r['overlap'] for r in receipt['formal']])
    wall = sorted(r['wall_ms'] for r in receipt['formal'])
    total = sorted(r['timings_ms']['total'] for r in receipt['formal'])
    receipt['latency'] = {'wall_p95_ms': wall[math.ceil(.95 * len(wall)) - 1],
                          'resident_p95_ms': total[math.ceil(.95 * len(total)) - 1],
                          'wall_max_ms': max(wall), 'resident_max_ms': max(total)}
    save_new(raw / 'quality-details.json', details)
    require(not receipt['quality']['failures'], 'hybrid v2/regression quality gate')
    require(all(v['pass'] for v in receipt['overlap'].values()), 'dense overlap gate')
    require(receipt['latency']['wall_p95_ms'] <= 1000 and
            receipt['latency']['resident_p95_ms'] <= 1000, 'resident p95 budget')


def run(job_path):
    job_path = local(job_path)
    job = load(job_path)
    output = local(job['output'])
    require(not output.exists(), 'receipt already exists')
    # Validate assets once per run; output diagnostics cannot authorize a product.
    receipt = {'schema': 'p4-rust-pilot-v1', 'status': 'FAIL', 'retries': 0,
               'warmups': [], 'formal': [], 'policy': POLICY,
               'memory': {'status': 'NOT_AVAILABLE', 'reason': 'optional; psutil not required'}}
    try:
        validate_job(job)
        qualify(job, receipt)
        receipt['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001
        receipt['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        for phase, total in (('warmups', 2), ('formal', 120)):
            rows = receipt[phase]
            receipt[phase + '_counts'] = {'attempted': len(rows),
                'failed': sum(r['status'] != 'PASS' for r in rows), 'not_run': total - len(rows)}
        save_new(output, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('pack', help='generate-only activation; hashes, no inference')
    pack.add_argument('--snapshot', required=True)
    pack.add_argument('--ort-dll', required=True)
    pack.add_argument('--output', default=PACK)
    job = commands.add_parser('job', help='create ordinary optional pilot evaluation configuration')
    job.add_argument('--binary', required=True)
    job.add_argument('--manifest', default=PACK)
    job.add_argument('--output', default=JOB)
    execute = commands.add_parser('run', help='run optional pilot quality evaluation')
    execute.add_argument('--job', default=JOB)
    args = parser.parse_args(argv)
    if args.command == 'pack':
        build_pack(args.snapshot, args.ort_dll, args.output)
    elif args.command == 'job':
        create_job(args.binary, args.output, args.manifest)
    else:
        return 0 if run(args.job)['status'] == 'PASS' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
