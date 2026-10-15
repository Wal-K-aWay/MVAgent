from __future__ import annotations

from typing import Any, Mapping, Protocol

from models.llm import LLMClient
from models.llm.api.client import ApiLLMClient
from models.vlm.api.client import ApiVLMClient
from models.vlm.local.client import LocalVLLMClient


class ModelReference(Protocol):
    model_type: str


class ModelInstance(Protocol):
    def to_runtime_config(self, name: str, model_ref: ModelReference) -> Any: ...


class ModelRegistryConfig(Protocol):
    models: Mapping[str, ModelInstance]
    runtime: Any


class ModelFactory:
    """Stateless builder for API-backed and local-vLLM clients."""

    @classmethod
    def _resolve_model_instance(
        cls,
        model_name: str,
        config: ModelRegistryConfig | None,
    ) -> ModelInstance:
        if config is None or model_name not in config.models:
            raise ValueError(f"Unknown model instance: {model_name}")
        return config.models[model_name]

    @classmethod
    def create_model(
        cls,
        model_ref: ModelReference,
        config: ModelRegistryConfig | None = None,
    ) -> LLMClient:
        """Build one text or visual model from a named model instance."""
        model_name = str(model_ref.model_type)
        model_cfg = cls._resolve_model_instance(model_name, config)
        runtime_cfg = model_cfg.to_runtime_config(
            model_name,
            model_ref,
        )
        runtime_type = str(getattr(runtime_cfg, "model_type", "") or "")

        if runtime_type == "api_llm":
            model = ApiLLMClient(runtime_cfg)
        elif runtime_type == "local_vllm":
            if config is None:
                raise ValueError(
                    "local_vllm model instances require runtime settings."
                )
            model = LocalVLLMClient(
                runtime_cfg,
                cache_dir=config.runtime.cache_dir,
            )
        elif runtime_type == "api_vlm":
            model = ApiVLMClient(runtime_cfg)
        else:
            raise ValueError(
                f"Unsupported resolved model type: {runtime_type or 'unknown'}"
            )
        return model


__all__ = [
    "ModelFactory",
    "ModelInstance",
    "ModelReference",
    "ModelRegistryConfig",
]
