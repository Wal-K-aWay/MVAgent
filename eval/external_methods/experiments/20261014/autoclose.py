"""One-shot completion handler for one existing experiment sandbox."""
import hashlib
import json
from pathlib import Path
import time
import modal

SANDBOX = 'sb-pkePyMfpAkafwHhbjqKes5'
PREFIX = 'devbox/external_methods_20261014'
sb = modal.Sandbox.from_id(SANDBOX)
wait_code = r'''
import json,time
from pathlib import Path
root=Path('/runs/devbox/external_methods_20261014')
pid=Path('/proc/8563/stat')
initial=pid.read_text().split()[21] if pid.exists() else None
while True:
    active=False
    try:
        fields=pid.read_text().split()
        active=fields[21]==initial and fields[2]!='Z'
    except FileNotFoundError:
        pass
    states=[json.loads((root/name/'progress.json').read_text())
            for name in ('vam_remaining','meta_early_run','meta_rest_run')]
    complete=all(s['phase']!='running' and s['completed']==s['expected'] for s in states)
    if complete and not active:break
    time.sleep(20)
print('Existing inference and finalizer have exited',flush=True)
'''
print('Waiting for existing inference and finalizer; no new evaluation submissions',flush=True)
p=sb.exec('python3','-u','-c',wait_code,timeout=14400)
print(p.stdout.read(),flush=True)
if p.wait()!=0:
    raise RuntimeError('Completion wait failed; automatic sandbox lifetime remains the fallback')
archive_code=r'''
import hashlib,json,shutil
from datetime import datetime,timezone
from pathlib import Path
root=Path('/runs/devbox/external_methods_20261014')
logs=root/'actor_server_logs'
for p in Path('/repo/.cache/mvagent/vllm').rglob('*'):
    if p.is_file() and p.suffix in ('.log','.json'):
        dest=logs/p.relative_to('/repo/.cache/mvagent/vllm')
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest)
files=[root/'final_summary.json']+[root/(m+'_combined')/'scores.json' for m in ('rsi','vam','meta')]
report=dict(completed_at=datetime.now(timezone.utc).isoformat(),
    status='completed' if all(p.exists() for p in files) else 'failed_finalization',
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()},
    finalizer_log='/runs/devbox/external_methods_20261014_finalize/job.log',
    sandbox='sb-pkePyMfpAkafwHhbjqKes5',
    shutdown='requested after external volume persistence verification')
(root/'completion.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
'''
p=sb.exec('python3','-c',archive_code,timeout=180)
report=json.loads(p.stdout.read())
assert p.wait()==0
volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
for attempt in range(12):
    try:
        saved=json.loads(b''.join(volume.read_file(PREFIX+'/completion.json')))
        assert saved==report
        for name,digest in report['hashes'].items():
            raw=b''.join(volume.read_file(PREFIX+'/'+name))
            assert hashlib.sha256(raw).hexdigest()==digest
        break
    except Exception:
        if attempt==11:raise
        time.sleep(10)
print('Persisted completion status: '+report['status'],flush=True)
sb.terminate()
state=Path.home()/'wxu-evolve-agent/devbox/state-external-methods-20261014.json'
if state.exists() and json.loads(state.read_text()).get('sandbox_id')==SANDBOX:
    state.unlink()
print('Terminated only '+SANDBOX,flush=True)
