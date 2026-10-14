"""Finish RSI/VAM scores after the user removed MetaVideoAgent from scope."""
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


for names in GROUPS.values():
    wait_for(names)

from datetime import datetime, timezone
cancelled_at = datetime.now(timezone.utc).isoformat()
meta_completed = 0
for name in ('meta_one_r3','meta_two_r3','meta_early_run','meta_rest_run'):
    path = ROOT/name/'progress.json'
    previous = path.read_text()
    progress = json.loads(previous)
    meta_completed += progress['completed']
    if progress['phase'] == 'running':
        (path.parent/'progress.before_cancellation.json').write_text(previous)
        progress.update(phase='cancelled_by_user', cancelled=progress['expected']-progress['completed'],
                        stopped_at=cancelled_at, stop_reason='User removed MetaVideoAgent from future evaluation')
        path.write_text(json.dumps(progress,indent=2)+'\n')
scope = dict(changed_at=cancelled_at, methods=['rsi','vam'], excluded=['meta'],
             meta_completed=meta_completed, meta_cancelled=33-meta_completed,
             previous_sandbox_exit_code=137, reason='User requested no further MetaVideoAgent evaluation')
(ROOT/'scope_change.json').write_text(json.dumps(scope,indent=2)+'\n')
env = dict(os.environ, JUDGE_LOG_DIR=str(ROOT/'judge_final'))
subprocess.run(['bash',str(FROZEN/'eval/agent_eval/serve_ccqa_judge.sh'),'0','8110'], env=env, check=True)
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

import hashlib
files=[ROOT/'final_summary.json']+[ROOT/(method+'_combined')/'scores.json' for method in GROUPS]
completion=dict(completed_at=datetime.now(timezone.utc).isoformat(), status='completed',
    methods=list(GROUPS),excluded=['meta'],meta_completed=meta_completed,
    hashes={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    execution='One-off single-H100 scoring function; GPU released when the app exits')
(ROOT/'completion.json').write_text(json.dumps(completion,indent=2)+'\n')
