"""Four optimizer stages, grounded plan validation and single-card authorship."""

from pathlib import Path
from copy import deepcopy
import json
from models.execution import execution_scope
from models.utils import validate_json_schema
from mvagent.skills.bank import next_skill_id
from skill_evolution.infra.bank import BankSnapshot
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import write_json
from .prompts import build_system_prompt, build_stage_prompt
from .evidence import render_stage_input, view
from .prompts.analyzer import schema as analyzer_schema
from .prompts.planner import schema as planner_schema
from .prompts.generator import schema as generator_schema
from .prompts.reviser import schema as reviser_schema


class StageValidationError(ValueError):
    """Invalid structured response; operational errors still abort the run."""


class Stages:
    def __init__(self, optimizer, config):
        self.optimizer = optimizer
        self.config = config
        self.max_context_chars = config.max_context_chars

    def call(self, directory, name, payload, schema, validate=lambda value: None):
        """Persist and validate one response; resume reuses it without another call."""
        directory = Path(directory)
        system = build_system_prompt(name)
        user = build_stage_prompt(name, render_stage_input(payload))
        if len(user) > self.max_context_chars:
            write_json(
                directory / "validation_0.json",
                dict(
                    errors=["Stage evidence exceeds max_context_chars"],
                    rendered_chars=len(user),
                ),
            )
            raise StageValidationError("Stage evidence exceeds max_context_chars")
        identity = hash_json([self.optimizer.identity, system, user, schema])
        path = directory / "attempt_0.json"
        if path.exists():
            saved = json.loads(path.read_text())
            if saved["identity"] != identity:
                raise ValueError("Stage resume identity mismatch")
            response = saved["response"]
        else:
            write_json(
                directory / "input_0.json",
                dict(
                    identity=identity,
                    system=system,
                    user=user,
                    payload=payload,
                    schema=schema,
                ),
            )
            events = []
            try:
                with execution_scope(emit=events.append):
                    response = self.optimizer.json_prompt(
                        user,
                        system_prompt=system,
                        json_schema=schema,
                        schema_name="global_" + name,
                    )
            finally:
                write_json(directory / "events_0.json", events)
            response = {
                k: response.get(k) for k in ("status", "value", "raw_response", "error")
            }
            write_json(path, dict(identity=identity, response=response))
        errors = []
        value = response.get("value")
        try:
            if response.get("status") != "ok" or value is None:
                raise ValueError(
                    response.get("error") or "No valid structured response"
                )
            validate_json_schema(value, schema)
            validate(value)
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            errors.append(str(exc))
        write_json(
            directory / "validation_0.json", dict(response=response, errors=errors)
        )
        if errors:
            raise StageValidationError(f"{name} validation failed; inspect {directory}")
        write_json(directory / "result.json", value)
        return value

    def plan(self, directory, cases, parent, issue):
        payload = view(
            "planner",
            cases,
            bank=parent,
            issue=issue,
            max_words=self.config.max_card_words,
            max_chars=self.config.max_context_chars,
        )
        related = [c["meta"]["id"] for c in payload["related_cards"]]
        plan = self.call(
            directory,
            "planner",
            payload,
            planner_schema.build_schema(),
            lambda v: validate_plan(parent, v, payload["cases"], related),
        )
        return plan, payload

    def diagnose(self, directory, cases, parent):
        analysis = view("analyzer", cases, max_chars=self.config.max_context_chars)
        issue = self.call(
            directory / "analyzer",
            "analyzer",
            analysis,
            analyzer_schema.build_schema(),
            lambda v: validate_issue(v, analysis["cases"]),
        )
        if issue["status"] == "no_issue":
            return issue, None
        plan, _ = self.plan(directory / "planner", cases, parent, issue)
        return issue, plan

    def author(self, directory, cases, parent, issue, plan, allowed, known_versions):
        """Yield validated alternatives; caller evaluates each complete bank."""
        name = "generator" if plan["operation"] == "NEW" else "reviser"
        payload = view(
            name,
            cases,
            bank=parent,
            issue=issue,
            plan=plan,
            max_words=self.config.max_card_words,
            max_chars=self.config.max_context_chars,
        )
        schema = (
            generator_schema.build_schema()
            if name == "generator"
            else reviser_schema.build_schema(plan["operation"])
        )
        earlier, seen = [], set(known_versions)
        for variant in range(allowed):
            value = self.call(
                directory / f"author_{variant}",
                name,
                {**payload, "variant": variant + 1, "earlier_edits": earlier},
                schema,
            )
            candidate = build(parent, plan, value, self.config.max_card_words)
            if candidate is None or candidate.skill_set_hash() in seen:
                continue
            yield variant, value, candidate
            seen.add(candidate.skill_set_hash())
            earlier.append(value)


