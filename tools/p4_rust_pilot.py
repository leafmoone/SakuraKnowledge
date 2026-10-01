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
RECEIPTS = {
    'ann': ann.RETRY_OUTPUT,
    'quality': ann.INPUTS['quality_receipt'],
    'cpu': ann.INPUTS['cpu_receipt'],
}
RECEIPT_HASHES = {
    'ann': '0a2f0d05a184c14e84ffa29d632e52c785b77c5095c679564ce1971ddb34fcd2',
    'quality': 'a74e3fb5fee45d6849e1e5030900ff00c6dd9378ce2fa1377d378a92af3e3d01',
    'cpu': '41da6e1ffab3568e9f94ec5e03c98dca72adabb5bd732c1a1bd7d18907df5264',
}
ANN_INPUT_HASHES = {
    'vectors': 'e3a8181933f4ee976a79e28ae978d07d5d6f5ab09b5124f2366953074bcb7261',
    'mapping': '8027c11f61ffcfb1a6d7cefbaff65e5ab3a0b2bd3b0c40b82517a4e434b4f2b2',
    'queries': '1c22703d7d0d8f191627554b1f14ac2081d738fe4c6a4d00bfea1532002e3757',
    'ranks': '6daad5b075411f18cb5847e6dd29315cef99a09e694b2048efa7bc3587a14f9e',
    'quality_receipt': RECEIPT_HASHES['quality'],
    'cpu_receipt': RECEIPT_HASHES['cpu'],
}
EXPORT_MANIFEST_SHA = 'b981d9c2b8f02691a200b9b88da8c778abcbaaaa3d49d0376f88590c89fbbb03'
DLL_SHA = '4fd859a7aeb657f256730a0cd5da8073a30806dd81c00a22bf25c87356baa847'
DLL_SIZE = 15355936
EXTERNAL_ORT_DLL = Path('C:/Users/PC/AppData/Local/Python/pythoncore-3.14-64/'
                        'Lib/site-packages/onnxruntime/capi/onnxruntime.dll')
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


def receipt_digest(inputs, path):
    """Historical receipts use absolute Windows paths; require a unique suffix."""
    matches = [digest for name, digest in inputs.items()
               if name.replace('\\', '/').endswith('/' + path)]
    require(len(matches) == 1, f'missing/ambiguous approved input: {path}')
    return matches[0]


def approved_receipts():
    records = {k: binding(v) for k, v in RECEIPTS.items()}
    for key, digest in RECEIPT_HASHES.items():
        require(records[key]['sha256'] == digest, f'unapproved {key} receipt')
    result = load(local(RECEIPTS['ann']))
    require(result['schema'] == 'p4-ann-v1-retry1' and result['status'] == 'PASS'
            and result['selected'] == SELECTED and result['input_validations'] ==
            {'before': 'PASS', 'after': 'PASS'}, 'approved ANN retry1 required')
    require(result['input_sha256_before'] == result['input_sha256_after'], 'ANN inputs changed')
    for key, digest in ANN_INPUT_HASHES.items():
        path = ann.INPUTS[key]
        require(receipt_digest(result['input_sha256_before'], path) == digest,
                f'unapproved ANN input: {key}')
        require(sha(local(path)) == digest, f'ANN input changed: {key}')
    return records, result


def quality_binding(path, pack_root, inputs):
    record = binding(path, pack_root)
    name = local(path).relative_to(ROOT).as_posix()
    require(record['sha256'] == receipt_digest(inputs, name),
            f'quality artifact changed: {name}')
    return record


