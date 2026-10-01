"""One authorized local FP32 legacy ONNX export; never run passage embeddings.

Consume the actual p4_query_reference PASS manifest and its three bound payloads.
The manifest digest below is an explicit authorization addendum, not a change to
any frozen input. Historical query receipts are not a substitute.
No inference dependencies are imported until all read-only provenance gates pass.
Failed output directories are evidence and may never be reused.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import platform
import sys
from pathlib import Path

from tools import p4_cpu_representation as cpu
from tools import p4_exact_pilot as exact
from tools import p4_query_reference as producer

REFERENCE_MANIFEST_SHA256 = 'fe334da082e67eaf3ff967c316ea2cde365a8a484f2c5c1c54a014993d706d73'
REFERENCE_VECTORS_SHA256 = 'b066abc933023b0980dc286f9c2c82e92eb3b9905406b5472176fb6e47c0817a'
REFERENCE_SCOPE = ('new authorized native representation-validation reference; '
                   'not historical pilot evidence')
ROW_COUNT = 52664
SAMPLE_ROWS = tuple(i * 52663 // 127 for i in range(128))


def validate_contract(contract, job, reference):
    expected = {
        'schema': 'p4-onnx-representation-contract-v1',
        'repository': cpu.B_REPOSITORY, 'revision': cpu.B_REVISION,
        'dimension': 1024, 'pooling': 'cls', 'normalize': True,
        'query_prefix': '', 'passage_prefix': '', 'dtype': 'float32',
        'quantization': 'none', 'provider': 'CPUExecutionProvider', 'threads': 8,
        'exporter': 'torch.onnx.export', 'dynamo': False, 'opset': 17,
        'external_data': True, 'attention_implementation': 'eager',
        'export_attempt_limit': 1, 'fallback_exporter': None,
        'query_reference_scope': REFERENCE_SCOPE,
        'queries': 'all 120 frozen cases sorted by case_id',
        'passage_sample': {
            'count': 128, 'row_rule': 'floor(i*(52664-1)/(128-1)) for i=0..127',
            'reference': 'build/p4/continuation-dense-b-v1/vectors.npy',
            'batch_sizes': [1, 8]},
    }
    for key, value in expected.items():
        exact.require(key in contract and type(contract[key]) is type(value) and
                      contract[key] == value, f'unsupported export contract: {key}')
    exact.require(type(job['threads']) is int and job['threads'] == 8, 'eight CPU threads required')
    exact.require(exact.local(contract['query_reference']) == Path(reference).resolve(),
                  'reference path differs from frozen contract')
    exact.require(exact.local(contract['passage_sample']['reference']) ==
                  exact.local(job['index']) / 'vectors.npy', 'frozen index path mismatch')


def verify_reference(path, contract, job, prepared):
    """Verify the producer's receipt; return every bound path for export snapshots."""
    import numpy as np

    path = Path(path).resolve()
    exact.bound(path, REFERENCE_MANIFEST_SHA256)
    reference = exact.load(path)
    exact.require(reference['status'] == 'PASS', 'new PASS query reference required')
    exact.require(reference['authorization_scope'] == producer.SCOPE and
                  contract['query_reference_scope'] == REFERENCE_SCOPE,
                  'historical reference forbidden')
    for key in ('historical_pilot', 'native_qualification_retry', 'selection_rerun', 'ranking'):
        exact.require(reference[key] is False, f'reference {key} forbidden')
    for key, value in (('warmups', 0), ('attempted_queries', 120), ('completed_queries', 120)):
        exact.require(type(reference[key]) is int and reference[key] == value,
                      f'reference {key} mismatch')
    model, native_contract, chunks_manifest, cases = prepared
    provenance = exact.provenance(job, model, chunks_manifest)
    exact.require(reference['frozen_provenance'] == provenance, 'reference provenance mismatch')
    for key in ('model_inventory_sha256', 'tokenizer_inventory_sha256'):
        exact.require(reference[key] == provenance[key], f'reference {key} mismatch')
    exact.require(reference['shape'] == [120, 1024] and reference['dtype'] == 'float32',
                  'reference vector metadata mismatch')
    payloads = reference['payload_sha256']
    exact.require(set(payloads) == {'vectors.npy', 'cases.json', 'inputs.json'},
                  'reference payload set mismatch')
    exact.require(reference['vectors_sha256'] == payloads['vectors.npy'] ==
                  REFERENCE_VECTORS_SHA256, 'reference vector digest mismatch')
    paths = [path]
    for name, digest in payloads.items():
        payload = path.parent / name
        exact.require(not payload.is_symlink(), 'reference payload symlink forbidden')
        exact.bound(payload, digest)
        paths.append(payload)
    inputs = exact.load(path.parent / 'inputs.json')
    validation = {'status': 'PASS', 'snapshot_sha256': exact.canonical_hash(inputs)}
    exact.require(reference['input_validations'] == {'before': validation, 'after': validation},
                  'reference input validations mismatch')
    # Reconstruct the producer's read-only snapshot, including selection inputs and
    # all four source dependencies. This never loads a model or reruns selection.
    expected_inputs = producer.snapshot(exact.local(producer.JOB), job, prepared)
    exact.require(inputs == expected_inputs, 'reference frozen input snapshot mismatch')
    exact.require(reference['code_sha256'] == inputs['code_sha256'], 'reference code mismatch')
    for binding in inputs['inputs'].values():
        source = exact.local(binding['path'])
        exact.bound(source, binding['sha256'])
        paths.append(source)
    for name, digest in reference['code_sha256'].items():
        source = exact.local(name)
        exact.bound(source, digest)
        paths.append(source)
    for record in model['obtained_receipt']['files']:
        asset = exact.local(model['asset_directory']) / record['path']
        exact.bound(asset, record['sha256'])
        paths.append(asset)
    ordered = exact.load(path.parent / 'cases.json')
    exact.require(len(cases) == len(ordered) == 120 and
                  len({case['case_id'] for case in cases}) == 120 and
                  cases == sorted(cases, key=lambda case: case['case_id']),
                  'reference case count/order mismatch')
    for row, (case, record) in enumerate(zip(cases, ordered, strict=True)):
        exact.require(type(record['row']) is int and record['row'] == row and
                      record['case_id'] == case['case_id'] and
                      record['query_text_sha256'] == hashlib.sha256(
                          case['query'].encode('utf-8')).hexdigest(),
                      'reference query identity mismatch')
        exact.require(type(record['actual_tokens']) is int and
                      0 < record['actual_tokens'] <= native_contract['max_sequence_tokens'],
                      'reference token count mismatch')
    exact.require(reference['versions_sha256'] == exact.canonical_hash(reference['versions']),
                  'reference versions mismatch')
    encoder = reference['encoder']
    for key, value in (('provider', 'huggingface/torch'), ('actual_device', 'cpu'),
                       ('requested_device', 'cpu'), ('actual_dtype', 'torch.float32'),
                       ('threads', 8), ('interop_threads', 8)):
        exact.require(type(encoder[key]) is type(value) and encoder[key] == value,
                      f'reference encoder {key} mismatch')
    vectors = np.load(path.parent / 'vectors.npy', mmap_mode='r', allow_pickle=False)
    exact.require(list(vectors.shape) == [120, 1024], 'reference vector count mismatch')
    exact.validate_vectors(vectors, 1024)
    del vectors
    return paths


