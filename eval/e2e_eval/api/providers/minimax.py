"""MiniMax China invocation."""

from .common import ModelProfile, base_request


PROFILE = ModelProfile(
    model="MiniMax-M3",
    base_url="https://api.minimaxi.com/v1",
    api_key_env="MINIMAX_API_KEY",
    completion_limit="max_completion_tokens",
    description="MiniMax China official API.",
)


def request_kwargs(messages, **generation):
    request = base_request(PROFILE, messages, **generation)
    request["extra_body"] = {"thinking": {"type": "disabled"}}
    return request
