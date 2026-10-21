"""Generate a frozen skill bank from the runtime contract without task feedback."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import yaml

from models.execution import execution_scope
from models.utils import validate_json_schema
from models.vlm.api import ApiVLMClient
from mvagent.configs.model_config import ApiVLMConfig
from mvagent.skills.bank import MAX_SKILL_WORDS, SkillBank
from skill_evolution.infra.trajectory import Role, build_role_architectures


SYSTEM = """You write reusable skills for a frozen multi-video question-answering system.
Use only the supplied task description, runtime contract, and skill format. No task
instances, media, answers, execution traces, scores, or existing skills are supplied.
Create complementary procedures for the requested role. Choose their scopes yourself;
do not invent a benchmark taxonomy or fill the card quota with redundant procedures.
Each card has exactly two nonempty English text fields:
- when_to_use: applicability recognizable from the selector's available input.
- strategy: a self-contained procedure using only the role's actions and visible evidence.
The selector chooses at most one card, or none. It reads only when_to_use; the Actor
receives only strategy. Include execution prerequisites and exclusions in strategy.
Do not rely on another skill. Put conditions depending on future observations inside
strategy. Preserve all action, memory, and answer contracts; do not invent tools,
extra output fields, or hidden information. Do not encode dataset names, task codes,
sample identities, or answer keys. A skill guides a reusable method, not one question.
Keep each card concise. Its two fields together, and the rendered strategy with its
heading, must each fit within the supplied word limit. Return only the requested JSON.
""".strip()


def schema(max_cards: int) -> dict:
    if type(max_cards) is not int or not 1 <= max_cards <= 8:
        raise ValueError("max_cards must be between 1 and 8")
    return {
        "type": "object", "additionalProperties": False, "required": ["skills"],
        "properties": {"skills": {
            "type": "array", "minItems": 1, "maxItems": max_cards,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["when_to_use", "strategy"],
                "properties": {name: {"type": "string", "minLength": 1}
                               for name in ("when_to_use", "strategy")},
            },
        }},
    }


def build_prompt(runtime: dict, role: str, max_cards: int) -> str:
    schema(max_cards)
    selected_role = Role(role)
    global_config = runtime["agents"]["global_agent"]
    video_config = runtime["agents"]["video_agent"]
    observer = runtime["models"][video_config["observer"]["model_type"]]
    architecture = build_role_architectures(
        max_videos_per_watch=global_config["max_videos_per_watch"],
        max_video_inputs_per_request=observer["max_videos_per_request"],
        max_video_frames_per_request=observer["max_video_frames_per_request"],
        max_ranges_per_action=video_config["max_ranges_per_action"],
        global_max_steps=global_config["max_steps"],
        video_max_steps=video_config["max_steps"],
    )[selected_role]
    selection = (
        "The selector sees the complete question, video IDs and durations. Selection "
        "occurs once at the beginning of the question and persists, including none."
        if selected_role == Role.GLOBAL else
        "The selector sees the active instruction, not retained Memory or the global "
        "question. Selection occurs once per request and persists during that request. "
        "A new request selects again; same-video observation Memory persists."
    )
    return f"""## Task description
Answer a question whose evidence is distributed across multiple input videos.
The system has a global coordinator and one evidence agent per video. Each evidence
agent receives a local instruction and returns a report; its internal observations
remain private. The coordinator may also obtain joint visual observations.

## Target role: {role}
{architecture}

## Skill selection
{selection}
All generated cards will be eligible at initial and evidence stages. Stage eligibility
does not schedule future selection. The selected strategy guides ordinary decisions.
The Global answer-only terminal decision retains its strategy. The Video forced
summary receives retained Memory and the instruction, without the planning strategy.

## Output
Generate 1 to {max_cards} cards for this role, without forcing the maximum count.
Maximum per-card text and rendered-body length: {MAX_SKILL_WORDS} words.
Return {{"skills": [{{"when_to_use": "...", "strategy": "..."}}]}}.
The caller assigns IDs, role, and stages; do not return metadata or commentary.
"""


def make_bank(value: dict, role: str, max_cards: int, *, offset: int = 0) -> SkillBank:
    role = Role(role).value
    validate_json_schema(value, schema(max_cards))
    return SkillBank.from_dict({"schema_version": 3, "skills": [
        {"meta": {"id": str(offset + i + 1), "role": role,
                  "stages": ["initial", "evidence"]}, **card}
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
        encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        path.write_text(encoded.replace(secret, "[REDACTED]"), encoding="utf-8")

    # Keep the exact source and contract beside the response, including failed runs.
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "src", output / "source" / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    write(output / "runtime_contract.json", runtime)
    write(output / "generation_config.json", asdict(client.cfg))
    write(output / "source_manifest.json", {
        "commit": os.environ.get("MVAGENT_SOURCE_COMMIT"),
        "files": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in sorted((root / "src").rglob("*"))
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
                digest = hashlib.sha256(bank_path.read_bytes()).hexdigest()
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
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    SkillBank.load(path=str(path), sha256=digest)
    summary = {"status": "completed", "created_at": datetime.now(timezone.utc).isoformat(),
               "bank_sha256": digest, "roles": summaries, "task_examples": 0,
               "trajectory_examples": 0, "score_feedback": False, "quality_evaluated": False}
    write(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", default="configs/skill_evolution/runtime/dynamic_35b_embedding.yaml")
    parser.add_argument("--role", choices=("global", "video", "both"), default="global")
    parser.add_argument("--max-cards", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    runtime = yaml.safe_load(Path(args.runtime_config).read_text())
    cfg = ApiVLMConfig(provider="bigmodel", model_name="glm-5.3-flash",
                       api_key="BIGMODEL_API_KEY", reasoning_effort="high",
                       temperature=1.0, top_p=0.95, max_tokens=16384,
                       timeout_sec=600, max_retries=1)
    roles = ["global", "video"] if args.role == "both" else [args.role]
    summary = generate(ApiVLMClient(cfg), runtime, roles, args.output_dir, args.max_cards)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
