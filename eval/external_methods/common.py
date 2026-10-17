"""Shared IO and the project's fixed local Qwen HTTP protocol."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class LocalQwen:
    def __init__(self, endpoint, audit_path):
        self.endpoint = endpoint.rstrip('/')
        self.audit_path = Path(audit_path)
        with urllib.request.urlopen(self.endpoint + '/models', timeout=30) as response:
            self.model = json.load(response)['data'][0]['id']

    def chat(self, messages, max_tokens=2048, **extra):
        body = dict(model=self.model, messages=messages, temperature=0, seed=0,
                    top_p=1, max_tokens=max_tokens, stream=False,
                    chat_template_kwargs={'enable_thinking': False}, **extra)
        wire = json.dumps(body).encode()
        request = urllib.request.Request(self.endpoint + '/chat/completions', data=wire,
                                        headers={'Content-Type': 'application/json'})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=1860) as response:
            value = json.load(response)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open('a') as stream:
            stream.write(json.dumps(dict(request_sha256=hashlib.sha256(wire).hexdigest(),
                request=body, response=value, seconds=time.monotonic()-started), ensure_ascii=False) + '\n')
        if not value.get('choices'):
            raise ValueError('Local Qwen returned no choices')
        return value
