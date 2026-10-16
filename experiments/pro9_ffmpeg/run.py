"""Isolated PRO6000 9B source restoration: FFmpeg only, fixed modern server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import time
import traceback
import urllib.request

HERE = Path(__file__).resolve().parent
CODE = HERE.parents[1]
PANEL = Path('/runs/devbox/direct_answer_random_20261015')
ROOT = Path('/runs/devbox/pro9_ffmpeg_20261016')
MODEL = 'qwen3_5_9b_local'
FROZEN = PANEL / 'frozen_repo'


def now():
    return datetime.now(timezone.utc).isoformat()


def read(p):
    return json.loads(Path(p).read_text())


def write(p, value):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name + f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n'); temp.replace(p)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare():
    import yaml
    if (ROOT / 'jobs.json').exists():
        return
    selection = read(PANEL / 'selection.json')
    ccqa = read('/runs/devbox/mvagent_final_score_20261016/9B/score/ccqa_scores_official_qwen3_30b_a3b.json')
    ccids = random.Random(0).sample(sorted(f"crossvid:CCQA:{r['id']}" for r in ccqa['samples']), 30)
    ids = selection['random_ids'] + ccids
    assert len(ids) == len(set(ids)) == 330
    metadata = {r['sample_id']: r for r in selection['models']['9B']}

    def load(sid):
        source = (PANEL / 'historical/9B' / f'{sid}.json' if sid in metadata else
                  Path('/runs/devbox/mvagent_full_20261014_transport/9B/records/crossvid') / sid / 'result.json')
        raw = read(source)
        inputs = raw['result']['input']
        assert raw['status'] == 'ok'
        assert all(Path(p).is_file() for p in inputs['videos'].values()), (sid, inputs)
        return dict(sample_id=sid, dataset=raw['dataset'], task=raw['native_task'],
                    inputs=inputs, ground_truth=raw['ground_truth'], judge_question=raw.get('judge_question'),
                    reference_answer=raw.get('reference_answer'), historical_prediction=raw['prediction'],
                    source=str(source), source_sha256=sha(source),
                    task_population=metadata[sid]['task_population'] if sid in metadata else 872)

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(load, ids))
    config = yaml.safe_load(Path('/runs/lightsail_outputs/mvagent/no_skill/qwen3_5_9b/input_config.yaml').read_text())
    model = config['models'][MODEL]
    model.update(model_name='/weights/Qwen3.5-9B', dtype='bfloat16', max_model_len=131072,
                 gpu_memory_utilization=.94, timeout_sec=1860)
    write(ROOT / 'base_config.json', config)
    write(ROOT / 'selection.json', {'seed': 0, 'closed_ids': selection['random_ids'], 'ccqa_ids': ccids,
          'panel_sha256': sha(PANEL / 'selection.json'), 'design': 'Reuse all 300 closed panel IDs; add 30 random CCQA IDs. No selection by outcomes.'})
    write(ROOT / 'jobs.json', jobs)
    print('PREPARED', len(jobs), flush=True)


def worker(args):
    import yaml
    from bridge import Bridge
    sys.path.insert(0, str(CODE / 'src'))
    from mvagent.configs import MVAgentConfig
    from mvagent.engine import MVAgentEngine
    target = ROOT / f'shard{args.shard}' / f'rank{args.rank}'
    config = read(ROOT / 'base_config.json')
    port = 18100 + args.rank
    config['models'][MODEL].update(gpus=[args.rank], endpoint=f'http://127.0.0.1:{port}/v1')
    config['runtime'].update(cache_dir=f'/work/pro9-cache-{args.rank}', output_dir=str(target))
    config_path = target / 'config.yaml'; target.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    bridge = Bridge(port, f'http://127.0.0.1:{8100+args.rank}', target / 'calls'); bridge.start()
    engine = MVAgentEngine(MVAgentConfig.from_yaml(config_path))
    engine.resolve_models()
    jobs = read(ROOT / 'jobs.json')
    assigned = jobs[args.shard * 8 + args.rank::16]

    def one(job, destination):
        bridge.sample_id = job['sample_id']; bridge.calls = []
        started = time.monotonic()
        try:
            result = engine.answer(**job['inputs'], output_dir=str(destination / 'artifacts'))
            prediction = str(result['answer']['answer'])
            value = dict(status='ok', result=result, prediction=prediction, error='')
        except Exception as exc:
            value = dict(status='error', result=None, prediction='', error=repr(exc), traceback=traceback.format_exc())
        value.update(sample_id=job['sample_id'], dataset=job['dataset'], native_task=job['task'],
                     ground_truth=job['ground_truth'], judge_question=job['judge_question'],
                     reference_answer=job['reference_answer'], seconds=time.monotonic()-started,
                     call_files=list(bridge.calls), input_sha256=hashlib.sha256(json.dumps(job['inputs'],sort_keys=True).encode()).hexdigest())
        write(destination / 'result.json', value)
        print(json.dumps({'sample_id': job['sample_id'], 'status': value['status'], 'prediction': value['prediction'][:200], 'seconds': value['seconds']}), flush=True)
        return value

    try:
        if args.smoke:
            chosen = [next(j for j in jobs if j['dataset']=='cvbench'), next(j for j in jobs if j['task']=='CCQA')]
            report = []
            for job in chosen:
                runs = [one(job, ROOT / 'smoke' / job['sample_id'] / str(r)) for r in range(2)]
                def trace(row):
                    calls = [read(p) for p in row['call_files']]
                    assert all(c['status']==200 for c in calls)
                    return [(c['response']['audit']['input_sha256'], c['response']['choices'][0]['token_ids']) for c in calls]
                assert all(r['status']=='ok' for r in runs), runs
                equal = trace(runs[0]) == trace(runs[1])
                report.append({'sample_id':job['sample_id'],'equal':equal,'calls':len(runs[0]['call_files']),
                               'answers':[r['prediction'] for r in runs]})
            write(ROOT / 'smoke.json', {'completed':True,'comparisons':report})
            return
        for i, job in enumerate(assigned):
            destination = ROOT / '9B/records' / job['dataset'] / job['sample_id']
            if not (destination / 'result.json').exists():
                one(job, destination)
            write(target / 'progress.json', {'finished':i+1,'total':len(assigned),'updated_at':now()})
    finally:
        engine.close();bridge.shutdown();bridge.server_close()


def serve(args):
    import importlib.util
    spec = importlib.util.spec_from_file_location('fixed_backend', HERE/'backend/sync_server.py')
    backend = importlib.util.module_from_spec(spec); spec.loader.exec_module(backend)
    target = ROOT / f'shard{args.shard}'
    target.mkdir(parents=True, exist_ok=True)
    source = read(CODE / 'experiments/pro9_ffmpeg/source_provenance.json')
    actual = {str(p.relative_to(CODE/'src')):sha(p) for p in (CODE/'src').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    assert actual == source['experiment_sha256']
    write(target / 'manifest.json', {'at':now(),'source':source,'runner_sha256':sha(__file__),
          'bridge_sha256':sha(HERE/'bridge.py'),'shard':args.shard,'ranks':8,'profile':'qwen35-bf16-flashinfer-sync',
          'src_changes':['mvagent/utils/media.py'], 'transport':'response_format.json_schema.schema -> structured_outputs.json, same schema object; seed0/thinking-off/token logging'})
    processes, logs = [], []
    try:
        for rank in range(8):
            log = (target / f'server{rank}.log').open('a');logs.append(log)
            processes.append(subprocess.Popen([sys.executable,str(HERE/'backend/sync_server.py'),
                 '--model','/weights/Qwen3.5-9B','--served-model-name',MODEL,
                 '--port',str(8100+rank),'--log-dir',str(target/f'server{rank}')],
                 stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':str(rank)}))
        write(target/'progress.json',{'phase':'loading','at':now()})
        deadline=time.monotonic()+1500;ready={}
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while len(ready)<8 and time.monotonic()<deadline:
            for rank,p in enumerate(processes):
                if rank in ready:continue
                if p.poll() is not None:raise RuntimeError(f'worker {rank} exited {p.returncode}')
                try:
                    with opener.open(f'http://127.0.0.1:{8100+rank}/v1/models',timeout=2) as response:
                        card=json.load(response)['data'][0]
                    backend.validate_card(card)
                    assert card['id']==MODEL and card['root']=='/weights/Qwen3.5-9B'
                    ready[rank]=card
                except (OSError,ValueError,KeyError):pass
            time.sleep(3)
        assert len(ready)==8, ready
        assert len({c['worker']['gpu_uuid'] for c in ready.values()})==8
        write(target/'servers.json',ready)
        def run_rank(rank, smoke=False):
            path=target/('smoke.log' if smoke else f'rank{rank}.log')
            with path.open('a') as log:
                cmd=[sys.executable,str(__file__),'worker','--shard',str(args.shard),'--rank',str(rank)]
                if smoke:cmd.append('--smoke')
                subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,cwd=CODE)
        if args.shard==0:
            write(target/'progress.json',{'phase':'smoke','at':now()});run_rank(0,True)
        else:
            deadline=time.monotonic()+1800
            while not (ROOT/'smoke.json').exists():
                if time.monotonic()>deadline:raise TimeoutError('First shard smoke did not finish')
                time.sleep(5)
        smoke=read(ROOT/'smoke.json');assert smoke['completed']
        write(target/'progress.json',{'phase':'inference','at':now(),'smoke':smoke})
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(run_rank,range(8)))
        write(target/'progress.json',{'phase':'completed','at':now()})
    except BaseException as exc:
        write(target/'progress.json',{'phase':'failed','at':now(),'error':repr(exc),'traceback':traceback.format_exc()})
        raise
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=30)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in logs:log.close()
        (Path('/work/jobs')/f'pro9_ffmpeg_20261016_shard{args.shard}.pid').unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','serve','worker'])
    parser.add_argument('--shard',type=int,default=0)
    parser.add_argument('--rank',type=int,default=0)
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    {'prepare':lambda:prepare(),'serve':lambda:serve(args),'worker':lambda:worker(args)}[args.mode]()


if __name__=='__main__':main()
