#!/usr/bin/env python3
"""Frozen direct-answer evaluation, two independent eight-GPU shards, saved E2E controls."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts'), str(ROOT/'eval/e2e_eval')]
import compare_direct_answer as core

PANEL = Path('/runs/devbox/direct_answer_random_20261015')
OUT = Path('/runs/devbox/direct_answer_large_20261016')
FULL = Path('/runs/devbox/mvagent_final_score_20261016/comparison')
MODELS = core.MODELS
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'
read, write, sha, now = core.read, core.write, core.sha, core.now


def select(records, count):
    """Proportional CV/MVU strata and equal Cross task allocation, without outcomes."""
    groups = defaultdict(list)
    for sid, record in sorted(records.items()):
        groups[record.dataset, record.native_task].append(sid)
    rng = random.Random(0)
    selected = []
    for dataset in ['cvbench', 'mvu_eval', 'crossvid']:
        keys = sorted(k for k in groups if k[0] == dataset)
        weights = {k: 1 if dataset == 'crossvid' else records[groups[k][0]].task_population for k in keys}
        allocation = {k: min(2, len(groups[k])) for k in keys}
        while sum(allocation.values()) < count:
            candidates = [k for k in keys if allocation[k] < len(groups[k])]
            k = max(candidates, key=lambda k: count*weights[k]/sum(weights.values())-allocation[k])
            allocation[k] += 1
        for k in keys:
            selected.extend(rng.sample(groups[k], allocation[k]))
    assert len(selected) == len(set(selected)) == count*3
    rng.shuffle(selected)
    return selected


def freeze():
    frozen = OUT/'frozen_repo'
    if ROOT == frozen.resolve():
        return
    assert not frozen.exists(), 'Do not replace a frozen source'
    OUT.mkdir(parents=True, exist_ok=True)
    temporary = OUT/'frozen_repo.tmp'
    temporary.mkdir()
    for name in ['src', 'scripts', 'eval', 'configs', '.git']:
        shutil.copytree(ROOT/name, temporary/name, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
    for name in ['requirements.txt', 'demo.py']:
        shutil.copy2(ROOT/name, temporary/name)
    (temporary/'prelaunch.py').write_text((PANEL/'frozen_repo/prelaunch.py').read_text().replace(str(PANEL/'frozen_repo/src'), str(frozen/'src')))
    temporary.rename(frozen)
    os.execv(sys.executable, [sys.executable, str(frozen/'scripts'/Path(__file__).name), *sys.argv[1:]])


def prepare():
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    from models.vlm.local.sync_server import execution_profile
    old = read(PANEL/'manifest.json')
    checked = {}
    for name, expected in old['source_hashes'].items():
        if name.startswith(('src/mvagent/', 'src/models/', 'configs/inference/')) or name == 'eval/agent_eval/run.py':
            actual = sha(ROOT/name)
            assert actual == expected, ('Inference source mismatch', name, actual, expected)
            checked[name] = actual
    assert execution_profile() == old['profile']
    assert not (OUT/'selection.json').exists()
    originals = {m: {r['sample_id']: r for r in read(FULL/f'{m}.json')['rows']} for m in MODELS}
    ids = set(originals['9B'])
    assert len(ids) == 5321 and all(set(rows) == ids for rows in originals.values())
    records = load_multibench_records('/assets', sorted(ids))
    reused = {m: {r['sample_id']: r for r in read(PANEL/'analysis'/m/'paired.json')} for m in MODELS}
    ratios = {m: sum(r['new']['seconds'] for r in rows.values()) / sum(r['old']['seconds'] for r in rows.values())
              for m, rows in reused.items()}
    candidates = []
    for n in range(300, 951, 50):
        chosen = select(records, n)
        seconds = {m: sum(max(1, originals[m][sid]['seconds'] or 120)*ratios[m]
                          for sid in chosen if sid not in reused[m]) for m in MODELS}
        # Reserve 45 minutes for loading/judging/aggregation and 25% for throughput variation.
        hours = .75 + 1.25*sum(seconds.values())/16/3600
        candidates.append(dict(per_benchmark=n, unique_questions=len(chosen), predicted_hours=hours,
                               model_gpu_seconds=seconds,
                               reused={m: sum(sid in reused[m] for sid in chosen) for m in MODELS}))
    feasible = [row for row in candidates if row['predicted_hours'] <= 8.75]
    assert feasible, ('Even the minimum panel exceeds the time budget', candidates[0])
    budget = feasible[-1]
    chosen = select(records, budget['per_benchmark'])
    partitions = [[], []]
    loads = [0., 0.]
    for sid in sorted(chosen, key=lambda sid: -sum(max(1, originals[m][sid]['seconds'] or 120)*ratios[m]
                                                  for m in MODELS if sid not in reused[m])):
        shard = min(range(2), key=lambda k: loads[k])
        partitions[shard].append(sid)
        loads[shard] += sum(max(1, originals[m][sid]['seconds'] or 120)*ratios[m]
                           for m in MODELS if sid not in reused[m])
    for shard in range(2):
        random.Random(shard).shuffle(partitions[shard])
    selection = dict(created_at=now(), inference_seed=0, sampling_seed=0, ids=chosen,
        per_benchmark=dict(Counter(records[s].dataset for s in chosen)),
        strata=dict(Counter(f'{records[s].dataset}/{records[s].native_task}' for s in chosen)),
        partitions=partitions, budget=budget, budget_candidates=candidates, timing_ratios=ratios,
        source_population=5321, reused={},
        policy='Sample from the full existing E2E population without reading correctness. Reuse only selected exact-source results. '
               'Previous development overlap and newly evaluated questions are reported separately; this is not an untouched test set.')
    for shard, samples in enumerate(partitions):
        group = OUT/f'shard{shard}'
        write(group/'samples.json', samples)
        for m in MODELS:
            selection['reused'].setdefault(m, {})
            for sid in samples:
                if sid not in reused[m]:
                    continue
                src = PANEL/m/'run/records'/records[sid].dataset/sid/'result.json'
                raw = read(src)
                assert raw['status'] == 'ok' and raw['sample_id'] == sid
                dest = group/m/'records'/records[sid].dataset/sid/'result.json'
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(src)
                selection['reused'][m][sid] = dict(source=str(src), sha256=sha(src))
    write(OUT/'selection.json', selection)
    write(OUT/'manifest.json', dict(created_at=now(), profile=execution_profile(), checked_source_hashes=checked,
        source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        source_hashes={str(p.relative_to(ROOT)):sha(p) for folder in ['src','scripts','configs','eval/agent_eval']
                       for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.py','.yaml','.sh']},
        selection_sha256=sha(OUT/'selection.json'), reference_manifest_sha256=sha(PANEL/'manifest.json'),
        reference=str(PANEL), skills=None, repeats=1, judge='Qwen3-30B-A3B-Instruct-2507',
        sampling_scope='Existing 997 CV + 1824 MVU + CrossVid Lite2500; existing three corrupt CV videos already excluded.'))
    write(OUT/'progress.json', dict(phase='prepared', at=now(), budget=budget))
    print(json.dumps(dict(budget=budget, candidates=candidates, strata=selection['strata']), ensure_ascii=False), flush=True)


def worker(shard):
    import yaml
    from models.vlm.local.sync_server import execution_profile
    sys.path.append(str(PANEL/'frozen_repo/scripts'))
    from run_mvagent_pilot import stop_actor_servers
    group = OUT/f'shard{shard}'
    selected = read(group/'samples.json')
    expected_profile = read(OUT/'manifest.json')['profile']
    assert execution_profile() == expected_profile
    state_path = group/'progress.json'
    state = read(state_path) if state_path.exists() else dict(started_at=now(), models={})
    state.pop('error', None)
    state['hardware'] = subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid','--format=csv,noheader'], text=True)
    assert len(state['hardware'].splitlines()) == 8 and all('H100' in x for x in state['hardware'].splitlines())

    def save(phase, **values):
        state.update(phase=phase, updated_at=now(), **values)
        write(state_path, state)

    def run(command, log, model=None, check=True):
        with (group/log).open('a') as stream:
            p = subprocess.Popen(list(map(str, command)), cwd=ROOT,
                env={**os.environ,'PYTHONPATH':str(ROOT/'src')}, stdout=stream, stderr=subprocess.STDOUT)
        while p.poll() is None:
            if model:
                paths = list((group/model/'records').glob('*/*/result.json'))
                state['models'][model]['finished'] = len(paths)
            save(state['phase'])
            time.sleep(30)
        if check and p.returncode:
            raise RuntimeError(f'Exit {p.returncode}: {log}')
        return p.returncode

    try:
        for model, suffix in MODELS.items():
            record = state['models'].setdefault(model, {})
            if record.get('inference_done'):
                continue
            target = group/model
            target.mkdir(exist_ok=True)
            cfg = yaml.safe_load((ROOT/f'configs/inference/modal_qwen35_{suffix}_no_skill.yaml').read_text())
            exname = 'modal_h200x8.yaml' if model == '35B-A3B' else f'modal_h200x8_qwen35_{suffix}.yaml'
            ex = yaml.safe_load((ROOT/'configs/inference/execution'/exname).read_text())
            cfg['runtime']['cache_dir'] = str(target/'runtime_cache')
            ex['media_cache']['root'] = str(group/'media')
            pool = next(iter(cfg['models']))
            assert len(ex['model_pools'][pool]['replicas']) == 8
            for filename, value in [('config.yaml',cfg),('execution.yaml',ex)]:
                (target/filename).write_text(yaml.safe_dump(value,sort_keys=False))
            for attempt in range(2):
                paths = {p.parent.name:p for p in (target/'records').glob('*/*/result.json')}
                failed = [sid for sid,p in paths.items() if read(p)['status'] != 'ok']
                missing = set(selected)-set(paths)
                if not failed and not missing:
                    break
                for sid in failed:
                    p = paths[sid]
                    destination = target/'attempts'/f'{time.time_ns()}_{sid}'
                    destination.parent.mkdir(exist_ok=True)
                    shutil.move(str(p.parent), destination)
                save('loading', model=model, attempt=attempt)
                run([sys.executable,ROOT/'prelaunch.py','--replace',target/'config.yaml',target/'execution.yaml',pool], f'{model}_startup.log')
                save('inference', model=model)
                command = [sys.executable,ROOT/'eval/agent_eval/run.py','--config',target/'config.yaml',
                    '--execution-config',target/'execution.yaml','--dataset-root','/assets',
                    '--sample-ids-file',group/'samples.json','--output',target,'--defer-open-qa-judge']
                if (target/'run_manifest.json').exists():
                    command.append('--resume')
                code = run(command, f'{model}_inference.log', model, check=False)
                record['last_exit_code'] = code
            paths = {p.parent.name:p for p in (target/'records').glob('*/*/result.json')}
            record.update(inference_done=True, finished=len(paths), missing=sorted(set(selected)-set(paths)),
                errors=[sid for sid,p in paths.items() if read(p)['status'] != 'ok'])
            save('inference_done', model=model)
        if not all(state['models'][m].get('judge_done') for m in MODELS):
            save('judge_loading')
            stop_actor_servers()
            os.environ['JUDGE_LOG_DIR'] = str(group/'judge_servers')
            run(['bash',ROOT/'eval/agent_eval/serve_ccqa_judge.sh','0-7','8100'],'judge_startup.log')
            for model in MODELS:
                if state['models'][model].get('judge_done'):
                    continue
                save('judging', model=model)
                run([sys.executable,ROOT/'eval/agent_eval/score_crossvid_ccqa.py','--output',group/model,
                     '--endpoints','8100-8107'],f'{model}_judge.log')
                judged = read(group/model/REPORT)
                assert not judged['failed_ids'], judged['failed_ids']
                state['models'][model]['judge_done'] = True
        save('completed', finished_at=now())
    except BaseException as exc:
        save('failed', error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        Path(f'/work/jobs/direct_answer_large_20261016_s{shard}.pid').unlink(missing_ok=True)


def self_check():
    from types import SimpleNamespace
    records = {f'{ds}:{task}:{i}':SimpleNamespace(dataset=ds,native_task=task,task_population=10)
               for ds in ['cvbench','mvu_eval','crossvid'] for task in ['a','b'] for i in range(10)}
    assert select(records, 8) == select(records, 8)
    assert Counter(s.split(':')[0] for s in select(records,8)) == dict(cvbench=8,mvu_eval=8,crossvid=8)
    assert len(set(select(records,8))) == 24
    print('Stratified selection self-check passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare','worker','self-check'])
    parser.add_argument('--shard', type=int, choices=[0,1])
    args = parser.parse_args()
    if args.mode == 'self-check':
        self_check()
    elif args.mode == 'prepare':
        freeze(); prepare()
    else:
        assert ROOT == (OUT/'frozen_repo').resolve() and args.shard is not None
        worker(args.shard)
