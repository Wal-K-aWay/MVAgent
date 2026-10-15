"""Audit an alternating run with no accepted updates, without inference or rescoring."""
import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
from types import SimpleNamespace


def read(path):
    return json.loads(path.read_text())


def video_runs(row):
    return [event for event in row["result"]["trajectory"]
            if event.get("agent") == "VideoAgent" and event["action"] == "run"]


def first_global_decision(row):
    decision = next(event["output"] for event in row["result"]["trajectory"]
                    if event.get("agent") == "GlobalAgent" and event["action"] == "decide")
    return {key: decision.get(key) for key in ("action", "parameters")}


def invalid_decisions(row):
    decisions = [("global", item) for item in row["result"]["action_history"]]
    decisions += [("video", {"video_id": run["video_id"], **item})
                  for run in video_runs(row) for item in run["output"].get("steps", [])]
    return [{"role": role, **item} for role, item in decisions
            if item.get("action") == "invalid_decision" or item.get("status") == "invalid"
            or item.get("result", {}).get("status") == "invalid"]


def macro(rows):
    tasks = defaultdict(list)
    for row in rows.values():
        weight = len(row["ground_truth"]) if row["output_task"] == "open_qa" else 1
        tasks[(row["dataset"], row["task"])].append((row["score"], weight))
    datasets = defaultdict(list)
    for (dataset, _), values in tasks.items():
        datasets[dataset].append(sum(score * weight for score, weight in values)
                                 / sum(weight for _, weight in values))
    return mean(mean(values) for values in datasets.values())


def counts(rows):
    total = Counter()
    for row in rows.values():
        result = row["result"]
        total.update(global_decisions=sum(t.get("agent") == "GlobalAgent" and
                     t["action"] == "decide" for t in result["trajectory"]),
                     video_runs=len(video_runs(row)),
                     watch=sum(t["action"] == "watch_videos" for t in result["action_history"]))
        for run in video_runs(row):
            steps = run["output"].get("steps", [])
            total["observe"] += sum(s["action"] == "observe" for s in steps)
            total["video_decisions"] += sum(not s.get("result", {}).get("terminal") for s in steps)
            total["failed_video_requests"] += run["output"].get("status") == "error"
            total["failed_observes"] += sum(s["action"] == "observe" and
                s.get("result", {}).get("status") == "error" for s in steps)
            total["video_finalizers"] += sum(bool(s.get("result", {}).get("terminal")) for s in steps)
        total["invalid"] += len(invalid_decisions(row))
    return dict(total)