def select_passages(job, native_contract, chunks_manifest, raw, tokenizer):
    """Stream the frozen rows, retaining only 128 texts, never computing vectors."""
    wanted = set(SAMPLE_ROWS)
    selected = []
    count = 0
    with exact.local(job['chunks']).open('rb') as stream:
        for row_index, line in enumerate(stream):
            count += 1
            if row_index not in wanted:
                continue
            row = json.loads(line)
            text = row['text']
            text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
            exact.require(text_hash == row['text_sha256'], 'sample text hash mismatch')
            encoded, counts = exact.checked_tokens(
                raw, tokenizer, [text], native_contract['passage_prefix'],
                native_contract['max_sequence_tokens'])
            exact.require(counts[0] == row['inference_token_count'], 'sample token count mismatch')
            exact.require(row['tokenizer_inventory_sha256'] ==
                          chunks_manifest['tokenizer_inventory_sha256'], 'sample tokenizer mismatch')
            selected.append({'row_index': row_index, 'chunk_id': row['chunk_id'],
                             'row_sha256': exact.canonical_hash(row),
                             'line_sha256': hashlib.sha256(line).hexdigest(),
                             'text': text, 'text_sha256': text_hash,
                             'input_ids': encoded['input_ids'][0],
                             'attention_mask': encoded['attention_mask'][0],
                             'token_sha256': exact.canonical_hash(encoded['input_ids'][0]),
                             'inference_token_count': counts[0]})
    exact.require(count == ROW_COUNT == chunks_manifest['chunk_count'], 'frozen row count mismatch')
    exact.require([r['row_index'] for r in selected] == list(SAMPLE_ROWS), 'sample coverage mismatch')
    return {'schema': 'p4-onnx-passage-sample-v2', 'count': 128,
            'row_rule': 'floor(i*52663/127), i=0..127',
            'row_hash_encoding': 'canonical JSON; line_sha256 includes original newline',
            'token_hash_encoding': 'canonical JSON input_ids including special tokens',
            'chunks_sha256': chunks_manifest['chunks_sha256'], 'rows': selected}


