from __future__ import annotations

import json
import os
import re
import tempfile
import hashlib
from collections.abc import Iterator, MutableMapping
from pathlib import Path

from .data import RolloutArtifact


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
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


def runtime_hash(source_root):
    """Version only code that changes execution, independent of optimization."""
    from .skills import hash_json
    root = Path(source_root)
    return hash_json({name: tree_hash(root / name) for name in ("mvagent", "models")})


def file_fingerprint(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


_CACHE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class JsonEpisodeCache(MutableMapping[str, RolloutArtifact]):
    """Exact-key persistent raw episode cache for checkpoint/resume and rescoring."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def __getitem__(self, key: str) -> RolloutArtifact:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RolloutArtifact(
            sample_id=payload["sample_id"],
            artifact=payload["artifact"],
            bucket=payload.get("bucket", "default"),
            status=payload.get("status", "ok"),
        )

    def __setitem__(self, key: str, value: RolloutArtifact) -> None:
        path = self._path(key)
        payload = {
            "cache_key": key,
            "sample_id": value.sample_id,
            "bucket": value.bucket,
            "status": value.status,
            "artifact": value.artifact,
        }
        write_json(path, payload)

    def __delitem__(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError as exc:
            raise KeyError(key) from exc

    def __iter__(self) -> Iterator[str]:
        return (path.stem for path in sorted(self.root.glob("*.json")))

    def __len__(self) -> int:
        return sum(1 for _ in self.root.glob("*.json"))

    def _path(self, key: str) -> Path:
        normalized = str(key).strip().lower()
        if not _CACHE_KEY_RE.fullmatch(normalized):
            raise KeyError(f"Invalid episode cache key: {key!r}")
        return self.root / f"{normalized}.json"

