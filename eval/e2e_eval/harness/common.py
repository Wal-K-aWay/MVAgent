"""Paths, file IO and loaders that read protocol pieces straight from the vendored official code."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

E2E_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = E2E_ROOT.parents[1]
CVBENCH_SOURCE = E2E_ROOT / "CVBench"
MVU_SOURCE = E2E_ROOT / "MVU-Eval"
CROSSVID_SOURCE = E2E_ROOT / "CrossVid"
UPSTREAM_COMMITS = {
    "cvbench": "f8dc8f752fb8e7a3a05ac90e9ff9b3a9e90d79ed",
    "mvu_eval": "a5937adea78e9649af53cd9a4e30a91ed7fd3df2",
    "crossvid": "b53ada63551f9ac4a726b381b627d17ece066281",
}


def read_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class JsonlAppender:
    """Thread-safe append-only JSONL writer; every record is flushed before returning."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def git(*args: str) -> str:
    # Copied checkouts (Modal sandboxes) are owned by another uid; trust only this repository.
    return subprocess.run(
        ("git", "-c", f"safe.directory={PROJECT_ROOT}", *args),
        cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()


# ---------------------------------------------------------------------------
# Reading protocol pieces from the official sources instead of re-typing them.
# ---------------------------------------------------------------------------

def _parse(path: Path) -> ast.Module:
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))


def official_function(path: Path, name: str, namespace: dict[str, Any] | None = None) -> Callable:
    """Compile one top-level function from an official file without importing the whole module."""
    for node in _parse(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            scope = dict(namespace or {})
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
            return scope[name]
    raise LookupError(f"{name} not found in {path}")


def official_constant(path: Path, name: str) -> Any:
    """Value of a top-level `NAME = <literal>` assignment in an official file."""
    for node in _parse(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise LookupError(f"{name} not found in {path}")


def official_string(path: Path, needle: str) -> str:
    """The unique string literal in an official file that contains `needle`."""
    found = {
        node.value
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and needle in node.value
    }
    if len(found) != 1:
        raise LookupError(f"expected one string containing {needle!r} in {path}, found {len(found)}")
    return found.pop()


def official_call_kwargs(path: Path, function: str, call: str) -> dict[str, Any]:
    """Literal keyword arguments of the `<...>.<call>(...)` inside an official top-level function."""
    for node in _parse(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == function:
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == call
                ):
                    return {
                        keyword.arg: ast.literal_eval(keyword.value)
                        for keyword in inner.keywords
                        if keyword.arg and isinstance(keyword.value, ast.Constant)
                    }
    raise LookupError(f"{function}() -> .{call}(...) not found in {path}")


_MODULE_LOCK = threading.Lock()


def load_official_module(path: Path, name: str, *, import_root: Path) -> ModuleType:
    """Import an official script whose helpers live in a top-level `utils` package.

    CrossVid and MVU-Eval both ship a package called `utils`; each load gets its own copy so the
    two sources never resolve each other's helpers.
    """
    with _MODULE_LOCK:
        saved = {key: sys.modules.pop(key) for key in list(sys.modules) if key == "utils" or key.startswith("utils.")}
        sys.path.insert(0, str(import_root))
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(import_root))
            for key in [key for key in sys.modules if key == "utils" or key.startswith("utils.")]:
                sys.modules.pop(key)
            sys.modules.update(saved)
