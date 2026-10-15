from __future__ import annotations

import json
from typing import Any, Callable

from mvagent.configs import Agent_Model_Config, MVAgentConfig


ModelBuilder = Callable[[Agent_Model_Config], Any]
class RuntimeResources:
    """Own reusable model clients for one Engine."""

    def __init__(
        self,
        cfg: MVAgentConfig,
        *,
        model_builder: ModelBuilder,
    ) -> None:
        self.cfg = cfg
        self._model_builder = model_builder
        self._models: dict[str, Any] = {}
        self._model_runtime: dict[str, dict[str, str]] = {}
        self._closed = False

    @staticmethod
    def _model_key(model_ref: Agent_Model_Config) -> str:
        return json.dumps(
            model_ref.to_dict(mask_api_key=False),
            sort_keys=True,
            default=str,
        )

    def get_model(self, model_ref: Agent_Model_Config) -> Any:
        """Build once and return the Engine-owned client for a model reference."""
        if self._closed:
            raise RuntimeError("RuntimeResources is closed.")
        key = self._model_key(model_ref)
        if key not in self._models:
            model = self._model_builder(model_ref)
            self._models[key] = model
            self._record_model_runtime(model_ref.model_type, model)
        return self._models[key]

    def resolve_models(self) -> dict[str, dict[str, str]]:
        """Eagerly resolve all model roles enabled by the configuration."""
        for _agent_name, _role_name, model_ref in self.cfg.model_roles():
            self.get_model(model_ref)
        return {
            model_name: dict(status)
            for model_name, status in self._model_runtime.items()
        }

    def _record_model_runtime(self, model_name: str, model: Any) -> None:
        runtime_status = getattr(model, "runtime_status", None)
        if callable(runtime_status):
            runtime = runtime_status()
            if isinstance(runtime, dict):
                self._model_runtime[model_name] = {
                    str(key): str(value)
                    for key, value in runtime.items()
                    if value is not None and str(value).strip()
                }
                return

        runtime = {"status": "api"}
        cfg = getattr(model, "cfg", None)
        provider = str(getattr(cfg, "provider", "") or "").strip()
        configured_model = str(getattr(cfg, "model_name", "") or "").strip()
        if provider:
            runtime["provider"] = provider
        if configured_model:
            runtime["model"] = configured_model
        self._model_runtime[model_name] = runtime

    def close(self) -> None:
        """Close each owned model client once without stopping persistent servers."""
        if self._closed:
            return
        self._closed = True

        resources = list(self._models.values())
        seen: set[int] = set()
        for resource in resources:
            if resource is None or id(resource) in seen:
                continue
            seen.add(id(resource))
            close_fn = getattr(resource, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass
        self._models.clear()
        self._model_runtime.clear()
