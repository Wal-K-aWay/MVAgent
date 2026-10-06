"""Registry of the deliberately small provider-specific invocation scripts."""

from . import deepseek, glm, mimo, minimax, qwen


PROVIDERS = {
    provider.PROFILE.model: provider
    for provider in (qwen, mimo, glm, minimax, deepseek)
}
MODEL_PROFILES = {model: provider.PROFILE for model, provider in PROVIDERS.items()}


def provider_for(model: str):
    try:
        return PROVIDERS[model]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported model {model!r}; choose one of: {', '.join(PROVIDERS)}"
        ) from exc
