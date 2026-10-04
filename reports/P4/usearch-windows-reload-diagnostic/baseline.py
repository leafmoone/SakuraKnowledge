"""Read-only baseline, Win32 lengths, and version-tag source acquisition. No native reload."""
import ctypes
import hashlib
import importlib.metadata
import json
import struct
import sys
import urllib.request
from pathlib import Path
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[3]
D = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from tools import p4_full_build as b
import usearch.compiled as native


def sha(p):
    return b.full.exact.sha(p)


def main():
    b.validate_partial_preservation(root=ROOT, new_absent=False)
    p = ROOT / b.RETRY_OUTPUT / 'vectors.usearch'
    assert p.stat().st_size == 5800312336
    assert sha(p) == '7a1f9da2983fb3e92aae336f64967f116b917ec8c4d91526eaf6f99498b09b10'
    names = list(b.ATTEMPT2_HISTORY) + [v['path'] for v in b.ATTEMPT1_BINDINGS.values()]
    # Explicit preserved products and all continuation history/evidence.
    names += [b.RETRY_OUTPUT + '/' + n for n in b.PARTIAL_PRODUCTS]
    names += [b.RETRY_OUTPUT + '/vectors.usearch', b.RETRY_OUTPUT + '/continuation-receipt.json',
              'build/p4-attempt2-continuation-authorization-5f8ba761.json',
              'reports/P4/attempt2-continuation-command.json', 'reports/P4/attempt2-continuation-handoff.json']
    names = [n for n in names if isinstance(n, str) and (ROOT / n).is_file()]
    refs = {n: {'bytes': (ROOT/n).stat().st_size, 'sha256': sha(ROOT/n)} for n in sorted(set(names))}
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    k.GetFileSizeEx.restype = wintypes.BOOL
    k.GetFileSize.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetFileSize.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    h = k.CreateFileW(str(p), 0x80000000, 1, None, 3, 0x80, None)
    assert h != ctypes.c_void_p(-1).value
    try:
        full = ctypes.c_longlong()
        assert k.GetFileSizeEx(h, ctypes.byref(full))
        ctypes.set_last_error(0)
        low = k.GetFileSize(h, None)
        error = ctypes.get_last_error()
        assert full.value == p.stat().st_size and low == (full.value & 0xffffffff) and error == 0
    finally:
        assert k.CloseHandle(h)
    with p.open('rb') as f:
        prefix = f.read(8)
        rows, row_bytes = struct.unpack('<II', prefix)
        matrix_end = 8 + rows * row_bytes
        f.seek(matrix_end)
        head = f.read(128)
    dist = importlib.metadata.distribution('usearch')
    meta = {n: dist.read_text(n) for n in ('INSTALLER', 'WHEEL', 'direct_url.json')}
    sources = {}
    for name in ('include/usearch/index.hpp', 'include/usearch/index_dense.hpp', 'python/lib.cpp'):
        url = 'https://raw.githubusercontent.com/unum-cloud/usearch/v2.26.2/' + name
        data = urllib.request.urlopen(url).read()
        target = D / ('upstream-' + Path(name).name)
        with target.open('xb') as f:
            f.write(data)
        sources[name] = {'url': url, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    report = {'python': sys.version, 'pointer_bits': struct.calcsize('P')*8,
              'usearch_version': dist.version, 'native_path': native.__file__, 'native_sha256': sha(Path(native.__file__)),
              'installation_metadata': meta, 'source_tag': 'v2.26.2', 'sources': sources,
              'LOCAL_BINARY_MATCH': 'NOT_ESTABLISHED by version label alone', 'before': refs,
              'win32': {'stat': p.stat().st_size, 'GetFileSizeEx': full.value, 'GetFileSize_null_high': low, 'last_error': error},
              'raw_serialization': {'prefix_hex': prefix.hex(), 'rows_candidate': rows, 'row_bytes_candidate': row_bytes,
                                    'matrix_end_candidate': matrix_end, 'dense_header_hex': head.hex()},
              'full_native_probe_started': False}
    with (D/'baseline.json').open('x', encoding='utf8') as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: v for k,v in report.items() if k not in ('before', 'installation_metadata')}, indent=2))


if __name__ == '__main__':
    main()
