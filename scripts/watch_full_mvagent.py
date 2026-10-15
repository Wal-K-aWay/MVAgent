#!/usr/bin/env python3
"""Run on modal-gpu: keep the frozen full evaluation alive across Sandbox lifetimes."""
import argparse
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import time

NAME='mvagent-full-20261013'
TAG='mvagent_full_20261013'
OUT='/runs/devbox/'+TAG
FROZEN=OUT+'/frozen_repo/scripts/run_full_mvagent.py'
RENEW_SECONDS=23*3600
TERMINAL={'completed','completed_with_errors','failed'}


def merge_completed(volume, plan_path):
    def read(path):
        return json.loads(b''.join(volume.read_file(path)))
    plan = read(plan_path)
    owners = [m for group in plan['groups'] for m in group['models']]
    assert len(owners) == 3 and set(owners) == {'9B', '27B', '35B-A3B'}
    states = [read(f"devbox/{g['tag']}/progress.json") for g in plan['groups']]
    if any(s.get('phase') != 'completed' for s in states):
        return False
    result = dict(phase='completed', updated_at=datetime.now(timezone.utc).isoformat(), models={}, comparisons={}, sources={})
    for group, state in zip(plan['groups'], states):
        assert state['model_scope'] == group['models']
        for model in group['models']:
            assert state['models'][model]['scoring_done']
            assert all(row['complete'] for row in state['comparisons'][model].values())
            result['models'][model] = state['models'][model]
            result['comparisons'][model] = state['comparisons'][model]
            result['sources'][model] = f"devbox/{group['tag']}/{model}"
    lines = ['# 三模型 MVAgent 与 E2E 同题比较', '', '三模型推理和评分均已完成。', '',
        '| 模型 | Benchmark | 配对题数 | E2E % | MVAgent % | 差值 pp |',
        '|---|---|---:|---:|---:|---:|']
    for model in ('9B', '27B', '35B-A3B'):
        for benchmark, row in result['comparisons'][model].items():
            lines.append(f"| {model} | {benchmark} | {row['paired']} | {100*row['e2e_score']:.2f} | {100*row['agent_score']:.2f} | {100*row['delta']:.2f} |")
    lines += ['', 'CrossVid 使用十任务 macro，CCQA 按评分点加权。两系统取证和输出预算不同。', '',
              '原始轨迹、逐题比较和完整来源保留在 progress.json 的 sources 所列目录。']
    with volume.batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(json.dumps(result, ensure_ascii=False, indent=2).encode()), plan['output']+'/progress.json')
        batch.put_file(io.BytesIO(('\n'.join(lines)+'\n').encode()), plan['output']+'/comparison.md')
    return True


def next_action(alive,phase,age,job_alive):
    if phase in TERMINAL:return 'finish'
    if alive and age>=RENEW_SECONDS:return 'renew'
    if not alive or not job_alive:return 'recover'
    return 'wait'


def self_check():
    assert next_action(True,'inference',10,True)=='wait'
    assert next_action(True,'inference',RENEW_SECONDS,True)=='renew'
    assert next_action(False,'inference',10,False)=='recover'
    assert next_action(True,'inference',10,False)=='recover'
    assert next_action(True,'failed',10,False)=='finish'
    assert next_action(False,'completed',RENEW_SECONDS,False)=='finish'
    print('Lifecycle checks passed: adopt active job, renew at 23h, stop on completion/failure')


