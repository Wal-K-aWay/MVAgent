"""Keep VAM's online indexing, memory and retrieval; replace only model transports."""
import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.request

from common import LocalQwen, write


class Embeddings:
    name = 'local-Qwen3-VL-Embedding-8B'

    def _embed(self, inputs):
        vectors = []
        for start in range(0,len(inputs),8):
            request = urllib.request.Request('http://127.0.0.1:8200/embeddings',
                data=json.dumps({'inputs':inputs[start:start+8]}).encode(),
                headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=600) as response:
                result = json.load(response)
            vectors.extend(result['vectors'])
        if not vectors or len(vectors) != len(inputs):
            raise ValueError('Missing VAM embeddings')
        return vectors, len(vectors[0])

    def embed_text(self, text, *, instruction):
        vectors, dim = self.embed_texts_batch([text], instruction=instruction, batch_size=8)
        return vectors[0], dim

    def embed_texts_batch(self, texts, *, instruction, batch_size):
        return self._embed([dict(text=text, instruction=instruction) for text in texts])

    def embed_image_base64(self, image_base64_or_data_uri, *, instruction):
        vectors, dim = self.embed_images_base64_batch([image_base64_or_data_uri], instruction=instruction, batch_size=8)
        return vectors[0], dim

    def embed_images_base64_batch(self, images_base64_or_data_uris, *, instruction, batch_size):
        return self._embed([dict(image=image, instruction=instruction) for image in images_base64_or_data_uris])


async def infer(args):
    args.output.mkdir(parents=True, exist_ok=True)
    temporary = args.output/'tmp'
    temporary.mkdir(exist_ok=True)
    # VAM atomically renames generated clips into its store; both must share a filesystem.
    tempfile.tempdir = str(temporary)
    sys.path.insert(0, str(args.source))
    os.environ['FRAME_STORE_PATH'] = str(args.output/'memory.sqlite3')
    client = LocalQwen(args.endpoint, args.output/'requests.jsonl')
    from vam.config import get_settings
    settings = get_settings()
    settings.llm_model = settings.siliconflow_model_id = client.model
    settings.llm_max_image_pixels = 448*448
    from vam.llm.openrouter import OpenRouterClient
    import vam.vision.backends
    vam.vision.backends.get_backend = lambda: Embeddings()

    async def chat(self, messages, *, temperature=None, max_tokens=None, stream=False, extra_params=None):
        if stream or extra_params:
            raise ValueError('Unexpected VAM streaming/native-tool request')
        value = await asyncio.to_thread(client.chat, messages, max_tokens or 2048)
        return value['choices'][0]['message']['content'], value

    OpenRouterClient._chat_impl = chat
    from vam.video import index_video_async
    from vam.jobs import manager as job_manager
    from vam.retrieval.frame_store import get_store
    from vam.retrieval.agent_search import search_generator
    item = json.loads(args.item.read_text())
    started = time.monotonic()
    job_id = await index_video_async(tmp_path=item['video_path'], cleanup_temp=False,
        fps=settings.video_fps, max_frames=None, laplacian_min=settings.video_laplacian_min,
        diff_threshold=settings.video_diff_threshold, ssim_threshold=settings.video_ssim_threshold,
        hist_threshold=settings.video_hist_threshold, similarity_threshold=settings.video_similarity_threshold,
        frame_id_prefix='input', video_absolute_start_time=None, debug=False,
        store_path=str(args.output/'memory.sqlite3'))
    while True:
        job = job_manager.get(job_id)
        write(args.output/'index_progress.json', asdict(job))
        if job.status in ('done','error'):
            break
        await asyncio.sleep(2)
    if job.status != 'done' or not job.result['count']:
        raise RuntimeError(f'VAM indexing failed: {job.error or job.result}')
    if job.result.get('filter_report',{}).get('embed_failures',{}).get('count',0):
        raise RuntimeError('VAM index contains failed embeddings; inspect index_progress.json')
    index_seconds = time.monotonic()-started
    query_started = time.monotonic()
    result = None
    with (args.output/'events.jsonl').open('w') as stream:
        async for event in search_generator(item['question'], store_instance=get_store(persist_path=str(args.output/'memory.sqlite3'))):
            stream.write(json.dumps(event, ensure_ascii=False)+'\n')
            stream.flush()
            if event['type'] == 'error':
                raise RuntimeError(event)
            if event['type'] == 'final':
                result = event['result']
    if not result or not str(result.get('answer') or '').strip():
        raise RuntimeError('VAM returned no final answer')
    result.update(sample_id=item['sample_id'], seconds=time.monotonic()-started, index=job.result,
                  index_seconds=index_seconds, query_seconds=time.monotonic()-query_started)
    write(args.output/'result.json',result)
    print(json.dumps({k:result.get(k) for k in ('sample_id','answer','seconds','found')}),flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--item',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--endpoint',required=True)
    asyncio.run(infer(p.parse_args()))


if __name__ == '__main__':
    main()
