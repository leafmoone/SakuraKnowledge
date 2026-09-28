"""ZIP extraction only into a new directory, after digest and full path validation."""
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

from .storage import digest


def safe_extract(archive, destination, expected_sha256, max_bytes=2_000_000_000):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    if digest(archive) != expected_sha256:
        raise ValueError("archive digest mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".extract-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive) as z:
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
            for info in z.infolist():
                target = temp / info.filename.replace("\\", "/")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(target, "xb") as dst:
                        shutil.copyfileobj(src, dst)
        os.rename(temp, destination)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
