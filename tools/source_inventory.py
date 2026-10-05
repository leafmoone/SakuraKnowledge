"""Authoritative adapter inventory: portable bindings, no directory recursion."""
import re
import stat
from pathlib import Path, PurePosixPath

from tools.source_pack import binding

MAX_FILES = 1_000_000
MAX_BYTES = 1 << 50


def validate_inventory(items):
    if not isinstance(items, list) or not items or len(items) > MAX_FILES:
        raise ValueError('input inventory must be nonempty and bounded')
    seen = set()
    total = 0
    for item in items:
        path = item.get('path')
        if not isinstance(path, str) or not path or '\\' in path or ':' in path or path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')):
            raise ValueError('unsafe input inventory path')
        if path in seen:
            raise ValueError('duplicate input inventory path')
        seen.add(path)
        size = item.get('size')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_BYTES or not re.fullmatch('[0-9a-f]{64}', str(item.get('sha256', ''))):
            raise ValueError('invalid input inventory binding')
        total += size
    if total > MAX_BYTES:
        raise ValueError('input inventory total size limit')
    return sorted(items, key=lambda item: item['path'])


def capture(adapter, raw):
    raw = Path(raw)
    root = raw if raw.is_dir() else raw.parent
    if not raw.exists():
        raise ValueError('unsafe input root')
    for ancestor in [raw, *raw.parents]:
        info = ancestor.lstat()
        if ancestor.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('unsafe input root symlink/reparse')
    plan = adapter.input_inventory(raw) if hasattr(adapter, 'input_inventory') else [{'path': raw.name}] if raw.is_file() else None
    if not isinstance(plan, list) or not plan or len(plan) > MAX_FILES:
        raise ValueError('directory adapter requires explicit input_inventory')
    portable = []
    for item in plan:
        item = {'path': item} if isinstance(item, str) else item
        relative = item['path']
        # Validate spelling before touching a path, then reject every symlink/reparse component.
        validate_inventory([{'path': relative, 'size': 0, 'sha256': '0' * 64}])
        path = root
        for part in PurePosixPath(relative).parts:
            path = path / part
            info = path.lstat()
            if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('input inventory symlink/reparse forbidden')
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('input inventory requires contained regular file')
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('input inventory not regular')
        actual = {**binding(path), 'path': relative}
        for field in ('size', 'sha256'):
            if field in item and item[field] != actual[field]:
                raise ValueError('input inventory claimed binding mismatch')
        if 'role' in item:
            actual['role'] = item['role']
        portable.append(actual)
    return validate_inventory(portable)
