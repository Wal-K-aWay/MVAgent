"""Repair NC80/VAM inputs and rerun RSI request failures with the approved longer HTTP wait."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request

ADAPTERS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ADAPTERS))
from common import sha256, write

BASE = Path('/runs/devbox/external_upstream_20261015')
ROOT = Path('/runs/devbox/external_upstream_nc80_20261015')
SID = 'crossvid:NC:80'
SUPPORT = '/runs/devbox/external_methods_20261014/support/deps'


def retry_reason(execution, requests):
    if execution['sample_id'] == SID:
        return 'hidden decoder preroll in original input'
    if not execution['success']:
        return 'original execution failed'
    if not requests or any(r.get('error') or not (r.get('response') or {}).get('choices') for r in requests):
        return 'completed execution contains request errors or lacks request evidence'
    return None


def prepare():
    ROOT.mkdir(exist_ok=False)
    frozen = ROOT/'frozen_repo'
    shutil.copytree(BASE/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    (frozen/'source_manifest.json').rename(frozen/'parent_source_manifest.json')
    shutil.copy2(ADAPTERS/'prepare.py', frozen/'eval/external_methods/prepare.py')
    shutil.copy2(__file__, frozen/'eval/external_methods/experiments/20261015/repair_preroll.py')
    write(frozen/'source_manifest.json', dict(parent=str(BASE/'frozen_repo'),
        reason='Only input preparation changes; Actor, adapter and scoring sources remain identical',
        files={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*') if p.is_file()}))
    write(ROOT/'selection.json', dict(sample_ids=[SID], reason='Remove hidden decoding preroll, preserving displayed frames'))
    write(BASE/'input_invalidations.json', dict(sample_ids=[SID],
        reason='Packet origins were negative while first displayed frames start at zero; hidden preroll became visible',
        replacement_run=str(ROOT), canonical_summary='final_analysis.json; original NC80 output is diagnostic only'))
    subprocess.run([sys.executable,str(frozen/'eval/external_methods/prepare.py'), '--selection',str(ROOT/'selection.json'),
        '--output',str(ROOT/'prepared')],env=dict(os.environ,PYTHONPATH=f'{SUPPORT}:{frozen}/src'),check=True)
    old = json.loads((BASE/'prepared/private_labels.json').read_text())[SID]
    new = json.loads((ROOT/'prepared/private_labels.json').read_text())[SID]
    assert old == new, 'Media repair must not change the question or scoring labels'


def freeze_runtime():
    frozen = ROOT/'runtime_repo'
    shutil.copytree(ROOT/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    (frozen/'source_manifest.json').rename(frozen/'media_source_manifest.json')
    for name in ('rsi.py', 'vam.py', 'embedding_server.py', 'upstream_settings.json', 'README.md',
                 'experiments/20261014/current_smoke.py',
                 'experiments/20261015/repair_preroll.py'):
        shutil.copy2(ADAPTERS/name, frozen/'eval/external_methods'/name)
    write(frozen/'source_manifest.json', dict(parent=str(ROOT/'frozen_repo'),
        reason='Approved RSI HTTP wait 1860 seconds and VAM 448 cap; native generation and step budgets unchanged',
        files={str(p.relative_to(frozen)):sha256(p) for p in frozen.rglob('*') if p.is_file()}))
    subprocess.run([sys.executable, '-m', 'compileall', '-q', str(frozen/'eval/external_methods')], check=True)
    write(BASE/'input_invalidations.json', dict(sample_ids=[SID],
        reason='NC80 hidden decoder preroll; initial VAM batch omitted approved 448 cap',
        replacement_run=str(ROOT), canonical_summary='final_analysis.json',
        excluded_vam_run=str(BASE/'vam')))
    progress = json.loads((BASE/'rsi/progress.json').read_text())
    assert progress['completed'] == progress['expected'] == 65
    reasons = {}
    for row in progress['samples']:
        requests = BASE/'rsi'/row['sample_id'].replace(':','_')/'requests.jsonl'
        reason = retry_reason(row, [json.loads(line) for line in requests.read_text().splitlines()]
                             if requests.exists() else [])
        if reason:
            reasons[row['sample_id']] = reason
    repaired = json.loads((ROOT/'prepared/items.json').read_text())[0]
    assert repaired['sample_id'] == SID
    items = [repaired if item['sample_id'] == SID else item
             for item in json.loads((BASE/'prepared/items.json').read_text()) if item['sample_id'] in reasons]
    prepared = ROOT/'retry_prepared'
    for item in items:
        write(prepared/'items'/(item['sample_id'].replace(':','_')+'.json'), item)
    write(prepared/'items.json', items)
    write(prepared/'selection.json', dict(reasons=reasons, policy='Reuse only successful executions without request errors'))
    shutil.copy2(BASE/'prepared/private_labels.json', prepared/'private_labels.json')
    write(ROOT/'runtime_ready.json', dict(source_manifest_sha256=sha256(frozen/'source_manifest.json'),
        actor_image_pixels=448*448, embedding_image_pixels=448*448, rsi_http_timeout_seconds=1860,
        rsi_reruns=len(items)))


def infer():
    frozen = ROOT/'runtime_repo'
    scripts = frozen/'eval/external_methods'
    sys.path.insert(0, str(scripts/'experiments/20261014'))
    from current_smoke import stop, score
    env = dict(os.environ, PYTHONPATH=f'{SUPPORT}:{frozen}/src')
    started = time.monotonic()
    state = dict(phase='starting_model', started_at=datetime.now(timezone.utc).isoformat())
    write(ROOT/'progress.json', state)
    with (ROOT/'actor.log').open('w') as log:
        model = subprocess.Popen([sys.executable,str(scripts/'native_server.py'),'--model','/weights/Qwen3.5-35B-A3B',
            '--gpus','0,1,2','--port','8100','--log-dir',str(ROOT/'servers')],env=env,stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True)
    with (ROOT/'embedding.log').open('w') as log:
        embedding = subprocess.Popen([sys.executable,str(scripts/'embedding_server.py'),
            '--source',str(frozen/'external_sources/Qwen3-VL-Embedding'),
            '--weights','/runs/devbox/external_methods_20261014/support/Qwen3-VL-Embedding-8B',
            '--output',str(ROOT/'embedding')], env=dict(env,CUDA_VISIBLE_DEVICES='3'),
            stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        deadline = time.monotonic()+1200
        pending = {f'http://127.0.0.1:{p}/v1/models' for p in (8100,8101,8102)} | {'http://127.0.0.1:8200/'}
        while pending:
            if model.poll() is not None or embedding.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Repair model startup failed')
            for url in list(pending):
                try:
                    with urllib.request.urlopen(url,timeout=3) as response:
                        json.load(response)
                    pending.remove(url)
                except OSError:
                    pass
            time.sleep(5)
        state.update(phase='running', model_startup_seconds=time.monotonic()-started)
        write(ROOT/'progress.json', state)
        inference_started = time.monotonic()
        subprocess.run([sys.executable,str(scripts/'run_batch.py'),'rsi','--prepared',str(ROOT/'retry_prepared'),
            '--output',str(ROOT/'rsi'),'--ports','8100,8101,8102'],env=env,check=True)
        subprocess.run([sys.executable,str(scripts/'run_batch.py'),'vam','--prepared',str(BASE/'prepared'),
            '--output',str(ROOT/'vam'),'--ports','8100','--smoke'],env=env,check=True)
        for path in (ROOT/'rsi').glob('*/effective_config.json'):
            config = json.loads(path.read_text())['config']
            assert config['services']['timeout_seconds'] == 1860
            assert config['services']['temperature'] == 0
            assert all(config['services'][role]['max_tokens'] == 8192 for role in ('qwen','deepseek'))
        for path in (ROOT/'vam').glob('*/effective_config.json'):
            assert json.loads(path.read_text())['settings']['llm_max_image_pixels'] == 448*448
        assert json.loads((ROOT/'embedding/manifest.json').read_text())['max_pixels'] == 448*448
        methods = {method:json.loads((ROOT/method/'progress.json').read_text()) for method in ('rsi','vam')}
        state.update(phase='inference_completed', inference_seconds=time.monotonic()-inference_started,
                     total_seconds=time.monotonic()-started,
                     methods={method:{key:row[key] for key in ('expected','successful','failed','batch_seconds')}
                              for method,row in methods.items()})
    except BaseException as exc:
        state.update(phase='failed', error=repr(exc))
        raise
    finally:
        stop(embedding)
        stop(model)
        write(ROOT/'progress.json', state)
    score(ROOT, prepared=ROOT/'retry_prepared')


def finalize():
    import modal
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    deadline = time.monotonic()+10000
    while True:
        volume.reload()
        main = json.loads((BASE/'progress.json').read_text())
        repair_path = ROOT/'progress.json'
        repair = json.loads(repair_path.read_text()) if repair_path.exists() else {}
        if main['phase'].startswith('failed') or repair.get('phase','').startswith('failed'):
            raise RuntimeError(f'Cannot merge failed controllers: {main["phase"]}, {repair.get("phase")}')
        if main['phase'] in ('completed','completed_with_errors') and repair.get('phase') in ('completed','completed_with_errors'):
            break
        if time.monotonic() > deadline:
            raise TimeoutError('Inference did not finish before the postprocessing deadline')
        time.sleep(20)
    sys.path.insert(0, str(BASE/'frozen_repo/src'))
    from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator
    labels = json.loads((BASE/'prepared/private_labels.json').read_text())
    original = json.loads((BASE/'rsi/scores.json').read_text())
    repaired = json.loads((ROOT/'rsi/scores.json').read_text())
    assert not original['pending_judge'] and not repaired['pending_judge']
    reasons = json.loads((ROOT/'retry_prepared/selection.json').read_text())['reasons']
    assert {row['sample_id'] for row in repaired['rows']+repaired['failed']} == set(reasons)
    rows = [row for row in original['rows'] if row['sample_id'] not in reasons]+repaired['rows']
    scores = {row['sample_id']:row['score'] for row in rows}
    assert len(rows) == len(scores)
    aggregator = HierarchicalScoreAggregator(dataset_of={s:r['dataset'] for s,r in labels.items()},
        category_of={s:r['task'] for s,r in labels.items()},
        task_population={(r['dataset'],r['task']):r['task_population'] for r in labels.values()},
        sample_weights={s:len(r['sample']['ground_truth']) if r['sample']['task']=='open_qa' else 1 for s,r in labels.items()})
    failures = [row for row in original['failed'] if row['sample_id'] not in reasons]+repaired['failed']
    progress = json.loads((BASE/'rsi/progress.json').read_text())
    rerun_progress = json.loads((ROOT/'rsi/progress.json').read_text())
    timings = [r for r in progress['samples'] if r['sample_id'] not in reasons]+rerun_progress['samples']
    assert len(timings) == 65 and len(rows)+len(failures) == 65
    vam = json.loads((ROOT/'vam/scores.json').read_text())
    report = dict(status='completed_with_errors' if failures or vam['failed'] else 'completed',
        rsi=dict(expected=65,scored=len(rows),failed=failures,rows=rows,
                 aggregate=asdict(aggregator.aggregate(sample_ids=list(scores),scores=scores,buckets={})) if scores else None,
                 covered_tasks={ds:len({labels[s]['task'] for s in scores if labels[s]['dataset']==ds})
                                for ds in ('crossvid','cvbench','mvu_eval')},
                 valid_input_question_seconds=dict(mean=statistics.mean(r['seconds'] for r in timings),
                    median=statistics.median(r['seconds'] for r in timings), maximum=max(r['seconds'] for r in timings)),
                 original_batch_seconds=progress['batch_seconds'],rerun_batch_seconds=rerun_progress['batch_seconds'],
                 rerun_reasons=reasons, reused_successes=65-len(reasons)),
        vam=vam, vam_timing=json.loads((ROOT/'vam/progress.json').read_text()),
        main_phase_timing=main, repair_phase_timing=repair,
        score_reuse='Reuse only error-free successful original executions; replace every retry selection, including NC80',
        original_invalid_output=str(BASE/'rsi'/SID.replace(':','_')), repaired_output=str(ROOT/'rsi'/SID.replace(':','_')),
        excluded_vam_output=str(BASE/'vam'), repaired_vam_output=str(ROOT/'vam'),
        limitation='Development panel; original NC80 and initial VAM without the approved 448 cap remain archived and excluded')
    write(BASE/'final_analysis.json', report)
    volume.commit()
    print(json.dumps({k:v for k,v in report.items() if k not in ('rsi','vam')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare','freeze_runtime','infer','finalize'])
    args = parser.parse_args()
    globals()[args.phase]()
