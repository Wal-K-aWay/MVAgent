#!/usr/bin/env python3
"""Run a frozen 66-question, two-pass 35B pilot through the unchanged Agent CLI."""
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

from check_mvagent_runtime import ROOT, analyze, records, run, self_check as audit_check, write

SEED = 20261013
SPLIT = Path('configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json')


def select(groups):
    rng = random.Random(SEED)
    return [sid for key in sorted(groups) for sid in rng.sample(sorted(groups[key]), 2)]


def prepare_panel(output):
    lite = {r['sample_id'] for r in json.loads((ROOT/SPLIT).read_text())['samples']}
    groups, sources = defaultdict(list), {}
    excluded = ['cvbench:64', 'cvbench:65', 'cvbench:66']
    for dataset, relative in [('cvbench', 'cvbench/QAs.json'), ('mvu_eval', 'mvu-eval/QAs.json'),
                              ('crossvid', 'crossvid/qa.jsonl')]:
        path = Path('/assets')/relative
        sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = ([json.loads(line) for line in path.read_text().splitlines()]
                if path.suffix == '.jsonl' else json.loads(path.read_text()))
        for row in rows:
            task = row['task_type'] if dataset == 'cvbench' else row['task']
            sid = (f'cvbench:{row["id"]}' if dataset == 'cvbench' else
                   f'mvu_eval:{task}:{row["id"]}' if dataset == 'mvu_eval' else row['id'])
            if sid in excluded or (dataset == 'crossvid' and sid not in lite):
                continue
            groups[dataset, task].append(sid)
    assert len(groups) == 33
    samples = select(groups)
    assert len(samples) == len(set(samples)) == 66
    write(output/'samples.json', samples)
    write(output/'selection.json', dict(seed=SEED, samples=samples, source_sha256=sources,
        sample_sha256=hashlib.sha256((output/'samples.json').read_bytes()).hexdigest(),
        split=str(SPLIT), split_sha256=hashlib.sha256((ROOT/SPLIT).read_bytes()).hexdigest(),
        selection='Two seeded random questions per native task, without inspecting answers or scores',
        per_benchmark=dict(Counter(sid.split(':')[0] for sid in samples)),
        excluded_known_corrupt=excluded, strata={f'{d}/{t}': len(v) for (d,t),v in groups.items()}))
    return samples


def freeze(output):
    frozen = output/'frozen_repo'
    if ROOT == frozen.resolve():
        return
    if frozen.exists():
        raise FileExistsError('Use a new pilot output; do not overwrite frozen experiments')
    temporary = output/'frozen_repo.tmp'
    temporary.mkdir()
    for name in ['src', 'scripts', 'eval', 'configs', '.git']:
        shutil.copytree(ROOT/name, temporary/name, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
    for name in ['requirements.txt', 'demo.py']:
        shutil.copy2(ROOT/name, temporary/name)
    source = Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"', repr(str(frozen/'src')))
    (temporary/'prelaunch.py').write_text(source)
    temporary.rename(frozen)
    os.execv(sys.executable, [sys.executable, str(frozen/'scripts'/Path(__file__).name),
                             '--output', str(output)])


def stop_actor_servers():
    # This controller owns all actor services in its dedicated Sandbox.
    subprocess.run(['pkill', '-f', '[s]ync_server.py'], check=False)
    deadline = time.monotonic()+600
    while time.monotonic() < deadline:
        used = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used',
                                        '--format=csv,noheader,nounits'], text=True).split()
        if used and all(int(value) < 2048 for value in used):
            return
        time.sleep(5)
    raise TimeoutError('Actor services did not release GPU memory before Judge startup')


