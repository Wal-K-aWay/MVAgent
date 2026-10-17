"""Two independent System candidates against the completed, frozen direct-answer panel."""
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'src'), str(ROOT/'eval/e2e_eval')]
from compare_direct_answer import read, write, sha, now, measure, event_stats, MODELS
from run_direct_answer_large import select

OUT = Path('/runs/devbox/system_ablation_20261017')
OLD = Path('/runs/devbox/direct_answer_large_recovery_20261017/analysis')
ORIGINAL = Path('/runs/devbox/direct_answer_large_20261016/frozen_repo')
GLOBAL = 'src/mvagent/agents/global_agent/prompts.py'
VIDEO = 'src/mvagent/agents/video_agent/prompts.py'
AGENT = 'src/mvagent/agents/video_agent/agent.py'
ARMS = ('global_short', 'video_rules')
VIDEO_RULES = '''Preserve the active instruction's definitions and distinctions in each observation request. Report the concrete observed evidence needed to resolve that instruction, retaining relevant identities, quantities, relations, and uncertainty. Keep explanations concise without omitting required information. Use only evidence from your assigned video; do not infer facts about other videos or select the global answer.'''
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'


def replace_constant(source, name, value):
    lines = source.splitlines(keepends=True)
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(nodes) == 1, name
    n = nodes[0]
    lines[n.lineno-1:n.end_lineno] = [f'{name} = {value!r}\n']
    return ''.join(lines)


def constant(source, name):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    return ast.literal_eval(node.value.func.value).strip() if isinstance(node.value, ast.Call) else ast.literal_eval(node.value)


def arm_source(arm, target):
    original = (ORIGINAL/GLOBAL).read_text()
    current = (target/GLOBAL).read_text()
    # Only the Global System differs in the checked-in candidate.
    assert replace_constant(current, 'GLOBAL_AGENT_SYSTEM_PROMPT', '') == replace_constant(original, 'GLOBAL_AGENT_SYSTEM_PROMPT', '')
    if arm == 'video_rules':
        (target/GLOBAL).write_text(original)
        p = target/VIDEO
        text = p.read_text()
        p.write_text(replace_constant(text, 'VIDEO_PLANNER_SYSTEM_PROMPT',
            constant(text, 'VIDEO_PLANNER_SYSTEM_PROMPT')+'\n\n'+VIDEO_RULES))
        p = target/AGENT
        text = p.read_text()
        before = 'system_prompt=VIDEO_PLANNER_SYSTEM_PROMPT,'
        assert text.count(before) == 1
        p.write_text(text.replace(before,
            'system_prompt=VIDEO_PLANNER_SYSTEM_PROMPT + f"\\nAssigned source video ID: {self.video_id}",'))
    return {name: sha(target/name) for name in [GLOBAL, VIDEO, AGENT]}


