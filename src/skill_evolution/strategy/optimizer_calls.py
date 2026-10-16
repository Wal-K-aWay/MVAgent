"""Content-addressed caching for deterministic optimizer model calls.

The cache deliberately knows nothing about Prompts, schemas, models, stages, or
experiments.  The caller owns the complete call identity and must include every input
that can change the result (normally the rendered Prompt, JSON Schema, model identity,
and decoding settings).  :func:`optimizer_call_hash` turns that JSON-serializable
identity into the opaque SHA256 accepted by :meth:`OptimizerCallCache.call`.

Only ordinary structured-model results whose ``status`` is ``ok`` or ``invalid`` are
cached.  Exceptions raised by the model call are audited and re-raised without creating
a cache entry.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


_FORMAT_VERSION = 1
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CACHEABLE_STATUSES = frozenset({"ok", "invalid"})

OptimizerCall = Callable[[], Mapping[str, Any]]
AuditCallback = Callable[[Mapping[str, Any]], None]


class OptimizerCallCacheCorruptionError(ValueError):
    """A persisted or in-memory cache record failed integrity validation."""


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize cache identity and payloads deterministically and strictly."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def optimizer_call_hash(identity: object) -> str:
    """Hash a complete caller-owned optimizer-call identity.

    ``identity`` must be JSON serializable.  This module does not add or infer Prompt,
    Schema, model, decoding, or experiment fields; omitting one of those inputs is a
    caller error and may cause an unsafe cache hit.
    """

    payload = {
        "kind": "skill_evolution_optimizer_call",
        "version": _FORMAT_VERSION,
        "identity": identity,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


class OptimizerCallCache:
    """Memory cache with optional atomic, content-addressed disk persistence.

    Args:
        directory: Optional directory for persistent records.  When omitted, the cache
            is memory-only.  Memory caching is always enabled for the lifetime of this
            object.
        audit: Optional callback receiving compact cache/call events.  Events contain
            the opaque call hash and optional caller-supplied audit context, never the
            identity, Prompt, raw response, or parsed result.

    The caller must compute ``call_hash`` from its complete immutable call identity,
    preferably with :func:`optimizer_call_hash`, and pass that hash to :meth:`call`.
    """

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        audit: AuditCallback | None = None,
    ) -> None:
        self.directory = (
            Path(directory).expanduser().resolve() if directory is not None else None
        )
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
        self.audit = audit
        self._memory: dict[str, dict[str, Any]] = {}

    def call(
        self,
        *,
        call_hash: str,
        invoke: OptimizerCall,
        audit_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a validated cached result or invoke and conditionally cache the call.

        Results with ``status`` equal to ``ok`` or ``invalid`` are cached.  Other
        result statuses are returned without caching.  A non-mapping return raises
        ``TypeError``.  Exceptions from ``invoke`` are never cached and are re-raised
        unchanged.
        """

        key = self._normalize_hash(call_hash)
        context = dict(audit_context or {})

        memory_record = self._memory.get(key)
        if memory_record is not None:
            try:
                result = self._validate_record(memory_record, expected_hash=key)
            except OptimizerCallCacheCorruptionError as exc:
                self._audit_error(
                    exc,
                    self._event(
                        key,
                        context,
                        event="cache_corruption",
                        source="memory",
                        error=str(exc),
                    ),
                )
                raise
            self._emit(
                self._event(
                    key,
                    context,
                    event="cache_hit",
                    source="memory",
                    result_status=str(result["status"]),
                )
            )
            return result

        if self.directory is not None:
            path = self._path(key)
            if path.is_file():
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    result = self._validate_record(record, expected_hash=key)
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    corruption = OptimizerCallCacheCorruptionError(
                        f"Optimizer cache record is unreadable: {path}: {exc}"
                    )
                    self._audit_error(
                        corruption,
                        self._event(
                            key,
                            context,
                            event="cache_corruption",
                            source="disk",
                            error=str(corruption),
                        ),
                    )
                    raise corruption from exc
                except OptimizerCallCacheCorruptionError as exc:
                    self._audit_error(
                        exc,
                        self._event(
                            key,
                            context,
                            event="cache_corruption",
                            source="disk",
                            error=str(exc),
                        ),
                    )
                    raise
                self._memory[key] = self._record(key, result)
                self._emit(
                    self._event(
                        key,
                        context,
                        event="cache_hit",
                        source="disk",
                        result_status=str(result["status"]),
                    )
                )
                return result

        started = time.perf_counter()
        try:
            raw_result = invoke()
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self._audit_error(
                exc,
                self._event(
                    key,
                    context,
                    event="call_exception",
                    source="model",
                    cached=False,
                    elapsed_seconds=elapsed,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )
            raise

        elapsed = time.perf_counter() - started
        if not isinstance(raw_result, Mapping):
            error = TypeError("Optimizer call must return a mapping.")
            self._audit_error(
                error,
                self._event(
                    key,
                    context,
                    event="call_invalid_result",
                    source="model",
                    cached=False,
                    elapsed_seconds=elapsed,
                    error=str(error),
                ),
            )
            raise error

        result = self._json_copy(dict(raw_result))
        status = str(result.get("status") or "")
        if status not in _CACHEABLE_STATUSES:
            self._emit(
                self._event(
                    key,
                    context,
                    event="call_complete",
                    source="model",
                    cached=False,
                    elapsed_seconds=elapsed,
                    result_status=status,
                )
            )
            return result

        record = self._record(key, result)
        if self.directory is not None:
            self._write_record(key, record)
        self._memory[key] = record
        self._emit(
            self._event(
                key,
                context,
                event="call_complete",
                source="model",
                cached=True,
                elapsed_seconds=elapsed,
                result_status=status,
            )
        )
        return self._json_copy(result)

    @staticmethod
    def _normalize_hash(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not _HASH_RE.fullmatch(normalized):
            raise ValueError("call_hash must be a 64-character hexadecimal SHA256.")
        return normalized

    def _path(self, call_hash: str) -> Path:
        assert self.directory is not None
        return self.directory / f"{call_hash}.json"

    @classmethod
    def _record(
        cls,
        call_hash: str,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_result = cls._json_copy(dict(result))
        return {
            "format_version": _FORMAT_VERSION,
            "call_hash": call_hash,
            "result_sha256": hashlib.sha256(
                _canonical_json_bytes(normalized_result)
            ).hexdigest(),
            "result": normalized_result,
        }

    @classmethod
    def _validate_record(
        cls,
        record: object,
        *,
        expected_hash: str,
    ) -> dict[str, Any]:
        if not isinstance(record, Mapping):
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record must be a JSON object."
            )
        required = {"format_version", "call_hash", "result_sha256", "result"}
        if set(record) != required:
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record fields do not match the current format."
            )
        if record["format_version"] != _FORMAT_VERSION:
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record format version is unsupported."
            )
        try:
            stored_hash = cls._normalize_hash(str(record["call_hash"]))
        except ValueError as exc:
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record contains an invalid call hash."
            ) from exc
        if stored_hash != expected_hash:
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record call hash does not match its lookup key."
            )
        result = record["result"]
        if not isinstance(result, Mapping):
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record result must be a JSON object."
            )
        normalized_result = cls._json_copy(dict(result))
        status = str(normalized_result.get("status") or "")
        if status not in _CACHEABLE_STATUSES:
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record contains a non-cacheable result status."
            )
        stored_result_hash = str(record["result_sha256"] or "").strip().lower()
        actual_result_hash = hashlib.sha256(
            _canonical_json_bytes(normalized_result)
        ).hexdigest()
        if stored_result_hash != actual_result_hash:
            raise OptimizerCallCacheCorruptionError(
                "Optimizer cache record result hash does not match its content."
            )
        return normalized_result

    def _write_record(self, call_hash: str, record: Mapping[str, Any]) -> None:
        assert self.directory is not None
        target = self._path(call_hash)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{call_hash}.",
            suffix=".tmp",
            dir=str(self.directory),
        )
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(_canonical_json_bytes(dict(record)))
                stream.write(b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _json_copy(value: object) -> Any:
        return json.loads(_canonical_json_bytes(value))

    @staticmethod
    def _event(
        call_hash: str,
        context: Mapping[str, Any],
        *,
        event: str,
        source: str,
        cached: bool | None = None,
        elapsed_seconds: float | None = None,
        result_status: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": event,
            "call_hash": call_hash,
            "source": source,
            "audit_context": dict(context),
        }
        if cached is not None:
            payload["cached"] = cached
        if elapsed_seconds is not None:
            payload["elapsed_seconds"] = float(elapsed_seconds)
        if result_status:
            payload["result_status"] = result_status
        if error:
            payload["error"] = error
        return payload

    def _emit(self, event: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit(dict(event))

    def _audit_error(self, error: Exception, event: Mapping[str, Any]) -> None:
        """Preserve the primary error if an audit callback also fails."""

        try:
            self._emit(event)
        except Exception as audit_error:
            error.add_note(
                "Optimizer-call audit callback also failed: "
                f"{type(audit_error).__name__}: {audit_error}"
            )


__all__ = [
    "AuditCallback",
    "OptimizerCall",
    "OptimizerCallCache",
    "OptimizerCallCacheCorruptionError",
    "optimizer_call_hash",
]
