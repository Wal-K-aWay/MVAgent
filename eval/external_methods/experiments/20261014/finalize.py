"""Finalize only this experiment after its existing inference batches finish."""
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path('/runs/devbox/external_methods_20261014')
FROZEN = ROOT/'r9/frozen_repo'
GROUPS = {
    'rsi': ['rsi_smoke', 'rsi_remaining'],
    'vam': ['vam_smoke_r4', 'vam_remaining'],
    'meta': ['meta_one_r3', 'meta_two_r3', 'meta_early_run', 'meta_rest_run'],
}


def wait_for(names):
    deadline = time.monotonic() + 7200
    while time.monotonic() < deadline:
        values = [json.loads((ROOT/n/'progress.json').read_text()) for n in names]
        if all(v['phase'] != 'running' and v['completed'] == v['expected'] for v in values):
            return
        time.sleep(20)
    raise TimeoutError(f'Existing inference did not complete: {names}')


def combine(method):
    out = ROOT/(method+'_combined')
    out.mkdir(exist_ok=True)
    seen = set()
    for name in GROUPS[method]:
        for path in (ROOT/name).glob('*/execution.json'):
            record = json.loads(path.read_text())
            assert record['sample_id'] not in seen, record['sample_id']
            seen.add(record['sample_id'])
            link = out/path.parent.name
            if link.exists():
                assert link.resolve() == path.parent.resolve()
            else:
                link.symlink_to(path.parent)
    expected = set(json.loads((ROOT/'selection.json').read_text())['sample_ids'])
    assert seen == expected, (method, sorted(expected-seen), sorted(seen-expected))
    return out


wait_for(GROUPS['vam'])
# The only users of GPU4/port8104 are the now-completed VAM batches.
cards = json.loads((ROOT/'vam_remaining/service_cards.json').read_text())
card = next(c['card'] for c in cards if c['endpoint'] == 'http://127.0.0.1:8104/v1')
pid = card['worker']['pid']
assert card['worker']['cuda_visible_devices'] == '4'
command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
assert b'8104' in command and b'/weights/Qwen3.5-35B-A3B' in command
assert any(b'sync_server.py' in part for part in command)
os.kill(pid, signal.SIGTERM)
for _ in range(60):
    memory = subprocess.check_output(['nvidia-smi','--id=4','--query-gpu=memory.used','--format=csv,noheader,nounits'], text=True)
    if int(memory.strip()) < 2048:
        break
    time.sleep(5)
else:
    raise RuntimeError('GPU4 did not release memory; Judge not started')
print('VAM finished; starting the fixed CCQA Judge on GPU4', flush=True)
env = dict(os.environ, JUDGE_LOG_DIR=str(ROOT/'judge'))
subprocess.run(['bash',str(FROZEN/'eval/agent_eval/serve_ccqa_judge.sh'),'4','8110'], env=env, check=True)
for method in GROUPS:
    wait_for(GROUPS[method])
    out = combine(method)
    subprocess.run([sys.executable,str(FROZEN/'eval/external_methods/score.py'),
        '--prepared',str(ROOT),'--run',str(out),'--judge-endpoint','http://127.0.0.1:8110/v1'],check=True)

labels = json.loads((ROOT/'private_labels.json').read_text())
summary = {}
for method in GROUPS:
    out = ROOT/(method+'_combined')
    scores = json.loads((out/'scores.json').read_text())
    assert not scores['pending_judge']
    rows = [json.loads(p.read_text()) for p in out.glob('*/execution.json')]
    assert len(rows) == 33 and scores['scored'] + len(scores['failed']) == 33
    if method == 'meta':
        for p in out.glob('*/execution.json'):
            if json.loads(p.read_text())['success']:
                assert json.loads((p.parent/'result.json').read_text())['behavioral_smoke']['passed']
    per_dataset = {}
    for dataset in ('crossvid','cvbench','mvu_eval'):
        selected = [x for x in rows if labels[x['sample_id']]['dataset'] == dataset]
        complete = scores['complete_task_coverage'][dataset]
        observed = scores['aggregate']['bucket_scores'].get('dataset:'+dataset)
        per_dataset[dataset] = dict(attempted=len(selected),valid=sum(x['success'] for x in selected),
            complete_task_coverage=complete,official_estimate=observed if complete else None,
            observed_covered_tasks_score=observed,mean_seconds=statistics.mean(x['seconds'] for x in selected),
            median_seconds=statistics.median(x['seconds'] for x in selected))
    summary[method] = dict(attempted=len(rows),valid=scores['valid_predictions'],scored=scores['scored'],
        failures=[x['sample_id'] for x in scores['failed']],datasets=per_dataset)
(ROOT/'final_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print('FINAL_SUMMARY '+json.dumps(summary),flush=True)
