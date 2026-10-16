"""Frozen full-panel LensWalk or Video-RSI evaluation on eight independent H100 replicas."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import queue
import random
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.request

ADAPTERS=Path(__file__).resolve().parent
SOURCE=ADAPTERS.parents[1]
sys.path[:0]=[str(ADAPTERS),str(SOURCE/'src'),str(SOURCE)]
from common import write,sha256

EXPECTED={'cvbench':997,'mvu_eval':1824,'crossvid':2500}
SMOKE=Path('/runs/devbox/external_lenswalk_20261016_r3')
OLD_MEDIA=Path('/runs/devbox/external_original_images_20261015/prepared')
CLIENT='/opt/lenswalk-client/bin/python'
RSI_DEPS=Path('/runs/devbox/external_methods_20261014/support/upstream_clients_20261015')


def method_config(method):
    if method=='rsi':
        return dict(server='native_server',upstream='Video-RSI',client=sys.executable,
                    question_timeout=7200,inspector='rsi_outcome')
    assert method=='lenswalk'
    return dict(server='lenswalk_server',upstream='LensWalk',client=CLIENT,
                question_timeout=1800,inspector='lenswalk_outcome')


def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_text())
def media_key(videos):
    return hashlib.sha256(json.dumps(list(videos.items()),ensure_ascii=False).encode()).hexdigest()[:24]


def archive_attempt(directory,compress=True):
    assert directory.name.startswith('attempt-') and not directory.is_symlink()
    hashes={str(p.relative_to(directory)):sha256(p) for p in directory.rglob('*') if p.is_file()}
    archive=directory.with_suffix('.tar.gz' if compress else '.tar');temporary=archive.with_suffix('.tmp')
    with tarfile.open(temporary,'w:gz' if compress else 'w',**({'compresslevel':1} if compress else {})) as stream:
        stream.add(directory,arcname=directory.name)
    with tarfile.open(temporary,'r:*') as stream:
        observed={}
        for member in stream:
            if not member.isfile():continue
            digest=hashlib.sha256()
            with stream.extractfile(member) as file:
                for chunk in iter(lambda:file.read(1024*1024),b''):digest.update(chunk)
            observed[str(Path(member.name).relative_to(directory.name))]=digest.hexdigest()
        assert observed==hashes, 'Raw archive verification failed; keep the original directory'
    temporary.replace(archive)
    result=dict(path=str(archive),sha256=sha256(archive),files=hashes)
    shutil.rmtree(directory)
    return result


def initialize(output,method='lenswalk'):
    spec=method_config(method)
    assert not output.exists(), 'Use the frozen driver to resume an existing run'
    output.mkdir(parents=True)
    frozen=output/'frozen_repo'
    shutil.copytree(SMOKE/'frozen_repo',frozen,ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('lenswalk_full.py','lenswalk_outcome.py','test_lenswalk_full.py',
                 'rsi_outcome.py','test_rsi_full.py','rsi.py','native_server.py','test_lenswalk_full_scoring.py'):
        shutil.copy2(ADAPTERS/name,frozen/'eval/external_methods'/name)
    # The tested client and upstream source are immutable; no dependency installation is needed.
    if method=='lenswalk':
        (output/'client_environment.tar.gz').symlink_to(SMOKE/'support/client_environment.tar.gz')
    else:
        shutil.copy2(RSI_DEPS/'rsi_manifest.json',output/'client_environment.json')
        settings=read(frozen/'eval/external_methods/upstream_settings.json')
        assert sha256(frozen/'external_sources/Video-RSI/solver_full_workspace/engine/services.py')==settings['source_sha256']['rsi_services']
    sys.path[:0]=[str(frozen/'src')]
    from prepare import candidate_groups
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    ids=sorted(sid for group in candidate_groups(frozen).values() for sid in group)
    assert len(ids)==len(set(ids))==5321 and dict(Counter(s.split(':')[0] for s in ids))==EXPECTED
    records=load_multibench_records('/assets',ids)
    cache={}
    for item in read(OLD_MEDIA/'items.json'):
        path=Path(item['video_path']); meta=read(path.parent/'timeline.json')
        assert meta['preprocessing_version']=='native_concat_repeated_headers_v2'
        videos={s['video_id']:s['source'] for s in meta['segments']}
        cache[media_key(videos)]=dict(video_path=str(path),timeline_path=str(path.parent/'timeline.json'))
    if method=='rsi':
        for path in Path('/runs/devbox/lenswalk_full_35b_20261016/media_cache').glob('*.json'):
            value=read(path)
            if Path(value['video_path']).is_file() and Path(value['timeline_path']).is_file():
                cache[path.stem]=value
    for name in ('media_cache','prepared/items',method,'episodes'):(output/name).mkdir(parents=True,exist_ok=True)
    for key,value in cache.items():write(output/'media_cache'/f'{key}.json',value)
    # Start with cached media, then keep a fixed shuffled schedule for the remaining panel.
    random.Random(0).shuffle(ids)
    ids.sort(key=lambda sid:media_key(records[sid].sample.videos) not in cache)
    write(output/'samples.json',ids)
    write(output/'prepared/private_labels.json',{sid:dict(dataset=r.dataset,task=r.native_task,
        sample=r.sample.to_dict(),reference_answer=r.reference_answer,judge_question=r.judge_question,
        task_population=r.task_population) for sid,r in records.items()})
    write(output/'manifest.json',dict(created_at=now(),method=method,expected=EXPECTED,sample_count=len(ids),
        samples_sha256=sha256(output/'samples.json'),source_snapshot=str(SMOKE/'frozen_repo'),
        adapter_commit='af42adb024b364be0e2260d37b24e112e27b3aaf',
        driver_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip(),
        driver_sha256=sha256(frozen/'eval/external_methods/lenswalk_full.py'),
        source_hashes={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts},
        asset_hashes={name:sha256(Path('/assets')/name) for name in
                      ('crossvid/qa.jsonl','cvbench/QAs.json','mvu-eval/QAs.json')},
        seed=0,upstream_commit=('5ad014499a5e009b75e3ef05ac83595b78adda09' if method=='rsi' else 'c3cdf13a6ffc6b1ce21af3a0c7813178d17fac77'),
        replicas=8,gpu='H100!:8',request_timeout_seconds=600,question_timeout_seconds=spec['question_timeout'],
        method_settings=(dict(max_steps=11,max_service_calls=64,max_frames=256,solver_timeout_seconds=1800,
                             image_width=768,planner_temperature=0,observer_temperature=0,max_output_tokens=8192,
                             provider_retries=1,generic_answers=True,linux_isolation=False,
                             client_manifest_sha256=sha256(output/'client_environment.json'),raw_archive='uncompressed tar')
                         if method=='rsi' else dict(max_turns=5,planner_temperature=None,observer_temperature=.2,max_output_tokens=None)),
        preprocessing='Reuse tested native concat; no resizing or FPS conversion; exact ordered-video caching',
        unique_media_groups=len({media_key(r.sample.videos) for r in records.values()}),
        existing_cached_groups=len(cache),judge='Qwen3-30B-A3B-Instruct-2507',
        excluded=['cvbench:64','cvbench:65','cvbench:66']))
    write(output/'progress.json',dict(phase='prepared',expected=5321,completed=0,updated_at=now()))
    print(json.dumps(read(output/'manifest.json')|{'source_hashes':'stored','asset_hashes':'stored'}),flush=True)


def stop(process):
    if process is None or process.poll() is not None:return
    os.killpg(process.pid,signal.SIGTERM)
    try:process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)


def start_actor(rank,episode,shutdown,method):
    backend=importlib.import_module(method_config(method)['server'])
    base,validate_card=backend.base,backend.validate_card
    directory=episode/f'worker{rank}'/str(time.time_ns());directory.mkdir(parents=True)
    env=dict(os.environ,**base.ENVIRONMENT,PYTHONPATH=str(SOURCE/'src'),CUDA_VISIBLE_DEVICES=str(rank))
    with (directory/'server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,str(ADAPTERS/(method_config(method)['server']+'.py')),
            '--model','/weights/Qwen3.5-35B-A3B','--port',str(8100+rank),'--log-dir',str(directory)]+(['--worker'] if method=='rsi' else []),
            env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    deadline=time.monotonic()+1200
    try:
        while time.monotonic()<deadline and not shutdown.is_set():
            if process.poll() is not None:raise RuntimeError(f'Actor {rank} exited during startup')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{8100+rank}/v1/models',timeout=2) as response:
                    card=json.load(response)['data'][0]
            except (OSError,ValueError):
                time.sleep(2);continue
            validate_card(card)
            assert card['worker']['gpu_name']=='NVIDIA H100 80GB HBM3'
            write(directory/'verified_card.json',card)
            return process,card
        raise RuntimeError(f'Actor {rank} startup interrupted or timed out')
    except BaseException:
        stop(process);raise


def prepare_item(output,record,lock):
    from prepare import prepare,timeline
    sid=record.sample_id; key=media_key(record.sample.videos)
    with lock:
        manifest=output/'media_cache'/f'{key}.json'
        if manifest.exists():
            cached=read(manifest)
        else:
            cache_record=replace(record,sample_id='media:'+key)
            target=output/'prepared/media'/('media_'+key)
            # No committed cache entry references an interrupted build.
            if target.exists():shutil.rmtree(target)
            item=prepare(cache_record,output/'prepared')
            cached=dict(video_path=item['video_path'],timeline_path=str(target/'timeline.json'))
            write(manifest,cached)
        meta=read(cached['timeline_path'])
        assert [(s['video_id'],s['source']) for s in meta['segments']]==list(record.sample.videos.items())
        assert Path(cached['video_path']).is_file()
    item=dict(sample_id=sid,video_path=cached['video_path'],duration=meta['duration'],
        question=timeline(meta['segments'])+'\n\nOriginal question:\n'+record.sample.question,
        options={chr(65+i):v for i,v in enumerate(record.sample.options)})
    path=output/'prepared/items'/(sid.replace(':','_')+'.json');write(path,item)
    return path


def closed_score(record,prediction):
    from skill_evolution.infra.benchmarks.contracts import SampleTask
    from skill_evolution.infra.benchmarks.scoring import ChoiceScorer,OrderingScorer,TemporalLocalizationScorer
    from skill_evolution.infra.benchmarks.catalog import CHOICE_PROTOCOL
    task=record.sample.task
    if task is SampleTask.OPEN_QA:return None
    scorer=ChoiceScorer(protocol=CHOICE_PROTOCOL[record.dataset]) if task is SampleTask.CHOICE else (
        OrderingScorer() if task is SampleTask.ORDERING else TemporalLocalizationScorer())
    return scorer.score(prediction=prediction,sample=record.sample).score


def main(output):
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    assert SOURCE.resolve()==(output/'frozen_repo').resolve(), 'Run only the frozen driver'
    manifest=read(output/'manifest.json')
    method=manifest['method'];spec=method_config(method)
    configure=importlib.import_module(spec['server']).configure
    inspect=importlib.import_module(spec['inspector']).inspect
    assert manifest['driver_sha256']==sha256(Path(__file__))
    assert manifest['samples_sha256']==sha256(output/'samples.json')
    for name in (method+'.py',spec['server']+'.py','prepare.py',spec['inspector']+'.py'):
        assert sha256(ADAPTERS/name)==manifest['source_hashes']['eval/external_methods/'+name]
    for name,expected in manifest['asset_hashes'].items():assert sha256(Path('/assets')/name)==expected
    client_env=dict(os.environ,PYTHONPATH=str(SOURCE/'src'))
    if method=='lenswalk':
        with tarfile.open(output/'client_environment.tar.gz') as archive:archive.extractall('/opt',filter='tar')
    else:
        assert sha256(RSI_DEPS/'rsi_manifest.json')==manifest['method_settings']['client_manifest_sha256']
        client_env['PYTHONPATH']=str(RSI_DEPS/'rsi')+os.pathsep+client_env['PYTHONPATH']
    ids=read(output/'samples.json');records=load_multibench_records('/assets',ids)
    rows={p.parent.name:read(p) for p in (output/method).glob('*/record.json')}
    shutdown=threading.Event();lock=threading.Lock();children={};active={};cards={}
    media_locks={media_key(r.sample.videos):threading.Lock() for r in records.values()}
    episode=output/'episodes'/str(time.time_ns());episode.mkdir()
    state=dict(phase='starting_models',method=method,expected=len(ids),episode=str(episode),started_at=now())
    def save():
        values=list(rows.values())
        state.update(updated_at=now(),completed=len(values),
            terminal_answers=sum(r.get('terminal') in ('finish','natural_text') and not r['infrastructure_error'] for r in values),
            infrastructure_failures=sum(r['infrastructure_error'] for r in values),
            unfinished=sum(r.get('terminal')=='unfinished_tool_plan' for r in values),
            by_dataset={name:dict(completed=sum(r['dataset']==name for r in values),expected=n)
                        for name,n in EXPECTED.items()},active=dict(active),
            models={'35B-A3B':{'finished':len(values)}})
        write(output/'progress.json',state)
    def interrupted(signum,frame):
        shutdown.set()
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    jobs=queue.Queue()
    for sid in ids:
        if sid.replace(':','_') not in rows:jobs.put(sid)
    def worker(rank,process,card):
        restarts=0
        try:
            while not shutdown.is_set():
                try:sid=jobs.get_nowait()
                except queue.Empty:break
                record=records[sid];directory=output/method/sid.replace(':','_')
                directory.mkdir(exist_ok=True)
                attempt=directory/('attempt-'+str(time.time_ns()));attempt.mkdir()
                prep_started=time.monotonic();prep_seconds=0;started=None;client=None;restart_needed=False
                with lock:active[str(rank)]=dict(sample_id=sid,phase='preparing_media',started_at=now());save()
                write(attempt/'started.json',dict(sample_id=sid,worker=card['worker'],started_at=now()))
                try:
                    item=prepare_item(output,record,media_locks[media_key(record.sample.videos)])
                    prep_seconds=time.monotonic()-prep_started
                    if shutdown.is_set():break
                    with lock:active[str(rank)].update(phase='inference',started_at=now());save()
                    started=time.monotonic()
                    with (attempt/'job.log').open('w') as log:
                        client=subprocess.Popen([spec['client'],str(ADAPTERS/(method+'.py')),'--source',str(SOURCE/'external_sources'/spec['upstream']),
                            '--item',str(item),'--output',str(attempt),'--endpoint',f'http://127.0.0.1:{8100+rank}/v1'],
                            env=client_env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    with lock:children[rank]=client
                    timed_out=False
                    while client.poll() is None and not shutdown.is_set():
                        if time.monotonic()-started>spec['question_timeout']:timed_out=True;break
                        if process.poll() is not None:break
                        time.sleep(1)
                    if client.poll() is None:stop(client)
                    if shutdown.is_set():break
                    outcome=inspect(attempt,card)
                    outcome.update(returncode=client.returncode,seconds=time.monotonic()-started,
                                   question_timeout=timed_out)
                    if timed_out or process.poll() is not None:outcome['infrastructure_error']=True
                    restart_needed=(timed_out or process.poll() is not None or outcome['http_errors']>0
                                    if method=='rsi' else outcome['infrastructure_error'])
                except AssertionError:
                    raise
                except Exception as exc:
                    if shutdown.is_set():break
                    if started is None:prep_seconds=time.monotonic()-prep_started
                    outcome=dict(answer='',terminal='execution_error',infrastructure_error=True,
                        error=repr(exc),traceback=traceback.format_exc(),seconds=time.monotonic()-started if started is not None else 0,
                        calls=0,visual_calls=0,http_errors=0,input_tokens=0,output_tokens=0,tool_errors=[])
                finally:
                    stop(client)
                    with lock:children.pop(rank,None)
                outcome.update(sample_id=sid,dataset=record.dataset,task=record.native_task,
                    attempt=str(attempt),prepared_seconds=prep_seconds,finished_at=now(),worker=card['worker'])
                outcome['score']=None if outcome['infrastructure_error'] else closed_score(record,outcome['answer'])
                archive_started=time.monotonic()
                outcome['raw_archive']=archive_attempt(attempt,compress=method=='lenswalk')
                outcome['archive_seconds']=time.monotonic()-archive_started
                write(directory/'record.json',outcome)
                with lock:rows[directory.name]=outcome;active.pop(str(rank),None);save()
                print(json.dumps({k:outcome.get(k) for k in ('sample_id','terminal','infrastructure_error','seconds','score')},ensure_ascii=False),flush=True)
                restarts=restarts+1 if outcome['infrastructure_error'] else 0
                if restarts>3:raise RuntimeError(f'Worker {rank} exceeded three consecutive infrastructure failures')
                if restart_needed and not jobs.empty() and not shutdown.is_set():
                    stop(process)
                    process,card=start_actor(rank,episode,shutdown,method)
        finally:stop(process)
    save()
    processes=[]
    try:
        if not jobs.empty():
            configure()
            startup_error=None
            with ThreadPoolExecutor(max_workers=8) as pool:
                starts={pool.submit(start_actor,rank,episode,shutdown,method):rank for rank in range(8)}
                for future in as_completed(starts):
                    try:
                        rank=starts[future];process,card=future.result();processes.append(process);cards[rank]=(process,card)
                    except Exception as exc:
                        startup_error=exc;shutdown.set()
            if startup_error is not None:raise startup_error
            assert len({c['worker']['gpu_uuid'] for _,c in cards.values()})==8
            write(episode/'pool_verification.json',{rank:c for rank,(_,c) in cards.items()})
            state['phase']='inference';save()
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures=[pool.submit(worker,rank,*cards[rank]) for rank in range(8)]
                for future in as_completed(futures):
                    try:future.result()
                    except BaseException:shutdown.set();raise
        if shutdown.is_set():state['phase']='interrupted';save();return
        assert len(rows)==len(ids)
        state['phase']='scoring';save()
        score_all(output,records,rows,state,save,shutdown,episode,method)
        state['phase']='completed_with_errors' if any(r['infrastructure_error'] for r in rows.values()) else 'completed'
        state['finished_at']=now();save()
    except InterruptedError:
        shutdown.set();state['phase']='interrupted';save()
    except BaseException as exc:
        shutdown.set();state.update(phase='failed',error=repr(exc),traceback=traceback.format_exc());save();raise
    finally:
        shutdown.set()
        for p in list(children.values())+processes:stop(p)


def score_all(output,records,rows,state,save,shutdown,episode,method='lenswalk'):
    from eval.agent_eval.score_crossvid_ccqa import LocalJudge,_score_one,SCORE_PROMPT
    pending=[r for r in rows.values() if not r['infrastructure_error'] and r['task']=='CCQA' and r['score'] is None]
    starter=None
    if pending:
        state['phase']='judging';save()
        env=dict(os.environ,JUDGE_LOG_DIR=str(episode/'judge'))
        with (episode/'judge_startup.log').open('w') as log:
            starter=subprocess.Popen(['bash',str(SOURCE/'eval/agent_eval/serve_ccqa_judge.sh'),'0-7','8100'],
                cwd=SOURCE,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+1250
            while starter.poll() is None and not shutdown.is_set() and time.monotonic()<deadline:time.sleep(2)
            if shutdown.is_set():raise InterruptedError('Judge interrupted')
            if starter.poll()!=0:raise RuntimeError('Judge startup failed or timed out')
            judge=LocalJudge([f'http://127.0.0.1:{p}/v1' for p in range(8100,8108)],1860)
            write(output/'judge_identity.json',judge.identity)
            def one(row):
                record=records[row['sample_id']]
                result=_score_one(judge,output/'judge_cache',dict(sample_id=row['sample_id'],
                    point_count=len(record.sample.ground_truth),prediction=row['answer'],
                    prompt=SCORE_PROMPT.format(QUESTION=record.judge_question,ANSWER=record.reference_answer,
                                              POINTS=record.sample.ground_truth,OUTPUT=row['answer'])),attempts=3)
                directory=output/method/row['sample_id'].replace(':','_');write(directory/'judge.json',result)
                if result['status']!='ok':raise RuntimeError(f"Judge failed for {row['sample_id']}: {result.get('error')}")
                row['score']=result['score']/(2*len(record.sample.ground_truth));write(directory/'record.json',row)
                return row['sample_id']
            with ThreadPoolExecutor(max_workers=8) as pool:
                for future in as_completed([pool.submit(one,row) for row in pending]):
                    future.result();state['judged']=sum(r['task']=='CCQA' and r['score'] is not None for r in rows.values());save()
        finally:
            # The shell exits after readiness; its vLLM children retain the process group.
            if starter is not None:
                try:os.killpg(starter.pid,signal.SIGTERM)
                except ProcessLookupError:pass
    if shutdown.is_set():raise InterruptedError('Scoring interrupted')
    results={}
    for dataset,expected in EXPECTED.items():
        selected=[r for r in rows.values() if r['dataset']==dataset]
        valid=[r for r in selected if not r['infrastructure_error']]
        assert len(selected)==expected and all(r['score'] is not None for r in valid)
        tasks={}
        for task in sorted({r['task'] for r in selected}):
            group=[r for r in valid if r['task']==task]
            weights=[len(records[r['sample_id']].sample.ground_truth) if task=='CCQA' else 1 for r in group]
            tasks[task]=dict(valid=len(group),score=sum(r['score']*w for r,w in zip(group,weights))/sum(weights) if weights else None)
        score=(sum(t['score'] for t in tasks.values())/10 if dataset=='crossvid' and len(tasks)==10 and
               all(t['score'] is not None for t in tasks.values()) else None) if dataset=='crossvid' else (
               sum(r['score'] for r in valid)/len(valid) if valid else None)
        results[dataset]=dict(expected=expected,scored=len(valid),score=score,task_scores=tasks,
            infrastructure_failures=[r['sample_id'] for r in selected if r['infrastructure_error']],
            unfinished=[r['sample_id'] for r in valid if r['terminal']=='unfinished_tool_plan'],
            invalid_answers=[r['sample_id'] for r in valid if r['terminal']=='invalid_decision'],
            terminal_answers=sum(r['terminal'] in ('finish','natural_text') for r in valid),
            total_inference_seconds=sum(r['seconds'] for r in selected),
            total_preparation_seconds=sum(r['prepared_seconds'] for r in selected),
            mean_inference_seconds=sum(r['seconds'] for r in selected)/len(selected))
    write(output/'summary.json',dict(benchmarks=results,rows=list(rows.values()),
        scoring='Official raw-answer scoring; infrastructure failures separate; unfinished plans remain raw model outputs',
        finished_at=now(),started_at=read(output/'manifest.json')['created_at']))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--initialize',action='store_true')
    p.add_argument('--method',choices=['lenswalk','rsi'],default='lenswalk',help='Initialization only; resume uses frozen manifest')
    args=p.parse_args();initialize(args.output,args.method) if args.initialize else main(args.output)
