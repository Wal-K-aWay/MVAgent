import argparse
import json
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any


_VIDEO_ID_RE = re.compile(r"^[a-z][A-Za-z0-9_]*$")


def _load_runtime_snapshot() -> ModuleType:
    """Load snapshot helpers without importing the live ``mvagent`` package."""
    module_path = (
        Path(__file__).resolve().parent
        / "src"
        / "mvagent"
        / "utils"
        / "snapshot.py"
    )
    spec = spec_from_file_location("_runtime_snapshot_bootstrap", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_video_inputs(videos: list[str] | None) -> dict[str, str]:
    """Parse repeated bare paths or ``role=path`` video arguments."""

    entries = [str(item).strip() for item in (videos or []) if str(item).strip()]
    if not entries:
        raise ValueError(
            "Provide at least one input video through repeated --video arguments."
        )

    resolved: dict[str, str] = {}
    for index, entry in enumerate(entries, 1):
        if "=" in entry:
            raw_video_id, raw_path = entry.split("=", 1)
            video_id = raw_video_id.strip()
            path = raw_path.strip()
            if not _VIDEO_ID_RE.fullmatch(video_id):
                raise ValueError(f"Invalid video identity: {video_id}")
        else:
            video_id = f"video_{index}"
            path = entry

        if not path:
            raise ValueError(f"Video path is empty for identity: {video_id}")
        if video_id in resolved:
            raise ValueError(f"Duplicate video identity: {video_id}")
        resolved[video_id] = path
    return resolved


def _load_sample_input(input_path: str | Path) -> dict[str, Any]:
    """Load one JSON sample and resolve its relative videos beside the file."""

    path = Path(input_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Sample input JSON not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid sample input JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Sample input JSON root must be an object.")

    question = str(payload.get("question") or "").strip()
    if not question:
        raise ValueError("Sample input question is empty.")
    raw_videos = payload.get("videos")
    if not isinstance(raw_videos, dict) or not raw_videos:
        raise ValueError("Sample input videos must be a non-empty role-to-path object.")

    videos: dict[str, str] = {}
    for raw_video_id, raw_path in raw_videos.items():
        video_id = str(raw_video_id).strip()
        video_path = str(raw_path or "").strip()
        if not _VIDEO_ID_RE.fullmatch(video_id):
            raise ValueError(f"Invalid video identity: {video_id}")
        if video_id in videos:
            raise ValueError(f"Duplicate video identity: {video_id}")
        if not video_path:
            raise ValueError(f"Video path is empty for identity: {video_id}")

        source = Path(video_path).expanduser()
        if not source.is_absolute():
            source = path.parent / source
        videos[video_id] = str(source.resolve())

    raw_options = payload.get("options")
    if raw_options is None:
        options: list[str] = []
    elif isinstance(raw_options, list):
        options = [str(option) for option in raw_options]
    else:
        raise ValueError("Sample input options must be an array.")

    raw_sample_id = payload.get("sample_id")
    sample = {
        "sample_id": "" if raw_sample_id is None else str(raw_sample_id),
        "question": question,
        "videos": videos,
        "options": options,
    }
    if "agent_question" in payload:
        agent_question = str(payload.get("agent_question") or "").strip()
        if not agent_question:
            raise ValueError("Sample input agent_question is empty.")
        sample["agent_question"] = agent_question
    return sample


def _resolve_sample_input(
    *,
    input_path: str | None,
    videos: list[str] | None,
    question: str | None,
) -> dict[str, Any]:
    """Normalize either JSON mode or quick CLI mode into one sample."""

    if input_path:
        if question is not None:
            raise ValueError("--question cannot be used with --input.")
        if videos:
            raise ValueError("--video cannot be used with --input.")
        return _load_sample_input(input_path)

    question_text = str(question or "").strip()
    if not question_text:
        raise ValueError("Quick mode requires --question.")
    return {
        "sample_id": "",
        "question": question_text,
        "videos": _resolve_video_inputs(videos),
        "options": [],
    }


def _build_parser() -> argparse.ArgumentParser:
    """Build the single-question CLI parser."""
    parser = argparse.ArgumentParser(description="MVAgent - Multi-Video Understanding System")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--input",
        default=None,
        help="Path to one sample JSON file",
    )
    input_group.add_argument(
        "--video",
        action="append",
        default=None,
        help="One video path or role=path, repeatable",
    )
    parser.add_argument("--question", default=None, help="Question for --video mode")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--execution-config", help="Required for local model pools")
    parser.add_argument("--output", default=None, help="Output directory path (optional, defaults to timestamped folder)")
    return parser


def main() -> None:
    """Parse CLI args, snapshot src, run one multi-video question, and save outputs."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        sample = _resolve_sample_input(
            input_path=args.input,
            videos=args.video,
            question=args.question,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    runtime_snapshot = _load_runtime_snapshot()
    output_dir, snapshot_dir, configs_module, engine_module, runtime_utils = runtime_snapshot.prepare_run_environment(
        config_path=args.config,
        output_arg=args.output,
    )
    MVAgentConfig = configs_module.MVAgentConfig
    MVAgentEngine = engine_module.MVAgentEngine

    cfg = MVAgentConfig.from_yaml(args.config)
    print(f"[CONFIG] Loaded from: {args.config}")
    print(f"[OUTPUT] Output directory: {output_dir}")
    runtime_snapshot.save_config(
        cfg=cfg,
        output_dir=output_dir,
        config_source=args.config,
        snapshot_dir=snapshot_dir,
        entry_script=Path(__file__).name,
    )
    from mvagent.batch import BatchExecutor, ExecutionConfig
    from models.execution import execution_scope
    batch = BatchExecutor(ExecutionConfig.from_yaml(args.execution_config) if args.execution_config else ExecutionConfig())
    batch.prepare(cfg.to_dict())
    engine = None
    try:
        engine = MVAgentEngine(cfg)
        runtime_snapshot.print_agent_configs(cfg, model_runtime=engine.resolve_models())
        complete_question = sample.get("agent_question") or runtime_utils.compose_question(
            sample["question"], sample["options"]
        )
        with execution_scope(emit=lambda e: None, media_cache=batch.execution.media_cache,
                             media_slots=batch.media_slots):
            result = engine.answer(
                videos=sample["videos"],
                question=complete_question,
                output_dir=str(output_dir),
            )

    finally:
        if engine is not None:
            engine.close()
        batch.close()

    result_path = output_dir / "result.json"
    result_record = {
        "sample_id": sample["sample_id"],
        "options": sample["options"],
        "result": result,
    }
    result_path.write_text(
        json.dumps(result_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OUTPUT] Result saved to: {result_path}")
    print(f"[OUTPUT] Runtime engine module: {engine_module.__file__}")
    print(f"[OUTPUT] Runtime config module: {configs_module.__file__}")

    runtime_snapshot.clean_cache(cfg.runtime.cache_dir)

if __name__ == "__main__":
    main()
