"""Command-line configuration for one-shot skill generation."""
import argparse
import json
from pathlib import Path

import yaml

from models.vlm.api import ApiVLMClient
from mvagent.configs.model_config import ApiVLMConfig
from mvagent.utils.tools import looks_like_env_var_name
from mvagent.skills.bank import ROLES

from .generator import generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/skill_evolution/llm_generation.yaml")
    parser.add_argument("--runtime-config", default="configs/inference/modal_qwen35_35b_a3b_no_skill.yaml")
    parser.add_argument("--role", choices=(*ROLES, "both"), default="global")
    parser.add_argument("--max-cards", type=int, choices=range(1, 9), default=8,
                        help="Per-role upper bound; the LLM chooses 1..N cards, without filling a quota")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    runtime = yaml.safe_load(Path(args.runtime_config).read_text())
    cfg = ApiVLMConfig(**yaml.safe_load(Path(args.config).read_text()))
    if not looks_like_env_var_name(cfg.api_key):
        raise ValueError("api_key must name an environment variable")
    if cfg.max_retries != 1:
        raise ValueError("One-shot generation requires max_retries: 1 (one attempt)")
    roles = list(ROLES) if args.role == "both" else [args.role]
    summary = generate(ApiVLMClient(cfg), runtime, roles, args.output_dir, args.max_cards)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
