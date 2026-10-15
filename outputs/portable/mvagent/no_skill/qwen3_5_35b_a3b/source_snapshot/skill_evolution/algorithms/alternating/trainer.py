"""Short Video/Global updates, followed by one joint review per epoch.

The runtime and benchmark scorer remain the authority for evidence and quality.
This module only samples evidence, asks for bounded edits, and tests complete pairs.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import asdict, dataclass, replace
from skill_evolution.infra.skills import edit_text, text_diff
from pathlib import Path

from models.utils import extract_json, validate_json_schema
from models.execution import execution_scope

from . import prompts, longitudinal
from .gate import GATE_REPEATS, GATE_RULE, summarize_gate
from skill_evolution.infra.evaluation import compare, episode_health, evaluate_batch
from skill_evolution.infra.store import JsonEpisodeCache, write_json
from skill_evolution.infra.data import EvaluationRequest
from skill_evolution.infra.skills import Role, SkillSet, hash_json, normalize_skill_text
from skill_evolution.infra.trajectory import render_trace_case, trace_case_event_count

OUTPUT_SELECTION_RULE = "confirmed-current-or-initial-v1"


@dataclass(frozen=True)
class AlternatingConfig:
    epochs: int = 2
    batch_size: int = 8
    minibatch_size: int = 2
    merge_size: int = 2
    top_l: int = 1
    joint_size: int = 4
    seed: int = 20260905
    max_changed_chars: int = 800
    max_skill_chars: int = 6000
    use_slow_update: bool = False
    use_meta_skill: bool = False
    slow_update_samples: int = 20

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name in {"use_slow_update", "use_meta_skill"}:
                if type(value) is not bool:
                    raise ValueError(f"{name} must be boolean")
                continue
            if name != "seed" and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        if self.merge_size < 2:
            raise ValueError("merge_size must be at least two")


def _object(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


_STRINGS = {"type": "array", "items": {"type": "string"}}
_POLICY_PATTERN = r"^(?![\s\S]*(?:^|\n)#{1,2}\s)(?![\s\S]*[\u3400-\u9fff])[\s\S]*$"


def _patch_schema(limit=None, *, merged=False, empty_skill=False):
    properties = {
        "op": {"type": "string", "enum": ["append"] if empty_skill else
               ["append", "insert_after", "replace", "delete"]},
        "target": {"type": "string"}, "content": {"type": "string", "pattern": _POLICY_PATTERN},
    }
    if empty_skill:
        properties["target"]["const"] = ""
    if merged:
        properties.update(source_type={"type": "string", "enum": ["failure", "success"]})
    edit = {"type": "object", "properties": properties, "required": ["op"],
            "additionalProperties": False}
    edits = {"type": "array", "items": edit}
    if limit is not None:
        edits["maxItems"] = limit
    return _object({"reasoning": {"type": "string"}, "edits": edits})


def _analyst_schema(success, limit=2, *, empty_skill=False):
    diagnosis = ({"success_patterns": _STRINGS} if success else {"failure_summary": {
        "type": "array", "items": _object({"failure_type": {"type": "string"},
            "count": {"type": "integer", "minimum": 0}, "description": {"type": "string"}})}})
    return _object({"batch_size": {"type": "integer", "minimum": 0}, **diagnosis,
                    "patch": _patch_schema(limit, empty_skill=empty_skill)})


_PAIR_SCHEMA = _object({"global_skill": {"type": "string"}, "video_skill": {"type": "string"}})


def _slow_schema(parent, config):
    scaffold = normalize_skill_text(longitudinal.replace_slow_update_field(parent, ""))
    previous = longitudinal.extract_slow_update_field(parent)
    overhead = 0 if longitudinal.protected_region(parent) else max(0, len(scaffold) - len(parent))
    # Existing guidance can be retained; exact added + deleted characters are still
    # checked by apply_edits. For a new region, reserve its markers and whitespace.
    limit = max(0, min(config.max_skill_chars - len(scaffold),
                       len(previous) + config.max_changed_chars - overhead))
    return _object({"reasoning": {"type": "string"}, "slow_update_content": {
        "type": "string", "maxLength": limit,
        "pattern": r"^(?![\s\S]*(?:^|\n)#{1,2}\s)(?![\s\S]*[\u3400-\u9fff])"
                   r"(?![\s\S]*<!-- SLOW_UPDATE_(?:START|END) -->)[\s\S]*$"}})


def apply_edits(parent, edits, config, *, allow_slow_update=False):
    candidate = edit_text(parent, edits)
    if not allow_slow_update and longitudinal.protected_region(parent) != longitudinal.protected_region(candidate):
        raise ValueError("fast/joint edits cannot change the protected slow-update region")
    changed = text_diff(parent, candidate)["changed_chars"]
    if changed > config.max_changed_chars:
        raise ValueError(f"candidate changes {changed} characters (limit {config.max_changed_chars})")
    if len(candidate) > config.max_skill_chars:
        raise ValueError(f"candidate has {len(candidate)} characters (total Skill limit {config.max_skill_chars})")
    return candidate




class AlternatingTrainer:
    def __init__(self, *, config, initial_skill_set, train_context, eval_context,
                 executor, scorer, aggregator, projector, optimizer,
                 role_architectures, sample_metadata, output_dir, episode_cache=None):
        self.config = config
        self.initial = initial_skill_set
        self.current = initial_skill_set
        self.train_context, self.eval_context = train_context, eval_context
        if set(train_context.sample_ids) & set(eval_context.sample_ids):
            raise ValueError("Train and Eval must be disjoint")
        self.executor, self.scorer, self.aggregator = executor, scorer, aggregator
        self.projector, self.optimizer = projector, optimizer
        self.architectures, self.metadata = role_architectures, sample_metadata
        self.output = Path(output_dir)
        self.cache = episode_cache if episode_cache is not None else JsonEpisodeCache(self.output / "cache" / "episodes")
        self.feedback = []
        self.cursor = 0
        self.anchor = initial_skill_set
        self.previous_epoch = None
        self.meta_skills = {role.value: "" for role in Role}
        self._proposal_invalid = False
        self.identity = hash_json({"config": asdict(config), "initial": initial_skill_set.to_dict(),
                                   "train": train_context.context_hash, "eval": eval_context.context_hash,
                                   "optimizer": dict(optimizer.identity),
                                   "architectures": dict(role_architectures), "metadata": sample_metadata,
                                   "gate_repeats": GATE_REPEATS,
                                   "gate_rule": GATE_RULE,
                                   "output_selection_rule": OUTPUT_SELECTION_RULE,
                                   "prompts": [prompts.SKILLOPT, prompts.GEPA,
                                               prompts.INTEGRATION, prompts.JOINT_FORMAT]})

    def _event(self, kind, **details):
        record = {"time": time.time(), "kind": kind, "step": self.cursor, **details}
        self.output.mkdir(parents=True, exist_ok=True)
        with (self.output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def _rollout(self, pair, context, ids, label):
        started = time.monotonic()
        missing = [sid for sid in ids if context.rollout_cache_key(pair, sid) not in self.cache]
        if missing:
            self._event("rollout_start", label=label, samples=len(missing), pair=pair.skill_set_hash())
        result = evaluate_batch(self.executor, self.cache, self.scorer, self.aggregator,
                                EvaluationRequest(pair, context, tuple(ids), label))
        self._event("rollout_done", label=label, samples=len(ids), generated=len(missing),
                    repeat_id=context.repeat_id,
                    seconds=round(time.monotonic() - started, 2), score=result["score"],
                    bucket_scores=result["bucket_scores"])
        return result

    def _evidence(self, result, role, epoch, *, reference=False):
        evidence = []
        for sample_id, episode in result["episodes"].items():
            score = result["scores"][sample_id]
            cases = [case for case in self.projector.project(episode.artifact, official_score=score.score)
                     if case.role == role]
            if role == Role.VIDEO:
                cases = [case for case in cases if trace_case_event_count(
                    case, include_runtime_finalizers=False) > 0]
            if role == Role.VIDEO and cases:
                offset = int(hash_json([self.config.seed, sample_id])[:8], 16)
                cases = [cases[(offset + epoch) % len(cases)]]
            for case in cases:
                item = {"case_ref": result["pair_hash"][:12] + ":" + case.case_id, "question_ref": sample_id,
                        "system_success": score.reflection_success, "system_score": score.score,
                        "trajectory": render_trace_case(case, heading=f"{role.value.title()} trajectory",
                            include_failure_reason=False, include_runtime_finalizers=False)}
                if reference and role == Role.GLOBAL:
                    item["hidden_reference"] = self.metadata[sample_id].get("reference", "")
                    item["scorer_feedback"] = score.feedback
                evidence.append(item)
        return evidence

    def _context(self, pair, role):
        context = {"target_role": role, "current_skills": pair.to_dict(),
            "online_contracts": {str(key): value for key, value in self.architectures.items()},
            "limits": {key: value for key, value in asdict(self.config).items()
                       if key not in {"use_slow_update", "use_meta_skill", "slow_update_samples"}},
            "recent_update_feedback": [item for item in self.feedback if item["step_type"] == role][-4:]}
        if self.meta_skills.get(role):
            context["meta_skill"] = self.meta_skills[role]
        return context

    def _integration(self):
        if self.config.use_slow_update or any(longitudinal.protected_region(self.current.get(role)) for role in Role):
            return prompts.INTEGRATION.replace(
                "This operator has no protected SLOW_UPDATE sections; do not create them.",
                "Only epoch-level slow_update may create or replace protected SLOW_UPDATE sections; "
                "fast and joint edits must preserve them exactly.")
        return prompts.INTEGRATION

    def _user_prompt(self, stage, context):
        """Use the upstream section layout; MVAgent supplies only task/interface data."""
        role = context["target_role"]
        if stage in {"slow_update", "meta_skill"}:
            return (longitudinal.user_prompt(stage, context) +
                f"\n\n## MVAgent Integration Contract\n{self._integration()}\n"
                f"Editable role: {role}. The partner Skill is frozen during this update.\n"
                "The comparison categories and scores describe complete question outcomes, "
                "not local correctness or causal attribution. Each side was executed with its "
                "own full Skill pair; partner changes may also affect the trajectories.\n"
                "Role trajectories retain their existing visibility boundary. "
                "No VideoAgent-local reference answer is inferred.\n"
                f"Maximum changed characters: {self.config.max_changed_chars}. "
                f"Maximum total Skill characters: {self.config.max_skill_chars}.\n"
                f"Target System Prompt:\n{context['online_contracts'][role]}" +
                ("\nFor meta_skill, write optimizer-only memory, not target-Agent policy. "
                 "The Skill limits above describe deployment; this memory is not deployed."
                 if stage == "meta_skill" else ""))
        memory = longitudinal.format_meta_skill_context(context.get("meta_skill", ""))
        text = (memory + "\n\n" if memory else "") + f"## Current Skill\n{context['current_skills'][role + '_skill']}\n\n"
        if stage.startswith("analyst_"):
            text += "## Edits Budget\nProduce at most L=2 edits.\n\n"
        text += (f"## Target System Prompt\n{context['online_contracts'][role]}\n\n"
                 f"## MVAgent Integration Contract\n{self._integration()}\n"
                 f"Editable role: {role}. The partner Skill is frozen.\n"
                 f"Maximum changed characters: {self.config.max_changed_chars}. "
                 f"Maximum total Skill characters: {self.config.max_skill_chars}.\n\n")
        if not context["current_skills"][role + "_skill"]:
            text += ("Current Skill is empty. Use only append edits with nonempty content; "
                     "omit target or use an empty string. The existing Runtime prompts already "
                     "provide the base policy and action contracts. Empty Skill means no additional "
                     "policy, not a missing foundation. Propose a useful behavioral change relative "
                     "to those prompts; do not prioritize copying successful default behavior merely "
                     "to fill the empty Skill.\n\n")
        text += ("Each proposed edit must work independently with the current Skill. Do not refer "
                 "to another proposed edit that may not be selected. Keep mutually dependent "
                 "guidance together within one edit and the existing budget. Source batch sizes "
                 "are not verified evidence that an edit improves those cases; do not infer "
                 "effectiveness from them or invent per-edit support counts.\n\n")
        if context["recent_update_feedback"]:
            text += "## Previous Steps\n" + json.dumps(context["recent_update_feedback"], indent=2) + "\n\n"
        if stage.startswith("analyst_"):
            trajectories = context["trajectories"]
            label = "Successful" if stage == "analyst_success" else "Failed"
            text += f"## {label} Trajectories ({len(trajectories)} total)\n"
            for item in trajectories:
                feedback = {key: value for key, value in item.items() if key != "trajectory"}
                text += item["trajectory"] + "\n[Offline feedback] " + json.dumps(feedback) + "\n\n"
        elif stage == "ranking":
            edits, budget = context["edits"], context["budget"]
            text += f"## Edits Pool ({len(edits)} edits, budget={budget})\n"
            text += "\n".join(f"[{index}] {json.dumps(edit)}" for index, edit in enumerate(edits))
            text += f"\n\nSelect the {budget} most important edits. Return their 0-based indices in priority order."
        elif stage == "merge_final":
            text += "## Group 1: Failure-driven patches (HIGH priority)\n"
            text += json.dumps(context["proposals"][0], indent=2)
            text += "\n\n## Group 2: Success-driven patches (lower priority)\n"
            text += json.dumps(context["proposals"][1], indent=2)
        else:
            text += f"## Patches to merge ({len(context['proposals'])} total, merge level {context['merge_level']})\n"
            text += json.dumps(context["proposals"], indent=2)
        return text

    def _ask(self, stage, instruction, context, schema):
        if stage == "joint":
            system_prompt = (self._integration() + "\n" + prompts.JOINT_FORMAT +
                f"\nPer-role maximum changed characters: {self.config.max_changed_chars}. "
                f"Per-role maximum total Skill characters: {self.config.max_skill_chars}.")
            if any(longitudinal.protected_region(value) for value in context["current_skills"].values()):
                system_prompt += ("\nPreserve each <!-- SLOW_UPDATE_START --> ... <!-- SLOW_UPDATE_END --> "
                                  "region exactly. Only the epoch slow update may change that region.")
            prompt = instruction.replace("<curr_param>", json.dumps(context["current_skills"], indent=2))
            prompt = prompt.replace("<side_info>", json.dumps(context, ensure_ascii=False, indent=2))
        else:
            system_prompt = instruction
            if stage.startswith("merge_"):
                # Keep vendored originals intact; the adapter no longer supplies or
                # asks the optimizer to invent per-edit support counts.
                system_prompt = "\n".join(line for line in instruction.split("\n")
                    if "support_count" not in line and "**Support count**" not in line)
            if stage == "slow_update":
                limit = schema["properties"]["slow_update_content"]["maxLength"]
                system_prompt = instruction.replace(
                    "- Be concise but comprehensive — you have no length limit, but every sentence\n"
                    "  should earn its place.",
                    f"- slow_update_content must contain at most {limit} characters, including spaces "
                    "and newlines, not words or tokens. Stay comfortably below this limit.\n"
                    "- Write English policy text. Use only ### or #### for any headings; never # or ##.\n"
                    "- Return only the guidance body, without SLOW_UPDATE markers or the main Skill.\n"
                    "- The existing added-plus-deleted character budget also applies when replacing "
                    "previous guidance. Retain unchanged wording where useful; the body length "
                    "limit does not grant permission to exceed the edit budget.")
            prompt = self._user_prompt(stage, context)
        key = hash_json([self.identity, stage, system_prompt, prompt, schema])
        path = self.output / "optimizer_calls" / f"{key}.json"
        if path.exists():
            saved = json.loads(path.read_text())
            self._proposal_invalid |= saved["status"] != "ok"
            return saved["result"]
        self._event("optimizer_start", stage=stage, call=key, input_chars=len(prompt))
        started = time.monotonic()
        model_events = []
        try:
            with execution_scope(emit=model_events.append):
                if stage == "joint":
                    raw = self.optimizer.chat(messages=[{"role": "system", "content": system_prompt},
                                                       {"role": "user", "content": prompt}])
                    try:
                        value = extract_json(raw)
                        validate_json_schema(value, schema)
                        response = {"status": "ok", "value": value, "error": "", "raw_response": raw}
                    except (ValueError, TypeError) as exc:
                        response = {"status": "invalid", "value": None, "error": str(exc), "raw_response": raw}
                else:
                    response = self.optimizer.json_prompt(prompt, system_prompt=system_prompt,
                                                          json_schema=schema, schema_name="skill_" + stage)
        finally:
            write_json(self.output / "optimizer_events" / f"{key}.json", {
                "stage": stage, "call": key, "optimizer": dict(self.optimizer.identity),
                "schema": schema, "seconds": time.monotonic() - started, "events": model_events})
        value = response["value"] if response["status"] == "ok" else None
        self._proposal_invalid |= response["status"] != "ok"
        write_json(path, {"stage": stage, "system_prompt": system_prompt, "user_prompt": prompt,
                           "context": context, "result": value, "status": response["status"],
                           "error": response.get("error", ""), "raw_response": response.get("raw_response", "")})
        self._event("optimizer_done", stage=stage, call=key, status=response["status"],
                    seconds=round(time.monotonic() - started, 2))
        return value

    def _merge(self, proposals, context, mode):
        proposals = [proposal for proposal in proposals if proposal and proposal["edits"]]
        if not proposals:
            return {"reasoning": "No patches", "edits": []}
        level = 0
        while len(proposals) > 1:
            level += 1
            merged = []
            for start in range(0, len(proposals), self.config.merge_size):
                group = proposals[start:start + self.config.merge_size]
                if len(group) == 1:
                    merged.append(group[0])
                else:
                    stage = "merge_" + mode
                    value = self._ask(stage, prompts.SKILLOPT[stage], {**context, "mode": mode,
                        "proposals": group, "merge_level": level}, _patch_schema(merged=True,
                            empty_skill=not context["current_skills"][context["target_role"] + "_skill"]))
                    if value and value["edits"]:
                        for edit in value["edits"]:
                            edit["merge_level"] = level
                        merged.append(value)
            proposals = merged
            if not proposals:
                return {"reasoning": "No patches", "edits": []}
        return proposals[0]

    def _role_proposal(self, role, evidence):
        self._proposal_invalid = False
        context = self._context(self.current, role.value)
        empty_skill = not self.current.get(role)
        merged = []
        for success, mode in ((False, "failure"), (True, "success")):
            pool = [item for item in evidence if item["system_success"] == success]
            reflected = []
            stage = "analyst_success" if success else "analyst_error"
            for start in range(0, len(pool), self.config.minibatch_size):
                batch = pool[start:start + self.config.minibatch_size]
                value = self._ask(stage, prompts.SKILLOPT[stage],
                    {**context, "mode": mode, "trajectories": batch},
                    _analyst_schema(success, empty_skill=empty_skill))
                if value is not None:
                    patch = value["patch"]
                    for edit in patch["edits"]:
                        edit.update(source_type=mode)
                    reflected.append(patch)
            merged.append(self._merge(reflected, context, mode))
        nonempty = [group for group in merged if group["edits"]]
        if not nonempty:
            return []
        proposal = nonempty[0] if len(nonempty) == 1 else self._ask(
            "merge_final", prompts.SKILLOPT["merge_final"],
            {**context, "mode": "final", "proposals": merged},
            _patch_schema(merged=True, empty_skill=empty_skill))
        if proposal is None:
            return []
        edits = proposal["edits"]
        if len(edits) > self.config.top_l:
            ranked = self._ask("ranking", prompts.SKILLOPT["ranking"], {**context, "edits": edits,
                "budget": self.config.top_l}, _object({"reasoning": {"type": "string"},
                    "selected_indices": {"type": "array", "items": {"type": "integer"},
                                         "maxItems": self.config.top_l}}))
            if ranked is None:
                return []
            indices = ranked["selected_indices"]
            if not indices or len(indices) != len(set(indices)) or any(
                index < 0 or index >= len(edits) for index in indices):
                self._proposal_invalid = True
                self._event("proposal_invalid", reason="ranking must select unique valid zero-based indices")
                return []
            edits = [edits[index] for index in indices]
        return edits

    def _candidate(self, proposals, evidence, *, allow_slow_update=False):
        pair = self.current
        hidden_ids = {item["case_ref"] for item in evidence} | {item["question_ref"] for item in evidence}
        for role, edits in proposals.items():
            for edit in edits:
                if any(identifier in edit.get("content", "") for identifier in hidden_ids):
                    raise ValueError("offline case/question references cannot enter Skill content")
            pair = pair.replace(role, apply_edits(pair.get(role), edits, self.config,
                allow_slow_update=allow_slow_update))
        return pair

    def _gate(self, candidate, label, proposals=None):
        if candidate == self.current:
            self._event("no_change", label=label)
            return False
        report = self._paired_evaluation(self.current, candidate, "gate", label)
        self._last_gate = report
        self._event("gate", step_type=label, **{k: v for k, v in report.items() if k != "repeats"})
        if report["accepted"]:
            self.current = candidate
        return report["accepted"]

    def _paired_evaluation(self, parent_pair, candidate, purpose, label):
        gate_key = hash_json([str(self.output.resolve()), self.identity, self.eval_context.context_hash,
                             parent_pair.skill_set_hash(), candidate.skill_set_hash(), GATE_REPEATS, purpose])
        path = self.output / "gates" / gate_key / "summary.json"
        if path.exists():
            report = json.loads(path.read_text())
        else:
            pairs = []
            for repeat in range(GATE_REPEATS):
                context = replace(self.eval_context, repeat_id=f"{self.eval_context.repeat_id}:gate:{gate_key}:{repeat}")
                order = [("parent", parent_pair), ("candidate", candidate)]
                if repeat % 2:
                    order.reverse()
                results = {name: self._rollout(pair, context, context.sample_ids,
                    "eval_parent" if name == "parent" else label) for name, pair in order}
                pairs.append((results["parent"], results["candidate"]))
                write_json(path.parent / f"repeat_{repeat}.json", {
                    "repeat_id": context.repeat_id, "order": [name for name, _ in order],
                    "comparison": compare(*pairs[-1])})
            report = {**summarize_gate(pairs), "parent_pair": parent_pair.skill_set_hash(),
                      "candidate_pair": candidate.skill_set_hash(), "gate_key": gate_key, "purpose": purpose}
            for index, name in enumerate(("parent", "candidate")):
                report[name + "_bucket_scores"] = {bucket: sum(pair[index]["bucket_scores"][bucket]
                    for pair in pairs) / GATE_REPEATS for bucket in pairs[0][index]["bucket_scores"]}
            write_json(path, report)
        return report

    def _record_attempt(self, label, status, **details):
        record = {"step": self.cursor, "step_type": label, "status": status, **details}
        write_json(self.output / "attempts" / f"{self.cursor:04d}_{label}.json", record)
        if status != "pending":
            # The complete record stays on disk; only aggregate Eval feedback enters prompts.
            feedback = {k: v for k, v in record.items() if k not in {"evidence", "candidate_skills"}}
            self.feedback = [r for r in self.feedback if (r["step"], r["step_type"]) != (self.cursor, label)]
            self.feedback.append(feedback)

    def _attempt(self, proposals, evidence, label, *, allow_slow_update=False):
        details = {"parent_pair": self.current.skill_set_hash(), "proposed_edits": proposals,
                   "evidence": [{k: v for k, v in item.items() if k != "trajectory"} for item in evidence]}
        self._record_attempt(label, "pending", **details)
        self._event("proposal", label=label, edits=proposals,
                    evidence_refs=[item["case_ref"] for item in evidence])
        try:
            candidate = self._candidate(proposals, evidence, allow_slow_update=allow_slow_update)
        except ValueError as exc:
            self._event("proposal_invalid", label=label, reason=str(exc))
            self._record_attempt(label, "static_rejected", error=str(exc), **details)
            return
        details.update(candidate_pair=candidate.skill_set_hash(), candidate_skills=candidate.to_dict())
        if candidate == self.current:
            self._record_attempt(label, "optimizer_invalid" if self._proposal_invalid else "no_change", **details)
            self._event("no_change", label=label)
            return
        self._record_attempt(label, "pending", **details)
        accepted = self._gate(candidate, label, proposals)
        self._record_attempt(label, "accepted" if accepted else "rejected", **details,
            **{k: self._last_gate[k] for k in ("gate_key", "accepted", "score_delta",
                "repeat_deltas", "new_reliability_regressions")})

    def _joint(self, epoch):
        self._proposal_invalid = False
        ids = random.Random(self.config.seed).sample(list(self.train_context.sample_ids),
            min(self.config.joint_size, len(self.train_context.sample_ids)))
        current = self._rollout(self.current, self.train_context, ids, "joint_current")
        previous = (self._rollout(self.anchor, self.train_context, ids, "joint_previous")
                    if self.anchor != self.current else None)
        def evidence_for(result):
            return [*self._evidence(result, Role.GLOBAL, epoch, reference=True),
                    *self._evidence(result, Role.VIDEO, epoch)]
        evidence = evidence_for(current)
        before = evidence_for(previous) if previous else []
        value = self._ask("joint", prompts.GEPA, {**self._context(self.current, "joint"),
            "previous_skills": self.anchor.to_dict() if previous else None,
            "current_trajectories": evidence, "previous_trajectories": before},
            _PAIR_SCHEMA)
        if value is not None:
            proposed = SkillSet(**value)
            edits = {role: ([] if proposed.get(role) == self.current.get(role) else [{
                "op": "replace" if self.current.get(role) else "append",
                "target": self.current.get(role), "content": proposed.get(role),
            }]) for role in Role}
            # Empty replacement is a native delete operation.
            for values in edits.values():
                for edit in values:
                    if not edit["content"]:
                        edit["op"] = "delete"
            self._attempt(edits, [*evidence, *before], "joint")
        else:
            self._record_attempt("joint", "optimizer_invalid", parent_pair=self.current.skill_set_hash())

    def _epoch_update(self, epoch):
        """SkillOpt adjacent-epoch comparison, separately for each planning role."""
        snapshot = self.current  # Post-fast/joint, before this epoch's slow updates.
        directory = self.output / "slow_meta" / f"epoch_{epoch + 1:02d}"
        if epoch == 0:
            self.previous_epoch = snapshot
            write_json(directory / "summary.json", {"status": "warmup", "epoch": 1,
                "last_step_skills": snapshot.to_dict(), "meta_skills": self.meta_skills})
            return
        if self.previous_epoch is None:
            raise ValueError("slow/meta update requires the previous epoch checkpoint")
        ids = random.Random(self.config.seed + (epoch + 1) * 2000).sample(
            list(self.train_context.sample_ids),
            min(self.config.slow_update_samples, len(self.train_context.sample_ids)))
        identity = hash_json([str(self.output.resolve()), self.identity, epoch + 1])
        context = replace(self.train_context,
            repeat_id=f"{self.train_context.repeat_id}:slow_meta:{identity}")
        results = {name: self._rollout(pair, context, ids, "slow_meta_" + name)
            for name, pair in (("prev", self.previous_epoch), ("curr", snapshot))}
        summaries = {}
        for role in (Role.VIDEO, Role.GLOBAL):
            views = {name: self._evidence(result, role, epoch, reference=True)
                     for name, result in results.items()}
            indexed = {name: {item["question_ref"]: item for item in items}
                       for name, items in views.items()}
            pairs = []
            for sample_id in ids:
                if role == Role.VIDEO and not any(sample_id in v for v in indexed.values()):
                    continue
                entry = {"id": sample_id, "task": self.metadata[sample_id].get("task", sample_id)
                    if role == Role.GLOBAL else "VideoAgent local request (see role trajectories)"}
                for name, result in results.items():
                    score = result["scores"][sample_id]
                    view = indexed[name].get(sample_id)
                    entry[name] = {"hard": int(score.reflection_success), "soft": score.score,
                        "predicted_answer": result["episodes"][sample_id].artifact.get("result", {}).get("answer", "")
                            if role == Role.GLOBAL else "See local role trajectory.",
                        "fail_reason": score.feedback if role == Role.GLOBAL else ""}
                    trajectory = view["trajectory"] if view else "(No VideoAgent Planner trajectory in this question.)"
                    if role == Role.GLOBAL and view:
                        trajectory += "\n[Offline reference] " + view.get("hidden_reference", "")
                    entry[name + "_trajectory"] = trajectory
                before, after = entry["prev"]["hard"], entry["curr"]["hard"]
                entry["category"] = ("stable_success" if before and after else "regressed" if before
                                     else "improved" if after else "persistent_fail")
                pairs.append(entry)
            stage_context = {**self._context(snapshot, role.value),
                "epoch_update_feedback": self._epoch_feedback(role),
                "previous_skills": self.previous_epoch.to_dict(), "comparison_pairs": pairs}
            write_json(directory / f"{role.value}_comparison.json", {
                "epoch": epoch + 1, "repeat_id": context.repeat_id, "sample_ids": ids,
                "previous_skills": self.previous_epoch.to_dict(), "current_skills": snapshot.to_dict(),
                "comparison_pairs": pairs})
            if not pairs:
                summaries[role.value] = {"status": "no_evidence"}
                continue
            evidence = [*views["prev"], *views["curr"]]
            if self.config.use_slow_update:
                self._proposal_invalid = False
                value = self._ask("slow_update", prompts.SKILLOPT["slow_update"], stage_context,
                    _slow_schema(self.current.get(role), self.config))
                label = "slow_" + role.value
                if value is not None and value["slow_update_content"].strip():
                    content = value["slow_update_content"]
                    if any(marker in content for marker in (longitudinal.SLOW_UPDATE_START, longitudinal.SLOW_UPDATE_END)):
                        self._record_attempt(label, "static_rejected", error="guidance must not contain region markers")
                    else:
                        parent = self.current.get(role)
                        candidate = longitudinal.replace_slow_update_field(parent, content)
                        self._attempt({role: [{"op": "replace" if parent else "append",
                            "target": parent, "content": candidate}]}, evidence, label, allow_slow_update=True)
                else:
                    self._record_attempt(label, "optimizer_invalid" if self._proposal_invalid else "no_change")
            if self.config.use_meta_skill:
                self._proposal_invalid = False
                stage_context = {**stage_context, "epoch_update_feedback": self._epoch_feedback(role)}
                value = self._ask("meta_skill", prompts.SKILLOPT["meta_skill"], stage_context,
                    _object({"reasoning": {"type": "string"}, "meta_skill_content": {"type": "string"}}))
                content = value["meta_skill_content"].strip() if value else ""
                if content:
                    self.meta_skills[role.value] = content
                self._record_attempt("meta_" + role.value,
                    "updated" if content else "optimizer_invalid" if self._proposal_invalid else "no_change",
                    meta_skill_content=self.meta_skills[role.value])
            summaries[role.value] = {"comparison_samples": len(pairs),
                "categories": {key: sum(p["category"] == key for p in pairs) for key in
                    ("improved", "regressed", "persistent_fail", "stable_success")}}
        self.previous_epoch = snapshot
        write_json(directory / "summary.json", {"status": "completed", "epoch": epoch + 1,
            "last_step_skills": snapshot.to_dict(), "result_skills": self.current.to_dict(),
            "meta_skills": self.meta_skills, "roles": summaries})

    def _epoch_feedback(self, role):
        """Only factual, role-relevant attempts from this epoch; no Eval cases."""
        batches = (len(self.train_context.sample_ids) + self.config.batch_size - 1) // self.config.batch_size
        first_step = self.cursor - (2 * batches + 1)
        rows = []
        for item in self.feedback:
            if not first_step <= item["step"] <= self.cursor or item["step_type"] not in {
                    role.value, "joint", "slow_" + role.value}:
                continue
            row = {key: item[key] for key in ("step", "step_type", "status", "parent_pair",
                "candidate_pair", "error", "repeat_deltas", "accepted") if key in item}
            row["phase"] = "after_comparison_snapshot" if item["step"] == self.cursor else "before_comparison_snapshot"
            row["proposed_edits"] = [{"op": edit["op"], "content_preview": edit.get("content", "")[:240]}
                for edit in item.get("proposed_edits", {}).get(role.value, [])]
            rows.append(row)
        return rows

    def _checkpoint(self, baseline_score):
        write_json(self.output / "state" / "trainer.json", {
            "identity": self.identity, "next_step": self.cursor, "current": self.current.to_dict(),
            "epoch_anchor": self.anchor.to_dict(), "feedback": self.feedback, "baseline_score": baseline_score,
            "previous_epoch": self.previous_epoch.to_dict() if self.previous_epoch is not None else None,
            "meta_skills": self.meta_skills})
        self._export_skills("current_skill_set", self.current)

    def _export_skills(self, directory, pair):
        # JSON is the atomic authority for the complete pair; Markdown is an export.
        root = self.output / directory
        write_json(root / "skill_set.json", pair.to_dict())
        for role in Role:
            (root / f"{role.value}.md").write_text(pair.get(role))

    def run(self, resume=False):
        state_path = self.output / "state" / "trainer.json"
        if resume:
            state = json.loads(state_path.read_text())
            if state["identity"] != self.identity:
                raise ValueError("resume requires the same frozen training identity")
            self.current = SkillSet(**state["current"])
            self.anchor = SkillSet(**state["epoch_anchor"])
            self.previous_epoch = SkillSet(**state["previous_epoch"]) if state["previous_epoch"] is not None else None
            self.meta_skills = state["meta_skills"]
            self.cursor, self.feedback = state["next_step"], state["feedback"]
            baseline_score = state["baseline_score"]
        else:
            if state_path.exists():
                raise ValueError("output already has a checkpoint; use resume or a new output directory")
            baseline_score = self._rollout(self.initial, self.eval_context,
                                          self.eval_context.sample_ids, "baseline_eval")["score"]
            self._checkpoint(baseline_score)
        position = 0
        for epoch in range(self.config.epochs):
            ids = list(self.train_context.sample_ids)
            random.Random(self.config.seed + epoch).shuffle(ids)
            if position == self.cursor:
                self.anchor = self.current
                self._checkpoint(baseline_score)
            for start in range(0, len(ids), self.config.batch_size):
                batch = ids[start:start + self.config.batch_size]
                for role in (Role.VIDEO, Role.GLOBAL):
                    if position >= self.cursor:
                        self._record_attempt(role.value, "pending", parent_pair=self.current.skill_set_hash())
                        self._event("step_start", epoch=epoch + 1, role=role.value, samples=len(batch))
                        result = self._rollout(self.current, self.train_context, batch, "train_" + role.value)
                        evidence = self._evidence(result, role, epoch, reference=True)
                        if evidence:
                            edits = self._role_proposal(role, evidence)
                            self._attempt({role: edits}, evidence, role.value)
                        else:
                            self._event("no_evidence", role=role.value)
                            self._record_attempt(role.value, "no_evidence", parent_pair=self.current.skill_set_hash())
                        self.cursor = position + 1
                        self._checkpoint(baseline_score)
                    position += 1
            if position >= self.cursor:
                self._record_attempt("joint", "pending", parent_pair=self.current.skill_set_hash())
                self._event("step_start", epoch=epoch + 1, role="joint")
                self._joint(epoch)
                self.cursor = position + 1
                self._checkpoint(baseline_score)
            position += 1
            if self.config.use_slow_update or self.config.use_meta_skill:
                if position >= self.cursor:
                    self._event("step_start", epoch=epoch + 1, role="slow_meta")
                    self._epoch_update(epoch)
                    self.cursor = position + 1
                    self._checkpoint(baseline_score)
                position += 1
        final = self._paired_evaluation(self.initial, self.current, "final_confirmation", "final_eval")
        changed = self.current != self.initial
        confirmed = changed and final["accepted"]
        selected = self.current if confirmed else self.initial
        selected_side = "candidate" if confirmed else "parent"
        self._export_skills("selected_skill_set", selected)
        summary = {"status": "completed", "completed_steps": self.cursor,
                   "output_selection_rule": OUTPUT_SELECTION_RULE,
                   "evolution_status": "confirmed_improvement" if confirmed else
                       "unconfirmed" if changed else "unchanged",
                   "selected_source": "current" if confirmed else "initial",
                   "baseline_eval_score": baseline_score,
                   "current_confirmation_score": final["candidate_score"],
                   "selected_confirmation_score": final[selected_side + "_score"],
                   "baseline_confirmation_score": final["parent_score"],
                   "final_confirmation": final,
                   "baseline_bucket_scores": final["parent_bucket_scores"],
                   "current_bucket_scores": final["candidate_bucket_scores"],
                   "selected_bucket_scores": final[selected_side + "_bucket_scores"],
                   "current_skill_set_hash": self.current.skill_set_hash(),
                   "selected_skill_set_hash": selected.skill_set_hash(), "config": asdict(self.config),
                   "evaluation_note": "Eval selects updates; it is not an unseen Test set."}
        write_json(self.output / "summary.json", summary)
        self._event("completed", **summary)
        return summary
