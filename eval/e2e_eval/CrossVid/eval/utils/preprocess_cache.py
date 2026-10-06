"""Optional model-independent cache for CrossVid media preprocessing results."""

from __future__ import annotations

import hashlib
import os
import pickle
import threading
from pathlib import Path
from typing import Any, Iterable


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _root() -> Path | None:
    value = os.environ.get("MVAGENT_E2E_MEDIA_CACHE_DIR", "").strip()
    return Path(value) / "crossvid" if value else None


def _lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _source_identity(paths: Iterable[str | Path]) -> list[tuple[str, int, int]]:
    identity = []
    for value in paths:
        path = Path(value)
        stat = path.stat()
        identity.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    return identity


def cache_key(
    namespace: str,
    *,
    source_paths: Iterable[str | Path],
    parameters: Any,
) -> str:
    payload = pickle.dumps(
        {
            "version": 1,
            "namespace": namespace,
            "sources": _source_identity(source_paths),
            "parameters": parameters,
        },
        protocol=5,
    )
    return hashlib.sha256(payload).hexdigest()


def load(namespace: str, key: str) -> Any | None:
    root = _root()
    if root is None:
        return None
    path = root / namespace / key[:2] / f"{key}.pickle"
    with _lock(key):
        if not path.exists():
            return None
        try:
            with path.open("rb") as handle:
                return pickle.load(handle)
        except (OSError, EOFError, pickle.PickleError):
            return None


def store(namespace: str, key: str, value: Any) -> None:
    root = _root()
    if root is None:
        return
    path = root / namespace / key[:2] / f"{key}.pickle"
    with _lock(key):
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with temporary.open("wb") as handle:
            pickle.dump(value, handle, protocol=5)
        temporary.replace(path)
