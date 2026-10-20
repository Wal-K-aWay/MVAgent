#!/usr/bin/env python3
"""K1 probe: run the scope pattern finder on prepared Train samples with the configured optimizer.

Inputs come from scripts/scope_k1_prepare.py. Each sample is rendered with the summary view and sent once;
input, response, program checks and model events are saved per sample. Run with PYTHONPATH=src.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path

from models.execution import execution_scope
from models.factory import ModelFactory
from models.utils import validate_json_schema
from mvagent.configs import MVAgentConfig
from skill_evolution.configs.model_config import EvolutionModelConfig

SCOPE = "skill_evolution.algorithms.alternating.global.scope"
views = import_module(SCOPE + ".views")
finder = import_module(SCOPE + ".prompts.pattern_finder")


def run_sample(optimizer, cases, labels, out: Path, max_chars: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    text, dropped = views.render_cases([cases[s] for s in labels.values()], list(labels), full=False, max_chars=max_chars)
    user = finder.build_user_prompt(text, [])
    (out / "input.json").write_text(json.dumps(dict(system=finder.SYSTEM_PROMPT, user=user, schema=finder.SCHEMA,
                                                    dropped=dropped, labels=labels), indent=1, ensure_ascii=False))
    events = []
    with execution_scope(emit=events.append):
        response = optimizer.json_prompt(user, system_prompt=finder.SYSTEM_PROMPT, json_schema=finder.SCHEMA,
                                         schema_name="scope_pattern_finder")
    (out / "events.json").write_text(json.dumps(events, indent=1, ensure_ascii=False, default=str))
    response = {k: response.get(k) for k in ("status", "value", "raw_response", "error")}
    errors = []
    try:
        if response["status"] != "ok" or response["value"] is None:
            raise ValueError(response.get("error") or "no structured response")
        validate_json_schema(response["value"], finder.SCHEMA)
        fails = {k for k, s in labels.items() if cases[s]["outcome"] != "pass"}
        errors = finder.validate(response["value"], fails, set(labels) - fails)
    except (ValueError, KeyError, TypeError) as exc:
        errors = [str(exc)]
    result = dict(response=response, errors=errors, user_chars=len(user))
    (out / "result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, required=True, help="directory with t_cases.jsonl and k1_sample_*.json")
    ap.add_argument("--runtime-config", default="configs/skill_evolution/runtime/dynamic_35b_embedding.yaml")
    ap.add_argument("--model", default="glm53_flash_optimizer")
    ap.add_argument("--max-chars", type=int, default=45000)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    optimizer = ModelFactory.create_model(EvolutionModelConfig(model_type=args.model),
                                          MVAgentConfig.from_yaml(args.runtime_config))
    cases = {c["sid"]: c for c in map(json.loads, (args.inputs / "t_cases.jsonl").read_text().splitlines())}
    samples = sorted(args.inputs.glob("k1_sample_*.json"))
    with ThreadPoolExecutor(len(samples)) as pool:
        futures = {p.stem: pool.submit(run_sample, optimizer, cases, json.loads(p.read_text()),
                                       args.out / p.stem, args.max_chars) for p in samples}
    for name, fut in futures.items():
        r = fut.result()
        value = r["response"].get("value") or {}
        print(name, "status", r["response"]["status"], "patterns", len(value.get("patterns", [])), "errors", r["errors"])


if __name__ == "__main__":
    main()
