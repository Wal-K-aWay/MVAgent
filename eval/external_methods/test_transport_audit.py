"""Remote CPU check: HTTP audit preserves upstream payloads and actual wire hashes."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import tempfile
import threading
import urllib.request
import httpx
from transport_audit import audit_httpx, audit_urllib


def main():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers['Content-Length']))))
            content = b'{"choices":[{"message":{"content":"ok"}}]}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    with tempfile.TemporaryDirectory() as temporary, HTTPServer(('127.0.0.1', 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        endpoint = f'http://127.0.0.1:{server.server_port}/v1'
        path = Path(temporary)/'requests.jsonl'
        payload = dict(model='local', messages=[dict(role='user', content='保持原参数')], temperature=.1, max_tokens=700)
        original_urlopen, original_send, original_post = urllib.request.urlopen, httpx.AsyncClient.send, httpx.post
        try:
            audit_urllib(path)
            audit_httpx(path, endpoint)
            with urllib.request.urlopen(urllib.request.Request(endpoint+'/chat/completions', data=json.dumps(payload).encode()), timeout=5) as response:
                assert json.load(response)['choices'][0]['message']['content'] == 'ok'

            async def request():
                async with httpx.AsyncClient() as client:
                    assert (await client.post(endpoint+'/chat/completions', json=payload)).status_code == 200

            asyncio.run(request())
            embedding = dict(model='original-embedding', input=['one','two'], encoding_format='float', input_type='search_query')
            httpx.post('http://unused.invalid/v1/embeddings', json=embedding, timeout=5)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            assert len(rows) == 2 and len(received) == 3
            assert received[1][1] == json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
            for row, (url, wire) in zip(rows, received):
                assert row['request'] == payload and row['seconds'] >= 0
                assert row['request_sha256'] == hashlib.sha256(wire).hexdigest()
                assert url == '/v1/chat/completions'
            assert received[-1][0] == '/v1/embeddings' and json.loads(received[-1][1]) == embedding
        finally:
            urllib.request.urlopen, httpx.AsyncClient.send, httpx.post = original_urlopen, original_send, original_post
            server.shutdown()
            worker.join()
    print('Native transport payload and timing audit checks passed')


if __name__ == '__main__':
    main()
