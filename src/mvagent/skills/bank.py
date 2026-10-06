"""Immutable Skill data, validation and hash-pinned static/dynamic loading."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from models.embeddings import EmbeddingConfig

from .prompts import render_skill_text

SOURCE_ROOT = Path(__file__).resolve().parents[1]
MAX_SKILL_WORDS = 1_200
_WORD = re.compile(r"\w+(?:['’-]\w+)*")


def count_words(text: str) -> int:
    """Count English words/identifiers/numbers; punctuation alone does not count."""
    return len(_WORD.findall(text))


ROLES = ("global", "video")
STAGES = ("initial", "evidence")

def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SkillCard:
    id: str
    role: str
    stages: tuple[str, ...]
    when_to_use: str
    strategy: str

    @classmethod
    def from_dict(cls, data: Any) -> "SkillCard":
        fields = {"meta", "when_to_use", "strategy"}
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("Skill requires exactly meta, when_to_use, strategy")
        meta = data["meta"]
        if not isinstance(meta, dict) or set(meta) != {"id", "role", "stages"}:
            raise ValueError("Skill meta requires exactly id, role, stages")
        sid, role, stages = (meta[k] for k in ("id", "role", "stages"))
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            raise ValueError("Skill reference must be a nonempty path-safe string")
        if role not in ROLES:
            raise ValueError("Skill role must be global or video")
        if (not isinstance(stages, list) or not stages
                or any(s not in STAGES for s in stages) or len(set(stages)) != len(stages)):
            raise ValueError("Skill stages must be a nonempty unique subset of initial/evidence")
        for field in ("when_to_use", "strategy"):
            if not isinstance(data[field], str) or count_words(data[field]) < 1:
                raise ValueError(f"Skill {field} must contain nonempty text")
        card = cls(sid, role, tuple(s for s in STAGES if s in stages),
                   *(data[k].strip() for k in ("when_to_use", "strategy")))
        if card.text_words > MAX_SKILL_WORDS or count_words(card.render()) > MAX_SKILL_WORDS:
            raise ValueError(f"Skill text/rendered body exceeds {MAX_SKILL_WORDS} words")
        return card

    @property
    def text_words(self) -> int:
        return sum(count_words(v) for v in (self.when_to_use, self.strategy))

    @property
    def sha256(self) -> str:
        return digest(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True))

    def render(self) -> str:
        # Each field owns its subtree, never the planner's surrounding prompt.
        return "### Strategy\n" + render_skill_text(self.strategy, minimum_level=4)

    def catalog_entry(self) -> dict[str, Any]:
        return dict(id=self.id, when_to_use=self.when_to_use)

    def to_dict(self) -> dict[str, Any]:
        return dict(meta=dict(id=self.id, role=self.role, stages=list(self.stages)),
                    when_to_use=self.when_to_use,
                    strategy=self.strategy)


@dataclass(frozen=True)
class SkillBank:
    cards: tuple[SkillCard, ...]
    sha256: str = ""
    retrieval_top_k: int = 8
    embedding: EmbeddingConfig | None = None

    def __post_init__(self):
        if type(self.retrieval_top_k) is not int or self.retrieval_top_k != 8:
            raise ValueError("Skill bank requires retrieval_top_k = 8")

    @classmethod
    def from_dict(cls, data: Any, *, sha256: str = "") -> "SkillBank":
        if (not isinstance(data, dict) or set(data) != {"schema_version", "skills"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 3
                or not isinstance(data["skills"], list)):
            raise ValueError("Skill bank requires schema_version=3 and skills array")
        cards = tuple(sorted((SkillCard.from_dict(c) for c in data["skills"]), key=lambda c: c.id))
        if len({c.id for c in cards}) != len(cards):
            raise ValueError("Duplicate Skill id")
        return cls(cards, sha256)

    @classmethod
    def load(cls, *, path: str, sha256: str, retrieval_top_k: int = 8,
             embedding: EmbeddingConfig | None = None) -> "SkillBank":
        raw = _resolve_skill_path(path).read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != sha256:
            raise ValueError(f"Skill bank SHA256 mismatch: expected {sha256}, got {actual}")
        bank = cls.from_dict(json.loads(raw.decode("utf-8")), sha256=actual)
        return replace(bank, retrieval_top_k=retrieval_top_k, embedding=embedding)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 3, "skills": [c.to_dict() for c in self.cards]}

    def eligible(self, *, role: str, stage: str) -> tuple[SkillCard, ...]:
        if role not in ROLES or stage not in STAGES:
            raise ValueError("Unknown Skill role or stage")
        return tuple(c for c in self.cards if c.role == role and stage in c.stages)

    def render(self, ids: list[str]) -> str:
        cards = {c.id: c for c in self.cards}
        if len(ids) > 1 or any(sid not in cards for sid in ids):
            raise ValueError("Select one Skill present in the bank, or none")
        text = cards[ids[0]].render() if ids else ""
        if count_words(text) > MAX_SKILL_WORDS:
            raise ValueError(f"Selected Skill bodies exceed {MAX_SKILL_WORDS} words")
        return text


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
    if count_words(skill) > MAX_SKILL_WORDS:
        raise ValueError(
            f"Skill exceeds {MAX_SKILL_WORDS} words: {path}"
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


def next_skill_id(cards):
    """Next stable sequential reference; existing references are never renumbered."""
    numbers = [int(card.id) for card in cards if card.id.isdecimal()]
    return str(max(numbers, default=0) + 1)
