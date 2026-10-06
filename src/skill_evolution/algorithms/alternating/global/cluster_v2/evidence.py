"""Train/Cal public evidence, exact exposure and separated stage views."""

import json
from skill_evolution.infra.skills import Role
from skill_evolution.infra.trajectory import routing_audit, render_global_steps


class EvidenceBudgetError(ValueError):
    """Required whole-case evidence cannot fit the configured stage budget."""


def training_case(report, sample_id, bank, projector, reference):
    """Project public evidence; never forward raw requests or private Video traces."""
    episode = report["episodes"][sample_id]
    case = next(
        c
        for c in projector.project(
            episode.artifact, official_score=report["scores"][sample_id].score
        )
        if c.role == Role.GLOBAL
    )
    audit = routing_audit(
        bank,
        {
            "episodes": {sample_id: episode},
            "scores": {sample_id: report["scores"][sample_id]},
        },
        {sample_id: case.source_group},
    )
    exposure = {r["decision_id"]: r for r in audit["rows"] if r["role"] == "global"}
    trajectory = json.loads(case.decisions_and_results)
    steps = []
    for index, row in enumerate(trajectory["rounds"], 1):
        row["decision"].pop("reason", None)
        route = exposure.get(f"global:{row['round']}", {})
        steps.append(
            dict(
                step=index,
                **row,
                editable=not row["decision"].get("runtime_finalizer", False),
                selected=route.get("selected"),
                injected=route.get("injected"),
            )
        )
    final_answer = json.loads(case.output)
    final_answer.pop("reason", None)
    result = dict(
        sample_id=sample_id,
        bank_hash=bank.skill_set_hash(),
        input=json.loads(case.visible_input),
        steps=steps,
        final_answer=final_answer,
        offline_feedback=dict(
            reference=reference,
            score=case.official_score,
            feedback=case.outcome_feedback,
        ),
    )
    result["used_skill"] = used_skill(result, bank)
    return result


def used_skill(case, bank):
    """Resolve one question-wide Skill from verified decision requests."""
    cards = {c.id: c for c in bank.bank.cards if c.role == "global"}
    if not cards:
        return None
    decisions = [s for s in case["steps"] if s.get("editable", True)]
    if not decisions:
        return None
    selections = []
    for step in decisions:
        selected, injected = step.get("selected"), step.get("injected")
        if selected is None or injected is None:
            # Null exposure stays explicit in steps; never infer non-selection.
            return None
        if len(selected) > 1 or selected != injected:
            raise ValueError("Question Skill selection and injection must agree")
        selections.append(tuple(selected))
    if len(set(selections)) != 1:
        raise ValueError("Question Skill changed between decisions")
    ids = selections[0]
    if not ids:
        return None
    if ids[0] not in cards:
        raise ValueError("Question Skill is absent from the current bank")
    return cards[ids[0]].to_dict()


def analysis_case(case):
    """No library, selected IDs, injected body, private traces or raw requests."""
    import copy

    value = copy.deepcopy(case)
    for key in ("used_skill", "bank_hash", "source_sample_id", "routing"):
        value.pop(key, None)
    for step in value["steps"]:
        for key in ("selected", "injected", "retrieval"):
            step.pop(key, None)
    return value


def related_cards(bank, cases, limit=8):
    import re

    cards = [c.to_dict() for c in bank.bank.cards if c.role == "global"]
    used = {sid for c in cases for s in c["steps"] for sid in (s.get("injected") or [])}
    words = set(
        re.findall(r"[a-z]+", " ".join(c["input"]["question"] for c in cases).lower())
    )
    ranked = sorted(
        cards,
        key=lambda c: (
            c["meta"]["id"] not in used,
            -len(words & set(re.findall(r"[a-z]+", c["when_to_use"].lower()))),
            c["meta"]["id"],
        ),
    )
    return ranked[:limit]


def view(
    stage,
    cases,
    *,
    bank=None,
    issue=None,
    plan=None,
    max_words=1200,
    max_chars=100000,
):
    """Whole-case budget, prioritized references, with explicit omissions."""
    required = {r["case_id"] for r in (plan or issue or {}).get("evidence_refs", [])}
    ordered = sorted(cases, key=lambda c: c["sample_id"] not in required)
    value = dict(stage=stage, cases=[], omitted_case_ids=[], max_card_words=max_words)
    if stage != "analyzer":
        related = related_cards(bank, cases)
        value.update(
            issue=issue,
            library_catalog=[
                dict(id=c.id, when_to_use=c.when_to_use)
                for c in bank.bank.cards
                if c.role == "global"
            ],
            related_cards=related,
        )
        if plan is not None:
            value["plan"] = plan
        if stage in ("generator", "reviser"):
            value["target_skill"] = next(
                (
                    c.to_dict()
                    for c in bank.bank.cards
                    if c.id == plan["target_skill_id"]
                ),
                None,
            )
    for case in ordered:
        rendered = analysis_case(case) if stage == "analyzer" else case
        value["cases"].append(rendered)
        if len(render_stage_input(value)) > max_chars:
            value["cases"].pop()
            value["omitted_case_ids"].append(case["sample_id"])
    if required & set(value["omitted_case_ids"]):
        raise EvidenceBudgetError(
            "Required evidence cannot fit whole-case context budget"
        )
    if len(render_stage_input(value)) > max_chars:
        raise EvidenceBudgetError("Library/plan exceeds context budget")
    return value


def render_stage_input(payload):
    return (
        "## Development evidence (offline feedback is not observation)\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
