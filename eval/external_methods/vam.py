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

from common import write
from native_server import validate_card
from transport_audit import audit_httpx



async def infer(args):
    args.output.mkdir(parents=True, exist_ok=True)
    temporary = args.output/'tmp'
    temporary.mkdir(exist_ok=True)
    # VAM atomically renames generated clips into its store; both must share a filesystem.
    tempfile.tempdir = str(temporary)
    sys.path.insert(0, str(args.source))
    os.environ['FRAME_STORE_PATH'] = str(args.output/'memory.sqlite3')
    with urllib.request.urlopen(args.endpoint.rstrip('/')+'/models', timeout=30) as response:
        card = json.load(response)['data'][0]
    validate_card(card)
    write(args.output/'service_card.json', card)
    from vam.config import get_settings
    settings = get_settings()
    settings.llm_model = settings.siliconflow_model_id = card['id']
    settings.llm_max_image_pixels = 448*448
    settings.dashscope_api_key = settings.openrouter_api_key = ''
    settings.siliconflow_api_key = 'local-no-auth'
    settings.siliconflow_base_url = args.endpoint.rstrip('/')
    write(args.output/'effective_config.json', dict(settings=settings.model_dump(
        exclude={'openrouter_api_key', 'siliconflow_api_key', 'dashscope_api_key'}),
        llm_parameter_policy='Original per-call max_tokens, temperature, retries and timeouts; no 2048 fallback',
        agent_entrypoint='vam.agent.stream_agent_response (same as upstream TUI and websocket)',
        adaptations=['local Qwen endpoint/model', 'local original embedding model transport',
                     'temporary files share memory-store filesystem', 'upstream missing re import',
                     'user-approved 448 input limit']))
    audit_httpx(args.output/'requests.jsonl', 'http://127.0.0.1:8200/v1')
    from vam.video import index_video_async
    from vam.jobs import manager as job_manager
    from vam.agent import stream_agent_response
    item = json.loads(args.item.read_text())
    started = time.monotonic()
    job_id = await index_video_async(tmp_path=item['video_path'], cleanup_temp=False,
        fps=settings.video_fps, max_frames=settings.video_max_frames, laplacian_min=settings.video_laplacian_min,
        diff_threshold=settings.video_diff_threshold, ssim_threshold=settings.video_ssim_threshold,
        hist_threshold=settings.video_hist_threshold, similarity_threshold=settings.video_similarity_threshold,
        frame_id_prefix='v', video_absolute_start_time=None, debug=False,
        store_path=str(args.output/'memory.sqlite3'))
    while True:
        job = job_manager.get(job_id)
        write(args.output/'index_progress.json', asdict(job))
        if job.status in ('done','error'):
            break
        await asyncio.sleep(0.25)
    if job.status != 'done' or not job.result['count']:
        raise RuntimeError(f'VAM indexing failed: {job.error or job.result}')
    if job.result.get('filter_report',{}).get('embed_failures',{}).get('count',0):
        raise RuntimeError('VAM index contains failed embeddings; inspect index_progress.json')
    index_seconds = time.monotonic()-started
    query_started = time.monotonic()
    result = None
    with (args.output/'events.jsonl').open('w') as stream:
        async for event in stream_agent_response(transcript=item['question'], history=[]):
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
