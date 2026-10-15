"""Run the released Video-RSI harness with local Qwen for both model roles."""
import argparse
import json
from pathlib import Path
import sys
import time

from common import LocalQwen, write


class Provider:
    def __init__(self, client, vision_max_tokens=2048):
        self.client = client
        self.vision_max_tokens = vision_max_tokens
        self.meter = None

    def chat(self, role, messages, frames=0, payload_extra=None, before_attempt=None):
        if payload_extra:
            raise ValueError('Unexpected native tool payload; final harness uses JSON decisions')
        if before_attempt:
            before_attempt()
        event = dict(kind='provider', role=role, frames=frames, status='pending')
        self.meter.events.append(event)
        started = time.monotonic()
        try:
            value = self.client.chat(messages, max_tokens=self.vision_max_tokens if role == 'qwen' else 8192)
            event.update(status='ok', usage=value['usage'], audit=value.get('audit'),
                         response_model=value['model'])
            return value
        except Exception as exc:
            event.update(status='error', error=str(exc))
            raise
        finally:
            event['latency_seconds'] = time.monotonic()-started


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--item', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--endpoint')
    p.add_argument('--preflight', action='store_true')
    p.add_argument('--vision-max-tokens', type=int, default=2048)
    args = p.parse_args()
    if not 1 <= args.vision_max_tokens <= 8192:
        p.error('--vision-max-tokens must be between 1 and 8192')
    sys.path.insert(0, str(args.source))
    from solver_full_workspace.engine.runner import run_item
    from solver_full_workspace.engine.services import Services, OfflineProvider
    item = json.loads(args.item.read_text())
    config = json.loads((args.source/'config.example.json').read_text())
    # Modal lacks Landlock; keep candidate seccomp and the outer Modal sandbox.
    config['execution'].update(concurrency=1, python=sys.executable, linux_isolation=False)
    config['services']['ffmpeg'] = 'ffmpeg'
    config['services']['ocr_model_root'] = '/runs/devbox/external_methods_20261014/ocr_models'
    provider = (OfflineProvider() if args.preflight else
                Provider(LocalQwen(args.endpoint, args.output/'requests.jsonl'), args.vision_max_tokens))
    services = Services(item, {'video_path': item['video_path']}, config,
                        args.output/'scratch', provider=provider)
    started = time.monotonic()
    result = run_item(args.source/'artifacts/final_harness', item, services, config,
                      check_only=args.preflight)
    result.update(seconds=time.monotonic()-started, source='released final_harness + recorded adapter patch',
                  vision_max_tokens=args.vision_max_tokens, planner_max_tokens=8192)
    write(args.output/('preflight.json' if args.preflight else 'result.json'), result)
    print(json.dumps({k: result.get(k) for k in ('sample_id','status','answer','error','seconds','usage')}, ensure_ascii=False))
    if result['status'] not in ('answered', 'startup_ok'):
        raise RuntimeError(f'Video-RSI did not complete: {result.get("error", result["status"])}')


if __name__ == '__main__':
    main()