def prepare():
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    from models.vlm.local.sync_server import execution_profile
    assert not OUT.exists(), 'Never replace a prepared experiment'
    baseline = {m: read(OLD/f'{m}_paired.json') for m in MODELS}
    ids = [r['sample_id'] for r in baseline['9B']]
    assert len(ids) == 1500 and all(set(ids) == {r['sample_id'] for r in rows} for rows in baseline.values())
    records = load_multibench_records('/assets', sorted(ids))
    chosen = select(records, 30)
    extra = sorted(s for s in ids if records[s].native_task == 'CCQA' and s not in chosen)
    chosen += random.Random(0).sample(extra, 12)
    random.Random(0).shuffle(chosen)
    assert len(chosen) == len(set(chosen)) == 102
    assert Counter(records[s].dataset for s in chosen) == dict(cvbench=30,mvu_eval=30,crossvid=42)
    assert sum(records[s].native_task == 'CCQA' for s in chosen) == 15
    subset = {m:[r for r in rows if r['sample_id'] in chosen] for m,rows in baseline.items()}
    seconds = {m:sum(r['stats']['seconds'] for r in rows) for m,rows in subset.items()}
    OUT.mkdir(parents=True)
    write(OUT/'samples.json', chosen)
    write(OUT/'baseline.json', subset)
    # One archive keeps the immutable source without multiplying Volume inodes.
    with tarfile.open(OUT/'source.tar.gz', 'w:gz', compresslevel=1) as tar:
        for name in ['src','scripts','configs','eval','.git','requirements.txt','demo.py']:
            tar.add(ROOT/name, arcname=name, filter=lambda t: None if '__pycache__' in Path(t.name).parts or '.cache' in Path(t.name).parts else t)
    for arm in ARMS:
        source = Path('/tmp')/f'system-ablation-check-{arm}'
        shutil.copytree(ROOT/'src', source/'src', ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
        hashes = arm_source(arm, source)
        write(OUT/arm/'source_changes.json', hashes)
        write(OUT/arm/'progress.json', dict(phase='prepared',models={},expected=306))
        for name in [GLOBAL, VIDEO, AGENT]:
            p = OUT/arm/'code'/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,p)
    commit = (ROOT/'.git/HEAD').read_text().strip()
    write(OUT/'manifest.json', dict(at=now(),commit=commit,baseline_commit='1b711bf6a466c6dee70c273d24fbd98bd4f0c80d',
        archive_sha256=sha(OUT/'source.tar.gz'),profile=execution_profile(),samples_sha256=sha(OUT/'samples.json'),
        baseline_sha256=sha(OUT/'baseline.json'),inference_seed=0,selection_seed=0,model_seconds=seconds,
        expected_hours_per_arm=.45+1.25*sum(seconds.values())/8/3600,
        arms={'global_short':'Only Global System replaced by PRO6000 text',
              'video_rules':'Original Global System; ordinary VideoPlanner System adds general evidence requirements and its own video ID'},
        full_question_to_video=False,terminal_video_summary_system_changed=False,
        design='Development screening, 30 CV + 30 MVU + 27 closed Cross + 15 CCQA per model. Selection uses no scores.'))
    print(json.dumps(read(OUT/'manifest.json')),flush=True)


