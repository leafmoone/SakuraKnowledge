"""Sparse actual-native regression runner; no original-index reads or writes."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
D = Path(__file__).resolve().parent
ROOT = D.parents[2]
BUILD = ROOT/'build/p4-usearch-native-fix'
K = ctypes.WinDLL('kernel32',use_last_error=True)
K.DeviceIoControl.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
K.DeviceIoControl.restype=wintypes.BOOL
K.GetCompressedFileSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)]
K.GetCompressedFileSizeW.restype=wintypes.DWORD

def sparse(p,size,writes):
    import msvcrt
    with p.open('xb') as f:
        returned=wintypes.DWORD()
        assert K.DeviceIoControl(msvcrt.get_osfhandle(f.fileno()),0x900c4,None,0,None,0,ctypes.byref(returned),None),ctypes.get_last_error()
        K.SetFilePointerEx.argtypes=[wintypes.HANDLE,ctypes.c_longlong,ctypes.POINTER(ctypes.c_longlong),wintypes.DWORD]
        K.SetFilePointerEx.restype=wintypes.BOOL
        K.SetEndOfFile.argtypes=[wintypes.HANDLE]
        K.SetEndOfFile.restype=wintypes.BOOL
        handle=msvcrt.get_osfhandle(f.fileno())
        assert K.SetFilePointerEx(handle,size,None,0)
        assert K.SetEndOfFile(handle)
        for offset,data in writes:
            f.seek(offset);f.write(data)
    high=wintypes.DWORD()
    low=K.GetCompressedFileSizeW(str(p),ctypes.byref(high))
    allocated=(high.value<<32)|low
    assert allocated < 1048576
    return allocated

def main():
    label=sys.argv[1]
    binding='patched' if label.startswith('patched') else 'old'
    exe=BUILD/(binding+'-native-boundary.exe')
    folder=BUILD/(label+'-sparse-fixtures');folder.mkdir()
    # Dense fixed header independently reflects v2.26.2 format (uint8 scalar codes).
    head=bytearray(64);head[:7]=b'usearch';struct.pack_into('<HHH',head,7,2,26,2)
    head[13:17]=bytes([99,11,14,15]);struct.pack_into('<QQQ',head,17,1,0,1024)
    cases=[]
    for bits,rows,col in [(32,1,4096),(32,2**19,4096),(64,2**19,4096),
                          (32,2**20,4096),(64,2**20,4096),(32,1366520,4096),(64,1366520,4096)]:
        prefix=struct.pack('<II' if bits==32 else '<QQ',rows,col)
        offset=len(prefix)+rows*col;p=folder/f'metadata-{bits}-{rows}.bin'
        allocated=sparse(p,offset+65,[(0,prefix),(offset,head),(offset+64,b'X')])
        cases.append(('metadata',p,{'expected':'PASS','u64':bits==64,'bytes':p.stat().st_size,'allocated':allocated}))
    for bits,size in [(32,2**32),(64,2**32),(32,2**32+1),(64,2**32+1)]:
        width=8 if bits==32 else 16
        col=size-width-65
        prefix=struct.pack('<II' if bits==32 else '<QQ',1,col)
        p=folder/f'metadata-exact-{bits}-{size}.bin'
        allocated=sparse(p,size,[(0,prefix),(width+col,head),(size-1,b'X')])
        cases.append(('metadata',p,{'expected':'PASS','u64':bits==64,'bytes':size,'allocated':allocated}))
    for size in [127,2**31-1,2**31,2**31+1,2**32-1,2**32,2**32+1,5800312336]:
        p=folder/f'mapping-{size}.bin';allocated=sparse(p,size,[(0,b'A'),(size-1,b'Z')])
        cases.append(('mapping',p,{'expected_length':size,'bytes':size,'allocated':allocated}))
    for name,data in [('empty',b''),('short',b'\x01\x02'),('truncated',struct.pack('<II',1,4096)+bytes(64)),
                      ('overflow',struct.pack('<QQ',2**64-1,2**64-1)+bytes(64)),
                      ('signed-offset',struct.pack('<QQ',2**63,1)+bytes(64)),
                      ('short-head',struct.pack('<II',1,1)+b'X'+b'usearch')]:
        p=folder/(name+'.bin');p.write_bytes(data);cases.append(('metadata',p,{'expected':'FAIL'}))
    cases.append(('metadata',folder/'missing.bin',{'expected':'FAIL'}))
    rows=[];env=dict(os.environ,PATH='C:/msys64/ucrt64/bin;'+os.environ['PATH'])
    for mode,p,expect in cases:
        result=subprocess.run([str(exe),mode,str(p)],env=env,capture_output=True)
        stdout=result.stdout.decode('utf8',errors='replace')
        passed=result.returncode==0 if expect.get('expected')=='PASS' else result.returncode!=0
        if mode=='mapping':passed=result.returncode==0 and f'length={expect["expected_length"]} first=65 last=90' in stdout
        if expect.get('expected')=='PASS':passed=passed and f'u64={int(expect["u64"])}' in stdout
        rows.append({'mode':mode,'fixture':p.name,'expect':expect,'exit':result.returncode,'stdout':stdout,'stderr':result.stderr.decode('utf8',errors='replace'),'meets_expected':passed})
    with (D/(label+'-native-regression.json')).open('x',encoding='utf8') as f:json.dump({'compiler':'UCRT64 GCC16.1 actual Windows64','fixtures':'metadata only NOT valid ANN; FSCTL_SET_SPARSE and actual allocated bytes verified','cases':rows},f,indent=2)
    print(json.dumps({'label':label,'pass':sum(x['meets_expected'] for x in rows),'total':len(rows),'failures':[x['fixture'] for x in rows if not x['meets_expected']]}))
    if binding=='patched':assert all(x['meets_expected'] for x in rows)

if __name__=='__main__':main()
