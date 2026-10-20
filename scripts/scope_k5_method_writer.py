#!/usr/bin/env python3
"""K5 probe, authoring half: write one strategy per pattern from selector-routed Train cases.

--patterns is a JSON list of {name, description, decision_point, when_to_use, failures: [sid], successes: [sid]};
--cases is t_cases.jsonl from scope_k1_prepare.py. Cases are rendered with the full view under local labels.
Writes <out>/<name>/{input,events,result}.json and a bank-ready <out>/<name>/card.json. Run with PYTHONPATH=src.
"""
from __future__ import annotations

import argparse
import json
import random
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
writer = import_module(SCOPE + ".prompts.method_writer")


def run(optimizer, pattern, cases, out: Path, max_chars: int, seed: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    chosen = pattern["failures"] + pattern["successes"]
    random.Random(seed).shuffle(chosen)
    labels = [f"case_{i}" for i in range(1, len(chosen) + 1)]
    text, dropped = views.render_cases([cases[s] for s in chosen], labels, full=True, max_chars=max_chars)
    user = writer.build_user_prompt(pattern["description"], pattern["decision_point"], pattern["when_to_use"], text)
    (out / "input.json").write_text(json.dumps(dict(system=writer.SYSTEM_PROMPT, user=user, schema=writer.SCHEMA,
                                                    labels=dict(zip(labels, chosen)), dropped=dropped),
                                               indent=1, ensure_ascii=False))
    events = []
    with execution_scope(emit=events.append):
        response = optimizer.json_prompt(user, system_prompt=writer.SYSTEM_PROMPT, json_schema=writer.SCHEMA,
                                         schema_name="scope_method_writer")
    (out / "events.json").write_text(json.dumps(events, indent=1, ensure_ascii=False, default=str))
    response = {k: response.get(k) for k in ("status", "value", "raw_response", "error")}
    try:
        if response["status"] != "ok" or response["value"] is None:
            raise ValueError(response.get("error") or "no structured response")
        validate_json_schema(response["value"], writer.SCHEMA)
        errors = writer.validate(response["value"])
    except (ValueError, KeyError, TypeError) as exc:
        errors = [str(exc)]
    result = dict(response=response, errors=errors, user_chars=len(user))
    (out / "result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    if not errors:
        v = response["value"]
        (out / "card.json").write_text(json.dumps(dict(when_to_use=v["when_to_use"], strategy=v["strategy"]),
                                                  indent=1, ensure_ascii=False))
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--patterns", type=Path, required=True)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--runtime-config", default="configs/skill_evolution/runtime/dynamic_35b_embedding.yaml")
    ap.add_argument("--model", default="glm53_flash_optimizer")
    ap.add_argument("--max-chars", type=int, default=45000)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    optimizer = ModelFactory.create_model(EvolutionModelConfig(model_type=args.model),
                                          MVAgentConfig.from_yaml(args.runtime_config))
    cases = {c["sid"]: c for c in map(json.loads, args.cases.read_text().splitlines())}
    patterns = json.loads(args.patterns.read_text())
    with ThreadPoolExecutor(len(patterns)) as pool:
        futures = {p["name"]: pool.submit(run, optimizer, p, cases, args.out / p["name"], args.max_chars, args.seed)
                   for p in patterns}
    for name, fut in futures.items():
        r = fut.result()
        words = len(((r["response"].get("value") or {}).get("strategy") or "").split())
        print(name, "status", r["response"]["status"], "strategy_words", words, "errors", r["errors"])


if __name__ == "__main__":
    main()
