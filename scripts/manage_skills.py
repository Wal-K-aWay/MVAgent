#!/usr/bin/env python3
"""Manage an authored JSON bank; export immutable hash-addressed runtime snapshots."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from mvagent.skills.bank import SkillBank, SkillCard


def read_card(path: Path) -> SkillCard:
    return SkillCard.from_dict(json.loads(path.read_text(encoding="utf-8")))


def encode(bank: SkillBank) -> bytes:
    return (json.dumps(bank.to_dict(), ensure_ascii=False, indent=2) + "\n").encode()


def load(path: Path) -> SkillBank:
    return SkillBank.from_dict(json.loads(path.read_text(encoding="utf-8")))


def edit(path: Path, operation: str, *, card: SkillCard | None = None,
         skill_id: str = "", expected_sha256: str | None = None) -> str:
    """Atomic offline edit with a locked compare-and-swap for update/remove."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        raw = path.read_bytes() if path.exists() else None
        if operation != "add" and expected_sha256 is None:
            raise ValueError("update/remove require expected bank SHA256")
        if expected_sha256 is not None and (raw is None or hashlib.sha256(raw).hexdigest() != expected_sha256):
            raise ValueError("Bank changed; reload before editing")
        bank = SkillBank.from_dict(json.loads(raw)) if raw is not None else SkillBank(())
        cards = {c.id: c for c in bank.cards}
        if operation == "add":
            if card is None or card.id in cards:
                raise ValueError("add requires a new unique Skill id")
            cards[card.id] = card
        elif operation == "update":
            if card is None or skill_id not in cards or card.id != skill_id:
                raise ValueError("update requires an existing matching Skill id")
            cards[skill_id] = card
        elif operation == "remove":
            if skill_id not in cards:
                raise ValueError("Unknown Skill id")
            del cards[skill_id]
        else:
            raise ValueError("Unknown operation")
        payload = encode(SkillBank.from_dict({"schema_version": 3, "skills": [c.to_dict() for c in cards.values()]}))
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".skill-bank-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return hashlib.sha256(payload).hexdigest()


def freeze(bank: SkillBank, output: Path) -> dict:
    payload = encode(bank)
    digest = hashlib.sha256(payload).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    path = output / (digest + ".json")
    # Publish a complete file atomically, without replacing an existing snapshot.
    fd, name = tempfile.mkstemp(dir=output, prefix=".skill-snapshot-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ValueError("Existing snapshot content does not match its hash")
    finally:
        os.unlink(name)
    return dict(enabled=True, mode="dynamic", path=str(path.resolve()), sha256=digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("add", "update", "remove", "list", "validate", "freeze", "search"))
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--id", default="")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--role", choices=("global", "video"))
    parser.add_argument("--stage", choices=("initial", "evidence"))
    parser.add_argument("--query")
    parser.add_argument("--embedding-config", type=Path, help="JSON with endpoint, model and optional timeout_sec")
    args = parser.parse_args()
    try:
        if args.command in {"add", "update", "remove"}:
            if args.command in {"add", "update"} and args.file is None:
                parser.error("add/update require --file")
            sha = edit(args.bank, args.command, card=read_card(args.file) if args.file else None,
                       skill_id=args.id, expected_sha256=args.expected_sha256)
            print(json.dumps({"sha256": sha}))
        elif args.command == "search":
            from mvagent.skills.selection import retrieve_candidates
            from models.embeddings import EmbeddingConfig
            if not args.role or not args.stage or args.query is None:
                parser.error("search requires --role, --stage, --query")
            embedding = EmbeddingConfig.from_dict(json.loads(args.embedding_config.read_text())) if args.embedding_config else None
            candidates, _ = retrieve_candidates(load(args.bank).eligible(role=args.role, stage=args.stage), args.query, embedding)
            print(json.dumps([dict(**card.catalog_entry(), score=score) for card, score in candidates],
                             ensure_ascii=False, indent=2))
        elif args.command == "freeze":
            if args.output is None:
                parser.error("freeze requires --output")
            print(json.dumps(freeze(load(args.bank), args.output), indent=2))
        else:
            raw = args.bank.read_bytes()
            bank = SkillBank.from_dict(json.loads(raw))
            print(json.dumps({"sha256": hashlib.sha256(raw).hexdigest(),
                              "skills": [{"id": c.id, "when_to_use": c.when_to_use, "role": c.role, "stages": c.stages}
                                         for c in bank.cards]}, indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
