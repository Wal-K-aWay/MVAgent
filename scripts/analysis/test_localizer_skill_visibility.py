"""Paired Localizer diagnostic with frozen prompts and selectable API model."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import fcntl
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]


def read(path): return json.loads(Path(path).read_text())


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def without_skill(localizer, background):
    fields={name:getattr(localizer,name) for name in ['TASK','INPUT','FAULT_TYPES','EXAMPLES','ANALYSIS','STAGE_CONSTRAINTS','OUTPUT']}
    fields['TASK']=re.sub(r'^- \*\*selected skill\*\*:.*\n','',fields['TASK'],flags=re.M)
    fields['TASK']=re.sub(r'^- \*\*steps\*\*:.*\n', '- **steps**: The actual sequence of actions, parameters and returned results produced while solving Input. The recorded actions establish what actually happened. For each step, assess the decision using information available before its action and assess execution using the request and returned result.\n',fields['TASK'],flags=re.M)
    fields['TASK']=re.sub(r'^The selected skill.*\n','',fields['TASK'],flags=re.M)
    fields['TASK']=fields['TASK'].replace('Assessment of whether to revise the Skill or create a new one belongs to later stages. ','')
    fields['INPUT']=fields['INPUT'].replace('input, question-level Skill guidance, all steps','input, all steps').replace('video metadata, fixed Skill guidance and results','video metadata and results')
    fields['FAULT_TYPES']=fields['FAULT_TYPES'].replace('Skill presence or absence does not determine fault type. ','')
    fields['EXAMPLES']=fields['EXAMPLES'].replace('Each example has its own step numbers and question-level Skill; these facts','Each example has its own input and step numbers; these facts')
    fields['EXAMPLES']=re.sub(r'^Selected skill:.*\n','',fields['EXAMPLES'],flags=re.M)
    fields['ANALYSIS']=fields['ANALYSIS'].replace('Keep Skill editing decisions for later stages; ','')
    fields['STAGE_CONSTRAINTS']=fields['STAGE_CONSTRAINTS'].replace(', leaving Skill content attribution and editing to later stages','')
    fields['STAGE_CONSTRAINTS']=re.sub(r'^- The question uses one fixed Skill.*$', '',fields['STAGE_CONSTRAINTS'],flags=re.M).rstrip()
    background=background.replace(', the fixed question-level Skill if selected,',' ,').replace('metadata , and History','metadata, and History')
    background=background.replace('A Skill supplies procedural guidance; its examples are hypothetical. ','')
    for name,text in {**fields,'BACKGROUND':background}.items():
        if re.search(r'\bskills?\b',text,re.I):raise ValueError('Skill wording remains in no-skill '+name)
    user='\n\n'.join(fields[name] for name in ['INPUT','FAULT_TYPES','EXAMPLES','ANALYSIS','STAGE_CONSTRAINTS','OUTPUT'])
    return fields, fields['TASK']+'\n\n'+background, user


def build_arm(job,arm, modules, no_system, no_template):
    evidence, prompts, localizer, trajectory=modules
    original=job['case']
    if arm=='with_skill':
        context=evidence.render_stage_input(dict(case=original,global_skills=job['cards']))
        return prompts.build_system_prompt('localizer'),prompts.build_stage_prompt('localizer',context)
    case=deepcopy(original);case.pop('used_skill',None)
    for step in case['steps']:
        step.pop('selected',None);step.pop('injected',None)
    truth=case.get('offline_feedback',{}).get('reference',{})
    truth=truth.get('reference_answer') or truth.get('ground_truth',[])
    truth='; '.join(map(str,truth)) if isinstance(truth,list) else str(truth)
    context='\n\n'.join(['## Input\n\n'+evidence._render_input(case['input']),
        '## steps\n'+trajectory.render_global_steps(case['steps']),
        '## output\n'+(str(case.get('final_answer',{}).get('answer','')) or 'None'),
        '## ground truth\n'+truth])
    from mvagent.skills.prompts import render_skill_text
    return no_system,no_template.replace('{trajectory}',render_skill_text(context,minimum_level=2))


def prepare(out, baseline_without_skill=None, inputs_json=None, model_name='glm-5.3-flash', prompts_from=None, thinking=True):
    if not thinking and model_name not in ('deepseek-v4-flash','deepseek-v4-pro'):raise ValueError('--no-thinking is supported for the DeepSeek diagnostic only')
    if out.exists():raise ValueError('Use a new output; resume frozen controller with run')
    out.mkdir(parents=True)
    prefix='skill_evolution.algorithms.alternating.global.adaptor'
    modules=(import_module(prefix+'.evidence'),import_module(prefix+'.prompts'),import_module(prefix+'.prompts.localizer.prompts'),import_module('skill_evolution.infra.trajectory'))
    common=import_module(prefix+'.prompts.common')
    fields,no_system,no_template=without_skill(modules[2],common.BACKGROUND)
    if inputs_json is not None:
        if baseline_without_skill is None:raise ValueError('Expanded inputs require a frozen no-skill baseline')
        jobs=read(inputs_json)
        assert jobs and len({j['case']['sample_id'] for j in jobs if j.get('cohort')=='expansion'})==sum(j.get('cohort')=='expansion' for j in jobs)
    else:
        old=ROOT/'outputs/analysis/20261001_localizer_glm53'
        selected=read(old/'inputs.json')
        jobs=[j for j in selected if j['case'].get('used_skill')]
        wanted={'crossvid:CC:621','crossvid:MOC:418','crossvid:PEA:226'}
        jobs += [j for j in selected if j['id'].startswith('baseline/') and j['case']['sample_id'] in wanted]
        fresh=read(ROOT/'outputs/analysis/20261001_localizer_flash_refined45/inputs.json')
        for task in ['BU','CC','NC','PI','PSS','MOC']:
            candidates=[j for j in fresh if j['case']['sample_id'].startswith('crossvid:'+task+':') and j['case']['sample_id'] not in {x['case']['sample_id'] for x in jobs}]
            candidates.sort(key=lambda j:hashlib.sha256(j['case']['sample_id'].encode()).hexdigest())
            jobs.append(candidates[0])
        assert len(jobs)==16 and sum(bool(j['case'].get('used_skill')) for j in jobs)==7
    for i,j in enumerate(jobs):
        j['experiment_case_id']=f'case_{i:02d}'
        j['used_skill_present']=bool(j['case'].get('used_skill'))
        if inputs_json is None:j['input_source']=str(old/'inputs.json' if j in selected else ROOT/'outputs/analysis/20261001_localizer_flash_refined45/inputs.json')
    save(out/'inputs.json',jobs)
    # Input/render equality checks guard against accidentally changing action evidence.
    schema=import_module(prefix+'.prompts.localizer.schema')
    prompt_records=[]
    for job in jobs:
        system_with,user_with=build_arm(job,'with_skill',modules,no_system,no_template)
        system_without,user_without=build_arm(job,'without_skill',modules,no_system,no_template)
        assert 'selected skill' not in user_without.lower()
        steptext=modules[3].render_global_steps(job['case']['steps'])
        from mvagent.skills.prompts import render_skill_text
        assert render_skill_text(steptext,minimum_level=2) in user_with and render_skill_text(steptext,minimum_level=2) in user_without
        assert not re.search(r'\bskills?\b',no_system+no_template,re.I)
        if job['used_skill_present']:
            assert job['case']['used_skill']['strategy'] in user_with
            assert job['case']['used_skill']['strategy'] not in user_without
        for arm,system,user in [('with_skill',system_with,user_with),('without_skill',system_without,user_without)]:
            prompt_records.append(dict(case_id=job['experiment_case_id'],arm=arm,system=system,user=user,schema=schema.build_schema(job['case'])))
    arms=['with_skill','without_skill']
    if baseline_without_skill is not None:
        baseline_without_skill=baseline_without_skill.resolve()
        baseline_jobs=read(baseline_without_skill/'inputs.json')
        if inputs_json is None:assert [(j['case'],j['cards']) for j in jobs]==[(j['case'],j['cards']) for j in baseline_jobs]
        baseline_templates=read(baseline_without_skill/'prompt_ablation.json')
        baseline={p['case_id']:p for p in read(baseline_without_skill/'prompts.json') if p['arm']=='without_skill'}
        no_skill_users={p['case_id']:p['user'] for p in prompt_records if p['arm']=='without_skill'}
        for p in prompt_records:
            if p['arm']=='with_skill':
                old_prompt=baseline[p['case_id']] if inputs_json is None else dict(schema=p['schema'],system=baseline_templates['system_without_skill'])
                if inputs_json is not None:
                    _,_,template=without_skill(modules[2],common.BACKGROUND)
                    head,tail=template.split('{trajectory}')
                    user=no_skill_users[p['case_id']]
                    assert user.startswith(head) and user.endswith(tail)
                    context=user[len(head):len(user)-len(tail)]
                    old_prompt['user']=baseline_templates['user_template_without_skill'].replace('{trajectory}',context)
                assert old_prompt['schema']==p['schema']
                p.update(system=old_prompt['system'],user=old_prompt['user'],arm='baseline_without_skill')
            else:p['arm']='revised_without_skill'
        arms=['baseline_without_skill','revised_without_skill']
        save(out/'baseline_reference.json',dict(output=str(baseline_without_skill),
            prompts_hash=sha(baseline_without_skill/'prompts.json'),inputs_hash=sha(baseline_without_skill/'inputs.json'),
            template_hash=sha(baseline_without_skill/'prompt_ablation.json'),
            design='Fresh calls for old and revised no-skill prompts; identical cases and schema. Historical responses are not reused.'))
    if prompts_from is not None:
        assert read(prompts_from/'inputs.json') == jobs
        frozen_prompts=read(prompts_from/'prompts.json')
        assert [(p['case_id'],p['arm'],p['schema']) for p in frozen_prompts] == [(p['case_id'],p['arm'],p['schema']) for p in prompt_records]
        prompt_records=frozen_prompts
        save(out/'prompt_reference.json',dict(output=str(prompts_from.resolve()),prompts_hash=sha(prompts_from/'prompts.json'),inputs_hash=sha(prompts_from/'inputs.json')))
    save(out/'prompts.json',prompt_records)
    save(out/'no_skill_prompt_fields.json',fields)
    save(out/'prompt_ablation.json',dict(background_without_skill=no_system.split('\n\n# Target Agent',1)[-1],system_without_skill=no_system,user_template_without_skill=no_template))
    shutil.copy2(ROOT/'configs/skill_evolution/runtime/dynamic_35b_embedding.yaml',out/'runtime.yaml')
    registry='glm53_flash_optimizer'
    if model_name in ('deepseek-v4-flash','deepseek-v4-pro'):
        import yaml
        runtime=yaml.safe_load((out/'runtime.yaml').read_text())
        registry='deepseek_localizer'
        runtime['models'][registry]=dict(type='api_llm',provider='deepseek',model_name=model_name,
            api_base='https://api.deepseek.com',api_key='DEEPSEEK_API_KEY',enable_thinking=thinking,
            reasoning_effort='high',temperature=1.0,top_p=0.95,max_tokens=16384,timeout_sec=600,max_retries=2)
        (out/'runtime.yaml').write_text(yaml.safe_dump(runtime,sort_keys=False))
    shutil.copy2(__file__,out/'controller.py')
    shutil.copy2(ROOT/'scripts/analysis/analyze_localizer_skill_visibility.py',out/'analyze.py')
    shutil.copy2(ROOT/'scripts/analysis/credentials.py',out/'credentials.py')
    shutil.copytree(ROOT/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    paths=list((out/'src').rglob('*'))+[out/'controller.py',out/'analyze.py',out/'credentials.py',out/'inputs.json',out/'prompts.json',out/'runtime.yaml',out/'no_skill_prompt_fields.json',out/'prompt_ablation.json']
    if baseline_without_skill is not None:paths.append(out/'baseline_reference.json')
    if prompts_from is not None:paths.append(out/'prompt_reference.json')
    if inputs_json is not None:
        shutil.copy2(inputs_json.parent/'sampling.json',out/'panel_sampling.json')
        shutil.copy2(ROOT/'scripts/analysis/prepare_localizer_boundary_panel.py',out/'panel_prepare.py')
        paths.extend([out/'panel_sampling.json',out/'panel_prepare.py'])
    manifest={str(p.relative_to(out)):sha(p) for p in paths if p.is_file()}
    save(out/'source_manifest.json',manifest)
    save(out/'protocol.json',dict(model=model_name,optimizer_registry=registry,enable_thinking=thinking,case_count=len(jobs),
        skill_cases=sum(j['used_skill_present'] for j in jobs),no_skill_cases=sum(not j['used_skill_present'] for j in jobs),correct_control_cases=sum(j['score']==1 for j in jobs),
        repeats=2,arms=arms,requests=len(jobs)*4,workers=4,
        design='Fresh paired calls for both arms, identical trajectories and schemas; two repeats. DeepSeek enables/disables thinking as recorded in runtime.yaml; thinking mode omits temperature/top_p, non-thinking sends temperature1/top_p.95. Reasoning, sampling and provider schema transport can differ. No historical outputs reused.',
        scope='Frozen development real traces; no new Actor/Judge/Gate/evolution. Schema-valid localization is not evidence of quality. Correct-answer controls can still have actionable faults.',
        prompt_change=('Compare last task-check revision without Skill against tightened verification/proven-defect boundaries on regression and three-benchmark expansion cohorts.' if inputs_json is not None else 'Compare frozen original no-skill prompts with revised no-skill prompts adding task-derived output, coverage, event-definition and verifiable-candidate checks.' if baseline_without_skill is not None else 'Remove selected-skill section and every guidance reference from TASK, examples, rules and shared BACKGROUND; remove selection/injection fields from no-skill rendering. Preserve all task/actions/results/output/GT and new action information-boundary guidance.'),
        evaluation='Paired status/primary-step/type agreement, within-arm repeat variability, grounded fault review, usage. No model-as-judge calls or deterministic-output assumption.',
        source_manifest_hash=sha(out/'source_manifest.json'),git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()))
    save(out/'status.json',dict(status='prepared',completed=0,total=len(jobs)*4))


def run(out):
    lock=(out/'controller.lock').open('a');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.path.insert(0,str(out/'src'))
    from models.factory import ModelFactory
    from models.execution import execution_scope
    from mvagent.configs import MVAgentConfig
    from skill_evolution.configs.model_config import EvolutionModelConfig
    from models.utils import validate_json_schema
    prefix='skill_evolution.algorithms.alternating.global.adaptor'
    validator=import_module(prefix+'.prompts.localizer.schema')
    manifest=read(out/'source_manifest.json')
    assert sha(out/'source_manifest.json')==read(out/'protocol.json')['source_manifest_hash']
    assert all(sha(out/p)==h for p,h in manifest.items())
    config=MVAgentConfig.from_yaml(out/'runtime.yaml')
    records=read(out/'prompts.json');cases={j['experiment_case_id']:j for j in read(out/'inputs.json')}
    jobs=[dict(p,repeat=repeat) for repeat in range(2) for p in records]
    random.Random(20261002).shuffle(jobs)
    save(out/'schedule.json',[dict(case_id=j['case_id'],arm=j['arm'],repeat=j['repeat']) for j in jobs])
    registry=read(out/'protocol.json')['optimizer_registry']
    model=ModelFactory.create_model(EvolutionModelConfig(model_type=registry),config)
    save(out/'model_identity.json',model.identity);model.close()
    started=time.monotonic();results=[]
    def call(job):
        folder=out/'calls'/job['case_id']/job['arm']/f'repeat_{job["repeat"]}'
        path=folder/'result.json'
        if path.exists():return read(path)
        folder.mkdir(parents=True,exist_ok=True)
        save(folder/'request.json',dict(system=job['system'],user=job['user'],schema=job['schema']))
        model=ModelFactory.create_model(EvolutionModelConfig(model_type=registry),config)
        events=[];begin=time.monotonic()
        result=dict(case_id=job['case_id'],sample_id=cases[job['case_id']]['case']['sample_id'],arm=job['arm'],repeat=job['repeat'],used_skill_present=cases[job['case_id']]['used_skill_present'],score=cases[job['case_id']]['score'])
        try:
            with execution_scope(emit=events.append):
                response=model.json_prompt(job['user'],system_prompt=job['system'],json_schema=job['schema'],schema_name='global_localizer')
            response={key:response.get(key) for key in ['status','value','raw_response','error']}
            save(folder/'response.json',response)
            if response['status']!='ok' or response['value'] is None:raise ValueError(response.get('error') or 'Invalid response')
            validate_json_schema(response['value'],job['schema']);validator.validate(response['value'])
            result.update(status='ok',value=response['value'])
        except Exception as error:
            result.update(status='error',error_type=type(error).__name__,error=str(error))
        finally:
            model.close();save(folder/'events.json',events)
        result['seconds']=time.monotonic()-begin;save(path,result);return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(call,j) for j in jobs]):
            results.append(future.result());save(out/'results.json',results)
            elapsed=time.monotonic()-started
            remaining=(elapsed/len(results))*(len(jobs)-len(results))
            save(out/'status.json',dict(status='running',pid=os.getpid(),completed=len(results),total=len(jobs),elapsed_seconds=elapsed,estimated_remaining_seconds=remaining,errors=sum(r['status']=='error' for r in results)))
            print(f'{len(results)}/{len(jobs)} complete; ETA {remaining/60:.1f} min',flush=True)
    save(out/'status.json',dict(status='completed',completed=len(results),total=len(jobs),elapsed_seconds=time.monotonic()-started,errors=sum(r['status']=='error' for r in results),estimated_remaining_seconds=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['launch','run']);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-without-skill',type=Path,help='Fresh paired old/revised no-skill calls using a frozen visibility experiment')
    parser.add_argument('--inputs-json',type=Path,help='Prepared extended cases; requires frozen baseline')
    parser.add_argument('--model',choices=['glm-5.3-flash','deepseek-v4-flash','deepseek-v4-pro'],default='glm-5.3-flash')
    parser.add_argument('--prompts-from',type=Path,help='Reuse exact frozen prompts from a matched experiment')
    parser.add_argument('--no-thinking',action='store_true',help='Disable thinking for DeepSeek diagnostic calls')
    args=parser.parse_args();out=args.output.resolve()
    if args.command=='launch':
        prepare(out,args.baseline_without_skill,args.inputs_json,args.model,args.prompts_from,thinking=not args.no_thinking)
        from credentials import credentials
        env=os.environ.copy()
        required='DEEPSEEK_API_KEY' if args.model in ('deepseek-v4-flash','deepseek-v4-pro') else 'BIGMODEL_API_KEY'
        if not env.get(required):env.update(credentials(ROOT/'.local/skill_evolution_keys.env'))
        if not env.get(required):raise RuntimeError('Missing '+required)
        for key in ['NO_PROXY','no_proxy']:env[key]=env.get(key,'')+',open.bigmodel.cn,api.deepseek.com'
        env['PYTHONPATH']=str(out/'src')
        with (out/'controller.log').open('a') as log:
            process=subprocess.Popen([sys.executable,str(out/'controller.py'),'run','--output',str(out)],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        save(out/'launch.json',dict(pid=process.pid,started_at=time.time()));print(json.dumps(dict(pid=process.pid,output=str(out))))
    else:
        try:run(out)
        except Exception as error:
            save(out/'status.json',dict(status='failed',error_type=type(error).__name__,error=str(error)))
            raise
