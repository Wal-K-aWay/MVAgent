"""Z.ai GLM invocation."""

from .common import ModelProfile, base_request


PROFILE = ModelProfile(
    model="glm-5.3-flash",
    base_url="https://api.z.ai/api/paas/v4",
    api_key_env="ZAI_API_KEY",
    minimum_output_tokens=512,
    thinking_setting="low (model cannot disable thinking)",
    description="Z.ai official API.",
)


def request_kwargs(messages, **generation):
    request = base_request(PROFILE, messages, **generation)
    request["reasoning_effort"] = "low"
    return request
