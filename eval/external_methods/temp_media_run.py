"""Paired storage A/B on unchanged local-Qwen external-method clients; no scoring/Judge."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

from common import write,sha256
from lenswalk_full import ADAPTERS,SOURCE,CLIENT,RSI_DEPS,method_config,start_actor,stop,now,read
from temp_media_probe import ROOT,SAMPLES,bytes_used
from prepare import timeline


def model_calls(path):
    rows=[]
    if not path.exists():return rows
    for line in path.read_text().splitlines():
        call=json.loads(line)
        if call.get('error') or call.get('http_status')!=200:
            rows.append(dict(error=call.get('error'),status=call.get('http_status')));continue
        response=call['response'];images=[]
        for message in call['request']['messages']:
            if isinstance(message.get('content'),list):
                images += [p['image_url'] for p in message['content'] if p.get('type')=='image_url']
        rows.append(dict(prompt_token_ids=response['prompt_token_ids'],
            image_sha256=hashlib.sha256(json.dumps(images,sort_keys=True).encode()).hexdigest(),
            token_ids=response['choices'][0]['token_ids'],wire_sha256=call['request_sha256']))
    return rows


def compare(left,right):
    def inputs(row):return (row.get('prompt_token_ids'),row.get('image_sha256'),row.get('error'),row.get('status'))
    def canonical(row):
        return json.dumps(dict(input=inputs(row),tokens=row.get('token_ids')),sort_keys=True,separators=(',',':'))
    n=min(len(left),len(right))
    mismatch=next((i for i in range(n) if inputs(left[i])!=inputs(right[i]) or
                   left[i].get('token_ids')!=right[i].get('token_ids')),None)
    if mismatch is None and len(left)!=len(right):mismatch=n
    return dict(calls=[len(left),len(right)],ordered_model_calls_equal=mismatch is None,
        first_ordered_mismatch=mismatch,
        model_call_multisets_equal=sorted(map(canonical,left))==sorted(map(canonical,right)),
        raw_wire_hashes_equal=[r.get('wire_sha256') for r in left]==[r.get('wire_sha256') for r in right])


def method_run(method):
    assert SOURCE.resolve()==(ROOT/'frozen_repo').resolve()
    backend=importlib.import_module(method_config(method)['server']);backend.configure()
    inspect=importlib.import_module(method_config(method)['inspector']).inspect
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    records=load_multibench_records('/assets',SAMPLES)
    target=ROOT/method;target.mkdir(exist_ok=False)
    offset=0 if method=='rsi' else len(SAMPLES)
    ranks=list(range(offset,offset+len(SAMPLES)));shutdown=threading.Event();servers={};state_lock=threading.Lock()
    write(target/'progress.json',dict(phase='starting_models',expected=2*len(SAMPLES),completed=0))
    env=dict(os.environ,PYTHONPATH=str(SOURCE/'src'))
    if method=='rsi':env['PYTHONPATH']=str(RSI_DEPS/'rsi')+os.pathsep+env['PYTHONPATH']
    previous=Path('/runs/devbox/'+('rsi_full_35b_recovery_20261017' if method=='rsi' else
                                 'lenswalk_full_35b_audit_recovery_20261017'))
    expected=next(iter(read(Path(read(previous/'progress.json')['episode'])/'pool_verification.json').values()))
    try:
        with ThreadPoolExecutor(max_workers=len(SAMPLES)) as pool:
            futures={rank:pool.submit(start_actor,rank,target/'servers',shutdown,method) for rank in ranks}
            startup_error=None
            for rank,future in futures.items():
                try:
                    process,card=future.result();servers[rank]=(process,card)
                    assert card['execution']==expected['execution'] and card['weights_manifest']==expected['weights_manifest']
                except BaseException as exc:startup_error=exc;shutdown.set()
        if startup_error is not None:raise startup_error
        write(target/'service_cards.json',{rank:card for rank,(_,card) in servers.items()})
        write(target/'progress.json',dict(phase='inference',expected=2*len(SAMPLES),completed=0,started_at=now()))
        def one(index):
            sid=SAMPLES[index];record=records[sid];rank=ranks[index];process,card=servers[rank]
            case=ROOT/'media'/sid.replace(':','_');probe=read(case/'comparison.json')
            meta=read(case/'volume_timeline.json');video=Path(probe['arms']['volume']['video_path'])
            assert sha256(video)==probe['arms']['volume']['video_sha256']
            pair_root=target/sid.replace(':','_');pair_root.mkdir()
            order=['volume','local'] if (index+(method=='lenswalk'))%2==0 else ['local','volume']
            rows={}
            with tempfile.TemporaryDirectory(prefix=method+'-',dir='/work') as directory:
                local=Path(directory)/'input.mp4'
                copied=time.monotonic();shutil.copyfile(video,local);copy_seconds=time.monotonic()-copied
                assert sha256(local)==probe['arms']['volume']['video_sha256']
                for arm in order:
                    out=pair_root/arm;out.mkdir()
                    item=dict(sample_id=sid,video_path=str(video if arm=='volume' else local),duration=meta['duration'],
                        question=timeline(meta['segments'])+'\n\nOriginal question:\n'+record.sample.question,
                        options={chr(65+i):v for i,v in enumerate(record.sample.options)})
                    write(out/'item.json',item)
                    client=method_config(method)['client'];started=time.monotonic()
                    command=[client,str(ADAPTERS/(method+'.py')),'--source',str(SOURCE/'external_sources'/method_config(method)['upstream']),
                        '--item',str(out/'item.json'),'--output',str(out),'--endpoint',f'http://127.0.0.1:{8100+rank}/v1']
                    with (out/'job.log').open('w') as log:
                        run=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                        try:run.wait(timeout=method_config(method)['question_timeout'])
                        finally:stop(run)
                    elapsed=time.monotonic()-started
                    row=inspect(out,card)
                    row.update(seconds=elapsed,returncode=run.returncode,sample_id=sid,arm=arm,worker=card['worker'])
                    write(out/'execution.json',row);rows[arm]=row
                    with state_lock:
                        complete=len(list(target.glob('*/*/execution.json')))
                        write(target/'progress.json',dict(phase='inference',expected=2*len(SAMPLES),completed=complete,at=now()))
                    print(method,sid,arm,row['terminal'],elapsed,flush=True)
                    if process.poll() is not None:raise RuntimeError('Server exited; do not continue the paired comparison')
                comparisons=compare(model_calls(pair_root/'volume/requests.jsonl'),model_calls(pair_root/'local/requests.jsonl'))
                write(pair_root/'comparison.json',dict(method=method,sample_id=sid,order=order,rows=rows,
                    valid_comparison=all(not r['infrastructure_error'] and r['calls']>0 for r in rows.values()),
                    answer_equal=rows['volume']['answer']==rows['local']['answer'],**comparisons,
                    local_video_bytes=local.stat().st_size,local_copy_seconds=copy_seconds,
                    timing='Inference includes tool/frame reads; concat timings measured separately on CPU; local copy is test staging only'))
            assert not local.exists()
            value=read(pair_root/'comparison.json');value['local_directory_removed']=True;write(pair_root/'comparison.json',value)
            return value
        with ThreadPoolExecutor(max_workers=len(SAMPLES)) as pool:
            pairs=list(pool.map(one,range(len(SAMPLES))))
        write(target/'summary.json',dict(pairs=pairs,at=now()))
        write(target/'progress.json',dict(phase='completed',expected=2*len(SAMPLES),completed=2*len(SAMPLES),at=now()))
    except BaseException as exc:
        write(target/'progress.json',dict(phase='failed',error=repr(exc),at=now()))
        raise
    finally:
        shutdown.set()
        for process,_ in servers.values():stop(process)


def main():
    assert SOURCE.resolve()==(ROOT/'frozen_repo').resolve()
    assert not any((ROOT/method).exists() for method in ('rsi','lenswalk')), 'Do not overwrite an interrupted trial'
    with tarfile.open('/runs/devbox/external_lenswalk_20261016_r3/support/client_environment.tar.gz') as archive:
        archive.extractall('/opt',filter='tar')
    write(ROOT/'progress.json',dict(phase='starting_models',expected_rollouts=4*len(SAMPLES),at=now()))
    children=[]
    try:
        for method in ('rsi','lenswalk'):
            log=(ROOT/(method+'_driver.log')).open('w')
            children.append(subprocess.Popen([sys.executable,__file__,'--method',method],stdout=log,stderr=subprocess.STDOUT))
            log.close()
        codes=[p.wait() for p in children]
        assert codes==[0,0], f'Method processes failed: {codes}'
        pairs=[p for method in ('rsi','lenswalk') for p in read(ROOT/method/'summary.json')['pairs']]
        write(ROOT/'summary.json',dict(pairs=pairs,at=now(),scoring='No Judge or correctness evaluation'))
        # These are disposable inputs generated only for this test; raw responses stay intact.
        removed=[]
        for case in (ROOT/'media').iterdir():
            path=case/'volume'
            if path.is_dir():removed.append(dict(path=str(path),bytes=bytes_used(path)));shutil.rmtree(path)
        write(ROOT/'cleanup.json',dict(removed=removed,at=now()))
        write(ROOT/'progress.json',dict(phase='completed' if all(p['valid_comparison'] for p in pairs) else 'completed_with_errors',
            expected_rollouts=4*len(SAMPLES),completed_rollouts=4*len(SAMPLES),at=now()))
    except BaseException as exc:
        write(ROOT/'progress.json',dict(phase='failed',error=repr(exc),at=now()));raise
    finally:
        for child in children:
            if child.poll() is None:child.terminate()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--method',choices=['rsi','lenswalk'])
    p.add_argument('--output',type=Path,default=ROOT)
    args=p.parse_args();assert args.output==ROOT
    method_run(args.method) if args.method else main()
