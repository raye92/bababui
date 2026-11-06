"""Atomic local artifacts and process-owned locks."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_bytes(path, encoded(value))


def atomic_copy(source, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as output, Path(source).open("rb") as input_file:
            shutil.copyfileobj(input_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@contextmanager
def file_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("This work is already executing in another session.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def artifact(root, kind, value):
    digest = hashlib.sha256(encoded(value)).hexdigest()
    relative = f"{kind}/{digest}.json"
    path = Path(root) / relative
    with file_lock(path.with_suffix(".lock")):
        if path.exists():
            if path.read_bytes() != encoded(value):
                raise ValueError("Stored artifact integrity check failed.")
        else:
            write_json(path, value)
    return {"path": relative, "sha256": digest}


def resolve(root, reference):
    relative = reference["path"]
    if not re.fullmatch(r"(?:requests/[0-9a-f]{64}|transcriptions/[a-z0-9.-]+/[0-9a-f]{64}/complete)\.json", relative):
        raise ValueError("Invalid artifact reference.")
    try:
        data = (Path(root) / relative).read_bytes()
    except OSError as exc:
        raise ValueError(f"Missing referenced artifact: {relative}. Restore it before retrying.") from exc
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError(f"Artifact integrity check failed: {relative}")
    return json.loads(data)
