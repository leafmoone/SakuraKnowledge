"""Static source receipts and final immutable-input rehash; no native reload."""
import hashlib
import json
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path
D = Path(__file__).resolve().parent
ROOT = D.parents[2]
sys.path.insert(0, str(ROOT))
from tools import p4_full_build as b


def main():
    before = json.loads((D/'baseline.json').read_bytes())
    after = {n: {'bytes':(ROOT/n).stat().st_size, 'sha256':b.full.exact.sha(ROOT/n)} for n in before['before']}
    assert after == before['before']
    b.validate_partial_preservation(root=ROOT, new_absent=False)
    assert not (ROOT/b.RETRY_OUTPUT/'manifest.json').exists()
    probe = json.loads((D/'full-buffer-probe.json').read_bytes())
    wheel = json.loads((D/'wheel-match.json').read_bytes())
    url = 'https://raw.githubusercontent.com/unum-cloud/usearch/v2.26.2/include/usearch/index_plugins.hpp'
    data = urllib.request.urlopen(url).read()
    with (D/'upstream-index_plugins.hpp').open('xb') as f:
        f.write(data)
    assert b'f32_k = 11' in data
    h = bytes.fromhex(before['raw_serialization']['dense_header_hex'])
    header = {'matrix_rows':1366520,'matrix_row_BYTES':4096,'matrix_dimensions_prefix_bytes':8,
              'matrix_end':5597265928,'magic':h[:7].decode(),'version':list(struct.unpack_from('<HHH',h,7)),
              'metric_code':h[13],'scalar_code':h[14],'scalar':'f32 (index_plugins.hpp enum f32_k=11)',
              'key_code':h[15],'slot_code':h[16],
              'present_deleted_dimensions':list(struct.unpack_from('<QQQ',h,17)),
              'boundary':'Header and total size alone do not establish graph integrity; native buffer and audits are separate'}
    crate = Path('C:/Users/PC/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/usearch-2.26.2')
    paths = [ROOT/'rust/Cargo.lock', ROOT/'rust/src/semantic.rs',crate/'build.rs',crate/'rust/lib.rs',crate/'rust/lib.cpp',
             crate/'include/usearch/index.hpp',crate/'include/usearch/index_dense.hpp',
             ROOT/'build/p4-full-attempt2-check-target/release/deps/usearch-04fd3a8ecbfc4116.d',
             ROOT/'build/p4-full-attempt2-check-target/release/build/usearch-2bd54f583dc4e5a8/output']
    static = {str(p): {'bytes':p.stat().st_size,'sha256':b.full.exact.sha(p)} for p in paths}
    snippets = {}
    for p in paths:
        lines = p.read_text('utf8').splitlines()
        needles = ('GetFileSize(', 'MapViewOfFile(', 'length_ = file_length', 'vectors matrix exceeds',
                   'memory_mapped_file_t', 'index.view(', 'checksum = "b43f3a7', 'cxx_build::bridge',
                   'rustc-link-lib=static=usearch','include/usearch/index.hpp')
        snippets[str(p)] = [{'line':i,'text':line[:800]} for i,line in enumerate(lines,1) if any(n in line for n in needles)]
    report = {'baseline_dev':'6780b8963ebbab7ca02e2bbc5976796e14f770e9',
              'UPSTREAM_SOURCE_DEFECT_CONFIRMED':'YES: v2.26.2 Windows memory_mapped_file_t uses GetFileSize(handle,NULL) low32 for mapping and length',
              'LOCAL_BINARY_MATCH':wheel['LOCAL_BINARY_MATCH'],
              'SOURCE_BINARY_REPRODUCIBLE_BUILD_MATCH':'NOT_ESTABLISHED; official wheel native bytes match, tag source is not build attestation',
              'LENGTH_TRUNCATION_OBSERVED':before['win32'],
              'READONLY_BUFFER_PROBE':probe,
              'INDEX_REUSE_STATUS':'READONLY_DIAGNOSTIC_OPEN_KEYS_AND_1200_VECTOR_MAPPING_QUALIFIED_ONLY; production reuse not authorized or implemented',
              'serialization_header':header,'rust_static_bindings':static,'rust_static_snippets':snippets,
              'rust_crate_checksum':'b43f3a7c8d3b100d53c1a34e9ce4cd76cc83627bdb4fcd035d4e82102778aeee',
              'rust_binary_match':'NOT_ESTABLISHED: dependency/build cache indicates compilation/link path only',
              'minimal_fix_proposal':'Use GetFileSizeEx with checked LARGE_INTEGER; on failure close handle; reject negative or size_t overflow; checked conversion feeds map length and length_. No change executed.',
              'source_enum':{'url':url,'sha256':hashlib.sha256(data).hexdigest()},
              'before_after_unchanged':True,'after':after,
              'original_continuation_status':'FAIL','manifest_created':False,'pack_sha256':None,
              'FULL_RUNTIME_QUALIFICATION':'NOT_RUN','FULL_QUALITY_ACCEPTANCE':'NOT_RUN','STOP_STATE':'WAITING_REVIEW'}
    with (D/'diagnostic-report.json').open('x',encoding='utf8') as f:
        json.dump(report,f,indent=2,ensure_ascii=False)
    print('ALL_INPUT_HISTORY_AUTH_RECEIPTS_INDEX_PARTIAL_PRODUCTS_UNCHANGED=PASS')
    print('REPORT_SHA256='+b.full.exact.sha(D/'diagnostic-report.json'))


if __name__ == '__main__':
    main()