def worker(arm):
    import yaml
    manifest = read(OUT/'manifest.json')
    source = Path('/work/system-ablation')/arm
    source.mkdir(parents=True,exist_ok=False)
    assert sha(OUT/'source.tar.gz') == manifest['archive_sha256']
    with tarfile.open(OUT/'source.tar.gz') as tar:tar.extractall(source, filter='fully_trusted')
    for name in [GLOBAL, VIDEO, AGENT]:shutil.copy2(OUT/arm/'code'/name, source/name)
    launcher = source/'prelaunch.py'
    launcher.write_text(Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"',repr(str(source/'src'))))
    group = OUT/arm;state = read(group/'progress.json')
    hardware = subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid','--format=csv,noheader'],text=True)
    assert len(hardware.splitlines()) == 8 and all('H100' in line for line in hardware.splitlines())
    state.update(started_at=now(),hardware=hardware,source=str(source))
    def save(phase, **values):
        state.update(phase=phase,updated_at=now(),**values);write(group/'progress.json',state)
    def run(args, name, model=None):
        with (group/name).open('a') as log:
            p = subprocess.Popen(list(map(str,args)),cwd=source,stdout=log,stderr=subprocess.STDOUT,
                env={**os.environ,'PYTHONPATH':str(source/'src'),'MVAGENT_PROJECT_ROOT':str(source),'PYTHONDONTWRITEBYTECODE':'1'})
        while p.poll() is None:
            if model:state['models'][model]['finished']=sum(1 for _ in (group/model/'records').glob('*/*/result.json'))
            save(state['phase']);time.sleep(15)
        if p.returncode:raise RuntimeError(f'{name}: rc={p.returncode}')
    try:
        for index,(model,slug) in enumerate(MODELS.items()):
            target=group/model;target.mkdir()
            state['models'][model]=dict(expected=102,finished=0)
            cfg=yaml.safe_load((source/f'configs/inference/modal_qwen35_{slug}_no_skill.yaml').read_text())
            exname='modal_h200x8.yaml' if model=='35B-A3B' else f'modal_h200x8_qwen35_{slug}.yaml'
            ex=yaml.safe_load((source/'configs/inference/execution'/exname).read_text())
            cfg['runtime']['cache_dir']=str(target/'runtime_cache')
            ex['media_cache']['root']=f'/work/system-media-{arm}-{model}'
            pool=next(iter(cfg['models']));replicas=ex['model_pools'][pool]['replicas']
            assert len(replicas)==8 and all(r['max_inflight']==1 and len(r['gpus'])==1 for r in replicas)
            ports=list(range(8100+index*100,8108+index*100))
            for r,port in zip(replicas,ports):r['endpoint']=f'http://127.0.0.1:{port}/v1'
            for name,value in [('config.yaml',cfg),('execution.yaml',ex)]:(target/name).write_text(yaml.safe_dump(value,sort_keys=False))
            save('loading',model=model)
            run([sys.executable,launcher,'--replace',target/'config.yaml',target/'execution.yaml',pool],f'{model}_startup.log')
            from models.vlm.local.sync_server import validate_card
            cards=[]
            for port in ports:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=15) as response:card=json.load(response)['data'][0]
                validate_card(card);assert card['execution']==manifest['profile'];cards.append(card)
            assert len({c['worker']['gpu_uuid'] for c in cards})==8
            write(target/'startup_identity.json',cards)
            save('inference',model=model)
            run([sys.executable,source/'eval/agent_eval/run.py','--config',target/'config.yaml',
                '--execution-config',target/'execution.yaml','--dataset-root','/assets',
                '--sample-ids-file',OUT/'samples.json','--output',target,'--defer-open-qa-judge'],f'{model}_inference.log',model)
            rows=[read(p) for p in (target/'records').glob('*/*/result.json')]
            assert {r['sample_id'] for r in rows}==set(read(OUT/'samples.json'))
            errors=[r['sample_id'] for r in rows if r['status']!='ok']
            state['models'][model].update(finished=len(rows),valid=len(rows)-len(errors),errors=errors,inference_done=True)
            save('inference_done',model=model)
        save('judge_loading')
        # All these services belong to this candidate's dedicated Sandbox.
        subprocess.run(['pkill','-f','[s]ync_server.py'],check=False)
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            used=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).split()
            if used and all(int(value)<2048 for value in used):break
            time.sleep(5)
        else:raise TimeoutError('Actor services did not release GPU memory before Judge startup')
        os.environ['JUDGE_LOG_DIR']=str(group/'judge_servers')
        run(['bash',source/'eval/agent_eval/serve_ccqa_judge.sh','0-7','8400'],'judge_startup.log')
        for model in MODELS:
            save('judging',model=model)
            run([sys.executable,source/'eval/agent_eval/score_crossvid_ccqa.py','--output',group/model,
                '--endpoints','8400-8407'],f'{model}_judge.log')
            judged=read(group/model/REPORT);assert not judged['failed_ids']
            state['models'][model]['judge_count']=len(judged['samples'])
        save('completed',finished_at=now())
    except BaseException as exc:
        save('failed',error=repr(exc),traceback=traceback.format_exc());raise


