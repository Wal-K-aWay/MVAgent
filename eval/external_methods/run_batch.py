"""Run an external method with one complete question per local Qwen replica."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import subprocess
import sys
import time
import urllib.request

from common import write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('method', choices=['rsi','meta','vam'])
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ports', default='8100,8101,8102,8103,8104,8105,8106,8107')
    p.add_argument('--bundle', type=Path)
    p.add_argument('--smoke', action='store_true')
    args = p.parse_args()
    script_dir = Path(__file__).resolve().parent
    frozen = script_dir.parents[1]
    upstream = frozen/'external_sources'/dict(rsi='Video-RSI',meta='MetaVideoAgent',vam='Visual-Agentic-Memory')[args.method]
    items = json.loads((args.prepared/'items.json').read_text())
    # Start with the shortest selected question in each benchmark; expand unchanged afterward.
    smoke = {}
    for item in sorted(items,key=lambda row:row['duration']):
        smoke.setdefault(item['sample_id'].split(':')[0],item)
    items = list(smoke.values()) if args.smoke else items
    endpoints = queue.Queue()
    cards = []
    for port in args.ports.split(','):
        endpoint = f'http://127.0.0.1:{int(port)}/v1'
        with urllib.request.urlopen(endpoint+'/models',timeout=30) as response:
            card = json.load(response)['data'][0]
        from models.vlm.local.sync_server import validate_card
        validate_card(card)
        if card['execution']['profile'] != 'qwen35-bf16-flashinfer-sync':
            raise ValueError('User confirmed v2 for this experiment')
        cards.append(dict(endpoint=endpoint,card=card))
        endpoints.put(endpoint)
    write(args.output/'service_cards.json',cards)
    state = dict(method=args.method, phase='running', started_at=datetime.now(timezone.utc).isoformat(),
                 expected=len(items), completed=0, successful=0, failed=0, samples=[])
    write(args.output/'progress.json',state)

    def one(item):
        sid = item['sample_id']
        output = args.output/sid.replace(':','_')
        if (output/'result.json').exists():
            raise FileExistsError(f'Existing result: {output}; use a new output directory')
        output.mkdir(parents=True,exist_ok=True)
        endpoint = endpoints.get()
        started = time.monotonic()
        try:
            command = [sys.executable,str(script_dir/f'{args.method}.py')]
            if args.method=='meta':
                command += ['infer','--bundle',str(args.bundle)]
            command += ['--source',str(upstream),'--item',str(args.prepared/'items'/(sid.replace(':','_')+'.json')),
                        '--output',str(output),'--endpoint',endpoint]
            with (output/'job.log').open('w') as log:
                result = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
            record = json.loads((output/'result.json').read_text()) if (output/'result.json').exists() else {}
            row = dict(sample_id=sid, success=result.returncode==0, returncode=result.returncode,
                       answer=record.get('answer'), seconds=time.monotonic()-started, endpoint=endpoint)
        except Exception as exc:
            row = dict(sample_id=sid,success=False,error=str(exc),seconds=time.monotonic()-started,endpoint=endpoint)
        finally:
            endpoints.put(endpoint)
        write(output/'execution.json',row)
        return row

    with ThreadPoolExecutor(max_workers=endpoints.qsize()) as pool:
        for future in as_completed([pool.submit(one,item) for item in items]):
            row = future.result()
            state['completed'] += 1
            state['successful' if row['success'] else 'failed'] += 1
            state['samples'].append(row)
            write(args.output/'progress.json',state)
            print(json.dumps(row,ensure_ascii=False),flush=True)
    state['phase'] = 'completed' if state['failed']==0 else 'completed_with_errors'
    write(args.output/'progress.json',state)


if __name__=='__main__':
    main()
