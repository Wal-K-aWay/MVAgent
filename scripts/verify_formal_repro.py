#!/usr/bin/env python3
"""Small Modal regression through the public E2E and MVAgent HTTP entry points."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from confirm_single_process_mvagent import compare_rollouts
from verify_e2e_sync import compare_rows, records
from models.vlm.local.sync_server import ENGINE_CONFIG, execution_profile, sha256_file, write_json
from harness.common import git

ROOT = Path(__file__).resolve().parents[1]
MODELS = [('9B', '9b', [0, 1]), ('27B', '27b', [0, 1]), ('35B-A3B', '35b_a3b', [0, 1])]
E2E_IDS = {'cvbench': ['cvbench:664'], 'mvu_eval': ['mvu_eval:ICL:713'], 'crossvid': ['crossvid:FSA:121']}
AGENT_IDS = ['mvu_eval:Comparison:818', 'crossvid:MOC:521']


def command(args, log):
    started = time.monotonic()
    with log.open('w') as stream:
        subprocess.run([str(a) for a in args], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, check=True)
    return round(time.monotonic() - started, 3)


def agent_records(directory):
    rows = [json.loads(p.read_text()) for p in (directory / 'records').rglob('result.json')]
    assert {r['sample_id'] for r in rows} == set(AGENT_IDS)
    for row in rows:
        assert row['status'] == 'ok' and row['scoring_status'] == 'skipped', row.get('error')
        responses = [e for e in row['events'] if e['kind'] == 'model_response']
        assert responses and all(e['worker']['forward_calls'] > 0 for e in responses)
        assert len({(e['worker']['pid'], e['worker']['gpu_uuid']) for e in responses}) == 1
        assert not any(e['kind'] in ('model_error', 'structured_invalid') for e in row['events'])
    return {r['sample_id']: r for r in rows}


def run_model(output, model, slug, gpus):
    import yaml
    root = output / model
    root.mkdir()
    config = yaml.safe_load((ROOT / f'configs/inference/modal_qwen35_{slug}_no_skill.yaml').read_text())
    name = next(iter(config['models']))
    config['runtime']['cache_dir'] = str(root / 'runtime_cache')
    cfg = root / 'config.yaml'
    cfg.write_text(yaml.safe_dump(config, sort_keys=False))
    replicas = [dict(gpus=[g], endpoint=f'http://127.0.0.1:{8100+g}/v1', max_inflight=1) for g in gpus]
    execution = dict(question_workers=2, max_prepared_requests=4, question_retries=0,
        question_timeout_sec=1800, media_cache=dict(root=str(root / 'media'), max_bytes=10*1024**3),
        model_pools={name: dict(replicas=replicas)})
    ex = root / 'execution.yaml'
    ex.write_text(yaml.safe_dump(execution))
    write_json(root / 'agent_ids.json', AGENT_IDS)
    state = dict(model=model, phase='loading', completed_e2e=0, completed_agent=0)
    write_json(root / 'progress.json', state)
    command([sys.executable, '/devtools/prelaunch.py', '--replace', cfg, ex, name], root / 'startup.log')
    e2e_runs, agent_runs, timings = [], [], []
    for repeat in range(2):
        state['phase'] = f'e2e-{repeat}'
        write_json(root / 'progress.json', state)
        endpoints = replicas[repeat:] + replicas[:repeat]
        e2e = root / f'e2e-{repeat}'
        args = [sys.executable, 'eval/e2e_eval/run.py', 'infer', '--output', e2e,
            '--endpoints', ','.join(r['endpoint'] for r in endpoints), '--media-cache-dir', output / 'e2e_media', '--workers', '3', '--retries', '1']
        for benchmark in E2E_IDS:
            args += ['--ids', f'{benchmark}={output / (benchmark + ".json")}']
        seconds = command(args, root / f'e2e-{repeat}.log')
        e2e_runs.append(records(e2e))
        state['completed_e2e'] += len(e2e_runs[-1])
        timings.append(dict(kind='e2e', repeat=repeat, seconds=seconds))
        state['phase'] = f'agent-{repeat}'
        write_json(root / 'progress.json', state)
        agent = root / f'agent-{repeat}'
        args = [sys.executable, 'eval/agent_eval/run.py', '--config', cfg, '--execution-config', ex,
                '--dataset-root', '/assets', '--sample-ids-file', root / 'agent_ids.json',
                '--output', agent, '--inference-only']
        seconds = command(args, root / f'agent-{repeat}.log')
        agent_runs.append(agent_records(agent))
        state['completed_agent'] += len(agent_runs[-1])
        timings.append(dict(kind='agent', repeat=repeat, seconds=seconds))
        write_json(root / 'progress.json', state)
    differences = dict(e2e=compare_rows(*e2e_runs), agent={})
    for sid in AGENT_IDS:
        delta = compare_rollouts(agent_runs[0][sid], agent_runs[1][sid])
        if delta['calls'] or delta['result_fields']:
            differences['agent'][sid] = delta
    calls = [[e for row in run.values() for e in row['events'] if e['kind'] == 'model_response'] for run in agent_runs]
    result = dict(model=model, e2e_responses=sum(map(len, e2e_runs)), e2e_comparisons=len(e2e_runs[0]),
        trajectories=sum(map(len, agent_runs)), trajectory_comparisons=len(AGENT_IDS),
        model_calls=sum(map(len, calls)), paired_call_comparisons=len(calls[0]), differences=differences,
        execution=execution_profile(), timings=timings,
        actual_e2e_outputs={sid: row['output'] for sid, row in e2e_runs[0].items()},
        actual_agent_answers={sid: row['prediction'] for sid, row in agent_runs[0].items()},
        agent_max_calls=max(sum(e['kind']=='model_response' for e in row['events']) for run in agent_runs for row in run.values()),
        gpu_uuids=sorted({e['worker']['gpu_uuid'] for run in calls for e in run}))
    write_json(root / 'report.json', result)
    write_json(root / 'progress.json', {**state, 'phase': 'completed'})
    if any(differences.values()):
        raise RuntimeError(f'{model}: repeated outputs differ; see report.json')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    if not output.resolve().is_relative_to(Path('/runs').resolve()) or (output / 'source.tar.gz').exists():
        parser.error('Use a fresh directory in the runs volume')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'prelaunch.py').write_bytes(Path('/devtools/prelaunch.py').read_bytes())
    for benchmark, ids in E2E_IDS.items():
        write_json(output / (benchmark + '.json'), ids)
    subprocess.run(['tar', '-czf', str(output / 'source.tar.gz'), '--exclude=__pycache__',
                    'src', 'eval', 'scripts', 'configs', 'requirements.txt', 'demo.py'], cwd=ROOT, check=True)
    write_json(output / 'manifest.json', dict(source_sha256=sha256_file(output / 'source.tar.gz'),
        commit=git('rev-parse', 'HEAD'), prelaunch_sha256=sha256_file(output / 'prelaunch.py'),
        engine_config=ENGINE_CONFIG, e2e_ids=E2E_IDS, agent_ids=AGENT_IDS, scoring_requested=False))
    results = [run_model(output, *item) for item in MODELS]
    write_json(output / 'report.json', results)
    lines = ['# 正式入口小规模回归', '', '三个 BF16 模型；两张 H100 顺序换模型；原正式 CLI；无评分/Judge。', '',
             '|模型|E2E响应/比较|Agent轨迹/比较|模型调用/比较|差异|', '|---|---:|---:|---:|---:|']
    for r in results:
        lines.append(f"|{r['model']}|{r['e2e_responses']}/{r['e2e_comparisons']}|{r['trajectories']}/{r['trajectory_comparisons']}|{r['model_calls']}/{r['paired_call_comparisons']}|0|")
    lines += ['', '每题全部 Agent 调用均固定在一个 GPU/进程；每个响应均验证真实 forward、输入与完整 token IDs。',
              '小样本仅验收正式入口接入，不替代此前大规模复现证据；本次没有重启矩阵或非空 skill 评估。', '',
              '原始记录：`' + str(output) + '`。源码 SHA256：`' + sha256_file(output / 'source.tar.gz') + '`。', '']
    for r in results:
        lines += ['## ' + r['model'], '', '实际输出（未评价正确率）：', '',
                  '```json', json.dumps({k: r[k] for k in ['actual_e2e_outputs', 'actual_agent_answers', 'agent_max_calls', 'timings']}, ensure_ascii=False, indent=2), '```', '']
    (output / 'report.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
