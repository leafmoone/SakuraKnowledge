"""Windows path spelling repair for the retry1 audit gate only.

The original frozen validator remains byte-for-byte unchanged. Importing this
module performs no acceptance, build, database access or evidence writes. Formal
execution requires separate authorization; original FAIL/STOP receipts remain.
"""
from pathlib import Path

import p3_retry1_acceptance as acceptance


def check_binding(ref):
    """Compare resolved identity and exact bytes/SHA, not slash spelling."""
    actual = acceptance.binding(ref['path'])
    if (Path(actual['path']).resolve() != Path(ref['path']).resolve() or
            actual['bytes'] != ref['bytes'] or actual['sha256'] != ref['sha256']):
        raise ValueError('changed frozen input: ' + ref['path'])


def main():
    acceptance.check_binding = check_binding
    return acceptance.main()


if __name__ == '__main__':
    raise SystemExit(main())
