"""Serve VAM's original Qwen3-VL-Embedding model on one reserved GPU."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import io
from pathlib import Path
import sys
import time

from common import write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--port', type=int, default=8200)
    args = p.parse_args()
    sys.path.insert(0, str(args.source/'src/models'))
    import torch
    from PIL import Image
    from qwen3_vl_embedding import Qwen3VLEmbedder
    torch.manual_seed(0)
    model = Qwen3VLEmbedder(str(args.weights), torch_dtype=torch.bfloat16,
                           attn_implementation='sdpa', max_pixels=448*448)
    preprocess = model._preprocess_inputs

    def checked_preprocess(conversations):
        result = preprocess(conversations)
        has_images = any(part.get('type') == 'image' for conversation in conversations
                         for message in conversation for part in message['content'])
        # Upstream catches media failures and embeds the text NULL; never score that as vision.
        if result['input_ids'].shape[0] != len(conversations) or (has_images and 'pixel_values' not in result):
            raise ValueError('Embedding preprocessing lost the requested media or batch')
        return result

    model._preprocess_inputs = checked_preprocess
    write(args.output/'manifest.json', dict(model='Qwen3-VL-Embedding-8B', dtype='bfloat16',
        implementation='official Qwen3VLEmbedder', attention='sdpa', max_pixels=model.max_pixels,
        default_instruction=model.default_instruction, max_length=model.max_length,
        input_protocol='upstream VAM embedding payload and batch boundaries; local official model implementation',
        limitation='Cloud provider internal defaults are not available; input_type is logged, no custom query instruction is injected'))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ready":true}')

        def do_POST(self):
            try:
                wire = self.rfile.read(int(self.headers['Content-Length']))
                body = json.loads(wire)
                if body.get('encoding_format', 'float') != 'float' or body.get('dimensions'):
                    raise ValueError('This local original model uses full-dimensional float embeddings')
                supplied = body['input']
                if not isinstance(supplied, list) or not supplied:
                    raise ValueError('Expected a nonempty embedding input list')
                inputs = []
                for value in supplied:
                    if isinstance(value, str):
                        inputs.append(dict(text=value))
                    else:
                        parts = value['content']
                        if len(parts) != 1 or parts[0].get('type') != 'image_url':
                            raise ValueError('Expected one image per VAM embedding input')
                        uri = parts[0]['image_url']['url']
                        if not isinstance(uri, str) or not uri.startswith('data:image/') or ';base64,' not in uri:
                            raise ValueError('Expected a base64 image data URI')
                        inputs.append(dict(image=Image.open(io.BytesIO(base64.b64decode(
                            uri.split(',',1)[1], validate=True))).convert('RGB')))
                started = time.monotonic()
                vectors = model.process(inputs).float().cpu().tolist()
                result = dict(object='list', model=body['model'], data=[dict(object='embedding', index=i, embedding=v)
                    for i, v in enumerate(vectors)])
                with (args.output/'requests.jsonl').open('a') as stream:
                    stream.write(json.dumps(dict(input_sha256=hashlib.sha256(wire).hexdigest(),
                        count=len(inputs), input_type=body.get('input_type'),
                        seconds=time.monotonic()-started, result=result))+'\n')
                self.send_response(200)
            except Exception as exc:
                result = dict(error=str(exc))
                self.send_response(500)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    HTTPServer(('127.0.0.1',args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
