"""Run the released AgentCVR executor; inputs contain no reference answers."""
import argparse
import copy
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time

from common import write, sha256


class EpisodeTimeout(BaseException):
    pass


def expire(signum, frame):
    raise EpisodeTimeout('Question exceeded 3600 seconds')


def redact_images(value):
    if isinstance(value, str) and value.startswith('data:image/'):
        return {'image_sha256': hashlib.sha256(value.encode()).hexdigest(), 'encoded_bytes': len(value)}
    if isinstance(value, dict):
        return {k: redact_images(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_images(v) for v in value]
    return value


def record_result(output, destination, result):
    calls = result['calls']
    usage = {key: sum(call.get('response', {}).get('usage', {}).get(key, 0) for call in calls)
             for key in ('prompt_tokens', 'completion_tokens')}
    write(output / 'records' / destination.name,
          {k: result[k] for k in ('sample_id', 'rank', 'status', 'answer', 'seconds', 'input_sha256')}
          | {'usage': usage, 'raw_sha256': sha256(destination), 'calls': len(calls)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rank', type=int, required=True)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, '/opt/AgentCVR/agent_system')
    from agent_executor import AgentExecutor
    from qwen_agent import QwenModel
    from utils import video_processor, caption_generator
    import requests
    import whisper

    logging.basicConfig(level=logging.INFO)
    post = requests.post
    audio_load = whisper.load_model
    whisper.load_model = lambda name, **kw: audio_load(
        name, download_root='/weights/Whisper-large-v3', **kw)
    calls = []

    def audited_post(url, **kwargs):
        body = copy.deepcopy(kwargs['json'])
        original_sha = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        # OpenAI requires an identifier; Qwen's chat template ignores this field.
        for index, message in enumerate(body.get('messages', [])):
            if message['role'] == 'tool':
                message.setdefault('tool_call_id', f'observation_{index}')
        body.update(seed=0, return_token_ids=True)
        kwargs['json'] = body
        entry = {'url': url, 'request': redact_images(body), 'original_request_sha256': original_sha,
                 'request_sha256': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
        start = time.monotonic()
        try:
            response = post(url, **kwargs)
            entry.update(http_status=response.status_code, response=response.json())
            return response
        except Exception as exc:
            entry['error'] = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            entry['seconds'] = time.monotonic() - start
            calls.append(entry)

    requests.post = audited_post
    signal.signal(signal.SIGALRM, expire)
    os.environ.update(MASTER_API_BASE_URL=f'http://127.0.0.1:{8100+args.rank*2}/v1/chat/completions',
                      TOOL_API_BASE_URL=f'http://127.0.0.1:{8101+args.rank*2}/v1/chat/completions',
                      MASTER_MODEL_NAME='agentcvr-master', TOOL_MODEL_NAME='agentcvr-vision',
                      MASTER_API_KEY='local', TOOL_API_KEY='local')
    prompt = {'master': str(args.output / 'agent_system.prompt')}
    executor = AgentExecutor(QwenModel(prompt_config=prompt), prompt_config=prompt)
    items = json.loads((args.output / 'items.json').read_text())
    if args.smoke:
        items = [next(x for x in items if x['dataset'] == dataset) for dataset in ('cvbench', 'mvu_eval')]
    else:
        items = items[args.rank::8]
    for item in items:
        sid = item['sample_id']
        destination = args.output / 'raw' / (sid.replace(':', '_') + '.json')
        if destination.exists():
            if not (args.output / 'records' / destination.name).exists():
                record_result(args.output, destination, json.loads(destination.read_text()))
            continue
        assert set(item) == {'sample_id', 'dataset', 'query', 'videos', 'system'}
        calls.clear()
        started = time.monotonic()
        signal.alarm(3600)
        result = {'sample_id': sid, 'rank': args.rank, 'status': 'running', 'answer': '',
                  'input_sha256': hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()}
        try:
            contexts = []
            for video in item['videos']:
                _, _, _, fps, total_frames, duration = video_processor.process_video(
                    video, 1, [(0, 1)], max_length=360, encode=False)
                assert fps > 0 and total_frames > 0 and duration > 0, video
                contexts.append(dict(path=video, fps=fps, total_frames=total_frames,
                                     duration_seconds=duration, clip_begin=0, clip_end=duration))
            executor.master_prompt_template = item['system'] + '\n\n' + Path(prompt['master']).read_text()
            executor.init_agent_state(query=item['query'], possible_answers=[], video_contexts=contexts)
            answer, history = executor.run_agent_loop(max_turns=20)
            payload = json.loads(history[1]['content'][0]['text'])
            assert payload['query'] == item['query'] and 'possible_answers' not in payload
            last = next((m['content'] for m in reversed(history) if m['role'] == 'assistant'), '')
            try:
                answered = executor._parse_llm_response(last).get('action') == 'answer'
            except ValueError:
                answered = False
            result.update(answer=answer, status='answered' if answered else 'no_answer',
                          history=history, tools=executor._tool_history, contexts=contexts)
            if any(c.get('error') or c.get('http_status', 200) >= 400 for c in calls):
                result['transport_errors'] = sum(bool(c.get('error') or c.get('http_status', 200) >= 400)
                                                 for c in calls)
                if not answered:
                    result['status'] = 'infrastructure_error'
        except (Exception, EpisodeTimeout) as exc:
            result.update(status='infrastructure_error', error=f'{type(exc).__name__}: {exc}')
        finally:
            signal.alarm(0)
            result.update(seconds=time.monotonic()-started, calls=calls,
                          upstream_source_sha256=sha256(Path('/opt/AgentCVR/agent_system/agent_executor.py')))
            write(destination, redact_images(result))
            record_result(args.output, destination, result)
            executor.cleanup_agent_state()
        print(json.dumps({k: result[k] for k in ('sample_id', 'status', 'answer', 'seconds')}), flush=True)
        if args.smoke and result['status'] != 'answered':
            raise RuntimeError(f'Smoke episode did not deliver an answer: {sid}')


if __name__ == '__main__':
    main()
