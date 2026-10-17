#!/usr/bin/env python3
"""Run the fixed three-model Agent matrix and pair its scores with completed E2E runs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback

from run_full_e2e import now, read, sha, write

ROOT = Path(__file__).resolve().parents[1]
MODELS = {'9B': '9b', '27B': '27b', '35B-A3B': '35b_a3b'}
E2E = {m: Path('/runs/devbox')/('e2e_full_20261012' if m == '9B' else 'e2e_full_20261013_timeout')/m for m in MODELS}
EXPECTED = {'cvbench': 997, 'mvu_eval': 1824, 'crossvid': 2500}
SPLIT = Path('configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json')
CCQA_REPORT = 'ccqa_scores_official_qwen3_30b_a3b.json'


def freeze(output, argv):
    frozen = output/'frozen_repo'
    if ROOT == frozen.resolve():
        return
    if not frozen.exists():
        temporary = output/'frozen_repo.tmp'
        temporary.mkdir()
        for name in ['src', 'scripts', 'eval', 'configs', '.git']:
            shutil.copytree(ROOT/name, temporary/name, ignore=shutil.ignore_patterns('__pycache__', '.cache'))
        for name in ['requirements.txt', 'demo.py']:
            shutil.copy2(ROOT/name, temporary/name)
        (temporary/'prelaunch.py').write_text(Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"', repr(str(frozen/'src'))))
        temporary.rename(frozen)
    os.execv(sys.executable, [sys.executable, str(frozen/'scripts'/Path(__file__).name), *argv])


def selected_ids(selection, unavailable):
    assert {key: len(value) for key, value in selection.items()} == {'cvbench': 1000, 'mvu_eval': 1824, 'crossvid': 2500}
    samples = [sid for ids in selection.values() for sid in ids if sid not in unavailable]
    assert len(samples) == len(set(samples)) == sum(EXPECTED.values())
    assert dict(Counter(sid.split(':')[0] for sid in samples)) == EXPECTED
    random.Random(0).shuffle(samples)
    return samples


def prepare(output):
    path = output/'manifest.json'
    if path.exists():
        manifest = read(path)
        assert manifest['driver_sha256'] == sha(Path(__file__)), 'Resume must use the original controller'
        return manifest
    import yaml
    from models.vlm.local.sync_server import execution_profile
    selection = read(E2E['9B']/'selection.json')
    unavailable = read(E2E['9B'].parent/'known_unavailable.json')
    bad_ids = {row['sample_id'] for row in unavailable['records']}
    assert bad_ids == {'cvbench:64', 'cvbench:65', 'cvbench:66'}
    assert Path(unavailable['source']).stat().st_size == unavailable['size']
    for model, source in E2E.items():
        assert read(source/'selection.json') == selection, model
        for benchmark, expected in EXPECTED.items():
            scored = read(source/'scored'/f'{benchmark}.json')
            assert len(scored) == expected and len({r['sample_id'] for r in scored}) == expected
    assert set(selection['crossvid']) == {r['sample_id'] for r in read(ROOT/SPLIT)['samples']}
    samples = selected_ids(selection, bad_ids)
    write(output/'samples.json', samples)
    write(output/'selection.json', selection)
    write(output/'known_unavailable.json', unavailable)
    configs, executions = {}, {}
    (output/'configs').mkdir()
    for model, suffix in MODELS.items():
        cfg = yaml.safe_load((ROOT/f'configs/inference/modal_qwen35_{suffix}_no_skill.yaml').read_text())
        exname = 'modal_h200x8.yaml' if model == '35B-A3B' else f'modal_h200x8_qwen35_{suffix}.yaml'
        execution = yaml.safe_load((ROOT/'configs/inference/execution'/exname).read_text())
        cfg['runtime']['cache_dir'] = str(output/'runtime_cache')
        execution['media_cache']['root'] = str(output/'media')
        actor = next(iter(cfg['models'].values()))
        assert actor['temperature'] == 0 and actor['top_p'] == 1 and actor['enable_thinking'] is False
        assert actor['max_tokens'] == 2048 and actor['max_video_frames_per_request'] == 512
        replicas = execution['model_pools'][next(iter(cfg['models']))]['replicas']
        assert len(replicas) == 8 and all(r['max_inflight'] == 1 and len(r['gpus']) == 1 for r in replicas)
        configs[model] = str(output/'configs'/f'{model}.yaml')
        executions[model] = str(output/'configs'/f'{model}.execution.yaml')
        Path(configs[model]).write_text(yaml.safe_dump(cfg, sort_keys=False))
        Path(executions[model]).write_text(yaml.safe_dump(execution, sort_keys=False))
    manifest = dict(created_at=now(), models=list(MODELS), selection_counts=EXPECTED, intended_counts={k: len(v) for k,v in selection.items()},
        samples_sha256=sha(output/'samples.json'), shuffle_seed=0, inference_seed=0, skills=None,
        split=str(SPLIT), split_sha256=sha(ROOT/SPLIT), source_commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
        source_hashes={str(p.relative_to(ROOT)): sha(p) for d in ['src','scripts','configs','eval/agent_eval'] for p in (ROOT/d).rglob('*') if p.is_file() and p.suffix in ('.py','.yaml','.sh')},
        driver_sha256=sha(Path(__file__)), execution_profile=execution_profile(), configs=configs, executions=executions,
        dataset_sha256={name: sha(Path('/assets')/rel) for name,rel in [('cvbench','cvbench/QAs.json'),('mvu_eval','mvu-eval/QAs.json'),('crossvid','crossvid/qa.jsonl')]},
        e2e={m: dict(path=str(p), manifest_sha256=sha(p/'manifest.json'), selection_sha256=sha(p/'selection.json')) for m,p in E2E.items()},
        judge='Qwen3-30B-A3B-Instruct-2507', scoring='Closed answers scored with the official scorer; CCQA deferred then point-weighted; CrossVid ten-task macro',
        comparison='Same available IDs as E2E. CVBench/MVU use per-question means, CrossVid uses task macro. Agent has adaptive, multiple visual calls and different output budgets.')
    write(path, manifest)
    return manifest


def compact(row):
    result = row.get('result') or {}
    events = row.get('events') or []
    responses = [e for e in events if e['kind'] == 'model_response']
    assert all(len(e['token_ids']) == e['usage']['completion_tokens'] and e['worker']['forward_calls'] > 0 for e in responses)
    return dict(sample_id=row['sample_id'], dataset=row['dataset'], task=row['native_task'], status=row['status'],
        prediction=row['prediction'], score=row.get('score'), scoring_status=row.get('scoring_status'), error=row.get('error'),
        points=len(row.get('ground_truth') or []), seconds=result.get('time'), calls=len(responses),
        completion_tokens=sum(len(e['token_ids']) for e in responses), prompt_tokens=sum(e['usage']['prompt_tokens'] for e in responses),
        model_errors=sum(e['kind']=='model_error' for e in events), structured_invalid=sum(e['kind']=='structured_invalid' for e in events),
        repairs=sum(e['kind']=='structured_repair' for e in events), token_truncations=sum(e['finish_reason']=='length' for e in responses))


def refresh(directory, cache):
    for path in directory.glob('records/*/*/result.json'):
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if path not in cache or cache[path][0] != signature:
            cache[path] = (signature, compact(read(path)))
    return [value for _, value in cache.values()]


def summary(rows):
    ok = [r for r in rows if r['status']=='ok']
    by_benchmark = {}
    for name, expected in EXPECTED.items():
        selected = [r for r in rows if r['dataset']==name]
        scored = [r for r in selected if r['status']=='ok' and r['score'] is not None]
        by_benchmark[name] = dict(expected=expected, finished=len(selected), ok=sum(r['status']=='ok' for r in selected),
            errors=sum(r['status']!='ok' for r in selected), scored=len(scored),
            scored_mean=sum(r['score'] for r in scored)/len(scored) if scored else None)
    return dict(finished=len(rows), ok=len(ok), errors=len(rows)-len(ok), calls=sum(r['calls'] for r in rows),
        completion_tokens=sum(r['completion_tokens'] for r in rows),
        mean_seconds=sum(r['seconds'] or 0 for r in ok)/len(ok) if ok else None, by_benchmark=by_benchmark)


def stop(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try: process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def paired_score(rows, key):
    if not rows or any(r[key] is None for r in rows):
        return None
    if rows[0]['dataset'] != 'crossvid':
        return sum(r[key] for r in rows)/len(rows)
    tasks = defaultdict(list)
    for row in rows: tasks[row['task']].append(row)
    if len(tasks) != 10:
        return None
    values = []
    for task, group in tasks.items():
        if task == 'CCQA':
            values.append(sum(r[key]*r['points'] for r in group)/sum(r['points'] for r in group))
        else: values.append(sum(r[key] for r in group)/len(group))
    return sum(values)/10


def compare(output, model, rows):
    judge_file = output/model/'score'/CCQA_REPORT
    judges = {f"crossvid:CCQA:{r['id']}": r for r in read(judge_file)['samples']} if judge_file.exists() else {}
    e2e = {r['sample_id']: r for name in EXPECTED for r in read(E2E[model]/'scored'/f'{name}.json')}
    paired = []
    for original in rows:
        row = copy.deepcopy(original)
        sid = row['sample_id']; before = e2e[sid]
        if sid in judges:
            judgement = judges[sid]
            assert judgement['prediction'] == row['prediction'] and judgement['status']=='ok'
            row['score'] = judgement['score']/(2*row['points'])
        score = row.pop('score')
        paired.append(dict(**row, e2e_prediction=before['prediction'], e2e_score=before['score'], agent_score=score))
    metrics = {}
    for name, expected in EXPECTED.items():
        group = [r for r in paired if r['dataset']==name]
        both = [r for r in group if r['status']=='ok' and r['agent_score'] is not None]
        before, after = paired_score(both,'e2e_score'), paired_score(both,'agent_score')
        metrics[name] = dict(expected=expected, paired=len(both), complete=len(both)==expected,
            e2e_score=before, agent_score=after, delta=after-before if before is not None and after is not None else None,
            improved=sum(r['agent_score']>r['e2e_score'] for r in both), regressed=sum(r['agent_score']<r['e2e_score'] for r in both))
    write(output/'comparison'/f'{model}.json',dict(model=model,metrics=metrics,rows=paired))
    return metrics


def report(output, state):
    lines=['# MVAgent 与 E2E 同题比较','',f"状态：{state['phase']}；更新：{now()}",'',
           '| 模型 | Benchmark | 配对/目标 | E2E % | MVAgent % | 差值 pp |','|---|---|---:|---:|---:|---:|']
    def pct(v): return '—' if v is None else f'{100*v:.2f}'
    for model in MODELS:
        for name, values in state.get('comparisons',{}).get(model,{}).items():
            lines.append(f"| {model} | {name} | {values['paired']}/{values['expected']} | {pct(values['e2e_score'])} | {pct(values['agent_score'])} | {pct(values['delta'])} |")
    lines += ['', '未满目标数时仅为已配对题目的暂定结果，不能当作完整成绩。CVBench均分使用与E2E相同的997题；损坏的64–66单独留档。',
              'CrossVid按十类任务等权macro，CCQA按评分点加权。Judge错误不记零分。',
              '两种系统的取证过程、调用数与输出预算不同；这是系统级比较，不是等计算预算的消融。']
    (output/'comparison.md').write_text('\n'.join(lines)+'\n')


def self_check():
    selection={k:[f'{k}:{i}' for i in range(n)] for k,n in [('cvbench',1000),('mvu_eval',1824),('crossvid',2500)]}
    samples=selected_ids(selection,{'cvbench:64','cvbench:65','cvbench:66'})
    assert samples==selected_ids(selection,{'cvbench:64','cvbench:65','cvbench:66'})
    assert paired_score([{'dataset':'cvbench','score':1},{'dataset':'cvbench','score':0}], 'score') == .5
    assert paired_score([{'dataset':'cvbench','score':None}], 'score') is None
    cross=[dict(dataset='crossvid',task=str(i),score=1.,points=1) for i in range(9)]
    cross += [dict(dataset='crossvid',task='CCQA',score=1.,points=1),dict(dataset='crossvid',task='CCQA',score=0.,points=3)]
    assert paired_score(cross,'score') == .925
    assert paired_score(cross[:-2],'score') is None
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'records/cvbench/cvbench:1/result.json';cache={}
        row=dict(sample_id='cvbench:1',dataset='cvbench',native_task='test',status='ok',prediction='A',score=None,result={},events=[])
        write(path,row);assert summary(refresh(Path(tmp),cache))['by_benchmark']['cvbench']['scored']==0
        row['score']=1;write(path,row);assert summary(refresh(Path(tmp),cache))['by_benchmark']['cvbench']['scored']==1
    print('Full Agent controller checks passed: exact selection, partial scores, CCQA weights and updated record cache')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    if args.self_check: self_check();return
    if not args.output: parser.error('--output is required')
    output=args.output.absolute();assert output.resolve().is_relative_to(Path('/runs').resolve())
    output.mkdir(parents=True,exist_ok=True);freeze(output,sys.argv[1:])
    sys.path.insert(0,str(ROOT/'src'))
    state=read(output/'progress.json') if (output/'progress.json').exists() else dict(started_at=now(),models={},comparisons={})
    state.pop('error',None);state.pop('traceback',None)
    process=None;caches={model:{} for model in MODELS}
    def save():
        state['updated_at']=now();write(output/'progress.json',state);report(output,state)
    def interrupt(signum,frame):raise InterruptedError(f'Controller interrupted by signal {signum}')
    signal.signal(signal.SIGTERM,interrupt)
    def run(command,log,model=None):
        nonlocal process
        with log.open('a') as stream:
            process=subprocess.Popen([str(v) for v in command],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'src')},
                                     stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        while process.poll() is None:
            if model:
                rows=refresh(output/model,caches[model]);state['models'][model].update(summary(rows))
            save();time.sleep(30)
        code=process.returncode;process=None
        if code:raise RuntimeError(f'Command exited {code}; see {log}')
    try:
        state['phase']='preparing';save();manifest=prepare(output)
        if args.prepare_only:
            state['phase']='prepared';save();return
        if not state.get('checks_passed'):
            run([sys.executable,Path(__file__),'--self-check'],output/'checks.log')
            run([sys.executable,'-m','compileall','-q','src','scripts','eval/agent_eval','demo.py'],output/'compile.log')
            run([sys.executable,'scripts/test_final_reason.py'],output/'checks.log')
            state['checks_passed']=True;save()
        for model,suffix in MODELS.items():
            previous=state['models'].setdefault(model,{})
            if previous.get('inference_done'):continue
            config,execution=manifest['configs'][model],manifest['executions'][model]
            state.update(phase='loading',model=model);save()
            run([sys.executable,ROOT/'prelaunch.py','--replace',config,execution,f'qwen3_5_{suffix}_local'],output/f'{model}_startup.log')
            state['phase']='inference';previous.setdefault('started_at',now());save()
            command=[sys.executable,'eval/agent_eval/run.py','--config',config,'--execution-config',execution,
                '--dataset-root','/assets','--sample-ids-file',output/'samples.json','--output',output/model,'--defer-open-qa-judge']
            if (output/model/'run_manifest.json').exists():command.append('--resume')
            run(command,output/f'{model}_inference.log',model)
            rows=refresh(output/model,caches[model]);previous.update(summary(rows))
            assert previous['finished']==sum(EXPECTED.values()),previous
            previous.update(inference_done=True,finished_at=now())
            state['comparisons'][model]=compare(output,model,rows);save()
        if not all(state['models'][m].get('scoring_done') for m in MODELS):
            from run_mvagent_pilot import stop_actor_servers
            state['phase']='judge_loading';save();stop_actor_servers()
            os.environ['JUDGE_LOG_DIR']=str(output/'judge')
            run(['bash','eval/agent_eval/serve_ccqa_judge.sh','0-7','8100'],output/'judge_startup.log')
            for model in MODELS:
                if state['models'][model].get('scoring_done'):continue
                state.update(phase='scoring',model=model);save()
                run([sys.executable,'eval/agent_eval/score_crossvid_ccqa.py','--output',output/model,'--endpoints','8100-8107'],output/f'{model}_score.log')
                judge=read(output/model/'score'/CCQA_REPORT)
                assert not judge['failed_ids'],judge['failed_ids']
                rows=refresh(output/model,caches[model])
                expected_ccqa=sum(r['task']=='CCQA' and r['status']=='ok' for r in rows)
                assert judge['scored_answer_count']==expected_ccqa,judge['scored_answer_count']
                run([sys.executable,'eval/agent_eval/finalize_results.py','--output',output/model],output/f'{model}_finalize.log')
                rows=refresh(output/model,caches[model]);state['comparisons'][model]=compare(output,model,rows)
                state['models'][model]['scoring_done']=True;save()
        state['phase']='completed_with_errors' if any(x['errors'] for x in state['models'].values()) else 'completed'
        state['finished_at']=now();save()
    except BaseException as exc:
        state.update(phase='interrupted' if isinstance(exc,InterruptedError) else 'failed',error=repr(exc),traceback=traceback.format_exc())
        save();print(state['traceback'],flush=True)
    finally:
        stop(process);(Path('/work/jobs')/f'{output.name}.pid').unlink(missing_ok=True)
        os.utime('/work/heartbeat',(0,0))


if __name__=='__main__':main()