def validate_refs(refs, cases):
    index = {c["sample_id"]: c for c in cases}
    if not refs:
        raise ValueError("Evidence references must be nonempty")
    for ref in refs:
        case = index.get(ref["case_id"])
        if case is None:
            raise ValueError("Unknown development case reference")
        if ref["step"] is not None and not any(
            s["step"] == ref["step"] and s.get("editable", True) for s in case["steps"]
        ):
            raise ValueError("Reference must identify an actual editable public step")
    return index


def validate_issue(value, cases):
    if value["status"] == "no_issue":
        if value["evidence_refs"]:
            raise ValueError("no_issue requires empty references")
        return
    index = validate_refs(value["evidence_refs"], cases)
    if not value["task_requirement"].strip() or not value["failure"].strip():
        raise ValueError("Issue requires task and failure")
    if not any(
        index[r["case_id"]]["offline_feedback"]["score"] < 1
        for r in value["evidence_refs"]
    ):
        raise ValueError("Issue must reference a non-perfect case")


def validate_plan(parent, plan, cases, related_ids):
    cards = {c.id: c.to_dict() for c in parent.bank.cards if c.role == "global"}
    if not set(plan["checked_skill_ids"]) <= set(related_ids):
        raise ValueError("Checked card was not provided in full")
    if plan["status"] != "ready":
        if (
            plan["operation"] is not None
            or plan["target_skill_id"] is not None
            or plan["frozen_fields"]
        ):
            raise ValueError("Non-ready plan cannot specify an edit")
        return
    index = validate_refs(plan["evidence_refs"], cases)
    if not any(
        index[r["case_id"]]["offline_feedback"]["score"] < 1
        for r in plan["evidence_refs"]
    ):
        raise ValueError("Edit requires non-perfect evidence")
    if not plan["goal"].strip() or not plan["expected_benefit"].strip():
        raise ValueError("Edit goal and expected benefit are required")
    op = plan["operation"]
    target = plan["target_skill_id"]
    frozen = {"WHEN": ["strategy"], "STRATEGY": ["when_to_use"], "NEW": []}[op]
    if plan["frozen_fields"] != frozen:
        raise ValueError("Wrong frozen fields for operation")
    if op == "NEW":
        if target is not None:
            raise ValueError("NEW target must be null")
        if not set(related_ids) <= set(plan["checked_skill_ids"]):
            raise ValueError("NEW requires checking every supplied related method")
    else:
        if target not in cards or target not in related_ids:
            raise ValueError("Revision target must be a supplied Global card")
        if op == "STRATEGY":
            if not any(
                r["step"] is not None
                and any(
                    s["step"] == r["step"]
                    and s.get("editable", True)
                    and s.get("injected") == [target]
                    for s in index[r["case_id"]]["steps"]
                )
                for r in plan["evidence_refs"]
            ):
                raise ValueError(
                    "STRATEGY requires verified exact target exposure at a referenced step"
                )
    return plan


def build(parent, plan, value, max_words):
    fields = (
        ("when_to_use", "strategy")
        if plan["operation"] == "NEW"
        else ({"WHEN": "when_to_use", "STRATEGY": "strategy"}[plan["operation"]],)
    )
    if value["status"] == "skip":
        if any(value[f] is not None for f in fields):
            raise StageValidationError("Author skip requires null content")
        return None
    if any(not isinstance(value[f], str) or not value[f].strip() for f in fields):
        raise StageValidationError("Empty author content")
    cards = [c.to_dict() for c in parent.bank.cards]
    target = plan["target_skill_id"]
    if plan["operation"] == "NEW":
        raw = dict(
            meta=dict(
                id=next_skill_id(parent.bank.cards),
                role="global",
                stages=["initial", "evidence"],
            ),
            **{f: value[f] for f in fields},
        )
        cards.append(raw)
    else:
        raw = deepcopy(
            next(
                c
                for c in cards
                if c["meta"]["id"] == target and c["meta"]["role"] == "global"
            )
        )
        raw.update({f: value[f] for f in fields})
        cards = [raw if c["meta"]["id"] == target else c for c in cards]
    try:
        parsed = BankSnapshot.from_dict(
            dict(schema_version=3, skills=[raw])
        ).bank.cards[0]
        if parsed.text_words > max_words:
            raise ValueError("Assembled card exceeds total word budget")
        if any(
            all(c[f] == raw[f] for f in ("when_to_use", "strategy"))
            for c in cards
            if c["meta"]["id"] != raw["meta"]["id"] and c["meta"]["role"] == "global"
        ):
            raise ValueError("Duplicate card content")
        candidate = BankSnapshot.from_dict(dict(schema_version=3, skills=cards))
        if candidate == parent:
            raise ValueError("No substantive change")
    except (ValueError, TypeError, KeyError) as exc:
        raise StageValidationError(str(exc)) from exc
    return candidate