def analyze():
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records,build_official_scorer
    from analyze_direct_answer_large import mean_score,interval
    ids=read(OUT/'samples.json');records=load_multibench_records('/assets',ids)
    scorer,_=build_official_scorer(records,{})
    baseline=read(OUT/'baseline.json');summary={}
    for arm in ARMS:
        report={}
        for model in MODELS:
            old={r['sample_id']:r for r in baseline[model]};rows=[];missing=[];errors=[]
            jpath=OUT/arm/model/REPORT
            judged=read(jpath) if jpath.exists() else {'samples':[],'failed_ids':[]}
            assert not judged['failed_ids']
            judges={f"crossvid:CCQA:{r['id']}":r for r in judged['samples']}
            for sid in ids:
                p=OUT/arm/model/'records'/records[sid].dataset/sid/'result.json'
                if not p.exists():missing.append(sid);continue
                raw=read(p)
                if raw['status']!='ok':errors.append(dict(sample_id=sid,error=raw.get('error')));continue
                stats=event_stats(raw)
                workers=set()
                for e in raw['events']:
                    if e['kind']=='model_response':
                        assert e['usage']['prompt_tokens_details']['cached_tokens']==0
                        assert e['request_sha256'] and e['prompt_token_ids_sha256']
                        workers.add((e['worker']['pid'],e['worker']['gpu_uuid']))
                assert len(workers)==1
                if records[sid].native_task=='CCQA':
                    if sid not in judges:missing.append(sid+' (Judge pending)');continue
                    j=judges[sid];assert j['status']=='ok' and j['prediction']==raw['prediction'].strip()
                    new=dict(prediction=raw['prediction'],score=j['score']/(2*len(j['coverage'])),format_ok=None,
                        empty=not raw['prediction'].strip(),brace_only=raw['prediction'].strip()=='}')
                else:
                    new=measure(raw['prediction'],records[sid],scorer)
                    assert abs(new['score']-raw['score'])<1e-8
                before=old[sid]
                rows.append(dict(sample_id=sid,dataset=before['dataset'],task=before['task'],task_population=before['task_population'],
                    points=before['points'],arms=dict(direct=new,baseline=before['arms']['direct'],e2e=before['arms']['e2e']),
                    stats=stats,path=str(p),sha256=sha(p)))
            metrics={}
            for ds in ['cvbench','mvu_eval','crossvid']:
                group=[r for r in rows if r['dataset']==ds]
                if not group:continue
                entry=dict(n=len(group),scores={a:mean_score(group,a) for a in ['direct','baseline','e2e']})
                entry['baseline_delta_ci95']=interval(group,'baseline')
                entry['format_errors']={a:sum(r['arms'][a].get('format_ok') is False for r in group) for a in ['direct','baseline']}
                entry['wins']=sum(r['arms']['direct']['score']>r['arms']['baseline']['score'] for r in group)
                entry['losses']=sum(r['arms']['direct']['score']<r['arms']['baseline']['score'] for r in group)
                metrics[ds]=entry
            report[model]=dict(valid=len(rows),missing=missing,errors=errors,benchmarks=metrics,
                empty=sum(r['arms']['direct']['empty'] for r in rows),braces=sum(r['arms']['direct']['brace_only'] for r in rows),
                calls=sum(r['stats']['calls'] for r in rows),mean_seconds=sum(r['stats']['seconds'] for r in rows)/max(1,len(rows)))
            write(OUT/'analysis'/f'{arm}_{model}_paired.json',rows)
        summary[arm]=report
    write(OUT/'analysis/summary.json',dict(at=now(),arms=summary,development_panel=True))
    print(json.dumps(summary),flush=True)


def self_check():
    text='A = "before"\nB = "unchanged"\n'
    changed=replace_constant(text,'A','after\nline')
    assert constant(changed,'A')=='after\nline' and constant(changed,'B')=='unchanged'
    assert constant('A = "  trimmed  ".strip()','A')=='trimmed'
    assert 'question' not in VIDEO_RULES and 'other videos' in VIDEO_RULES
    print('System replacement and role-boundary checks passed')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','worker','analyze','self-check']);p.add_argument('--arm',choices=ARMS)
    a=p.parse_args()
    if a.mode=='worker':assert a.arm;worker(a.arm)
    else:globals()[a.mode.replace('-','_')]()
