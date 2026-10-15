"""Xiaomi MiMo invocation."""

from .common import ModelProfile, base_request


PROFILE = ModelProfile(
    model="mimo-v2.6-flash",
    base_url="https://api.xiaomimimo.com/v1",
    api_key_env="MIMO_API_KEY",
    completion_limit="max_completion_tokens",
    description="Xiaomi MiMo official API.",
)


def request_kwargs(messages, **generation):
    request = base_request(PROFILE, messages, **generation)
    request["extra_body"] = {"thinking": {"type": "disabled"}}
    return request
