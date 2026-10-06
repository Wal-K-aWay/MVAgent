import importlib
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple

import yaml

try:
    from .tools import format_header_line
except ImportError:
    tools_path = Path(__file__).resolve().with_name("tools.py")
    tools_spec = importlib.util.spec_from_file_location(
        "_mvagent_snapshot_tools",
        tools_path,
    )
    if tools_spec is None or tools_spec.loader is None:
        raise ImportError(f"Cannot load snapshot tools from {tools_path}")
    tools_module = importlib.util.module_from_spec(tools_spec)
    tools_spec.loader.exec_module(tools_module)
    format_header_line = tools_module.format_header_line


REPO_ROOT = Path(
    os.environ.get("MVAGENT_PROJECT_ROOT")
    or Path(__file__).resolve().parents[3]
).expanduser().resolve()
WORKSPACE_SOURCE_ROOT = REPO_ROOT / "src"
_SENSITIVE_CONFIG_KEY_NAMES = {
    "api_key",
    "secret",
    "password",
    "token",
    "access_token",
    "auth_token",
    "credential",
}
_SENSITIVE_CONFIG_KEY_SUFFIXES = (
    "_api_key",
    "_secret",
    "_password",
    "_token",
    "_credential",
)


def _snapshot_ignore(_directory: str, names: list[str]) -> set[str]:
    """Skip generated caches and inactive binary tool checkpoints."""
    ignored = {
        name
        for name in names
        if name in {
            "__pycache__",
            ".pytest_cache",
            ".venv",
            "checkpoints",
            "vendor",
        }
        or name.endswith((".pyc", ".pyo"))
    }
    return ignored


def _is_sensitive_config_key(key: str) -> bool:
    lowered = key.lower()
    if "key" in lowered or "secret" in lowered:
        return True
    return lowered in _SENSITIVE_CONFIG_KEY_NAMES or lowered.endswith(_SENSITIVE_CONFIG_KEY_SUFFIXES)


