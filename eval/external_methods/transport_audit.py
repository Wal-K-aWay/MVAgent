"""Record actual HTTP bodies and latency without changing upstream request/retry logic."""
import hashlib
import io
import json
from pathlib import Path
import time
import threading
import urllib.request

_record_lock = threading.Lock()

def record(path, wire, started, response=None, error=None, status=None):
    row = dict(request_sha256=hashlib.sha256(wire).hexdigest(), request=json.loads(wire),
               seconds=time.monotonic()-started, response=response, error=error, http_status=status)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _record_lock, path.open('a') as stream:
        stream.write(json.dumps(row, ensure_ascii=False)+'\n')


def audit_urllib(path):
    original = urllib.request.urlopen

    def urlopen(request, *args, **kwargs):
        if not isinstance(request, urllib.request.Request) or not request.full_url.endswith('/chat/completions'):
            return original(request, *args, **kwargs)
        started = time.monotonic()
        try:
            with original(request, *args, **kwargs) as response:
                content = response.read()
                record(path, request.data, started, json.loads(content), status=response.status)
            return io.BytesIO(content)
        except Exception as exc:
            record(path, request.data, started, error=type(exc).__name__, status=getattr(exc, 'code', None))
            raise

    urllib.request.urlopen = urlopen


def audit_httpx(path):
    import httpx
    original = httpx.Client.send

    def send(client, request, *args, **kwargs):
        if request.url.path != '/v1/chat/completions':
            return original(client, request, *args, **kwargs)
        started = time.monotonic()
        try:
            response = original(client, request, *args, **kwargs)
            try:
                value = response.json()
            except ValueError:
                value = {'unparsed_body': response.text[:1000]}
            record(path, request.content, started, value, status=response.status_code)
            return response
        except Exception as exc:
            record(path, request.content, started, error=type(exc).__name__)
            raise

    httpx.Client.send = send
