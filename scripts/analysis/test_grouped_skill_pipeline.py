"""Diagnostic Generator/Selector integration using frozen grouping inputs and traces."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import replace
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[2]


def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)


def prepare(root):
    output=root/'skill_pipeline';output.mkdir(exist_ok=True)
    inputs=read(ROOT/'outputs/analysis/20261001_localizer_flash_refined45/inputs.json')
    localizations={x['id']:x for x in read(ROOT/'outputs/analysis/20261001_localizer_flash_refined45/results.json')}
    for name in ['runtime.yaml','execution.yaml']:
        source=ROOT/('configs/skill_evolution/runtime/dynamic_35b_embedding.yaml' if name=='runtime.yaml' else 'configs/inference/execution/gpu2_7_single.yaml')
        if not (output/name).exists():shutil.copy2(source,output/name)
    jobs=[]
    for family,sid in [('sequence_order','crossvid:PSS:617'),('counting','crossvid:MOC:474'),('gap_completion','crossvid:PI:65')]:
        job=next(x for x in inputs if x['case']['sample_id']==sid)
        localized=localizations[job['id']]['value']
        assert localized['status']=='located'
        jobs.append(dict(family=family,case=job['case'],localization=localized))
    if not (output/'generation_sources.json').exists():save(output/'generation_sources.json',jobs)
    save(output/'protocol.json',dict(generation_arms=['single_case','grouped_cases'],max_card_words=1200,
        scope='Generator/selection integration diagnostic only; no QA/Gate or deployment',
        selector='Actual initial task-scope select_skills, full catalog; question/options/video IDs/durations only',
        source='Frozen no-Skill actual cases and existing localized faults',
        ground_truth_boundary='GT/trajectory only in Generator training evidence, never selector or embedding',
        no_test_context='Generator receives development input-only applicability examples, never confirmation questions or scores'))
    shutil.copy2(__file__,output/'controller.py')
    return output


def generate(root):
    from models.embeddings import EmbeddingConfig,embed
    from models.execution import execution_scope
    from models.factory import ModelFactory
    from mvagent.configs import MVAgentConfig
    from skill_evolution.configs.model_config import EvolutionModelConfig
    from skill_evolution.infra.bank import BankSnapshot
    from mvagent.skills.bank import SkillBank
    evidence=importlib.import_module('skill_evolution.algorithms.alternating.global.adaptor.evidence')
    stages=importlib.import_module('skill_evolution.algorithms.alternating.global.adaptor.stages')
    grouping=importlib.util.spec_from_file_location('grouping',root/'controller.py')
    module=importlib.util.module_from_spec(grouping);grouping.loader.exec_module(module)
    out=prepare(root);jobs=read(out/'generation_sources.json');cfg=MVAgentConfig.from_yaml(out/'runtime.yaml')
    spec=importlib.util.spec_from_file_location('credentials',ROOT/'scripts/analysis/credentials.py');credentials=importlib.util.module_from_spec(spec);spec.loader.exec_module(credentials)
    os.environ.update(credentials.credentials(ROOT/'.local/skill_evolution_keys.env'))
    for key in ['NO_PROXY','no_proxy']:os.environ[key]=os.environ.get(key,'')+',open.bigmodel.cn'
    if not os.environ.get('BIGMODEL_API_KEY'):raise RuntimeError('Missing optimizer credential')
    rows=read(root/'inputs.json');partition=read(root/'partition.json');train=[i for i,r in enumerate(rows) if partition[r['sample_id']]=='dev']
    vectors=np.vstack([np.load(p) for p in sorted((root/'embeddings/strategy_summary').glob('batch_*.npy'))])
    # Selected representation contains derived option count: recover options solely from question text.
    def task_row(case):
        q=case['input']['question'];options=[]
        if '\n\nOptions:\n' in q:options=q.split('\n\nOptions:\n',1)[1].split('\n\nYour answer:',1)[0].splitlines()
        return dict(videos=case['input']['videos'],options=[x for x in options if x.strip()])
    texts=[]
    parent=BankSnapshot.empty()
    initial=read(ROOT/'outputs/analysis/20261001_question_embedding_clusters_small/question_options/embedding_inputs.json')
    renderer=importlib.util.spec_from_file_location('renderer',ROOT/'outputs/analysis/20261001_question_embedding_clusters_small/source.py');render=importlib.util.module_from_spec(renderer);renderer.loader.exec_module(render)
    for job in jobs:
        row=task_row(job['case']);text=render.render_input(job['case']['input']['question'],row['options'],row['videos'],False)
        texts.append(f'Instruct: {module.STRATEGY_INSTRUCTION}\nQuery: {text}\n\n{module.profile(row)}')
    save(out/'embedding_inputs.json',texts)
    path=out/'anchor_vectors.npy'
    if not path.exists():
        events=[]
        with execution_scope(emit=events.append):query=embed(EmbeddingConfig('http://127.0.0.1:8110/v1','qwen3_embedding_8b',120),tuple(texts))
        np.save(path,query);save(out/'embedding_events.json',events)
    query=np.load(path)
    planned=[]
    for i,job in enumerate(jobs):
        similarities=vectors@query[i];candidates=[j for j in train if similarities[j]>=.65]
        nearest=sorted(candidates,key=lambda j:-similarities[j])[:16]
        if not nearest:nearest=sorted(train,key=lambda j:-similarities[j])[:1]
        save(out/f'{job["family"]}_material_neighbors.json',[dict(**rows[j],similarity=float(similarities[j]),
            evidence_kind='Input-only applicability example; no trajectory/GT/localization') for j in nearest])
        # Train scope examples only; no fabricated failed actions or localization.
        related=[dict(case=dict(sample_id=rows[j]['sample_id'],bank_hash=job['case']['bank_hash'],
            input=dict(question=rows[j]['question'],videos=rows[j]['videos']),steps=[],
            offline_feedback=dict(reference=dict(ground_truth=[]))),faults=[]) for j in nearest[:4]]
        entry=job['localization']['fault_chain'][0];context=evidence.fault_context(job['case'],entry)
        for arm in ['single_case','grouped_cases']:
            payload={**context,'group_cases':related if arm=='grouped_cases' else []}
            planned.append(dict(family=job['family'],arm=arm,case=job['case'],context=payload))
    save(out/'generation_plan.json',planned)
    def work(job):
        directory=out/'generation'/job['arm']/job['family'];model=ModelFactory.create_model(EvolutionModelConfig(model_type='glm53_flash_optimizer'),cfg)
        try:
            value=stages.Stages(model).generate(directory,job['case'],job['context'],parent,
                dict(action='create',skill_id='',reason='No Skill was used; generate a question-wide strategy from this localized fault.'),[],[],1200)
            return dict(family=job['family'],arm=job['arm'],status='ok',card=value['card'])
        except stages.StageValidationError as exc:return dict(family=job['family'],arm=job['arm'],status='invalid',error=str(exc))
        finally:model.close()
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(work,job) for job in planned]):
            results.append(future.result());save(out/'generation_results.json',results)
            save(out/'status.json',dict(phase='generation',completed=len(results),total=len(planned)))
            print(results[-1]['arm'],results[-1]['family'],results[-1]['status'],flush=True)
    for arm in ['single_case','grouped_cases']:
        cards=[x['card'] for x in results if x['arm']==arm and x['status']=='ok']
        value=dict(schema_version=3,skills=cards);SkillBank.from_dict(value);save(out/(arm+'_bank.json'),value)
    return results


def select(root):
    from models.factory import ModelFactory
    from models.execution import execution_scope
    from models.pool import install_pools
    from mvagent.batch import BatchExecutor,ExecutionConfig
    from mvagent.configs import MVAgentConfig
    from mvagent.engine import MVAgentEngine
    from mvagent.skills.bank import SkillBank
    from mvagent.skills.selection import select_skills
    out=root/'skill_pipeline';cfg=MVAgentConfig.from_yaml(out/'runtime.yaml')
    if not (out/'selector_controller.py').exists():shutil.copy2(__file__,out/'selector_controller.py')
    banks={};family_card={}
    generated=read(out/'shadow_generation_results.json') if (out/'shadow_generation_results.json').exists() else read(out/'generation_results.json')
    shadow=any(x.get('shadow') for x in generated)
    for arm in ['single_case','grouped_cases']:
        bank_file=out/(arm+('_shadow_bank.json' if shadow else '_bank.json'))
        settings=replace(cfg.global_agent.skill,path=str(bank_file.resolve()),
            sha256=__import__('hashlib').sha256(bank_file.read_bytes()).hexdigest())
        banks[arm]=MVAgentEngine._load_configured_skill(settings)
        family_card[arm]={x['family']:x['card']['meta']['id'] for x in generated if x['arm']==arm and x['status']=='ok'}
    banks['existing']=MVAgentEngine._load_configured_skill(cfg.global_agent.skill)
    family_card['existing']={'sequence_order':'global-process-order','difference_comparison':'global-visual-discriminants'}
    rows={r['sample_id']:r for r in read(root/'inputs.json')};partition=read(root/'partition.json')
    refs=read(root/'references.json');jobs=[]
    # Keep both arms' reference universe identical; missing cards count as inability to supply the intended strategy.
    for ref in refs:
        for arm in banks:
            if arm!='existing' and partition[ref['sample_id']]!='confirm':continue
            jobs.append(dict(arm=arm,reference=ref,row=rows[ref['sample_id']]))
    save(out/'selection_plan.json',jobs)
    pool_events=[];batch=BatchExecutor(ExecutionConfig.from_yaml(out/'execution.yaml'),on_event=pool_events.append)
    clients=[];local=threading.local();results=[]
    try:
        batch.prepare(cfg.to_dict());save(out/'pool.json',pool_events)
        prepared=next(e for e in pool_events if e['kind']=='batch_prepared')
        if prepared['question_workers']!=6 or prepared['unavailable']:raise RuntimeError('Six healthy Actor replicas required')
        install_pools(batch.pools)
        def work(job):
            row=job['row'];ref=job['reference'];arm=job['arm'];path=out/'selection'/arm/(row['sample_id'].replace(':','_')+'.json')
            if path.exists():return read(path)
            if not hasattr(local,'model'):local.model=ModelFactory.create_model(cfg.global_agent.model,cfg);clients.append(local.model)
            recorded=[];started=time.monotonic()
            try:
                state=dict(videos={v['video_id']:dict(duration_sec=v['duration_sec']) for v in row['videos']},history='')
                def decide(prompt,**kwargs):return local.model.json_prompt(prompt,**kwargs)
                with execution_scope(emit=recorded.append,deadline=time.monotonic()+240):
                    response=select_skills(banks[arm],role='global',has_evidence=False,task=row['question'],
                        state=state,decide=decide,selection_cache={})
                event=next(e for e in reversed(recorded) if e['kind']=='skill_selection')
                chosen=[x['id'] for x in event.get('selected',[])]
                expected=family_card[arm].get(ref['family'])
                # Broad-family intent agreement only, not independent exact applicability truth.
                result=dict(sample_id=row['sample_id'],arm=arm,shadow=(shadow and arm!='existing'),partition=partition[row['sample_id']],family=ref['family'],dataset=row['dataset'],status='ok',
                    selected=chosen,expected=expected,
                    intent_match=(chosen==[expected] if expected else (not chosen and ref['family']=='difference_comparison')),
                    positive_family=ref['family']!='difference_comparison',seconds=time.monotonic()-started,events=recorded)
            except Exception as exc:result=dict(sample_id=row['sample_id'],arm=arm,status='error',error=type(exc).__name__,events=recorded)
            save(path,result);return result
        with ThreadPoolExecutor(max_workers=6) as pool:
            for future in as_completed([pool.submit(work,job) for job in jobs]):
                results.append(future.result());save(out/'selection_results.json',results)
                save(out/'status.json',dict(phase='selection',completed=len(results),total=len(jobs)))
                if len(results)%24==0:print('Selector',len(results),'/',len(jobs),flush=True)
    finally:
        for client in clients:client.close()
        batch.close()
    summaries={}
    for arm in banks:
        subset=[r for r in results if r['arm']==arm];counts={}
        for family in sorted({r['reference']['family'] for r in jobs}):
            values=[r for r in subset if r.get('family')==family]
            counts[family]=dict(n=len(values),intent_match=sum(r.get('intent_match',False) for r in values),
                selected=sum(bool(r.get('selected')) for r in values),
                card_available=family in family_card[arm])
        summaries[arm]=dict(cases=len(subset),errors=sum(r['status']!='ok' for r in subset),families=counts)
    save(out/'selection_summary.json',summaries);save(out/'status.json',dict(phase='completed',selection_jobs=len(jobs)))
    print(json.dumps(summaries),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=['generate','select'])
    parser.add_argument('--input',type=Path,required=True);args=parser.parse_args()
    sys.path.insert(0,str(args.input.resolve()/'src'))
    if args.stage=='generate':generate(args.input.resolve())
    else:select(args.input.resolve())
