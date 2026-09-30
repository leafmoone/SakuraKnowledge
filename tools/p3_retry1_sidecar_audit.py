"""Authorized read-only-sidecar gate; no repair, deletion or refreeze.

Original validator and frozen evidence stay unchanged. No gold rerun is allowed.
An empty WAL is not by itself an immutability or absence-of-writer proof.
"""
import hashlib
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

import p3_retry1_acceptance as acceptance
from p3_evidence import save
from p3_retry1_path_audit import check_binding

TARGET = acceptance.DB
OBSERVATION = acceptance.REPORTS / 'full-retry1-sidecar-gate.json'


def metadata(db):
    result = {}
    for suffix in ('-wal', '-shm', '-journal'):
        path = Path(str(db) + suffix)
        result[suffix] = ({'exists': True, 'bytes': path.stat().st_size,
                           'mtime_ns': path.stat().st_mtime_ns} if path.exists() else {'exists': False})
        if path.exists() and suffix == '-shm':
            with path.open('rb') as stream:
                data = stream.read(32769)
            result[suffix]['sha256'] = hashlib.sha256(data).hexdigest()
            if len(data) == 32768:
                result[suffix]['header_copies_equal'] = data[:48] == data[48:96]
                fields = struct.unpack('<III BBH II', data[:24])
                result[suffix]['version'] = fields[0]
                result[suffix]['initialized'] = fields[3]
                result[suffix]['mx_frame'] = fields[6]
    return result


def validate_metadata(state):
    if state['-journal']['exists']:
        raise ValueError('rollback journal exists; STOP')
    wal, shm = state['-wal'], state['-shm']
    if wal['exists'] and wal['bytes'] != 0:
        raise ValueError('nonempty WAL; STOP')
    if shm['exists'] and (not wal['exists'] or shm['bytes'] != 32768 or
                          not shm.get('header_copies_equal') or shm.get('version') != 3007000 or
                          shm.get('initialized') != 1 or shm.get('mx_frame') != 0):
        raise ValueError('unexpected SHM/WAL structure; STOP')


def process_observation(db):
    script = ('$ErrorActionPreference="Stop"; Get-CimInstance Win32_Process | '
              'Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Depth 3')
    proc = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                          capture_output=True, timeout=30, check=False)
    if proc.returncode != 0 or proc.stderr:
        raise ValueError('process inspection failed; BLOCKED')
    rows = json.loads(proc.stdout.decode('utf-8-sig', errors='strict'))
    rows = rows if isinstance(rows, list) else [rows]
    watched = (str(db.parent).lower(), db.parent.as_posix().lower(),
               'p3_full_candidate_retry1.py')
    permitted = ('p3_retry1_sidecar_audit.py', 'record_check.py', 'bash.exe', 'powershell.exe')
    hits = []
    for row in rows:
        cmd = row.get('CommandLine') or ''
        if (any(word in cmd.lower() for word in watched) and
                not any(word in cmd.lower() for word in permitted)):
            hits.append(row)
    if hits:
        raise ValueError('related process still active; cannot establish quiescent gate')
    return {'command': ['powershell.exe', '-NoProfile', '-Command', script],
            'exit': proc.returncode, 'matched_related_processes': hits,
            'limitations': ['Command-line inspection is not complete handle enumeration',
                            'Process silence does not prove no writer; TOCTOU remains',
                            'Read-only reader is not classified as writer; active related processes conservatively block']}


def verify_snapshot(db, expected, *, inspect_process=process_observation):
    db = Path(db).resolve()
    if db != TARGET.resolve() or not db.is_file() or db.is_symlink():
        raise ValueError('only published retry1 database permitted')
    lock = db.parent.parent / ('.' + db.parent.name + '.sknow.lock')
    if lock.exists():
        raise ValueError('retry1 activity lock exists; STOP')
    before = metadata(db)
    validate_metadata(before)
    process = inspect_process(db)
    check_binding(expected)
    if Path(expected['path']).resolve() != db:
        raise ValueError('frozen database path differs')
    after = metadata(db)
    validate_metadata(after)
    if before != after:
        raise ValueError('sidecars changed during whole-database hash; STOP')
    return db, {'kind': 'quiescent read-only sidecar gate', 'database': expected,
                'sidecars_before': before, 'sidecars_after': after,
                'retry1_lock_absent': True, 'historical_attempt_lock_untouched': True,
                'process_observation': process,
                'limitations': ['Whole hash proves bytes only at check time',
                                'Empty WAL alone is not an immutable snapshot proof',
                                'No permissions changed and no exclusive handle acquired'],
                'created_ns': time.time_ns()}


def published(db):
    expected = acceptance.load(acceptance.P2)['database']
    verified, report = verify_snapshot(db, expected)
    save(OBSERVATION, report)
    return verified


def main():
    if '--accept-P2' not in sys.argv or '--accept-gold' in sys.argv or '--freeze' in sys.argv:
        raise ValueError('only authorized P2 acceptance continuation permitted')
    acceptance.check_binding = check_binding
    acceptance.published = published
    return acceptance.main()


if __name__ == '__main__':
    raise SystemExit(main())
