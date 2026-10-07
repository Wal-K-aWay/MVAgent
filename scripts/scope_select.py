#!/usr/bin/env python3
"""Selector-only pass: which Global card the runtime selector picks for each question, without rollouts.

Builds each question's GlobalAgent through MVAgentEngine._preprocess (same question text, video probing and
initial History as a real run) and calls select_skills with the agent's own fields and decide function, so
the selector request matches the first decision of a rollout. Video skills are disabled, as in Global-only
evolution. Run on the GPU dev box with PYTHONPATH=src; outputs one JSON line per question.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import yaml

from models.execution import execution_scope
from models.pool import install_pools
from mvagent.batch import ExecutionConfig, prepare_model_pools
from mvagent.configs import MVAgentConfig
from mvagent.engine import MVAgentEngine
from mvagent.skills.selection import select_skills
from skill_evolution.infra.benchmarks.catalog import load_multibench_records


def runtime_config(path: str, bank: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text())
    skill = data["agents"]["global_agent"]["skill"]
    skill.update(enabled=True, mode="dynamic", path=str(bank.resolve()),
                 sha256=hashlib.sha256(bank.read_bytes()).hexdigest())
    data["agents"]["video_agent"]["skill"] = {"enabled": False}
    return data


def select_one(engine: MVAgentEngine, sample) -> dict:
    events = []
    with tempfile.TemporaryDirectory() as tmp, execution_scope(emit=events.append):
        agent, _ = engine._preprocess(videos=sample.videos, question=sample.question, output_dir=tmp)
        decide = (agent.decide_json if agent.skill_selector_model is None else
                  lambda *a, **k: agent.decide_json(*a, model=agent.skill_selector_model, **k))
        result = select_skills(agent.decision_skill, selection_cache={}, role="global", has_evidence=False,
                               task=agent.question,
                               state=dict(history=agent.memory.render_action_history(),
                                          videos={vid: {"duration_sec": meta["duration_sec"]}
                                                  for vid, meta in agent.video_metadata.items()} or agent.video_ids),
                               decide=decide)
    selection = next((e for e in events if e.get("kind") == "skill_selection"), {})
    retrieval = next((e for e in events if e.get("kind") == "skill_retrieval"), {})
    return dict(status=result.get("status"), error=result.get("error"),
                selected=[s["id"] for s in selection.get("selected", [])],
                candidates=[c["id"] for c in retrieval.get("candidates", [])])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bank", type=Path, required=True, help="schema_version 3 bank JSON")
    ap.add_argument("--ids", type=Path, required=True, help="JSON array of sample IDs")
    ap.add_argument("--runtime-config", default="configs/skill_evolution/runtime/dynamic_35b_embedding.yaml")
    ap.add_argument("--execution-config", default="configs/inference/execution/modal_h200x8.yaml")
    ap.add_argument("--dataset-root", default="/assets")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    config_data = runtime_config(args.runtime_config, args.bank)
    pools, failures = prepare_model_pools(config_data, ExecutionConfig.from_yaml(args.execution_config))
    if failures:
        raise RuntimeError(f"model pools unavailable: {failures}")
    install_pools(pools)
    ids = json.loads(args.ids.read_text())
    records = load_multibench_records(args.dataset_root, ids)
    local = threading.local()

    def run(sid):
        if not hasattr(local, "engine"):
            local.engine = MVAgentEngine(MVAgentConfig.from_dict(deepcopy(config_data)), logger=lambda _: None)
            local.engine.resolve_models()
        try:
            return dict(sample_id=sid, **select_one(local.engine, records[sid].sample))
        except Exception as exc:  # recorded per question; the summary counts them
            return dict(sample_id=sid, status="error", error=f"{type(exc).__name__}: {exc}", selected=[], candidates=[])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.workers) as pool, args.out.open("w") as f:
        for row in pool.map(run, ids):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    rows = [json.loads(line) for line in args.out.read_text().splitlines()]
    picked = {}
    for r in rows:
        for cid in r["selected"]:
            picked[cid] = picked.get(cid, 0) + 1
    print(json.dumps(dict(questions=len(rows), errors=sum(r["status"] != "ok" for r in rows),
                          none=sum(not r["selected"] for r in rows), selected=picked)))


if __name__ == "__main__":
    main()
