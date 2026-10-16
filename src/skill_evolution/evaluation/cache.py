from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator, MutableMapping
from pathlib import Path

from .evaluator import RolloutArtifact


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
        handle, temporary = tempfile.mkstemp(
            prefix=f".{key}.", suffix=".tmp", dir=str(self.root)
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

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


__all__ = ["JsonEpisodeCache"]
