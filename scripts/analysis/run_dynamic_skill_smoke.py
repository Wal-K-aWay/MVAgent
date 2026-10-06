"""Freeze and launch handwritten Skill tests, then audit actual context and actions."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml
from run_action_parameter_validation import score as result_score

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "outputs/analysis/20260922_action_parameter_validation"
DEFAULT = ROOT / "outputs/analysis/20260923_handwritten_v003"
SEED_PANEL = ROOT / "outputs/analysis/20260923_state_aware_skill_smoke/panel.json"
SKILLS_DIR = ROOT / "src/mvagent/skills/authored/dynamic-v003"
BUCKETS = ("crossvid/CC", "crossvid/PI", "crossvid/PSS", "crossvid/FSA",
           "mvu_eval/Comparison", "mvu_eval/Counting", "mvu_eval/TR",
           "cvbench/Joint-video Spatial Navigating")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def prepare(root, *, skills_dir=SKILLS_DIR, per_family=8):
    from mvagent.skills.bank import SkillBank
    spec = importlib.util.spec_from_file_location("manage_skills", ROOT / "scripts/manage_skills.py")
    manage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manage)
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new empty output directory")
    if per_family < 4:
        raise ValueError("Keep all four previous development questions per family")
    root.mkdir(parents=True, exist_ok=True)
    bank = SkillBank.from_dict(dict(schema_version=3, skills=[manage.read_card(p).to_dict()
        for p in sorted(skills_dir.glob("*.json"))]))
    if not bank.cards:
        raise ValueError("No authored skills")
    reference = manage.freeze(bank, root / "skills")
    config = yaml.safe_load((ROOT / "configs/inference/local_qwen35_35b_a3b_historical_no_skill.yaml").read_text())
    for role in ("global_agent", "video_agent"):
        config["agents"][role]["skill"] = dict(reference, selector=dict(model_type='qwen3_5_35b_a3b_local'))
    (root / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    shutil.copy2(ROOT / "configs/inference/execution/gpu2_7_single.yaml", root / "execution.yaml")
    grouped = defaultdict(dict)
    for row in read(PARENT / "panel.json")["samples"]:
        grouped[row["bucket"]][row["sample_id"]] = row
    rows = []
    seeds = read(SEED_PANEL)
    used = {r["group_id"] for r in seeds}
    for bucket in BUCKETS:
        candidates = sorted(grouped[bucket].values(), key=lambda r: hashlib.sha256(
            ("dynamic-smoke-20260922:" + r["sample_id"]).encode()).hexdigest())
        selected = [r for r in seeds if r["bucket"] == bucket]
        if len(selected) != 4:
            raise ValueError("Seed panel must have four questions per family")
        for row in candidates:
            if len(selected) >= per_family:
                break
            if row["group_id"] not in used and row["sample_id"] not in {r["sample_id"] for r in selected}:
                selected.append(row)
                used.add(row["group_id"])
        # Engineering coverage takes precedence over independence in this smoke.
        # Counting has only three known source groups in the retained panel.
        selected_ids = {r["sample_id"] for r in selected}
        selected.extend(r for r in candidates if r["sample_id"] not in selected_ids)
        selected = selected[:per_family]
        if len(selected) != per_family:
            raise ValueError("Insufficient panel coverage: " + bucket)
        rows.extend(selected)
    save(root / "ids.json", [r["sample_id"] for r in rows])
    for row in rows:
        if sha(Path(row["artifact"])) != row["artifact_sha256"]:
            raise ValueError("Historical raw record changed")
    save(root / "panel.json", rows)
    save(root / "protocol.json", dict(
        git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        parent=str(PARENT), skills=reference, count=len(rows), skills_dir=str(skills_dir),
        seed_panel=dict(path=str(SEED_PANEL), sha256=sha(SEED_PANEL)),
        selection=f"Keep previous32; expand to {per_family} per family in SHA256 seed order, prefer unique known groups then fill; no new outcome selection",
        unique_known_groups=len({r["group_id"] for r in rows}),
        scope="Engineering development smoke from an already selected panel; not representative or independent Test",
        no_skill_rerun=False, forced_watch_rerun=False, optimizer=False, api_judge=False,
        immutable_sha256={str(p.relative_to(root)): sha(p) for p in root.rglob("*") if p.is_file()}))


def launch(root, *, skills_dir=SKILLS_DIR, per_family=8):
    if not (root / "protocol.json").exists():
        prepare(root, skills_dir=skills_dir, per_family=per_family)
    if (root / "launch.json").exists():
        raise ValueError("Already launched; inspect saved run state and use the frozen runner to resume")
    protocol = read(root / "protocol.json")
    for name, expected in protocol["immutable_sha256"].items():
        if sha(root / name) != expected:
            raise ValueError("Prepared input changed: " + name)
    # BatchExecutor verifies resident service identity and admission through its normal pool path.
    command = [sys.executable, str(ROOT / "eval/agent_eval/run.py"), "--config", str(root / "config.yaml"),
               "--execution-config", str(root / "execution.yaml"), "--sample-ids-file", str(root / "ids.json"),
               "--output", str(root / "run"), "--defer-open-qa-judge", "--progress-every", "8"]
    with (root / "run.log").open("ab") as log:
        proc = subprocess.Popen(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    save(root / "launch.json", dict(pid=proc.pid, command=command))
    print(json.dumps(dict(pid=proc.pid, output=str(root))))


def summarize(root):
    from mvagent.skills.bank import SkillBank, digest
    protocol = read(root / "protocol.json")
    ref = protocol["skills"]
    bank = SkillBank.load(path=ref["path"], sha256=ref["sha256"])
    old = {r["sample_id"]: r for r in read(root / "panel.json")}
    counts, selections, selected_cards, results = Counter(), Counter(), Counter(), []
    traces = []
    for path in sorted((root / "run/records").glob("*/*/result.json")):
        raw = read(path)
        baseline = old[raw["sample_id"]]
        if sha(Path(baseline["artifact"])) != baseline["artifact_sha256"]:
            raise ValueError("Historical record changed")
        previous = read(Path(baseline["artifact"]))
        if raw["judge_question"] != previous["judge_question"] or raw["ground_truth"] != previous["ground_truth"]:
            raise ValueError("Question/reference mismatch")
        pending, selector_outputs, nodes = {}, {}, {}
        for event in raw["events"]:
            key = event.get("decision_id")
            if event["kind"] == "skill_retrieval":
                nodes[key] = dict(decision_id=key, role=event["role"], stage=event["stage"],
                                  candidate_ids=[c["id"] for c in event["candidates"]])
            elif event["kind"] == "structured_parsed" and event.get("skill_phase") == "selection":
                selector_outputs[key] = event["value"]
            elif event["kind"] == "structured_parsed" and key in nodes:
                nodes[key]["action_decision"] = event["value"]
            elif event["kind"] == "skill_selection":
                if event["status"] == "ok":
                    if event["candidates"]:
                        actual = selector_outputs.pop(key)
                        if actual["selected_skill_ids"] != [c["id"] for c in event["selected"]]:
                            raise ValueError("Recorded selection differs from actual LLM output")
                        counts["selector_outputs_checked"] += 1
                    pending[key] = event
                    nodes.setdefault(key, dict(decision_id=key, role=event["role"], stage=event["stage"]))["selection"] = {k: event[k] for k in ('selected',)}
                    selected_cards.update(c["id"] for c in event["selected"])
                    counts["empty_selections"] += not event["selected"]
                counts["selection_status_" + event["status"]] += 1
                selections[event["role"] + "/" + event["stage"]] += 1
            elif event["kind"] == "structured_request":
                # Use actual message content, preserving newlines for exact inclusion checks.
                text = "\n".join(m["content"] for m in event["messages"] if isinstance(m.get("content"), str))
                if event["schema"] in {"global_decision", "video_action"}:
                    chosen = pending.pop(key)
                    selected_ids = [c["id"] for c in chosen["selected"]]
                    expected = bank.render(selected_ids)
                    if chosen["bank_sha256"] != ref["sha256"] or digest(expected) != chosen["rendered_sha256"]:
                        raise ValueError("Selection provenance mismatch")
                    ids = {c["id"] for c in chosen["selected"]}
                    eligible = {c.id: c for c in bank.eligible(role=chosen["role"], stage=chosen["stage"])}
                    recalled = {c["id"] for c in chosen["candidates"]}
                    if not ids <= eligible.keys() or not ids <= recalled:
                        raise ValueError("Selection outside eligible/retrieved catalog")
                    expected_cards = [eligible[sid] for sid in selected_ids]
                    if chosen["selected"] != [{"id": c.id, "sha256": c.sha256} for c in expected_cards]:
                        raise ValueError("Selected card identities differ from frozen bank")
                    if expected not in text or any(c.render() in text for c in bank.cards if c.id not in ids):
                        raise ValueError("Wrong Skill in actual decision Prompt")
                    counts["decision_prompts_checked"] += 1
                elif event["schema"] == "skill_selection":
                    from mvagent.skills.prompts import selection_input
                    context = event["messages"][-1]["content"]
                    nodes[key].update(time=event['time'], visible_input=context)
                    eligible_ids = {c.id for c in bank.eligible(role=nodes[key]['role'], stage=nodes[key]['stage'])}
                    candidate_ids = nodes[key]['candidate_ids']
                    if not set(candidate_ids) <= eligible_ids:
                        raise ValueError("Selector received a wrong-role/stage candidate")
                    catalog = {c.id: c for c in bank.cards}
                    expected = selection_input('', {}, [catalog[sid] for sid in candidate_ids], role=nodes[key]['role'])
                    separator = "\n\n# Candidate skills\n\n"
                    if context.rpartition(separator)[2] != expected.rpartition(separator)[2] or separator not in context:
                        raise ValueError("Selector catalog differs from frozen metadata")
                    if any(c.render() in text for c in bank.cards):
                        raise ValueError("Selector saw full Skill bodies")
                    counts["selector_prompts_checked"] += 1
                elif any(c.render() in text for c in bank.cards):
                    raise ValueError("Skill leaked into Observer/terminal prompt")
            elif event["kind"] == "model_request":
                messages = event["payload"].get("messages", [])
                visual = any(isinstance(m.get("content"), list) and
                    any(p.get("type") in {"video_url", "image_url"} for p in m["content"])
                    for m in messages)
                if visual:
                    encoded = json.dumps(messages, ensure_ascii=False)
                    if any(json.dumps(c.render(), ensure_ascii=False)[1:-1] in encoded for c in bank.cards):
                        raise ValueError("Skill leaked into visual model request")
                    counts["visual_requests_checked"] += 1
            counts[event["kind"]] += 1
        if pending:
            raise ValueError("Selection without recorded decision request")
        results.append(dict(sample_id=raw["sample_id"], bucket=baseline["bucket"],
                            old_score=result_score(previous), new_score=result_score(raw), status=raw["status"]))
        traces.append(dict(sample_id=raw['sample_id'], record=str(path), question=raw['result'].get('input', {}).get('question'),
                           prediction=raw['prediction'], ground_truth=raw['ground_truth'],
                           old_score=result_score(previous), new_score=result_score(raw),
                           nodes=list(nodes.values()), trajectory=raw['result'].get('trajectory')))
    by_bucket = {}
    for bucket in BUCKETS:
        rows = [r for r in results if r["bucket"] == bucket]
        valid = [r for r in rows if r["new_score"] is not None and r["old_score"] is not None]
        by_bucket[bucket] = dict(completed=len(rows), scored=len(valid),
            old_mean=sum(r["old_score"] for r in valid) / len(valid) if valid else None,
            new_mean=sum(r["new_score"] for r in valid) / len(valid) if valid else None)
    result = dict(completed=len(results), expected=protocol['count'], selections=dict(selections),
                  selected_card_counts=dict(selected_cards),
                  audit=dict(counts), by_bucket=by_bucket, rows=results,
                  scope=protocol["scope"])
    save(root / "audit.json", result)
    save(root / "selection_traces.json", traces)
    print(json.dumps({k:v for k,v in result.items() if k != "rows"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "launch", "summarize"))
    parser.add_argument("--output", type=Path, default=DEFAULT)
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR)
    parser.add_argument("--per-family", type=int, default=8)
    args = parser.parse_args()
    if args.mode == 'summarize':
        summarize(args.output.resolve())
    else:
        {"prepare": prepare, "launch": launch}[args.mode](args.output.resolve(),
            skills_dir=args.skills_dir.resolve(), per_family=args.per_family)


if __name__ == "__main__":
    main()
