"""Translate the legacy HTTP schema envelope without editing historical src."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request


def translate(body):
    result = dict(body)
    form = result.pop('response_format', None)
    if form is not None:
        assert form['type'] == 'json_schema' and form['json_schema']['strict'] is True
        assert 'structured_outputs' not in result
        result['structured_outputs'] = {'json': form['json_schema']['schema']}
    result.update(return_token_ids=True, seed=0, chat_template_kwargs={'enable_thinking': False})
    return result


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and value.startswith('data:'):
        return {'data_url_sha256': hashlib.sha256(value.encode()).hexdigest(), 'length': len(value)}
    return value


class Bridge(HTTPServer):
    def __init__(self, port, backend, log):
        super().__init__(('127.0.0.1', port), Handler)
        self.backend, self.log, self.calls = backend, Path(log), []
        self.log.mkdir(parents=True, exist_ok=True)
        self.sample_id, self.sequence = 'startup', 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.forward(None)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        if not 0 < length <= 2 * 1024**3:
            self.send_error(400, 'Invalid content length')
            return
        self.forward(json.loads(self.rfile.read(length)))

    def forward(self, original):
        server = self.server
        body = translate(original) if original is not None else None
        request = urllib.request.Request(server.backend + self.path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            with server.opener.open(request, timeout=1860) as response:
                data, status = response.read(), response.status
        except urllib.error.HTTPError as exc:
            data, status = exc.read(), exc.code
        except Exception as exc:
            data, status = json.dumps({'error': str(exc)}).encode(), 503
        if original is not None:
            server.sequence += 1
            value = json.loads(data)
            event = {'sample_id': server.sample_id, 'sequence': server.sequence, 'status': status,
                     'request': redact(original), 'translated': redact(body), 'response': value}
            path = server.log / f'{server.sequence:06d}.json'
            path.write_text(json.dumps(event, ensure_ascii=False) + '\n')
            server.calls.append(str(path))
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def self_check():
    schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}}}
    raw = {'model': 'test', 'messages': [{'role': 'user', 'content': 'Q'}],
           'response_format': {'type': 'json_schema', 'json_schema': {'strict': True, 'schema': schema}}}
    out = translate(raw)
    assert out['structured_outputs']['json'] is schema and out['messages'] is raw['messages']
    assert 'response_format' in raw and 'response_format' not in out
    assert 'maxLength' not in json.dumps(out) and out['seed'] == 0
    assert redact({'url': 'data:video/mp4;base64,abc'})['url']['length'] == 25


if __name__ == '__main__':
    self_check()