def audit(root):
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    assert not any(e.get("accepted") for e in events), "This audit expects no accepted updates."
    manifest = read(root / "run_manifest.json")
    eval_ids = manifest["eval_sample_ids"]
    train_ids = manifest["train_sample_ids"]
    assert not set(eval_ids) & set(train_ids)
    parent_hash = next(e["pair"] for e in events if e["kind"] == "rollout_start")

    # Reuse the historical Gate's exact health function, without importing its runtime.
    source = (root / "src/skill_evolution/alternating.py").read_text()
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == "episode_health")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "frozen_episode_health", "exec"), namespace)
    health = lambda row: namespace["episode_health"](SimpleNamespace(artifact=row, status=row["status"]))

    def rows(pair, ids):
        folder = root / "candidates" / ("candidate-" + pair[:16]) / "questions"
        result = {sid: read(folder / sid / "result.json") for sid in ids}
        assert all(row["sample_id"] == sid for sid, row in result.items())
        return result

    parent = rows(parent_hash, eval_ids)
    train = rows(parent_hash, train_ids)
    parent_health = {sid: health(row) for sid, row in parent.items()}
    steps = {}
    for event in events:
        if event["kind"] == "step_start":
            steps[event["step"]] = {"step": event["step"], "epoch": event["epoch"],
                                    "role": event["role"]}
        elif event["kind"] == "proposal":
            steps[event["step"]]["edits"] = event["edits"]
        elif event["kind"] == "proposal_invalid":
            steps[event["step"]].update(outcome="text_rejected", reason=event["reason"])
        elif event["kind"] == "gate":
            candidate = rows(event["candidate_pair"], eval_ids)
            assert abs(macro(parent) - event["parent_score"]) < 1e-12
            assert abs(macro(candidate) - event["candidate_score"]) < 1e-12
            pairs = {}
            for sid, before in parent.items():
                after = candidate[sid]
                assert before["result"]["input"] == after["result"]["input"]
                assert before["ground_truth"] == after["ground_truth"]
                after_health = health(after)
                regression = any(after_health[k] > parent_health[sid][k] for k in ("fatal", "invalid"))
                pairs[sid] = dict(score_before=before["score"], score_after=after["score"],
                    prediction_before=before["prediction"], prediction_after=after["prediction"],
                    health_before=parent_health[sid], health_after=after_health,
                    reliability_regression=regression,
                    invalid_before=invalid_decisions(before), invalid_after=invalid_decisions(after),
                    first_global_action_parameters_equal=first_global_decision(before) == first_global_decision(after),
                    video_runs_before=len(video_runs(before)), video_runs_after=len(video_runs(after)))
            regression_ids = [sid for sid, p in pairs.items() if p["reliability_regression"]]
            assert len(regression_ids) == event["new_reliability_regressions"]
            assert event["accepted"] == (event["candidate_score"] > event["parent_score"] and not regression_ids)
            inactive = [sid for sid, p in pairs.items() if p["video_runs_before"] == p["video_runs_after"] == 0]
            inactive_changed = [sid for sid in inactive if pairs[sid]["score_before"] != pairs[sid]["score_after"]]
            role_delta = {name: sum(p["score_after"] > p["score_before"] if name == "improved" else
                                   p["score_after"] < p["score_before"] if name == "regressed" else
                                   p["score_after"] == p["score_before"] for p in pairs.values())
                          for name in ("improved", "regressed", "unchanged")}
            steps[event["step"]].update(outcome="accepted" if event["accepted"] else "gate_rejected",
                candidate=event["candidate_pair"], score=event["candidate_score"],
                delta=event["score_delta"], reliability_regression_ids=regression_ids,
                inactive_both=inactive, inactive_score_changed=inactive_changed,
                score_changes=role_delta, counts=counts(candidate), pairs=pairs)

    calls = {p.stem: read(p) for p in (root / "optimizer_calls").glob("*.json")}
    starts = [e for e in events if e["kind"] == "optimizer_start"]
    assert set(calls) == {e["call"] for e in starts}
    evidence = defaultdict(dict)
    evidence_by_step = defaultdict(list)
    for event in starts:
        call = calls[event["call"]]
        if call["stage"] in ("analyst_error", "analyst_success"):
            role = call["context"]["target_role"]
            for item in call["context"]["trajectories"]:
                evidence[role][item["case_ref"]] = item
                evidence_by_step[event["step"]].append(item)
    for step, items in evidence_by_step.items():
        steps[step]["reflection"] = dict(trajectories=len(items),
            successes=sum(t["system_success"] for t in items),
            unique_questions=len({t["question_ref"] for t in items}))

    joint_calls = [{"step": event["step"], "previous_skills": calls[event["call"]]["context"]["previous_skills"],
                    "question_ids": sorted({t["question_ref"] for t in
                        calls[event["call"]]["context"]["current_trajectories"]})}
                   for event in starts if event["stage"] == "joint"]
    for step in steps.values():
        if step["role"] == "joint":
            step["copied_prior_proposal_roles"] = {
                role: [old["step"] for old in steps.values() if old["step"] < step["step"]
                       and old["edits"].get(role) and
                       old["edits"][role][0]["content"].strip() == edits[0]["content"].strip()]
                for role, edits in step["edits"].items()}
    prompt_root = root / "src/skill_evolution/prompts/upstream"
    provenance = read(prompt_root / "provenance.json")
    for name, entry in provenance["files"].items():
        assert hashlib.sha256((prompt_root / name).read_bytes()).hexdigest() == entry["sha256"]
    rollouts = [e for e in events if e["kind"] == "rollout_done"]
    optimizer_done = [e for e in events if e["kind"] == "optimizer_done"]
    return dict(run=str(root.resolve()), health_source_sha256=hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest(),
        event_counts=dict(Counter(e["kind"] for e in events)),
        optimizer_stages=dict(Counter(c["stage"] for c in calls.values())),
        optimizer_statuses=dict(Counter(c["status"] for c in calls.values())),
        upstream_prompt_hashes_verified=True,
        baseline_score=macro(parent), baseline_counts=counts(parent),
        train_counts=counts(train),
        train_video_active=sum(bool(video_runs(r)) for r in train.values()),
        eval_video_active=sum(bool(video_runs(r)) for r in parent.values()),
        eval_task_sizes=dict(Counter(f'{r["dataset"]}/{r["task"]}' for r in parent.values())),
        train_task_sizes=dict(Counter(f'{r["dataset"]}/{r["task"]}' for r in train.values())),
        generated=sum(e["generated"] for e in rollouts),
        elapsed_seconds=events[-1]["time"]-events[0]["time"],
        optimizer_seconds=sum(e["seconds"] for e in optimizer_done),
        rollout_seconds=sum(e["seconds"] for e in rollouts),
        candidate_eval_seconds=sum(e["seconds"] for e in rollouts if e["label"] in ("video", "global", "joint")),
        unique_candidates=len({s["candidate"] for s in steps.values() if "candidate" in s}),
        evidence={role: {"unique_trajectories": len(items),
                         "unique_questions": len({t["question_ref"] for t in items.values()}),
                         "success_trajectories": sum(t["system_success"] for t in items.values()),
                         "memory_none": sum("Memory: None" in t["trajectory"] for t in items.values())}
                  for role, items in evidence.items()},
        joint_calls=joint_calls, steps=list(steps.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = ["| Step | Role | Outcome | Score | Delta (pp) | New reliability cases |",
             "|---:|---|---|---:|---:|---:|"]
    for step in result["steps"]:
        score = f'{step["score"]:.2%}' if "score" in step else "—"
        delta = f'{100 * step["delta"]:+.2f}' if "delta" in step else "—"
        reliability = len(step["reliability_regression_ids"]) if "score" in step else "—"
        lines.append(f'| {step["step"]} | {step["role"]} | {step["outcome"]} | {score} | {delta} | {reliability} |')
    (args.output / "candidates.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("steps", "joint_calls")}, indent=2))


if __name__ == "__main__":
    main()
