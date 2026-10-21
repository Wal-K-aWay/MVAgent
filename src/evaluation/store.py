"""Atomic JSON persistence and fingerprints shared by offline tools."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


def write_json(path, value, *, redact=""):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            encoded = json.dumps(value, ensure_ascii=False, indent=2)
            stream.write(encoded.replace(redact, "[REDACTED]") if redact else encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def file_fingerprint(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def hash_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
