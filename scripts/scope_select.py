#!/usr/bin/env python3
"""Selector-only pass: which Global card the runtime selector picks for each question, without rollouts.

Builds each question's GlobalAgent once through MVAgentEngine._preprocess (same question text, video probing
and initial History as a real run), then calls select_skills with the agent's own fields and decide function
for every given bank, so each selector request matches the first decision of a rollout with that bank. Video
skills are disabled, as in Global-only evolution. Run on the GPU dev box with PYTHONPATH=src.
Writes <out-dir>/<bank stem>.jsonl, one line per question.
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
from mvagent.skills import SkillBank
from mvagent.skills.selection import select_skills
from skill_evolution.infra.benchmarks.catalog import load_multibench_records


def runtime_config(path: str, bank: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text())
    skill = data["agents"]["global_agent"]["skill"]
    skill.update(enabled=True, mode="dynamic", path=str(bank.resolve()),
                 sha256=hashlib.sha256(bank.read_bytes()).hexdigest())
    data["agents"]["video_agent"]["skill"] = {"enabled": False}
    return data


def select(agent, bank: SkillBank) -> dict:
    events = []
    decide = (agent.decide_json if agent.skill_selector_model is None else
              lambda *a, **k: agent.decide_json(*a, model=agent.skill_selector_model, **k))
    with execution_scope(emit=events.append):
        result = select_skills(bank, selection_cache={}, role="global", has_evidence=False, task=agent.question,
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
    ap.add_argument("--bank", type=Path, action="append", required=True, help="schema_version 3 bank JSON (repeatable)")
    ap.add_argument("--ids", type=Path, required=True, help="JSON array of sample IDs")
    ap.add_argument("--runtime-config", default="configs/skill_evolution/runtime/dynamic_35b_embedding.yaml")
    ap.add_argument("--execution-config", default="configs/inference/execution/modal_h200x8.yaml")
    ap.add_argument("--dataset-root", default="/assets")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    config_data = runtime_config(args.runtime_config, args.bank[0])
    pools, failures = prepare_model_pools(config_data, ExecutionConfig.from_yaml(args.execution_config))
    if failures:
        raise RuntimeError(f"model pools unavailable: {failures}")
    install_pools(pools)
    skill = MVAgentConfig.from_dict(deepcopy(config_data)).global_agent.skill
    banks = {p.stem: SkillBank.load(path=str(p.resolve()), sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                    retrieval_top_k=skill.retrieval_top_k, embedding=skill.embedding)
             for p in args.bank}
    ids = json.loads(args.ids.read_text())
    records = load_multibench_records(args.dataset_root, ids)
    local = threading.local()

    def run(sid):
        if not hasattr(local, "engine"):
            local.engine = MVAgentEngine(MVAgentConfig.from_dict(deepcopy(config_data)), logger=lambda _: None)
            local.engine.resolve_models()
        sample = records[sid].sample
        try:
            with tempfile.TemporaryDirectory() as tmp:
                agent, _ = local.engine._preprocess(videos=sample.videos, question=sample.question, output_dir=tmp)
                return sid, {name: select(agent, bank) for name, bank in banks.items()}
        except Exception as exc:  # recorded per question; the summary counts them
            err = dict(status="error", error=f"{type(exc).__name__}: {exc}", selected=[], candidates=[])
            return sid, {name: err for name in banks}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    streams = {name: (args.out_dir / f"{name}.jsonl").open("w") for name in banks}
    with ThreadPoolExecutor(args.workers) as pool:
        for sid, by_bank in pool.map(run, ids):
            for name, row in by_bank.items():
                streams[name].write(json.dumps(dict(sample_id=sid, **row), ensure_ascii=False) + "\n")
                streams[name].flush()
    for name, stream in streams.items():
        stream.close()
        rows = [json.loads(line) for line in (args.out_dir / f"{name}.jsonl").read_text().splitlines()]
        picked = {}
        for r in rows:
            for cid in r["selected"]:
                picked[cid] = picked.get(cid, 0) + 1
        print(name, json.dumps(dict(questions=len(rows), errors=sum(r["status"] != "ok" for r in rows),
                                    none=sum(not r["selected"] for r in rows), selected=picked)))


if __name__ == "__main__":
    main()
