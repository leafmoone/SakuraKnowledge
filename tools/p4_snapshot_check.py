"""Hash-only P4 FULL baseline check; never opens SQLite or modifies sidecars."""
import hashlib
import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'build/p3-full-authorized-retry1/knowledge.sqlite'
EXPECTED_BYTES = 21718736896
EXPECTED_SHA256 = '61562f2e76fa9a77a44d34adcc2482f44c4fa4950352e84e410b888b035315d9'


def binding(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('file changed while hashing')
    return {'bytes': after.st_size, 'sha256': digest.hexdigest(),
            'mtime_ns': after.st_mtime_ns}


def sidecars(db):
    result = {}
    for suffix in ('-wal', '-shm', '-journal'):
        path = Path(str(db) + suffix)
        result[suffix] = {'exists': path.exists()}
        if path.exists():
            result[suffix].update(binding(path))
    return result


def main():
    start = time.perf_counter()
    db = ROOT / RELATIVE
    before = sidecars(db)
    actual = binding(db)
    after = sidecars(db)
    passed = (actual['bytes'] == EXPECTED_BYTES and actual['sha256'] == EXPECTED_SHA256
              and before == after
              and all(not after[s].get('bytes', 0) for s in ('-wal', '-journal')))
    print(json.dumps({'path': RELATIVE, **actual, 'sidecars_before': before,
                      'sidecars_after': after, 'status': 'PASS' if passed else 'FAIL',
                      'disk_free_bytes': shutil.disk_usage(ROOT).free,
                      'elapsed_seconds': time.perf_counter() - start,
                      'sql_opened': False, 'limitations': [
                          ('Metadata consistency does not exclude a concurrent writer; '
                           'only observed bytes are attested.')]}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
