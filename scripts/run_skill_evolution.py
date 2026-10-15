#!/usr/bin/env python3
"""Run or independently evaluate Skills with one frozen infrastructure snapshot."""
import argparse
from pathlib import Path
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--execution-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mode", choices=("train", "evaluate"), default="evaluate")
    parser.add_argument("--split-manifest")
    parser.add_argument("--dataset-root")
    parser.add_argument("--skills", help="schema_version=3 Skill bank JSON; omitted means an empty bank")
    parser.add_argument("--split", choices=("train", "cal", "eval", "test"), default="eval")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--repeat-id", default="0")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    # Only the parent bootstraps the workspace. Spawn children inherit frozen sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from mvagent.utils.snapshot import configure_workspace_runtime_env, ensure_source_snapshot, load_runtime_modules
    configure_workspace_runtime_env()
    output = Path(args.output_dir).resolve()
    if args.resume:
        snapshot = output / "src/mvagent"
        if not (snapshot / "engine.py").is_file():
            raise ValueError("Resume requires the existing frozen source")
    else:
        if output.exists() and any(output.iterdir()):
            raise ValueError("A new experiment requires an empty output directory")
        snapshot = ensure_source_snapshot(output)
    load_runtime_modules(snapshot)
    from skill_evolution.runner import run
    run(args)


if __name__ == "__main__":
    main()