def create_timestamp_dir(base_output_dir: str) -> Path:
    """
    Create a unique timestamped output directory for one run.
    
    Args:
        base_output_dir (str): Base output directory under which a timestamped run directory is created.
    
    Returns:
        Path: The resolved filesystem path.
    """
    os.makedirs(base_output_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    unique_id = now.strftime("%f")
    output_dir = Path(base_output_dir) / f"{timestamp}_{unique_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def read_runtime_output_dir(config_path: str, default: str = "outputs") -> str:
    """
    Read runtime.output_dir directly from YAML without importing runtime modules.
    
    Args:
        config_path (str): Path to the YAML configuration file.
        default (str): Default value used when the input cannot be coerced. Defaults to 'outputs'.
    
    Returns:
        str: The generated text result.
    """
    config_file = Path(config_path).expanduser().resolve()
    with open(config_file, "r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    runtime = raw.get("runtime")
    if isinstance(runtime, dict):
        value = runtime.get("output_dir")
        if isinstance(value, str) and value.strip():
            return value
    return default


def ensure_source_snapshot(output_dir: Path) -> Path:
    """
    Create a fresh runtime-package snapshot under the run output directory.
    
    Args:
        output_dir (Path): Directory where generated artifacts are written.
    
    Returns:
        Path: The resolved filesystem path.
    """
    snapshot_root = output_dir / "src"
    snapshot_dir = snapshot_root / "mvagent"
    if snapshot_root.exists():
        if snapshot_root.is_dir():
            shutil.rmtree(snapshot_root)
        else:
            snapshot_root.unlink()

    shutil.copytree(
        WORKSPACE_SOURCE_ROOT,
        snapshot_root,
        ignore=_snapshot_ignore,
    )
    print(f"[OUTPUT] Runtime snapshot saved to: {snapshot_root}")
    return snapshot_dir


def _is_packaged_snapshot(snapshot_dir: Path) -> bool:
    return snapshot_dir.name == "mvagent" and (snapshot_dir / "engine.py").is_file()


def _existing_snapshot_dir(output_dir: Path) -> Path | None:
    """Resolve the current package layout or one legacy flat snapshot."""
    snapshot_root = output_dir / "src"
    packaged = snapshot_root / "mvagent"
    if _is_packaged_snapshot(packaged):
        return packaged
    if (snapshot_root / "engine.py").is_file():
        return snapshot_root
    return None


def activate_snapshot_imports(snapshot_dir: Path) -> None:
    """
    Load project modules from the run snapshot instead of the workspace src.
    
    Args:
        snapshot_dir (Path): Directory containing the runtime source snapshot.
    
    Returns:
        None: None. The function performs its work through side effects.
    """
    resolved = snapshot_dir.resolve()
    import_root = resolved.parent if _is_packaged_snapshot(resolved) else resolved
    snapshot_path = str(import_root)
    if snapshot_path in sys.path:
        sys.path.remove(snapshot_path)
    sys.path.insert(0, snapshot_path)


def _forget_runtime_modules(*, packaged: bool) -> None:
    """Prevent a previously imported workspace Runtime from shadowing a snapshot."""
    if packaged:
        prefixes = ("mvagent", "models", "skill_evolution")
    else:
        prefixes = ("agents", "configs", "engine", "models", "runtime", "skills", "utils")
    for module_name in tuple(sys.modules):
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in prefixes
        ):
            sys.modules.pop(module_name, None)


def load_runtime_modules(snapshot_dir: Path):
    """
    Import configs, engine, and utils from the activated source snapshot.
    
    Args:
        snapshot_dir (Path): Directory containing the runtime source snapshot.
    
    Returns:
        Any: None. The function performs its work through side effects.
    """
    resolved = snapshot_dir.resolve()
    packaged = _is_packaged_snapshot(resolved)
    activate_snapshot_imports(resolved)
    _forget_runtime_modules(packaged=packaged)
    importlib.invalidate_caches()
    if packaged:
        module_names = ("mvagent.configs", "mvagent.engine", "mvagent.utils")
    else:
        module_names = ("configs", "engine", "utils")
    configs, engine, utils = (
        importlib.import_module(module_name) for module_name in module_names
    )
    return configs, engine, utils


def configure_workspace_runtime_env() -> None:
    """Expose workspace deployment paths to source snapshots."""
    os.environ.setdefault("MVAGENT_PROJECT_ROOT", str(REPO_ROOT.resolve()))


def mask_sensitive_data(data: Any) -> Any:
    """
    Recursively mask secret-like values before persisting config snapshots.
    
    Args:
        data (Any): Raw dictionary data to load or inspect.
    
    Returns:
        Any: The computed result of the operation.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if _is_sensitive_config_key(str(key)):
                result[key] = "***" if value else None
            else:
                result[key] = mask_sensitive_data(value)
        return result
    if isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    return data


def _model_instance_type(cfg: Any, model_name: str) -> str:
    models = getattr(cfg, "models", {}) or {}
    model_cfg = models.get(model_name)
    explicit_type = str(getattr(model_cfg, "type", "") or "").strip() if model_cfg is not None else ""
    if explicit_type:
        return explicit_type
    return "unknown"


def _backend_label(model_type: str) -> str:
    if model_type.startswith("api_"):
        return "api"
    return model_type


def save_config(cfg: Any, output_dir: Path, config_source: str, snapshot_dir: Path, entry_script: str) -> None:
    """
    Write the effective runtime config and snapshot metadata into the output directory.
    
    Args:
        cfg (Any): Configuration object used by the current component.
        output_dir (Path): Directory where generated artifacts are written.
        config_source (str): Text value for `config_source`.
        snapshot_dir (Path): Directory containing the runtime source snapshot.
        entry_script (str): Name of the script that launched the current run.
    
    Returns:
        None: None. The function performs its work through side effects.
    """
    config_data = mask_sensitive_data(cfg.to_dict())
    resolved_snapshot = snapshot_dir.resolve()
    code_snapshot_dir = (
        resolved_snapshot.parent
        if _is_packaged_snapshot(resolved_snapshot)
        else resolved_snapshot
    )
    payload = {
        "config_source": config_source or "yaml_file",
        "code_snapshot_dir": str(code_snapshot_dir),
        "entry_script": entry_script,
        "config": config_data,
    }
    config_path = output_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fp:
        yaml.dump(payload, fp, allow_unicode=True, default_flow_style=False)
    print(f"[OUTPUT] Config saved to: {config_path}")


def _format_model_runtime(runtime: dict[str, Any] | None) -> str:
    if not runtime:
        return ""
    status = str(runtime.get("status") or "").strip()
    provider = str(runtime.get("provider") or "").strip()
    model = str(runtime.get("model") or "").strip()
    url = str(runtime.get("url") or "").strip()
    parts = []
    if status:
        parts.append(f"Runtime: {status}")
    if provider:
        parts.append(f"Provider: {provider}")
    if model:
        parts.append(f"Model: {model}")
    if url:
        parts.append(f"URL: {url}")
    return "   ".join(parts)


def print_agent_configs(cfg: Any, *, model_runtime: dict[str, dict[str, Any]] | None = None) -> None:
    """
    Print a compact summary of required Agent roles and their model backends.
    
    Args:
        cfg (Any): Configuration object used by the current component.
    
    Returns:
        None: None. The function performs its work through side effects.
    """
    agent_configs = []
    name_mapping = {
        "global_agent": "Global Agent",
        "video_agent": "Video Agent",
    }
    for attr_name, model_attr, model_cfg in cfg.model_roles():
        agent_configs.append(
            (
                name_mapping.get(attr_name, attr_name.replace("_", " ").title()),
                model_attr,
                model_cfg.model_type,
                _backend_label(_model_instance_type(cfg, model_cfg.model_type)),
            )
        )

    print("[CONFIG] Agent Configurations:")
    print(format_header_line(fill="="))
    runtime_by_model = model_runtime or {}
    for agent_name, model_attr, model_type, backend in sorted(agent_configs):
        line = f"[{agent_name}]   Role: {model_attr}   Model: {model_type}   Backend: {backend}"
        runtime_text = _format_model_runtime(runtime_by_model.get(model_type))
        if runtime_text:
            line = f"{line}   {runtime_text}"
        print(line)
    print(format_header_line(fill="="))


def clean_cache(cache_dir: str) -> None:
    """
    Best-effort cleanup for the runtime cache directory after a run.
    
    Args:
        cache_dir (str): Directory used to store temporary runtime artifacts.
    
    Returns:
        None: None. The function performs its work through side effects.
    """
    cache_path = Path(cache_dir)
    if not cache_path.exists() or not cache_path.is_dir():
        return

    for item in cache_path.iterdir():
        if item.name == "vllm" and item.is_dir():
            continue
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception as exc:
            print(f"[WARN] Failed to clean cache item {item}: {exc}")
    print(f"[CLEAN] Cache cleaned: {cache_path}")


def prepare_run_environment(
    config_path: str,
    output_arg: str | None,
    *,
    reuse_snapshot: bool = False,
) -> Tuple[Path, Path, Any, Any, Any]:
    """
    Create the run directory, snapshot ``mvagent``, and import that frozen Runtime.
    
    Args:
        config_path (str): Path to the YAML configuration file.
        output_arg (str | None): Value for `output_arg`.
        reuse_snapshot (bool): Reuse an existing output-level source snapshot.
    
    Returns:
        Tuple[Path, Path, Any, Any, Any]: The resolved filesystem path.
    """
    config_file = Path(config_path).expanduser().resolve()
    if output_arg:
        output_dir = Path(output_arg).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = create_timestamp_dir(read_runtime_output_dir(str(config_file)))

    if reuse_snapshot:
        snapshot_dir = _existing_snapshot_dir(output_dir)
        if snapshot_dir is None:
            raise FileNotFoundError(
                "Cannot resume without an existing Runtime snapshot under "
                f"{output_dir / 'src'}"
            )
        print(f"[OUTPUT] Reusing Runtime snapshot: {snapshot_dir}")
    else:
        snapshot_dir = ensure_source_snapshot(output_dir)
    configure_workspace_runtime_env()
    configs, engine, utils = load_runtime_modules(snapshot_dir)
    return output_dir, snapshot_dir, configs, engine, utils
