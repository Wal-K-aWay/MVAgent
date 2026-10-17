"""Recover only missing/failed rows; preserve the original frozen experiment."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

BASE = Path('/runs/devbox/direct_answer_large_20261016')
SOURCE = BASE/'frozen_repo'
OUT = Path('/runs/devbox/direct_answer_large_recovery_20261017')
PATCH = 'src/mvagent/agents/video_agent/agent.py'
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'
sys.path[:0] = [str(SOURCE/'scripts'), str(SOURCE/'src'), str(SOURCE/'eval/e2e_eval')]
from compare_direct_answer import read, write, sha, now


def remaining(selected, existing):
    assert set(existing) <= set(selected)
    return [sid for sid in selected if existing.get(sid) != 'ok']


def prepare():
    repo = Path(__file__).resolve().parents[1]
    assert not OUT.exists(), 'Do not replace a prepared recovery'
    summary = read(BASE/'analysis_status_20261017_parallel/summary.json')
    selected = read(BASE/'selection.json')
    targets = {m: summary['models'][m]['missing'] + [e['sample_id'] for e in summary['models'][m]['errors']]
               for m in ['35B-A3B', '27B']}
    assert len(targets['35B-A3B']) == 694 and targets['27B'] == ['mvu_eval:TR:1493']
    original = {}
    for m, result in summary['models'].items():
        paired = read(BASE/f'analysis_status_20261017_parallel/{m}_paired.json')
        original[m] = {r['sample_id']:dict(path=r['path'],sha256=r['sha256'],status='ok') for r in paired}
        for error in result['errors']:
            p = Path(error['path'])
            original[m][error['sample_id']] = dict(path=str(p),sha256=sha(p),status=read(p)['status'])
        assert remaining(selected['ids'],{s:r['status'] for s,r in original[m].items()}) == [
            s for s in selected['ids'] if s in targets.get(m,[])]
    checked = read(BASE/'manifest.json')['checked_source_hashes']
    changed = [name for name,digest in checked.items() if sha(repo/name) != digest]
    assert changed == [PATCH], changed
    OUT.mkdir()
    (OUT/'code').mkdir()
    for name in ['recover_direct_answer_large.py','analyze_direct_answer_large.py','verify_short_video_recovery.py']:
        shutil.copy2(repo/'scripts'/name, OUT/'code'/name)
    shutil.copy2(repo/PATCH, OUT/'code/video_agent.py')
    import yaml
    for model,slug,base_port in [('35B-A3B','35b_a3b',8100),('27B','27b',8200)]:
        target=OUT/model;target.mkdir()
        write(target/'samples.json',targets[model])
        cfg=yaml.safe_load((SOURCE/f'configs/inference/modal_qwen35_{slug}_no_skill.yaml').read_text())
        exname='modal_h200x8.yaml' if model=='35B-A3B' else 'modal_h200x8_qwen35_27b.yaml'
        ex=yaml.safe_load((SOURCE/'configs/inference/execution'/exname).read_text())
        cfg['runtime']['cache_dir']=str(target/'runtime_cache')
        ex['media_cache']['root']=f'/work/direct-recovery-media-{model}'
        name=next(iter(cfg['models']))
        for i,replica in enumerate(ex['model_pools'][name]['replicas']):
            replica['endpoint']=f'http://127.0.0.1:{base_port+i}/v1'
        for filename,value in [('config.yaml',cfg),('execution.yaml',ex)]:
            (target/filename).write_text(yaml.safe_dump(value,sort_keys=False))
    # Remove only reproducible bytecode in this stopped experiment, never source or results.
    removed=[]
    for p in BASE.rglob('*.pyc'):
        if '__pycache__' in p.parts:
            removed.append(dict(path=str(p),bytes=p.stat().st_size));p.unlink()
    for p in sorted(BASE.rglob('__pycache__'),key=lambda p:len(p.parts),reverse=True):
        if not any(p.iterdir()):p.rmdir()
    write(OUT/'recovery_manifest.json',dict(at=now(),parent=str(BASE),source=str(SOURCE),
        selection_sha256=sha(BASE/'selection.json'),original=original,targets=targets,
        changed_source_files={'35B-A3B':[], '27B':[PATCH]},
        code_sha256={p.name:sha(p) for p in (OUT/'code').iterdir()},
        config_sha256={str(p.relative_to(OUT)):sha(p) for m in targets for p in (OUT/m).glob('*.yaml')},
        source_commit=(repo/'.git/HEAD').read_text().strip(),removed_bytecode=removed,
        policy='No resampling. Original successes and failures remain immutable. Only 27B uses the temporal sampling repair.'))
    write(OUT/'progress.json',dict(phase='prepared',at=now(),models={m:dict(expected=len(ids),finished=0) for m,ids in targets.items()}))
    print(json.dumps({'targets':{m:len(ids) for m,ids in targets.items()},'removed_pyc':len(removed),
                      'free_inodes':os.statvfs('/runs').f_favail}),flush=True)


def repaired_source():
    target=Path('/work/direct-recovery-27b-source')
    if target.exists():return target
    target.mkdir()
    shutil.copytree(SOURCE/'src',target/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(OUT/'code/video_agent.py',target/PATCH)
    (target/'eval/agent_eval').mkdir(parents=True)
    shutil.copy2(SOURCE/'eval/agent_eval/run.py',target/'eval/agent_eval/run.py')
    for name in ['configs','scripts','.git']:(target/name).symlink_to(SOURCE/name,target_is_directory=True)
    (target/'eval/e2e_eval').symlink_to(SOURCE/'eval/e2e_eval',target_is_directory=True)
    for name in ['requirements.txt','demo.py']:(target/name).symlink_to(SOURCE/name)
    return target


def worker():
    import yaml
    state=read(OUT/'progress.json')
    state['started_at']=state.get('started_at',now())
    hardware=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid','--format=csv,noheader'],text=True)
    assert len(hardware.splitlines())==8 and all('H100' in s for s in hardware.splitlines())
    state['hardware']=hardware
    def save(phase,**values):
        state.update(phase=phase,updated_at=now(),**values);write(OUT/'progress.json',state)
    def run(command,log,source=SOURCE,model=None):
        with (OUT/log).open('a') as stream:
            p=subprocess.Popen(list(map(str,command)),cwd=source,stdout=stream,stderr=subprocess.STDOUT,
                env={**os.environ,'PYTHONPATH':str(source/'src'),'PYTHONDONTWRITEBYTECODE':'1',
                     'MVAGENT_PROJECT_ROOT':str(source)})
        while p.poll() is None:
            if model:
                state['models'][model]['finished']=sum(1 for _ in (OUT/model/'records').glob('*/*/result.json'))
            save(state['phase']);time.sleep(20)
        if p.returncode:raise RuntimeError(f'Exit {p.returncode}: {log}')
    try:
        for model in ['35B-A3B','27B']:
            if state['models'][model].get('inference_done'):continue
            target=OUT/model
            source=SOURCE if model=='35B-A3B' else repaired_source()
            cfg=yaml.safe_load((target/'config.yaml').read_text())
            pool=next(iter(cfg['models']))
            launcher=OUT/f'prelaunch_{model}.py'
            text=(SOURCE/'prelaunch.py').read_text()
            lines=text.splitlines()
            lines=[f'sys.path.insert(0, {str(source/"src")!r})' if s.startswith('sys.path.insert(0,') else s for s in lines]
            launcher.write_text('\n'.join(lines)+'\n')
            save('loading',model=model)
            run([sys.executable,launcher,'--replace',target/'config.yaml',target/'execution.yaml',pool],f'{model}_startup.log',source)
            save('inference',model=model)
            command=[sys.executable,source/'eval/agent_eval/run.py','--config',target/'config.yaml',
                '--execution-config',target/'execution.yaml','--dataset-root','/assets',
                '--sample-ids-file',target/'samples.json','--output',target,'--defer-open-qa-judge']
            if (target/'run_manifest.json').exists():command.append('--resume')
            run(command,f'{model}_inference.log',source,model)
            paths={p.parent.name:p for p in (target/'records').glob('*/*/result.json')}
            statuses={sid:read(p)['status'] for sid,p in paths.items()}
            pending=remaining(read(target/'samples.json'),statuses)
            state['models'][model].update(finished=len(paths),pending=pending,inference_done=not pending)
            assert not pending, (model,pending)
            save('inference_done',model=model)
            if model=='27B':
                save('verifying_repair',model=model)
                run([sys.executable,OUT/'code/verify_short_video_recovery.py','gpu'], '27B_repeat_check.log',source)
        save('judge_loading',model='35B-A3B')
        sys.path.append(str(Path('/runs/devbox/direct_answer_random_20261015/frozen_repo/scripts')))
        from run_mvagent_pilot import stop_actor_servers
        stop_actor_servers()
        os.environ['JUDGE_LOG_DIR']=str(OUT/'judge_servers')
        run(['bash',SOURCE/'eval/agent_eval/serve_ccqa_judge.sh','0-7','8300'],'judge_startup.log')
        save('judging')
        run([sys.executable,SOURCE/'eval/agent_eval/score_crossvid_ccqa.py','--output',OUT/'35B-A3B',
             '--endpoints','8300-8307'],'35B-A3B_judge.log')
        judged=read(OUT/'35B-A3B'/REPORT)
        assert not judged['failed_ids'] and len(judged['samples'])==28
        state['models']['35B-A3B']['judge_done']=True
        save('judge_completed',finished_at=now())
    except BaseException as exc:
        save('failed',error=repr(exc),traceback=traceback.format_exc());raise


def self_check():
    assert remaining(['a','b','c'],{'a':'ok','b':'error'})==['b','c']
    assert remaining(['a'],{'a':'ok'})==[]
    try:remaining(['a'],{'other':'ok'})
    except AssertionError:pass
    else:raise AssertionError('Unexpected rows must fail')
    print('Recovery selection checks passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','worker','self-check'])
    args=parser.parse_args()
    {'prepare':prepare,'worker':worker,'self-check':self_check}[args.mode]()
