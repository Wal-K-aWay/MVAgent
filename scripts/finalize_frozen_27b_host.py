import fcntl,json,os,sys,time
from pathlib import Path
os.environ['MODAL_ENVIRONMENT']='zheng-dev'
sys.path.insert(0,'/home/weili/wxu-evolve-agent/devbox')
import modal,devbox
base=Path('/tmp/mvagent-27b-results-20261019')
lock=(base/'judge.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
devbox.REPO=str(base/'source')
devbox.NAME='mvagent-frozen-27b-judge-20261019'
devbox.STATE=str(Path(devbox.HERE)/f'state-{devbox.NAME}.json')
assert not Path(devbox.STATE).exists(), 'Inspect an existing owner before restarting'
v=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
sb=None
try:
 sys.argv=['devbox.py','up','--gpu','H100!:4','--no-pool','--hours','2','--idle','15']
 devbox.main();sb=devbox._sandbox();print('OWNED_SANDBOX',sb.object_id,flush=True)
 devbox._sh(sb,'mkdir -p /runs/devbox/frozen_27b_results_20261019; cat > /runs/devbox/frozen_27b_results_20261019/controller_source.py',stdin_bytes=Path(__file__).read_bytes(),timeout=30)
 assert devbox.start_job(sb,'frozen_27b_results_20261019','MVAGENT_EXPORT_MODEL=27B python scripts/finalize_frozen_results.py self-check && MVAGENT_EXPORT_MODEL=27B python scripts/finalize_frozen_results.py judge')==0
 while True:
  assert sb.poll() is None, 'Judge Sandbox exited unexpectedly'
  try:d=json.loads(b''.join(v.read_file('devbox/frozen_27b_results_20261019/progress.json')))
  except FileNotFoundError:d={'phase':'starting'}
  print(json.dumps(d),flush=True)
  if d['phase']=='judge_completed':break
  assert d['phase']!='failed',d
  time.sleep(45)
finally:
 if sb is None and Path(devbox.STATE).exists():sb=devbox._sandbox()
 if sb is not None and sb.poll() is None:sb.terminate(wait=True)
 Path(devbox.STATE).unlink(missing_ok=True)
 print('OWNED_GPU_RELEASED',flush=True)

import frozen_27b_results_cpu as cpu
command='MVAGENT_EXPORT_MODEL=27B python scripts/finalize_frozen_results.py '
with cpu.app.run(environment_name='zheng-dev'):
 rc,out,err=cpu.job.remote(command+'self-check && '+command+'prepare && '+command+'export && '+command+'verify')
print(out,err,flush=True)
assert rc==0,rc
print('PACKAGE_VERIFIED',flush=True)
