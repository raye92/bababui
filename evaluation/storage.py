"""Content-addressed artifacts for evaluation runs."""
import hashlib
import json
from pathlib import Path
import re

from shared.storage import encoded, file_lock, write_json


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
    if not re.fullmatch(r"(?:(?:requests|responses)/[0-9a-f]{64}|transcriptions/[a-z0-9.-]+/(?:speakers-v1/)?[0-9a-f]{64}/complete)\.json", relative):
        raise ValueError("Invalid artifact reference.")
    try:
        data = (Path(root) / relative).read_bytes()
    except OSError as exc:
        raise ValueError(f"Missing referenced artifact: {relative}. Restore it before retrying.") from exc
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError(f"Artifact integrity check failed: {relative}")
    return json.loads(data)
