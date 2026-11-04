"""Reuse the existing API clients; credentials remain environment references."""
from pathlib import Path
from urllib.parse import urlparse
import yaml
from models.llm.api import ApiLLMClient
from models.vlm.api import ApiVLMClient
from mvagent.configs.model_config import ApiLLMConfig, ApiVLMConfig
from mvagent.utils.tools import looks_like_env_var_name
from models.utils import is_loopback_host


def validate_model_settings(settings):
    settings = dict(settings)
    if 'local_transport' in settings and settings['local_transport'] != 'standalone':
        raise ValueError('local_transport must be standalone when supplied')
    transport = settings.pop('local_transport', None)
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
    if transport == 'standalone' and not (
            kind == 'api_vlm' and str(config.provider or '').strip() == 'openai_compatible'
            and is_loopback_host(urlparse(config.api_base or '').hostname)):
        raise ValueError('Standalone optimizer requires a loopback OpenAI-compatible API VLM endpoint')
    return config, client_class, transport


def load_client(path):
    config, client_class, transport = validate_model_settings(yaml.safe_load(Path(path).read_text()))
    if transport == 'standalone':
        from models.pool import get_pool
        if get_pool(config.model_name, config.api_base) is not None:
            raise ValueError('Standalone optimizer conflicts with a registered model pool')
    client = client_class(config)
    client.local_transport = transport
    return client
