from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from difflib import SequenceMatcher, unified_diff
from mvagent.skills.bank import MAX_SKILL_WORDS, count_words

class Role(StrEnum):
    GLOBAL = "global"
    VIDEO = "video"


class EditOp(StrEnum):
    APPEND = "append"
    INSERT_AFTER = "insert_after"
    REPLACE = "replace"
    DELETE = "delete"


def normalize_skill_text(content: str) -> str:
    """Return the canonical in-memory and on-disk representation of a Skill."""
    if not isinstance(content, str):
        raise TypeError("Skill content must be text.")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"{normalized}\n" if normalized else ""


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def hash_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SkillSet:
    """The complete pair of role-local planning Skills used by one rollout."""

    global_skill: str = ""
    video_skill: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "global_skill", normalize_skill_text(self.global_skill))
        object.__setattr__(self, "video_skill", normalize_skill_text(self.video_skill))

    @classmethod
    def zero(cls) -> SkillSet:
        return cls()

    @classmethod
    def from_text(cls, *, global_skill: str, video_skill: str) -> SkillSet:
        return cls(global_skill=global_skill, video_skill=video_skill)

    def get(self, role: Role) -> str:
        return self.global_skill if Role(role) is Role.GLOBAL else self.video_skill

    def replace(self, role: Role, content: str) -> SkillSet:
        role = Role(role)
        if role is Role.GLOBAL:
            return SkillSet(global_skill=content, video_skill=self.video_skill)
        return SkillSet(global_skill=self.global_skill, video_skill=content)

    def skill_sha256(self, role: Role) -> str:
        return sha256_text(self.get(role))

    @property
    def is_promotable(self) -> bool:
        return bool(self.global_skill or self.video_skill)

    def skill_set_hash(self) -> str:
        """Hash only Skill content; rollout context has a separate identity."""
        return hash_json(
            {
                "global_sha256": self.skill_sha256(Role.GLOBAL),
                "video_sha256": self.skill_sha256(Role.VIDEO),
            }
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "global_skill": self.global_skill,
            "video_skill": self.video_skill,
        }


@dataclass(frozen=True)
class SkillEdit:
    op: EditOp
    target: str = ""
    content: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "op", EditOp(self.op))
        object.__setattr__(self, "target", str(self.target or ""))
        object.__setattr__(self, "content", str(self.content or "").strip())

    def to_dict(self) -> dict[str, str]:
        return {
            "op": self.op.value,
            "target": self.target,
            "content": self.content,
        }


def validate_text(text):
    if count_words(text) > MAX_SKILL_WORDS:
        raise ValueError(f"Skill exceeds {MAX_SKILL_WORDS} words")
    if re.search(r"[\u3400-\u9fff]", text) or re.search(r"^#{1,2}\s", text, re.M):
        raise ValueError("Skill must be English policy text with H3/H4 headings")


def text_diff(parent, candidate):
    added = deleted = 0
    for tag, a, b, c, d in SequenceMatcher(None, parent, candidate, autojunk=False).get_opcodes():
        if tag != "equal":
            added += d - c
            deleted += b - a
    return {"added_chars": added, "deleted_chars": deleted,
            "changed_chars": added + deleted, "total_chars": len(candidate),
            "diff": "".join(unified_diff(parent.splitlines(True), candidate.splitlines(True),
                                         fromfile="parent", tofile="candidate"))}


@dataclass(frozen=True)
class SkillChange:
    skills: SkillSet
    changes: dict


def set_pair(parent, candidate):
    for role in Role:
        validate_text(candidate.get(role))
    return SkillChange(candidate, {role.value: text_diff(parent.get(role), candidate.get(role))
                                   for role in Role})


def set_text(parent, *, role, text):
    return set_pair(parent, parent.replace(role, text))


def apply(parent, edits_by_role, expected_parent_hash):
    if parent.skill_set_hash() != expected_parent_hash:
        raise ValueError("Skill edits target a different parent version")
    candidate = parent
    for role, edits in edits_by_role.items():
        candidate = candidate.replace(role, edit_text(parent.get(role), edits))
    return set_pair(parent, candidate)


def edit_text(parent, edits):
    """Apply nonoverlapping spans against one unchanged parent, never by an LLM."""
    spans, appended = [], []
    for edit in edits:
        operation, target, content = edit["op"], edit.get("target", ""), edit.get("content", "")
        if re.search(r"[\u3400-\u9fff]", content) or re.search(r"^#{1,2}\s", content, re.M):
            raise ValueError("Skill edits must be English policy text with H3/H4 headings")
        if operation == "append":
            if target or not content.strip():
                raise ValueError("append needs empty target and nonempty content")
            appended.append(content.strip())
            continue
        if operation not in {"insert_after", "replace", "delete"} or not target or parent.count(target) != 1:
            raise ValueError("edit target must occur exactly once in the parent")
        if operation == "insert_after":
            if not content.strip():
                raise ValueError("insert_after needs nonempty content")
            newline = parent.find("\n", parent.index(target) + len(target))
            point = newline + 1 if newline >= 0 else len(parent)
            spans.append((point, point, "\n" + content + "\n"))
            continue
        if (operation == "delete" and content) or (operation == "replace" and not content.strip()):
            raise ValueError("delete needs empty content; replace needs nonempty content")
        start = parent.index(target)
        spans.append((start, start + len(target), content))
    spans.sort()
    if any(left[1] > right[0] or left[0] == right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("edits overlap")
    candidate = parent
    for start, end, content in reversed(spans):
        candidate = candidate[:start] + content + candidate[end:]
    candidate = normalize_skill_text("\n\n".join([candidate.strip(), *appended]))
    validate_text(candidate)
    return candidate