def export_artifacts(directory, pack_root):
    """Inventory only: no ONNX parser/session and no tensor materialization."""
    manifest = load(directory / 'manifest.json')
    records = manifest['files']
    names = [r['path'] for r in records]
    require(len(names) == len(set(names)) and 'model.onnx' in names, 'export inventory')
    result = {}
    external = []
    for record in records:
        path = (directory / record['path']).resolve()
        require(path.is_relative_to(directory.resolve()), 'external tensor escapes export')
        verify_binding(record, directory)
        if record['path'] == 'model.onnx':
            result['model'] = binding(path, pack_root)
        elif record['path'] != 'passage-sample.json':
            external.append(binding(path, pack_root))
    require(external, 'missing external tensors')
    # Every existing export file must be accounted for, including all tensor shards.
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    require(actual == set(names) | {'manifest.json'}, 'unlisted export file')
    result['external_data'] = external
    return result


def build_pack(snapshot, ort_dll, output=PACK):
    output = local(output)
    require(not output.exists(), 'pack already exists')
    receipts, approved = approved_receipts()
    quality_inputs = load(local(RECEIPTS['quality']))['input_sha256']
    directory = local('build/p4/bge-onnx-v2')
    export_manifest = quality_binding(directory / 'manifest.json', output.parent, quality_inputs)
    require(export_manifest['sha256'] == EXPORT_MANIFEST_SHA, 'unapproved export manifest')
    artifacts = export_artifacts(directory, output.parent)
    paths = {'tokenizer': f'model/BAAI--bge-m3/{REVISION}/tokenizer.json',
             'ort_dll': ort_dll, 'index': 'build/p4/ann-v1-retry1/M16-Eadd256.usearch',
             'mapping': ann.INPUTS['mapping'], 'corpus': 'build/p4/continuation-pilot-v1.jsonl',
             'lexical': 'build/p4/continuation-lexical-v1.sqlite'}
    artifacts.update({k: binding(v, output.parent, ort_dll=k == 'ort_dll')
                      for k, v in paths.items()})
    for key in ('tokenizer', 'corpus'):
        artifacts[key] = quality_binding(paths[key], output.parent, quality_inputs)
    require(artifacts['mapping']['sha256'] == ANN_INPUT_HASHES['mapping'],
            'unapproved ANN mapping')
    require(artifacts['ort_dll']['sha256'] == DLL_SHA and
            artifacts['ort_dll']['size'] == DLL_SIZE, 'unpinned ORT DLL')
    require(artifacts['lexical']['sha256'] == LEX_SHA, 'unpinned lexical sidecar')
    selected = next(b for b in approved['builds'] if b['M'] == 16 and b['Eadd'] == 256)
    require(selected['status'] == 'PASS' and
            artifacts['index']['sha256'] == selected['index_sha256'] and
            artifacts['index']['size'] == selected['index_bytes'], 'wrong selected index')
    with sqlite3.connect(local(paths['lexical']).as_uri() + '?mode=ro', uri=True) as conn:
        metadata = json.loads(conn.execute('SELECT value FROM metadata').fetchone()[0])
    snap = binding(snapshot, output.parent)
    snap['identity'] = local(snapshot).relative_to(ROOT).as_posix()
    for name, record in (('snapshot', snap), ('corpus', artifacts['corpus'])):
        require(all(metadata[name][k] == record[k] for k in ('sha256', 'size')),
                f'lexical {name} binding mismatch')
    value = {'schema': 'p4-rust-semantic-pack-v1', 'pack_version': 'rust-semantic-pilot-v1',
             'snapshot': snap, 'contract': fixed_contract(), 'lexical_metadata': metadata,
             'artifacts': artifacts, 'approved_receipts': receipts,
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
    paths += [verify_binding(r) for r in pack['approved_receipts'].values()]
    paths.append(manifest_path)
    return pack, paths


def freeze_job(binary, output=JOB, manifest=PACK):
    output = local(output)
    require(not output.exists(), 'job already exists')
    pack, paths = pack_bindings(manifest)
    approved_receipts()
    score_job = load(local(ann.selection.JOB))
    paths += [local(score_job[k]) for k in ann.selection.BINDINGS.values()]
    paths += [local(p) for p in (ann.selection.JOB, ann.selection.CONFIG, ann.selection.SOURCE,
                               ann.RETRY_CONFIG, ann.INPUTS['queries'], ann.INPUTS['ranks'],
                               f'{ann.RETRY_RAW}/{SELECTED}.json')]
    # Freeze all Python scoring dependencies and Rust implementation/build inputs.
    paths += list((ROOT / 'tools').glob('p4_*.py'))
    paths += list((ROOT / 'rust/src').rglob('*.rs'))
    paths += [ROOT / 'rust/Cargo.toml', ROOT / 'rust/Cargo.lock', local(binary)]
    frozen = {(p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix()):
              sha(p) for p in sorted(set(paths))}
    value = {'schema': 'p4-rust-pilot-job-v1', 'manifest': manifest,
             'snapshot': pack['snapshot']['identity'], 'binary': binary,
             'binary_sha256': sha(local(binary)), 'code_sha': subprocess.check_output(
                 ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
             'policy': POLICY, 'frozen_sha256': frozen, 'raw_directory': RAW, 'output': RECEIPT}
    save_new(output, value)
    return value


def check_frozen(job):
    require(job['schema'] == 'p4-rust-pilot-job-v1' and job['policy'] == POLICY, 'job contract')
    require(sha(local(job['binary'])) == job['binary_sha256'], 'binary changed')
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
            == job['code_sha'], 'code commit changed')
    for name, digest in job['frozen_sha256'].items():
        require(sha(read_artifact(name, ort_dll=True)) == digest, f'frozen input changed: {name}')


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


def qualify(job, receipt):
    import numpy as np

    inputs = ann.quality.score_inputs()
    cases = sorted(inputs[0]['cases'], key=lambda c: c['case_id'])
    require(len(cases) == 120 and len({c['case_id'] for c in cases}) == 120, '120 unique cases')
    reference = load(local(f'{ann.RETRY_RAW}/{SELECTED}.json'))
    require(reference['candidate']['status'] == 'PASS', 'selected raw status')
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
    for label, mode in [('ANN_DENSE_B', 'EXACT_DENSE_MODEL_B'), ('ANN_HYBRID_B', 'RRF_HYBRID_MODEL_B')]:
        require(baseline['metrics'][mode] == reference['candidate']['quality']['metrics'][label],
                'selected Python ANN scoring reproduction')
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
    receipt = {'schema': 'p4-rust-pilot-v1', 'status': 'FAIL', 'retries': 0,
               'warmups': [], 'formal': [], 'job_sha256': sha(job_path),
               'policy': POLICY, 'bindings_before': 'NOT_COMPLETED', 'bindings_after': 'NOT_COMPLETED',
               'memory': {'status': 'NOT_AVAILABLE', 'reason': 'optional; psutil not required'}}
    try:
        check_frozen(job)
        receipt['bindings_before'] = 'PASS'
        qualify(job, receipt)
        receipt['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001
        receipt['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        try:
            check_frozen(job)
            require(sha(job_path) == receipt['job_sha256'], 'job changed during run')
            receipt['bindings_after'] = 'PASS'
        except Exception as exc:  # noqa: BLE001
            receipt.update(status='FAIL', bindings_after='FAIL', immutable_error=str(exc))
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
    freeze = commands.add_parser('freeze', help='create job to review/freeze before real run')
    freeze.add_argument('--binary', required=True)
    freeze.add_argument('--manifest', default=PACK)
    freeze.add_argument('--output', default=JOB)
    execute = commands.add_parser('run', help='explicit authorized qualification only')
    execute.add_argument('--job', default=JOB)
    args = parser.parse_args(argv)
    if args.command == 'pack':
        build_pack(args.snapshot, args.ort_dll, args.output)
    elif args.command == 'freeze':
        freeze_job(args.binary, args.output, args.manifest)
    else:
        return 0 if run(args.job)['status'] == 'PASS' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
