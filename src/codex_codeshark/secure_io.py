from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"private storage path is not a directory: {path}")
    path.chmod(0o700)


def ensure_private_file(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"private storage path is not a regular file: {path}")
    if path.is_file():
        path.chmod(0o600)


def read_private_bytes(path: Path, *, max_bytes: int | None = None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"cannot open private file safely: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"private storage path is not a regular file: {path}")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            data = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if max_bytes is not None and len(data) > max_bytes:
        raise RuntimeError(f"private file exceeds the {max_bytes}-byte limit: {path}")
    return data


def read_private_text(
    path: Path,
    *,
    encoding: str = "utf-8",
    max_bytes: int | None = None,
) -> str:
    return read_private_bytes(path, max_bytes=max_bytes).decode(encoding)


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    mode: int = 0o600,
    private_parent: bool = True,
) -> None:
    if private_parent:
        ensure_private_directory(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise RuntimeError(f"storage parent is not a directory: {path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(mode)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
    private_parent: bool = True,
) -> None:
    atomic_write_bytes(
        path,
        text.encode(encoding),
        mode=mode,
        private_parent=private_parent,
    )