def load_model(model, threads):
    import torch
    from transformers import AutoModel

    torch.set_num_threads(threads)
    torch.set_num_interop_threads(threads)
    # BGE-M3's obtained local weights are pytorch_model.bin, as in LocalEncoder.
    base = AutoModel.from_pretrained(
        str(exact.local(model['asset_directory'])), local_files_only=True,
        trust_remote_code=False, weights_only=True, use_safetensors=False,
        torch_dtype=torch.float32, attn_implementation='eager').to('cpu').eval()
    exact.require(base.config._attn_implementation == 'eager', 'eager attention required')
    exact.require(all(p.dtype == torch.float32 and p.device.type == 'cpu'
                      for p in base.parameters()), 'FP32 CPU weights required')

    class NormalizedCLS(torch.nn.Module):
        def __init__(self, encoder):
            super().__init__()
            self.encoder = encoder

        def forward(self, input_ids, attention_mask):
            hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
            return torch.nn.functional.normalize(hidden[:, 0], p=2, dim=1)

    return NormalizedCLS(base).eval()


def export_once(model, sample, tokenizer, path):
    import torch

    # Require explicit support: older exporters must fail, not silently ignore kwargs.
    parameters = inspect.signature(torch.onnx.export).parameters
    exact.require({'dynamo', 'external_data', 'opset_version', 'do_constant_folding'} <=
                  set(parameters), 'exporter lacks frozen legacy/external-data options')
    row = sample['rows'][0]
    batch = tokenizer.pad({'input_ids': [row['input_ids']],
                           'attention_mask': [row['attention_mask']]},
                          padding=True, return_tensors='pt')
    inputs = tuple(batch[key].to('cpu') for key in ('input_ids', 'attention_mask'))
    with torch.no_grad():
        torch.onnx.export(
            model, inputs, str(path), input_names=['input_ids', 'attention_mask'],
            output_names=['embeddings'],
            dynamic_axes={'input_ids': {0: 'batch', 1: 'sequence'},
                          'attention_mask': {0: 'batch', 1: 'sequence'},
                          'embeddings': {0: 'batch'}},
            dynamo=False, opset_version=17, external_data=True,
            do_constant_folding=True, export_params=True)


def check_model(path):
    import onnx

    # A path, not a loaded proto/BytesIO, is required for the >2GB model.
    onnx.checker.check_model(str(path))


def versions():
    return {'python': sys.version, 'platform': platform.platform(),
            **{name: importlib.metadata.version(name)
               for name in ('torch', 'transformers', 'tokenizers', 'onnx', 'numpy')}}


def snapshot(paths):
    return {str(Path(p).resolve()): exact.sha(p) for p in paths}


def inventory(directory):
    records = []
    for path in sorted(directory.rglob('*')):
        exact.require(not path.is_symlink(), 'export output symlink forbidden')
        if path.is_file():
            records.append({'path': path.relative_to(directory).as_posix(),
                            'size': path.stat().st_size, 'sha256': exact.sha(path)})
    exact.require(any(r['path'] == 'model.onnx' and r['size'] > 0 for r in records),
                  'export produced no model')
    return records


