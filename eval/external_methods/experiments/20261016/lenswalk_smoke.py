"""Freeze and run six LensWalk integration cases on an isolated Modal H100."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

ADAPTERS=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ADAPTERS))
from common import sha256, write

ROOT=Path('/runs/devbox/external_lenswalk_20261016_r3')
BASE=Path('/runs/devbox/external_original_images_20261015/prepared')


def prepare():
    ROOT.mkdir(exist_ok=False)
    source=ADAPTERS.parents[1]
    subprocess.run([sys.executable,str(ADAPTERS/'freeze.py'),'--output',str(ROOT)],check=True)
    frozen=ROOT/'frozen_repo'
    shutil.copytree(source/'scripts',frozen/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(source/'demo.py',frozen/'demo.py')
    labels=json.loads((BASE/'private_labels.json').read_text())
    items={r['sample_id']:r for r in json.loads((BASE/'items.json').read_text())}
    selected=['cvbench:764','mvu_eval:TR:1585','crossvid:MSR:361']
    for task in ('ordering','temporal_localization','open_qa'):
        candidates=[s for s in items if labels[s]['sample']['task']==task]
        selected.append(min(candidates,key=lambda s:(items[s]['duration'],s)))
    assert len(selected)==len(set(selected))==6
    for sid in selected:
        assert Path(items[sid]['video_path']).is_file()
        write(ROOT/'prepared/items'/(sid.replace(':','_')+'.json'),items[sid])
    write(ROOT/'prepared/items.json',[items[s] for s in selected])
    write(ROOT/'prepared/private_labels.json',{s:labels[s] for s in selected})
    write(ROOT/'selection.json',dict(sample_ids=selected,source=str(BASE),
        policy='Three fixed benchmark anchors, then shortest existing ordering/temporal/open QA case; no answer-dependent selection'))
    support=ROOT/'support'
    support.mkdir()
    subprocess.run([sys.executable,'-m','pip','install','--target',str(support/'installer'),'uv'],check=True)
    uv=str(support/'installer/bin/uv')
    # uv's atomic Python installation is unsupported on a Modal volume; build on local disk.
    env=dict(os.environ,UV_PYTHON_INSTALL_DIR='/opt/lenswalk-python',UV_CACHE_DIR='/tmp/lenswalk-uv-cache')
    subprocess.run([uv,'venv','--python','3.11','/opt/lenswalk-client'],env=env,check=True)
    client='/opt/lenswalk-client/bin/python'
    subprocess.run([uv,'pip','install','--python',client,'-r',str(frozen/'external_sources/LensWalk/requirements.txt'),
                    'openai==2.24.0','transformers==4.57.6','numpy==2.2.6',
                    'opencv-python-headless==4.13.0.92','pandas==2.2.3'],env=env,check=True)
    subprocess.run([uv,'pip','freeze','--python',client],env=env,check=True,
                   stdout=(support/'requirements.lock').open('w'))
    with tarfile.open(support/'client_environment.tar.gz','w:gz') as archive:
        for name in ('lenswalk-python','lenswalk-client'):
            archive.add('/opt/'+name,arcname=name)
    env=dict(os.environ,PYTHONPATH=str(frozen/'src'))
    subprocess.run([sys.executable,'-m','compileall','-q','src','scripts','eval/agent_eval','eval/external_methods','demo.py'],
                   cwd=frozen,env=env,check=True)
    for name in ('test_contracts.py','test_transport_audit.py','test_lenswalk_transport.py'):
        subprocess.run([sys.executable,str(ADAPTERS/name)],env=env,check=True)
    subprocess.run([sys.executable,str(ADAPTERS/'test_rsi_timeout.py'),str(frozen/'external_sources/Video-RSI')],env=env,check=True)
    scratch=Path('/tmp/lenswalk-upstream-tests')
    shutil.copytree(frozen/'external_sources/LensWalk',scratch)
    for name in ('mock_inference_smoke.py','mock_subject_registry_smoke.py'):
        subprocess.run([client,str(scratch/'tests'/name)],cwd=scratch,env=dict(os.environ,PYTHONPATH=str(scratch)),check=True)
    write(ROOT/'runtime_hashes.json',{str(p.relative_to(frozen)):sha256(p) for p in sorted(frozen.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts})
    write(ROOT/'ready.json',dict(samples=6,client_python=client,selected=selected,
        client_requirements_sha256=sha256(support/'requirements.lock')))
    print('READY',json.dumps(selected),flush=True)


def infer():
    frozen=ROOT/'frozen_repo'
    scripts=frozen/'eval/external_methods'
    ready=json.loads((ROOT/'ready.json').read_text())
    with tarfile.open(ROOT/'support/client_environment.tar.gz') as archive:
        archive.extractall('/opt',filter='tar')
    sys.path[:0]=[str(scripts),str(frozen/'src')]
    from lenswalk_server import base, validate_card, configure
    state=dict(phase='starting_model',expected=6,completed=0,samples=[])
    write(ROOT/'progress.json',state)
    env=dict(os.environ,**base.ENVIRONMENT,PYTHONPATH=str(frozen/'src'),CUDA_VISIBLE_DEVICES='0')
    started=time.monotonic()
    with (ROOT/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,str(scripts/'lenswalk_server.py'),
            '--model','/weights/Qwen3.5-35B-A3B','--log-dir',str(ROOT/'server')],env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        while True:
            if server.poll() is not None or time.monotonic()-started>900:
                raise RuntimeError('Qwen service startup failed')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8100/v1/models',timeout=2) as response:
                    card=json.load(response)['data'][0]
                break
            except (OSError,ValueError):
                time.sleep(2)
        validate_card(card)
        assert card['worker']['gpu_name']=='NVIDIA H100 80GB HBM3'
        state.update(phase='inference',startup_seconds=time.monotonic()-started)
        write(ROOT/'startup_verification.json',card)
        write(ROOT/'progress.json',state)
        for item in json.loads((ROOT/'prepared/items.json').read_text()):
            sid=item['sample_id']; out=ROOT/'lenswalk'/sid.replace(':','_')
            out.mkdir(parents=True)
            t=time.monotonic()
            try:
                with (out/'job.log').open('w') as log:
                    proc=subprocess.run([ready['client_python'],str(scripts/'lenswalk.py'),
                        '--source',str(frozen/'external_sources/LensWalk'),'--item',str(ROOT/'prepared/items'/(sid.replace(':','_')+'.json')),
                        '--output',str(out),'--endpoint','http://127.0.0.1:8100/v1'],
                        env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
                result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else {}
                row=dict(sample_id=sid,success=proc.returncode==0,returncode=proc.returncode,
                         answer=result.get('answer'),seconds=time.monotonic()-t)
            except Exception as exc:
                row=dict(sample_id=sid,success=False,error=repr(exc),seconds=time.monotonic()-t)
            write(out/'execution.json',row)
            state['completed']+=1;state['samples'].append(row)
            write(ROOT/'progress.json',state)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            if server.poll() is not None:
                raise RuntimeError('Model service exited; remaining cases were not attempted')
        state['phase']='scoring_and_audit'
        write(ROOT/'progress.json',state)
        subprocess.run([sys.executable,str(scripts/'score.py'),'--prepared',str(ROOT/'prepared'),
                        '--run',str(ROOT/'lenswalk')],env=env,check=True)
        runtime=configure()
        audited=[]
        for path in sorted((ROOT/'lenswalk').glob('*/requests.jsonl')):
            for line in path.read_text().splitlines():
                request=json.loads(line);response=request['response']
                if not response or not response.get('choices'): continue
                wire=json.dumps(request['request'],ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
                audit=runtime.token_audit(response,wire)
                assert response['usage']['prompt_tokens_details']['cached_tokens']==0
                assert audit['worker']['gpu_uuid']==card['worker']['gpu_uuid']
                audited.append(dict(sample=path.parent.name,request_sha256=audit['request_sha256'],usage=response['usage']))
        write(ROOT/'audit.json',dict(responses=len(audited),records=audited))
        state.update(phase='completed' if all(r['success'] for r in state['samples']) else 'completed_with_errors',
                     elapsed_seconds=time.monotonic()-started,audited_responses=len(audited))
        write(ROOT/'progress.json',state)
    except Exception as exc:
        state.update(phase='failed',error=repr(exc));write(ROOT/'progress.json',state)
        raise
    finally:
        server.terminate()
        try: server.wait(timeout=30)
        except subprocess.TimeoutExpired: server.kill();server.wait()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','infer'])
    args=p.parse_args();prepare() if args.mode=='prepare' else infer()
