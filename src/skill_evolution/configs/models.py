"""Reuse the existing API clients; credentials remain environment references."""
from pathlib import Path
import yaml
from models.llm.api import ApiLLMClient
from models.vlm.api import ApiVLMClient
from mvagent.configs.model_config import ApiLLMConfig, ApiVLMConfig
from mvagent.utils.tools import looks_like_env_var_name


def validate_model_settings(settings):
    kind = settings.get('model_type', 'api_vlm')
    config_class, client_class = {
        'api_llm': (ApiLLMConfig, ApiLLMClient),
        'api_vlm': (ApiVLMConfig, ApiVLMClient),
    }[kind]
    config = config_class(**settings)
    if not looks_like_env_var_name(config.api_key):
        raise ValueError('api_key must name an environment variable')
    if config.max_retries != 1:
        raise ValueError('Skill proposals require max_retries: 1 (at most one transient retry)')
    return config, client_class


def load_client(path):
    config, client_class = validate_model_settings(yaml.safe_load(Path(path).read_text()))
    return client_class(config)
