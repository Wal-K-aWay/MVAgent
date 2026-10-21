"""One call per role: persist raw output, validate, and freeze the complete bank."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from mvagent.utils.io import file_fingerprint, write_json
from models.execution import execution_scope
from models.utils import validate_json_schema
from mvagent.skills.bank import ROLES, STAGES, SkillBank
from mvagent.utils.snapshot import ensure_source_snapshot

from .prompts import SYSTEM, build_prompt, schema


def make_bank(value: dict, role: str, max_cards: int, *, offset: int = 0) -> SkillBank:
    if role not in ROLES:
        raise ValueError(f"Unknown skill role: {role}")
    validate_json_schema(value, schema(max_cards))
    return SkillBank.from_dict({"schema_version": 3, "skills": [
        {"meta": {"id": str(offset + i + 1), "role": role,
                  "stages": list(STAGES)}, **card}
        for i, card in enumerate(value["skills"])
    ]})


def generate(client, runtime: dict, roles: list[str], output: Path, max_cards: int) -> dict:
    schema(max_cards)
    if not roles or len(set(roles)) != len(roles):
        raise ValueError("Supply distinct roles")
    prompts = {role: build_prompt(runtime, role, max_cards) for role in roles}
    output.mkdir(parents=True, exist_ok=False)
    secret = client.api_key

    def write(path: Path, value):
        write_json(path, value, redact=secret)

    # Keep the exact source and contract beside the response, including failed runs.
    snapshot = ensure_source_snapshot(output / "source").parent
    write(output / "runtime_contract.json", runtime)
    write(output / "generation_config.json", asdict(client.cfg))
    write(output / "source_manifest.json", {
        "commit": os.environ.get("MVAGENT_SOURCE_COMMIT"),
        "files": {str(path.relative_to(snapshot.parent)): file_fingerprint(path)
                  for path in sorted(snapshot.rglob("*"))
                  if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"},
    })
    summaries, cards = [], []
    for role, prompt in prompts.items():
        directory = output / role
        directory.mkdir()
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt}]
        write(directory / "request.json", {"messages": messages, "schema": schema(max_cards)})
        started = time.monotonic()
        events = []
        with (directory / "events.jsonl").open("w", encoding="utf-8") as log:
            def emit(event):
                events.append(event)
                log.write((json.dumps(event, ensure_ascii=False) + "\n").replace(secret, "[REDACTED]"))
                log.flush()

            try:
                with execution_scope(emit=emit):
                    raw = client.chat(messages, json_schema=schema(max_cards),
                                      schema_name=f"one_shot_{role}_skills")
                # Persist before parsing or deciding whether the output is usable.
                write(directory / "response.json", {"raw_response": raw})
                responses = [event for event in events if event["kind"] == "model_response"]
                if any(event.get("finish_reason") == "length" for event in responses):
                    raise ValueError("Generation was truncated")
                bank = make_bank(json.loads(raw), role, max_cards, offset=len(cards))
                bank_path = directory / "bank.json"
                write(bank_path, bank.to_dict())
                digest = file_fingerprint(bank_path)
                loaded = SkillBank.load(path=str(bank_path), sha256=digest)
                for card in loaded.cards:
                    loaded.render([card.id])
                summary = {"role": role, "cards": len(loaded.cards), "sha256": digest,
                           "seconds": time.monotonic() - started,
                           "requests": sum(e["kind"] == "model_request" for e in events),
                           "responses": [{k: e.get(k) for k in
                                          ("model", "request_id", "finish_reason", "usage")}
                                         for e in responses],
                           "card_words": [card.text_words for card in loaded.cards]}
                write(directory / "validation.json", {"valid": True, **summary})
            except Exception as exc:
                write(directory / "validation.json", {"valid": False, "error": str(exc)})
                raise RuntimeError(f"{role} generation failed; inspect {directory}") from None
        cards.extend(bank.to_dict()["skills"])
        summaries.append(summary)
        print(json.dumps({"completed_role": role, "cards": len(bank.cards), "sha256": digest}), flush=True)
    combined = SkillBank.from_dict({"schema_version": 3, "skills": cards})
    path = output / "bank.json"
    write(path, combined.to_dict())
    digest = file_fingerprint(path)
    SkillBank.load(path=str(path), sha256=digest)
    summary = {"status": "completed", "created_at": datetime.now(timezone.utc).isoformat(),
               "bank_sha256": digest, "roles": summaries, "task_examples": 0,
               "trajectory_examples": 0, "score_feedback": False, "quality_evaluated": False}
    write(output / "summary.json", summary)
    return summary
