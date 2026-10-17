"""Run the released Video-RSI harness with local Qwen for both model roles."""
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request

from common import write
from native_server import validate_card
from transport_audit import audit_urllib


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--item', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--endpoint')
    p.add_argument('--preflight', action='store_true')
    args = p.parse_args()
    sys.path.insert(0, str(args.source))
    from solver_full_workspace.engine.runner import run_item
    from solver_full_workspace.engine.services import Services, OfflineProvider, PinnedProvider
    item = json.loads(args.item.read_text())
    config = json.loads((args.source/'config.example.json').read_text())
    # Modal lacks Landlock; keep candidate seccomp and the outer Modal sandbox.
    config['execution'].update(python=sys.executable, linux_isolation=False)
    config['services']['ocr_model_root'] = '/runs/devbox/external_methods_20261014/ocr_models'
    config['services']['timeout_seconds'] = 600  # User-approved local HTTP wait; generation budgets stay upstream.
    if args.preflight:
        provider = OfflineProvider()
    else:
        with urllib.request.urlopen(args.endpoint.rstrip('/')+'/models', timeout=30) as response:
            card = json.load(response)['data'][0]
        validate_card(card)
        for role in ('qwen', 'deepseek'):
            config['services'][role]['request_model'] = card['id']
        write(args.output/'service_card.json', card)

        class LocalProvider(PinnedProvider):
            def __init__(self):
                # The upstream HTTPS/key guard targets cloud APIs; reuse its unchanged chat/retry logic locally.
                self.config, self.meter = config['services'], None
                self.key, self.endpoint = 'local-no-auth', args.endpoint.rstrip('/')

        provider = LocalProvider()
        audit_urllib(args.output/'requests.jsonl')
    write(args.output/'effective_config.json', dict(config=config,
        image_policy='upstream Services unchanged: width 768, aspect ratio preserved',
        adaptations=['local model identity and loopback endpoint', 'local Python/OCR paths',
                     'Modal isolation: seccomp retained, Landlock unavailable',
                     'user-approved generic answer contract',
                     'user-approved local HTTP timeout 600 seconds (upstream 240)'],
        protocol='upstream budgets, sampling, retries and serial extraction; explicit user-approved adapters'))
    services = Services(item, {'video_path': item['video_path']}, config,
                        args.output/'scratch', provider=provider)
    started = time.monotonic()
    result = run_item(args.source/'artifacts/final_harness', item, services, config,
                      check_only=args.preflight)
    result.update(seconds=time.monotonic()-started, source='released final_harness + recorded adapter patch',
                  vision_max_tokens=config['services']['qwen']['max_tokens'],
                  planner_max_tokens=config['services']['deepseek']['max_tokens'])
    write(args.output/('preflight.json' if args.preflight else 'result.json'), result)
    print(json.dumps({k: result.get(k) for k in ('sample_id','status','answer','error','seconds','usage')}, ensure_ascii=False))
    if result['status'] not in ('answered', 'startup_ok'):
        raise RuntimeError(f'Video-RSI did not complete: {result.get("error", result["status"])}')


if __name__ == '__main__':
    main()
