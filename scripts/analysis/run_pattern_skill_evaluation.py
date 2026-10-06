#!/usr/bin/env python3
"""Freeze, evaluate and audit a shared-workflow Global bank on frozen benchmark panels."""
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

import yaml

ROOT = Path(os.environ.get('MVAGENT_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
SNAPSHOT = Path(__file__).resolve().parent/'src'
sys.path.insert(0, str(SNAPSHOT if SNAPSHOT.is_dir() else ROOT/'src'))
from mvagent.skills.bank import SkillBank
from skill_evolution.infra.store import write_json, file_fingerprint
from skill_evolution.infra.data import DataSplitManifest, SplitSample, group_by_media

BASE = ROOT/'outputs/mvagent/no_skill/qwen3_5_35b_a3b'
PRIOR = ROOT/'outputs/analysis/20260924_global_skillclaw_empty_expanded_revision1'
SEED = 20260925


def read(path):
    return json.loads(Path(path).read_text())


def status(out, phase, **extra):
    write_json(out/'status.json', dict(phase=phase, pid=os.getpid(), updated_at=datetime.now(timezone.utc).isoformat(), **extra))


def actions(events):
    # Keep actual successful parsed decisions, not the presence of action names in Prompts.
    return [e for e in events if e.get('kind') == 'structured_parsed' and e.get('skill_phase') != 'selection' and isinstance(e.get('value'), dict) and 'action' in e['value']]


def transfer_panel(per_task):
    from skill_evolution.infra.benchmarks import load_multibench_records
    data = Path('/home/kww/datasets/Multi-Video')
    cv = read(data/'CVBench/QAs.json'); mv = read(data/'MVU-Eval/QAs.json')
    categories = {'cvbench:'+str(r['id']):r['task_type'] for r in read(ROOT/'eval/e2e_eval/CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json')}
    ids = list(categories) + ['mvu_eval:'+r['task']+':'+str(r['id']) for r in mv]
    assert set(categories)=={'cvbench:'+str(r['id']) for r in cv}
    records = load_multibench_records(data, ids)
    source_keys = {sid:['path:'+p for p in r.sample.videos.values()] for sid,r in records.items()}
    groups = group_by_media(source_keys)
    exclusion_path = ROOT/'outputs/mvagent/skill/20260916_evolution_redesign/train130_gate300.json'
    used = {r['sample_id'] for r in read(exclusion_path)['samples']} & set(records)
    blocked_groups = {groups[sid] for sid in used}
    pools = defaultdict(list)
    for sid,r in records.items():
        if sid in used:continue
        task = categories[sid] if r.dataset=='cvbench' else r.native_task
        pools[r.dataset+'/'+task].append(dict(sample_id=sid,dataset=r.dataset,task=task,
            bucket=r.dataset+'/'+task,source_keys=source_keys[sid],group_id=groups[sid],
            scope='shared_prior_source' if groups[sid] in blocked_groups else 'known_source_excluded'))
    selected={}
    for bucket,pool in sorted(pools.items()):
        ordered=sorted(pool,key=lambda r:hashlib.sha256(f'{SEED}:{r["sample_id"]}'.encode()).hexdigest())
        selected[bucket]=ordered[:per_task]
        for i,r in enumerate(selected[bucket]):r['cohort']='A' if i%2==0 else 'B'
    panel=[selected[t][i] for i in range(per_task) for t in sorted(selected) if i<len(selected[t])]
    return panel,dict(ids=sorted(used),source_manifest=str(exclusion_path),source_manifest_sha256=file_fingerprint(exclusion_path),
        available={k:len(v) for k,v in pools.items()},
        limits='Exclude prior Train130/Gate300 IDs; shared media groups flagged, not silently excluded. A/B cohorts are outcome-blind but not source-disjoint. Historical benchmark exposure remains; not independent Test.')


def prepare(out, per_task, bank_path, panel_kind='crossvid'):
    from mvagent.utils.snapshot import ensure_source_snapshot
    from mvagent.skills.bank import SkillBank
    if out.exists():
        raise ValueError('Use a new output directory; resume the frozen controller separately')
    if panel_kind=='transfer':
        panel, exclusions = transfer_panel(per_task)
    else:
        rows = read(ROOT/'outputs/analysis/20260919_crossvid_lite2500/all_features.json')
        authored = {x['id'] for x in read(ROOT/'analysis/skill_evolution/crossvid_global_library_20260925/examples.json')['cases']}
        used = authored | {x['sample_id'] for x in read(PRIOR/'split.json')['samples']}
        blocked = {k for r in rows if r['sample_id'] in used for k in r['source_keys']}
        eligible = [r for r in rows if not blocked.intersection(r['source_keys'])]
        selected = {}
        for task in sorted({r['task'] for r in rows}):
            pool = sorted((r for r in eligible if r['task']==task), key=lambda r: hashlib.sha256(f'{SEED}:{r["sample_id"]}'.encode()).hexdigest())
            if len(pool)<per_task:
                raise ValueError(f'Insufficient source-excluded {task}: {len(pool)}')
            selected[task] = pool[:per_task]
        # Interleave tasks; disjoint smoke/main avoid hashing the full panel twice.
        panel = [selected[t][i] for i in range(per_task) for t in sorted(selected)]
        assert len({r['sample_id'] for r in panel}) == 10*per_task
        assert not any(blocked.intersection(r['source_keys']) for r in panel)
        exclusions=dict(ids=sorted(used),source_keys=sorted(blocked),limits='Known path/UAV-source exclusion, not full film/session or byte-alias isolation; historical benchmark and diagnostic exposure remains.')
    out.mkdir(parents=True)
    groups = ({r['sample_id']:r['group_id'] for r in panel} if panel_kind=='transfer' else group_by_media({r['sample_id']: r['source_keys'] for r in panel}))
    smoke_size = len({r.get('bucket',r['task']) for r in panel})
    DataSplitManifest(panel_kind+' authored Skill development evaluation', SEED,
        tuple(SplitSample(r['sample_id'], 'eval', groups[r['sample_id']]) for r in panel)).write(out/'split.json')
    for phase, members in [('smoke', panel[:smoke_size]), ('main', panel[smoke_size:])]:
        DataSplitManifest(panel_kind+' acquisition '+phase, SEED,
            tuple(SplitSample(r['sample_id'], 'eval', groups[r['sample_id']]) for r in members)).write(out/(phase+'_split.json'))
    write_json(out/'panel.json', panel)
    write_json(out/'exclusions.json', exclusions)
    shutil.copyfile(bank_path, out/'skills.json')
    bank = SkillBank.from_dict(read(out/'skills.json'))
    if not bank.cards or len(bank.cards)>32 or any(c.role!='global' for c in bank.cards):
        raise ValueError('Provide 1–32 Global cards for Skill selection')
    config = yaml.safe_load((PRIOR/'runtime.yaml').read_text())
    config['models'].pop('glm53_flash_optimizer', None)
    config['agents']['global_agent']['skill'] = dict(enabled=True, mode='dynamic', selection_scope='task',
        path=str(out/'skills.json'), sha256=file_fingerprint(out/'skills.json'), retrieval_top_k=8, embedding=dict(endpoint='http://127.0.0.1:8110/v1',model='qwen3_embedding_8b'),
        selector=dict(model_type='qwen3_5_35b_a3b_local'))
    config['agents']['video_agent']['skill'] = {**config['agents']['global_agent']['skill']}  # No Video-role cards: no body or selector model call.
    from mvagent.configs import MVAgentConfig
    if panel_kind=='transfer':config['models'].pop('deepseek_judge_fixed',None)
    MVAgentConfig.from_dict(config)
    shutil.copyfile(ROOT/'configs/inference/execution/gpu2_7_single.yaml', out/'execution.yaml')
    (out/'runtime.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
    recipe = dict(algorithm='global-targeted-v1', dataset_root='/home/kww/datasets/Multi-Video',
        runtime=dict(mvagent_config=str(out/'runtime.yaml'),cache_dir=str(out/'cache')),
        open_qa_judge=dict(enabled=panel_kind=='crossvid',model=dict(model_type='deepseek_judge_fixed',temperature=0.0,max_tokens=8192)))
    (out/'recipe.yaml').write_text(yaml.safe_dump(recipe, sort_keys=False))
    # Freeze historical scores only after the outcome-blind sample list is fixed.
    scored = {f'crossvid:CCQA:{x["id"]}':x for x in read(BASE/'score/ccqa_scores_official_deepseek_v4_flash.json')['samples']} if panel_kind=='crossvid' else {}
    baseline = {}
    if panel_kind=='transfer':
        from skill_evolution.infra.benchmarks import load_multibench_records
        canonical_records=load_multibench_records(recipe['dataset_root'],[r['sample_id'] for r in panel])
    for r in panel:
        sid = r['sample_id']; path = BASE/'records'/sid.split(':')[0]/sid/'result.json'; d = read(path)
        score = d['score']; weight = 1
        if score is None and d.get('scoring_status')=='ok' and isinstance(d.get('correct'),bool):score=float(d['correct'])
        if panel_kind=='transfer':
            canonical=canonical_records[sid].sample
            assert d['result']['input']['videos']==dict(canonical.videos), ('Historical videos differ',sid)
            assert d['result']['input']['question']==canonical.question, ('Historical input differs',sid)
            assert d.get('ground_truth')==list(canonical.ground_truth), ('Historical labels differ',sid)
        if r['task']=='CCQA':
            s = scored[sid]
            assert s['status']=='ok' and s['prediction']==d['prediction']
            weight = len(s['coverage'])+len(s['correctness'])
            score = s['score']/weight
        assert score is not None
        baseline[sid] = dict(score=score,weight=weight,prediction=d['prediction'],path=str(path),sha256=file_fingerprint(path),decisions=actions(d['events']))
    write_json(out/'baseline.json', baseline)
    ensure_source_snapshot(out)
    shutil.copyfile(__file__, out/'controller.py')
    shutil.copyfile(ROOT/'scripts/analysis/credentials.py',out/'credential_reader.py')
    old_config = yaml.safe_load((BASE/'input_config.yaml').read_text())
    changed = []
    for p in sorted((out/'src/mvagent').rglob('*.py')):
        old=BASE/'src'/p.relative_to(out/'src')
        if not old.exists() or file_fingerprint(old)!=file_fingerprint(p):
            changed.append(str(p.relative_to(out/'src')))
    write_json(out/'baseline_comparability.json',dict(changed_runtime_files=changed,
        actor_configs_equal=old_config.get('models',{}).get('qwen3_5_35b_a3b_local')==config['models']['qwen3_5_35b_a3b_local'],
        baseline_input_config_sha256=file_fingerprint(BASE/'input_config.yaml'),
        note='Historical paired comparison, not a freshly randomized causal estimate. No no-Skill rerun; current runtime differs. Judge requested/returned identity and scorer details retained in raw artifacts.'))
    write_json(out/'control.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        questions=len(panel),per_task=per_task,seed=SEED,known_source_groups=len(set(groups.values())),
        bank_hash=file_fingerprint(out/'skills.json'),bank_source=str(bank_path),card_count=len(bank.cards),
        panel_kind=panel_kind, phase_sizes=dict(smoke=smoke_size,main=len(panel)-smoke_size),repeat_id=out.name,keys_file=str(ROOT/'.local/skill_evolution_keys.env'),
        source_snapshot=str(out/'src'),baseline_root=str(BASE),
        hashes={p.name:file_fingerprint(p) for p in [out/n for n in ('controller.py','credential_reader.py','skills.json','split.json','smoke_split.json','main_split.json','panel.json','baseline.json','recipe.yaml','runtime.yaml','execution.yaml')]}))
    status(out,'prepared')


def transfer_metrics(cases, bootstrap_repeats=2000):
    """Paired summaries; resample whole known-media groups, not independent QAs."""
    def summary(rows):
        buckets=defaultdict(list)
        for r in rows:buckets[r['task']].append(r)
        return dict(n=len(rows),baseline=sum(r['baseline_score'] for r in rows)/len(rows),
            skill=sum(r['score'] for r in rows)/len(rows),
            macro_delta=sum(sum(r['delta'] for r in rs)/len(rs) for rs in buckets.values())/len(buckets),
            improved=sum(r['delta']>0 for r in rows),regressed=sum(r['delta']<0 for r in rows))
    result={}
    for dataset in sorted({r['dataset'] for r in cases}):
        rows=[r for r in cases if r['dataset']==dataset]
        metric=summary(rows)
        for key in ('cohort','scope'):
            metric[key]={v:summary([r for r in rows if r[key]==v]) for v in sorted({r[key] for r in rows})}
        groups=defaultdict(list)
        for r in rows:groups[r['group_id']].append(r)
        rng=random.Random(SEED);names=sorted(groups);tasks={r['task'] for r in rows};deltas=[]
        for _ in range(bootstrap_repeats):
            sampled=[r for name in rng.choices(names,k=len(names)) for r in groups[name]]
            if {r['task'] for r in sampled}==tasks:deltas.append(summary(sampled)['macro_delta'])
        deltas.sort()
        metric['known_media_groups']=len(groups)
        metric['cluster_bootstrap_macro_delta_ci95']=([deltas[int(.025*(len(deltas)-1))],deltas[int(.975*(len(deltas)-1))]] if deltas else None)
        metric['bootstrap_accepted']=len(deltas)
        metric['bootstrap_requested']=bootstrap_repeats
        result[dataset]=metric
    return dict(datasets=result,limits='Historical baseline, not causal ablation. Task-balanced sample; micro is panel micro, not full benchmark estimate. Cohorts share sources. Cluster bootstrap uses known path-linked media groups; not whole-film/content isolation. Intervals are unadjusted descriptive uncertainty, not multiple-testing claims.')


def report(out, phase):
    from skill_evolution.infra.evaluation import episode_health
    from skill_evolution.infra.data import RolloutArtifact
    summary=read(out/phase/'summary.json'); ids=set(summary['samples'])
    from mvagent.skills.prompts import render_skill_text
    bank={c.id:c.render() for c in SkillBank.from_dict(read(out/'skills.json')).cards}
    panel={r['sample_id']:r for r in read(out/'panel.json')} if (out/'panel.json').exists() else {}
    baseline=read(out/'baseline.json'); cases={}; errors=[]; routes=Counter(); by_task=defaultdict(list)
    for path in sorted((out/'cache/rollouts').glob('*.json')):
        d=read(path);sid=d['sample_id']
        if sid not in ids:continue
        a=d['artifact'];events=a['events']
        selections=[e for e in events if e['kind']=='skill_selection' and e.get('role')=='global']
        requests={e['decision_id']:e for e in events if e['kind']=='structured_request' and e.get('schema')=='global_decision'}
        active=[e for e in events if e['kind'] in ('skill_selection','skill_reuse') and e.get('role')=='global']
        selected=[c['id'] for c in selections[0]['selected']] if selections else []
        if len(selections)!=1 or any(e.get('status')!='ok' for e in selections):errors.append([sid,'selection count/status'])
        if len(selected)>1:errors.append([sid,'multiple selected'])
        for e in active:
            if [c['id'] for c in e['selected']]!=selected:errors.append([sid,'selection changed'])
            req=requests.get(e['decision_id']);text='\n'.join(m['content'] for m in (req or {}).get('messages',[]) if isinstance(m.get('content'),str))
            if req is None or any(bank[c] not in text for c in selected):errors.append([sid,'missing actor injection'])
        if len(active)!=len(requests):errors.append([sid,'actor/skill event coverage'])
        if any(e.get('kind')=='skill_selection' and e.get('role')=='video' and e.get('selected') for e in events):errors.append([sid,'unexpected Video Skill'])
        retrieval=[e for e in events if e['kind']=='skill_retrieval' and e.get('role')=='global']
        if not retrieval or any(e.get('retriever') not in ('full-catalog-v1','bm25-embedding-rrf-v1') for e in retrieval):errors.append([sid,'unexpected retrieval method'])
        route=selected[0] if selected else 'NONE';routes[route]+=1
        value=summary['samples'][sid];old=baseline[sid]
        history=a['result'].get('action_history',[])
        # Full events remain the authority when a result schema uses a different history key.
        meta=panel.get(sid,{})
        case=dict(sample_id=sid,task=meta.get('bucket',sid.split(':')[1]),dataset=sid.split(':')[0],
            cohort=meta.get('cohort'),group_id=meta.get('group_id'),scope=meta.get('scope'),selected=selected,
            reason=selections[0].get('reason','') if selections else '',
            question=a['result'].get('input',{}).get('question',''),
            videos=a['result'].get('video_metadata',{}),
            baseline_score=old['score'],score=value['score'],delta=value['score']-old['score'],weight=old['weight'],
            baseline_prediction=old['prediction'],prediction=value['prediction'],
            health=episode_health(RolloutArtifact(sid,a,bucket=d['bucket'])),
            trajectory=history,decisions=actions(events),baseline_decisions=old['decisions'],artifact=str(path),baseline_artifact=old['path'])
        cases[sid]=case;by_task[case['task']].append(case)
    assert set(cases)==ids,(len(cases),len(ids))
    table={t:dict(n=len(rs),baseline=sum(r['baseline_score']*r['weight'] for r in rs)/sum(r['weight'] for r in rs),
        skill=sum(r['score']*r['weight'] for r in rs)/sum(r['weight'] for r in rs),
        improved=sum(r['delta']>1e-9 for r in rs),regressed=sum(r['delta']< -1e-9 for r in rs),
        selections=dict(Counter((r['selected'] or ['NONE'])[0] for r in rs))) for t,rs in sorted(by_task.items())}
    metrics=dict(questions=len(cases),buckets=table,selection_counts=dict(routes),injection_errors=errors,
        macro_baseline=sum(v['baseline'] for v in table.values())/len(table),
        macro_skill=sum(v['skill'] for v in table.values())/len(table),
        global_actions=dict(Counter(e['value']['action'] for c in cases.values() for e in c['decisions'] if e.get('agent')=='GlobalAgent')),
        baseline_global_actions=dict(Counter(e['value']['action'] for c in cases.values() for e in c['baseline_decisions'] if e.get('agent')=='GlobalAgent')),
        selection_quality='Pending semantic review; task labels and outcome are not selection GT',
        guidance_quality='Injection audit is not proof of strategy compliance; inspect decisions and evidence in review.json/raw artifacts')
    if panel and all(r.get('cohort') for r in cases.values()):
        metrics['transfer']=transfer_metrics(list(cases.values()),2000 if phase=='combined' else 0)
    write_json(out/(phase+'_audit.json'),metrics)
    write_json(out/(phase+'_review.json'),list(cases.values()))
    write_json(out/(phase+'_routing_blind.json'),[{k:c[k] for k in ('sample_id','question','videos','selected','reason')} for c in cases.values()])
    lines=['# Pattern Skill evaluation', '',json.dumps(metrics,ensure_ascii=False,indent=2),'',
           'Selection rationality must be reviewed independently of correctness; inspect raw traces for evidence and action parameters. Historical comparison is not a fresh no-Skill control.']
    for sid,c in sorted(cases.items()):
        lines += ['', '## '+sid, '', c['question'].replace('\\n','\n'), '',
            'Selected: '+str(c['selected']), 'Reason: '+c['reason'],
            f"Score: {c['baseline_score']:.4f} → {c['score']:.4f}",
            'Baseline answer: '+str(c['baseline_prediction']), 'Skill answer: '+str(c['prediction']),
            '```json',json.dumps(c['decisions'] or c['trajectory'],ensure_ascii=False,indent=2),'```',
            'Raw artifact: '+c['artifact']]
    (out/(phase+'_review.md')).write_text('\n'.join(lines)+'\n')
    return metrics


def controller(out):
    import importlib.util
    spec=importlib.util.spec_from_file_location('keys_reader',out/'credential_reader.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    control=read(out/'control.json')
    for name,digest in control['hashes'].items():
        if file_fingerprint(out/name)!=digest:raise ValueError('Frozen input changed: '+name)
    env={**os.environ,**(mod.credentials(control['keys_file']) if control['panel_kind']=='crossvid' else {}), 'PYTHONPATH':str(out/'src'),
         'MVAGENT_PROJECT_ROOT':str(ROOT),'PYTHONUNBUFFERED':'1'}
    if control['panel_kind']=='crossvid' and not env.get('DEEPSEEK_API_KEY'):raise ValueError('Missing DEEPSEEK_API_KEY in configured credential file')
    for key in ('NO_PROXY','no_proxy'):
        env[key]=','.join(filter(None,[env.get(key,''),'localhost','127.0.0.1','api.deepseek.com']))
    try:
        for phase in ('smoke','main'):
            run=out/phase;run.mkdir(exist_ok=True)
            args=dict(config=str(out/'recipe.yaml'),execution_config=str(out/'execution.yaml'),output_dir=str(run),
                mode='evaluate',split_manifest=str(out/(phase+'_split.json')),dataset_root=None,skills=str(out/'skills.json'),
                split='eval',limit=None,repeat_id=control['repeat_id'],resume=(run/'manifest.json').exists())
            if not (run/'summary.json').exists() or read(run/'summary.json').get('status')!='completed':
                code='import json,sys; from argparse import Namespace; from skill_evolution.runner import run; run(Namespace(**json.loads(sys.argv[1])))'
                with (out/(phase+'.log')).open('a') as log:
                    child=subprocess.Popen([sys.executable,'-u','-c',code,json.dumps(args)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                    status(out,phase,child_pid=child.pid,log=str(out/(phase+'.log')))
                    rc=child.wait()
                if rc:raise RuntimeError(f'{phase} failed ({rc}); inspect log, resume preserves results')
            audit=report(out,phase)
            if phase=='smoke' and (audit['injection_errors'] or any(c['health'].get('fatal') for c in read(out/'smoke_review.json'))):
                raise RuntimeError('Smoke engineering audit failed; main not started')
        smoke=read(out/'smoke/summary.json'); main_result=read(out/'main/summary.json')
        if set(smoke['samples']) & set(main_result['samples']):raise ValueError('Phase question overlap')
        samples={**smoke['samples'],**main_result['samples']}
        if set(samples)!={s.sample_id for s in DataSplitManifest.from_json(out/'split.json').samples}:raise ValueError('Incomplete combined panel')
        write_json(out/'combined/summary.json',dict(status='completed',sample_count=len(samples),samples=samples,
            phase_summary_hashes={p:file_fingerprint(out/p/'summary.json') for p in ('smoke','main')}))
        report(out,'combined')
        status(out,'completed',report=str(out/'combined_review.md'),audit=str(out/'combined_audit.json'))
    except Exception as exc:
        status(out,'failed',error=str(exc));raise


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['launch','run','report']);p.add_argument('--output',type=Path,required=True);p.add_argument('--panel',choices=['crossvid','transfer'],default='crossvid');p.add_argument('--per-task',type=int,default=100);p.add_argument('--bank',type=Path,default=ROOT/'configs/skill_evolution/skills/global_acquisition_v002.json');a=p.parse_args();out=a.output.resolve()
    if a.mode=='launch':
        if a.per_task<2:raise ValueError('per-task must be at least 2 for disjoint smoke/main')
        prepare(out,a.per_task,a.bank.resolve(),a.panel)
        with (out/'controller.log').open('a') as log:
            child=subprocess.Popen([sys.executable,'-u',str(out/'controller.py'),'run','--output',str(out)],cwd=ROOT,
                env={**os.environ,'MVAGENT_PROJECT_ROOT':str(ROOT)},stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write_json(out/'launch.json',dict(pid=child.pid));print(json.dumps(dict(output=str(out),pid=child.pid)))
    elif a.mode=='run':controller(out)
    else:print(json.dumps(report(out,'combined' if (out/'combined/summary.json').exists() else 'main' if (out/'main/summary.json').exists() else 'smoke'),indent=2))

if __name__=='__main__':main()
