from __future__ import annotations

import hashlib
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
MAX_SKILL_CHARS = 6_000


def load_skill(
    *,
    path: str,
    sha256: str,
) -> str:
    """Load one immutable, explicitly selected plain-Markdown Skill."""
    skill_path = _resolve_skill_path(path)
    if not skill_path.is_file():
        raise ValueError(f"Skill path must identify a file: {path}")

    raw = skill_path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != str(sha256 or "").strip().lower():
        raise ValueError(
            f"Skill SHA256 mismatch for {path}: expected {sha256}, "
            f"got {actual_sha256}."
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Skill must be UTF-8 text: {path}") from exc
    skill = text.strip()
    if not skill:
        raise ValueError(f"Skill must be non-empty: {path}")
    if len(skill) > MAX_SKILL_CHARS:
        raise ValueError(
            f"Skill exceeds {MAX_SKILL_CHARS} characters: {path}"
        )
    return skill


def _resolve_skill_path(path: str) -> Path:
    raw_path = str(path or "").strip()
    if not raw_path:
        raise ValueError("Skill path must be non-empty.")
    configured = Path(raw_path).expanduser()
    if configured.is_absolute():
        return configured.resolve()
    return (SOURCE_ROOT / configured).resolve()


__all__ = ["MAX_SKILL_CHARS", "load_skill"]