def main():
    global NAME, TAG, OUT, FROZEN
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--devbox-name', default=NAME)
    parser.add_argument('--tag', default=TAG)
    parser.add_argument('--driver', help='Persisted orchestration script; the inference snapshot stays unchanged')
    parser.add_argument('--source')
    parser.add_argument('--models', nargs='+')
    parser.add_argument('--merge-plan', help='Optional runs-volume plan to merge scored model groups')
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--inspect',action='store_true',help='Read-only check; do not start or stop anything')
    args=parser.parse_args()
    if args.self_check:self_check();return
    NAME, TAG = args.devbox_name, args.tag
    OUT = '/runs/devbox/' + TAG
    FROZEN = OUT + '/frozen_repo/scripts/run_full_mvagent.py'
    driver = args.driver or FROZEN
    command = ['python', driver, '--output', OUT]
    if args.source:
        command += ['--source', args.source]
    if args.models:
        command += ['--models', *args.models]
    here=Path.home()/'wxu-evolve-agent/devbox'
    assert (here/'devbox.py').is_file(),'Run this controller on modal-gpu'
    os.environ['DEVBOX_NAME']=NAME
    sys.path.insert(0,str(here))
    import devbox
    import modal
    volume=modal.Volume.from_name(devbox.RUNS_VOLUME,environment_name='zheng-dev')
    def log(value):print(datetime.now(timezone.utc).isoformat(),json.dumps(value,ensure_ascii=False),flush=True)
    def progress():
        try:return json.loads(b''.join(volume.read_file(f'devbox/{TAG}/progress.json')))
        except FileNotFoundError:return {}
    def view():
        state=json.loads(Path(devbox.STATE).read_text()) if Path(devbox.STATE).exists() else None
        sb=modal.Sandbox.from_id(state['sandbox_id']) if state else None
        alive=sb is not None and sb.poll() is None
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['created_at'].replace('Z','+00:00'))).total_seconds() if state else 0
        job_alive=False
        if alive:
            code,out,_=devbox._sh(sb,f"python - <<'PY'\nfrom pathlib import Path\nimport os\np=Path('/work/jobs/{TAG}.pid')\ntry:\n pid=int(p.read_text());os.kill(pid,0)\n print('alive' if {Path(driver).name.encode()!r} in Path(f'/proc/{{pid}}/cmdline').read_bytes() else 'stopped')\nexcept (FileNotFoundError,ProcessLookupError,ValueError):print('stopped')\nPY",timeout=20)
            if code:raise RuntimeError('Could not inspect the controller PID')
            job_alive=out.strip()=='alive'
        data=progress()
        return sb,alive,age,job_alive,data
    if args.inspect:
        sb,alive,age,job_alive,data=view()
        log(dict(sandbox=sb.object_id if sb else None,alive=alive,age_seconds=age,job_alive=job_alive,phase=data.get('phase'),
                 action=next_action(alive,data.get('phase'),age,job_alive)))
        return
    lock=(here/f'watch-{TAG}.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    pidfile=here/f'watch-{TAG}.pid';pidfile.write_text(str(os.getpid()))
    stopping=False
    def requested_stop(signum,frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,requested_stop);signal.signal(signal.SIGINT,requested_stop)
    recoveries=0;failures=0;last_log=0;last_phase=None;sb=None
    def terminate(current):
        if current is not None and current.poll() is None:current.terminate()
        Path(devbox.STATE).unlink(missing_ok=True)
    def start():
        subprocess.run([sys.executable,str(here/'devbox.py'),'up','--gpu','H100!:8','--no-pool','--hours','24','--idle','15'],
                       cwd=here,check=True)
        new=devbox._sandbox()
        assert devbox.start_job(new,TAG,shlex.join(command))==0
        return new
    try:
        while not stopping:
            try:
                sb,alive,age,job_alive,data=view();phase=data.get('phase')
                action=next_action(alive,phase,age,job_alive)
                if phase!=last_phase or time.monotonic()-last_log>=900 or action!='wait':
                    log(dict(action=action,phase=phase,model=data.get('model'),sandbox=sb.object_id if sb else None,
                             finished={m:r.get('finished',0) for m,r in data.get('models',{}).items()}))
                    last_log=time.monotonic();last_phase=phase
                if action=='finish':
                    if alive:terminate(sb)
                    if args.merge_plan:
                        log(dict(merged=merge_completed(volume,args.merge_plan)))
                    break
                if action=='renew':
                    # Saved result files are atomic; the unfinished questions are retried by the frozen CLI.
                    devbox._sh(sb,f"python - <<'PY'\nfrom pathlib import Path\nimport os,signal\np=Path('/work/jobs/{TAG}.pid')\nif p.exists():os.kill(int(p.read_text()),signal.SIGTERM)\nPY",timeout=20)
                    time.sleep(45)
                    terminate(sb);sb=start()
                elif action=='recover':
                    # Restart the container too, so an orphaned CLI cannot coexist with its resumed replacement.
                    recoveries+=1
                    if recoveries>2:raise RuntimeError('Two unexpected restarts exhausted; inspect the saved failure before continuing')
                    if sb is not None:terminate(sb)
                    sb=start()
                failures=0
            except Exception as exc:
                failures+=1;log(dict(watcher_error=repr(exc),consecutive_failures=failures))
                if failures>=5:raise
            time.sleep(60)
    finally:
        if stopping:
            log({'action':'user_stop'})
            if sb is not None:terminate(sb)
        pidfile.unlink(missing_ok=True)


if __name__=='__main__':main()
