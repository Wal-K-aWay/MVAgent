#!/usr/bin/env python3
"""Derive a run config from the no-Skill Modal config, changing only the Global skill section.

  --static FILE   inject FILE (a rendered card body) at every Global decision, bypassing the selector
  --bank FILE     dynamic schema_version 3 bank with task-scoped selection by the Actor model
Video skills stay disabled. The skill path and SHA256 are pinned in the written config.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml

EMBEDDING = {"endpoint": "http://127.0.0.1:8110/v1", "model": "qwen3_embedding_8b", "timeout_sec": 60}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, default=Path("configs/inference/modal_qwen35_35b_a3b_no_skill.yaml"))
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--static", type=Path)
    mode.add_argument("--bank", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    config = yaml.safe_load(args.base.read_text())
    source = args.static or args.bank
    skill = dict(enabled=True, path=str(source.resolve()), sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    if args.static:
        skill.update(mode="static")
    else:
        model = config["agents"]["global_agent"]["model"]["model_type"]
        skill.update(mode="dynamic", selection_scope="task", selector={"model_type": model}, embedding=EMBEDDING)
    config["agents"]["global_agent"]["skill"] = skill
    config["agents"]["video_agent"]["skill"] = {"enabled": False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(config, sort_keys=False))
    print(args.out, skill["mode"], skill["sha256"][:12])


if __name__ == "__main__":
    main()
