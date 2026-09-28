"""ZIP extraction only into a new directory, after digest and full path validation."""
import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def safe_extract(archive, destination, expected_sha256, max_bytes=2_000_000_000):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".extract-", dir=destination.parent))
    try:
        with open(archive, "rb") as stream:
            before = os.fstat(stream.fileno())
            h = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
            if h.hexdigest().lower() != expected_sha256.lower():
                raise ValueError("archive digest mismatch")
            stream.seek(0)
            with zipfile.ZipFile(stream) as z:
                _extract_members(z, temp, max_bytes)
            stream.seek(0)
            h = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
            after = os.fstat(stream.fileno())
            if h.hexdigest().lower() != expected_sha256.lower() or (
                before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("archive changed during extraction")
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(temp, destination)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def _extract_members(z, temp, max_bytes):
    size = 0
    names = set()
    for info in z.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        size += info.file_size
        mode = info.external_attr >> 16
        if (path.is_absolute() or ".." in path.parts or ":" in name
                or stat.S_ISLNK(mode) or size > max_bytes
                or any(p.split(".")[0].upper() in {"AUX", "CON", "NUL", "PRN"}
                       for p in path.parts)
                or name.casefold() in names):
            raise ValueError("unsafe ZIP member")
        names.add(name.casefold())
        if not (temp / name).resolve().is_relative_to(temp):
            raise ValueError("ZIP escape")
    extracted = 0
    for info in z.infolist():
        target = temp / info.filename.replace("\\", "/")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "xb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    extracted += len(chunk)
                    if extracted > max_bytes:
                        raise ValueError("extracted ZIP exceeds byte limit")
                    dst.write(chunk)