def self_check():
    groups = {('dataset', str(i)): [f'{i}:{j}' for j in range(5)] for i in range(33)}
    chosen = select(groups)
    assert len(chosen) == len(set(chosen)) == 66 and chosen == select(groups)
    assert set(Counter(sid.split(':')[0] for sid in chosen).values()) == {2}
    audit_check()
    print('Pilot selection and paired-output audit self-check passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if not args.output:
        parser.error('--output is required')
    output = args.output.resolve()
    assert output.is_relative_to(Path('/runs').resolve())
    output.mkdir(parents=True, exist_ok=True)
    freeze(output)
    import yaml
    from models.vlm.local.sync_server import execution_profile
    state = dict(started_at=datetime.now(timezone.utc).isoformat(), phase='preparing')
    try:
        self_check()
        samples = prepare_panel(output)
        config = yaml.safe_load((ROOT/'configs/inference/modal_qwen35_35b_a3b_no_skill.yaml').read_text())
        execution = yaml.safe_load((ROOT/'configs/inference/execution/modal_h200x8.yaml').read_text())
        config['runtime']['cache_dir'] = str(output/'runtime_cache')
        execution['media_cache']['root'] = str(output/'media')
        cfg, ex = output/'config.yaml', output/'execution.yaml'
        cfg.write_text(yaml.safe_dump(config, sort_keys=False))
        ex.write_text(yaml.safe_dump(execution, sort_keys=False))
        write(output/'manifest.json', dict(model='Qwen3.5-35B-A3B', precision='BF16', gpus=8,
            hardware=subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid',
                '--format=csv,noheader'], text=True), execution=execution_profile(), samples=len(samples),
            repeats=2, skills=None, config=config, resources=execution,
            judge='Qwen3-30B-A3B-Instruct-2507', score_pass=0))
        state.update(phase='loading')
        write(output/'progress.json', state)
        run([sys.executable, ROOT/'prelaunch.py', '--replace', cfg, ex, next(iter(config['models']))],
            output/'startup.log')
        for repeat in range(2):
            state.update(phase='agent', repeat=repeat)
            write(output/'progress.json', state)
            run([sys.executable, 'eval/agent_eval/run.py', '--config', cfg, '--execution-config', ex,
                 '--sample-ids-file', output/'samples.json', '--dataset-root', '/assets',
                 '--output', output/f'repeat{repeat}',
                 '--inference-only' if repeat else '--defer-open-qa-judge'], output/f'repeat{repeat}.log')
        report = analyze(records(output/'repeat0'), records(output/'repeat1'), samples=samples)
        write(output/'reliability.json', report)
        state.update(phase='judge_loading', reliability={k: v for k,v in report.items() if k != 'answers'})
        write(output/'progress.json', state)
        stop_actor_servers()
        os.environ['JUDGE_LOG_DIR'] = str(output/'judge')
        run(['bash', 'eval/agent_eval/serve_ccqa_judge.sh', '0', '8100'], output/'judge_startup.log')
        state.update(phase='scoring')
        write(output/'progress.json', state)
        run([sys.executable, 'eval/agent_eval/score_crossvid_ccqa.py', '--output', output/'repeat0',
             '--endpoints', '8100'], output/'score.log')
        run([sys.executable, 'eval/agent_eval/finalize_results.py', '--output', output/'repeat0'],
            output/'finalize.log')
        run([sys.executable, 'eval/agent_eval/export_results.py', output/'repeat0'], output/'export.log')
        summary = json.loads((output/'repeat0/summary_scored.json').read_text())
        state['scores'] = {name: {k:v for k,v in data.items() if k in
            ['expected', 'completed', 'errors', 'official_score', 'official_task_macro', 'accuracy']}
            for name,data in summary['datasets'].items()}
        findings = report['errors'] or report['differences'] or report['answer_format_failures'] or any(report['event_errors'].values())
        state['phase'] = 'completed_with_findings' if findings else 'completed'
    except Exception as exc:
        import traceback
        state.update(phase='failed', error=repr(exc), traceback=traceback.format_exc())
        print(state['traceback'], flush=True)
    finally:
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        write(output/'progress.json', state)
        (output/'report.md').write_text('# MVAgent pilot\n\n```json\n'+json.dumps(state, ensure_ascii=False, indent=2)+'\n```\n')
        (Path('/work/jobs')/f'{output.name}.pid').unlink(missing_ok=True)
        os.utime('/work/heartbeat', (0, 0))


if __name__ == '__main__':
    main()