def run(job_path, contract_path, reference_path, output):
    output = Path(output)
    # Never write failure evidence into somebody else's existing output directory.
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(f'cannot reserve exclusive output: {exc}', file=sys.stderr)
        return 1
    phase, attempts = 'validation', 0
    try:
        initial = snapshot([job_path, contract_path, reference_path, Path(__file__),
                            Path(cpu.__file__), Path(exact.__file__)])
        job, contract = exact.load(job_path), exact.load(contract_path)
        validate_contract(contract, job, reference_path)
        prepared = cpu.validate(job)
        model, native_contract, chunks_manifest, _ = prepared
        reference_paths = verify_reference(reference_path, contract, job, prepared)
        index_path = exact.local(job['index']) / 'index.json'
        index = exact.load(index_path)
        exact.require(index['shape'] == [ROW_COUNT, 1024] and index['dtype'] == 'float32',
                      'frozen passage vector metadata mismatch')
        exact.require(index['provenance'] == exact.provenance(job, model, chunks_manifest),
                      'frozen passage provenance mismatch')
        vector_path = exact.local(contract['passage_sample']['reference'])
        exact.bound(vector_path, index['vectors_sha256'])
        paths = reference_paths + [index_path, vector_path]
        paths += [exact.local(job[k]) for k in ('chunks', 'chunks_manifest', 'gold', 'corpus',
                                               'summary', 'authorization', 'selection_receipt')]
        paths += [exact.local(model['contract']['path'])]
        paths += [exact.local(model['asset_directory']) / r['path']
                  for r in model['obtained_receipt']['files']]
        bound_inputs = snapshot(paths)
        bound_inputs.update(initial)
        phase = 'passage_sample'
        raw, tokenizer = exact.frozen_tokenizers(exact.local(model['asset_directory']))
        sample = select_passages(job, native_contract, chunks_manifest, raw, tokenizer)
        sample['reference'] = {'path': contract['passage_sample']['reference'],
                               'sha256': index['vectors_sha256']}
        sample_path = output / 'passage-sample.json'
        exact.save(sample_path, sample)
        sample_hash = exact.sha(sample_path)
        dependencies = versions()
        phase = 'model_load'
        wrapper = load_model(model, job['threads'])
        phase, attempts = 'export', 1
        export_once(wrapper, sample, tokenizer, output / 'model.onnx')
        phase = 'onnx_checker'
        check_model(output / 'model.onnx')
        phase = 'final_verification'
        files = inventory(output)
        exact.require(snapshot(bound_inputs) == bound_inputs, 'inputs changed during export')
        exact.require(exact.sha(sample_path) == sample_hash, 'passage sample changed during export')
        exact.require(cpu.validate(job) == prepared, 'original model/input validation changed')
        verify_reference(reference_path, contract, job, prepared)
        exact.save(output / 'manifest.json', {
            'schema': 'p4-onnx-export-v2', 'status': 'PASS',
            'scope': 'representation export only; not numerical/retrieval/performance qualification',
            'repository': model['repository'], 'revision': model['revision'],
            'provenance': exact.provenance(job, model, chunks_manifest),
            'contract': contract, 'export_attempts': attempts, 'exporter': 'torch.onnx.export',
            'dynamo': False, 'opset': 17, 'external_data': True,
            'do_constant_folding': True, 'dtype': 'float32', 'device': 'cpu',
            'attention_implementation': 'eager', 'dependencies': dependencies,
            'input_sha256': bound_inputs, 'files': files,
            'passage_sample_sha256': sample_hash, 'onnx_checker': 'PASS'})
        return 0
    # Preserve partial export as failure evidence; never retry or fall back.
    except Exception as exc:  # noqa: BLE001
        exact.save(output / 'failure.json', {
            'schema': 'p4-onnx-export-v2', 'status': 'FAIL', 'phase': phase,
            'export_attempts': attempts, 'error': f'{type(exc).__name__}: {exc}'})
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('job', 'contract', 'reference', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.job, args.contract, args.reference, args.output_dir)


if __name__ == '__main__':
    raise SystemExit(main())
