"""Replay frozen Train evidence; compare mixed reflection with split analysis + merge."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse, json, sys, os, subprocess, shutil, fcntl

FAILURE = '''Analyze only these healthy unsuccessful public Train trajectories. Identify at most three supported recurring failure patterns. Distinguish missing method, selection mismatch, specific card content defect, ignored existing guidance, visual/report uncertainty and insufficient evidence. Do not equate a wrong answer with a card defect. Give each pattern concrete case/step references and short evidence quotations. A body defect requires the exact card version actually used. Ground truth is discrepancy feedback, never observed evidence. Generalize task/evidence relationships, not incidental domain/count/duration. You are an analyst, not a card author. Return patterns and limitations; propose no final edit or new evidence.'''
SUCCESS = '''Analyze only these successful public Train trajectories. Identify at most three reusable observed effective action patterns and rules that should be preserved. Success alone does not prove a card caused it; separate actions observed from causal claims. Cite case/step references and short evidence quotations. Distinguish successful use of an existing card from successful behavior without it. Do not turn incidental domain/count/duration into prerequisites or invent observations from ground truth. You are an analyst, not a card author. Return patterns and limitations; propose no final edit or new evidence.'''
MERGE = '''Use the separate unsuccessful and successful analyses as hypotheses. Verify them against the complete original public cases below; reject unsupported summaries, reconcile contradictions and preserve effective existing guidance. Success and failure categories alone do not establish causality. Choose at most one edit using the exact reflection output contract. You may skip. Do not add evidence absent from the original trajectories.'''


def read(path):
    return json.loads(Path(path).read_text())


def prepare(out):
    from skill_evolution.infra.store import write_json, tree_hash, file_fingerprint
    root=Path.cwd(); out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(root/'src',out/'src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(__file__,out/'controller.py')
    shutil.copy(root/'outputs/analysis/20261004_shared_library_split_author/runtime.yaml',out/'runtime.yaml')
    origins=[]; batches=[]
    for source in sorted((root/'outputs/analysis/20261003_isolated_clusters').glob('cluster_*/train/batches/*/materials.json')):
        raw=read(source); cases=raw['cases']; catalog=[]
        bankpath=source.parents[2]/'banks'/raw['train_bank_hash']/'bank.json'
        if bankpath.exists():catalog=read(bankpath)['skills']
        elif raw['target_skill']:catalog=[raw['target_skill']]
        # Preserve actual historical catalog/exposure; never relabel isolated runs as full-library rollouts.
        for c in cases:
            if c.get('used_skill') and c['used_skill'] not in catalog:raise ValueError('Historical card version mismatch')
        cases=json.loads(json.dumps(cases))
        for i,c in enumerate(cases,1):c['source_sample_id']=c['sample_id'];c['sample_id']='case_'+str(i)
        key=source.parts[-5]+'-'+source.parts[-2]
        payload=dict(cases=cases,library=catalog,target_skill=None,rejected=[],max_card_words=1200)
        write_json(out/'inputs'/f'{key}.json',payload)
        batches.append(key);origins.append(dict(batch=key,path=str(source),hash=file_fingerprint(source)))
    counts=dict(batches=len(batches),cases=sum(len(read(out/'inputs'/f'{k}.json')['cases']) for k in batches))
    write_json(out/'protocol.json',dict(**counts,batches_order=batches,repeats=2,workers=2,arms=['mixed','split'],model='glm53_flash_optimizer',origins=origins,limits='Frozen historical Train343,45 batches from10 clusters; historical isolated catalogs retained. No Gate, no new Actor runs, no Skill editing or optimization. Split sees original cases again at merge to reduce summary loss. More model calls in split; this tests workflow, not equal compute. Structural validity and repeat agreement are not semantic accuracy; final claim needs Codex manual evidence audit.'))
    write_json(out/'manifest.json',dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),source=tree_hash(out/'src'),files={p.name:file_fingerprint(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}))
    env=os.environ.copy()
    sys.path.insert(0,str(root/'scripts/analysis'))
    from credentials import credentials
    env.update(credentials(root/'.local/skill_evolution_keys.env'))
    for k in ('NO_PROXY','no_proxy'):env[k]=env.get(k,'')+',open.bigmodel.cn'
    with (out/'controller.log').open('a') as log:
        proc=subprocess.Popen([sys.executable,str(out/'controller.py'),'run','--output',str(out)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write_json(out/'launch.json',dict(pid=proc.pid));print(json.dumps(dict(output=str(out),pid=proc.pid,**counts)))


def run(out):
    from mvagent.configs import MVAgentConfig
    from models.factory import ModelFactory
    from skill_evolution.configs.model_config import EvolutionModelConfig
    from skill_evolution.infra.store import write_json,tree_hash,file_fingerprint
    from importlib import import_module
    stages=import_module('skill_evolution.algorithms.alternating.global.cluster.stages')
    reflect=import_module('skill_evolution.algorithms.alternating.global.cluster.prompts.reflect.schema')
    prompts=import_module('skill_evolution.algorithms.alternating.global.cluster.prompts')
    evidence=import_module('skill_evolution.algorithms.alternating.global.cluster.evidence')
    from models.execution import execution_scope
    from models.utils import validate_json_schema
    m=read(out/'manifest.json');assert tree_hash(out/'src')==m['source']
    assert all(file_fingerprint(out/k)==v for k,v in m['files'].items())
    lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    config=MVAgentConfig.from_yaml(out/'runtime.yaml');protocol=read(out/'protocol.json')
    def status(**kw):write_json(out/'status.json',dict(time=datetime.now(timezone.utc).isoformat(),pid=os.getpid(),**kw))
    def context(payload):
        return evidence.render_stage_input(payload).replace('Each case used the full current library; verified usage is listed.','These are frozen historical Train rollouts. The listed catalog and verified used versions are historical; do not infer they were rerun under a new library.')
    def call(model,path,system,user,schema,validator):
        if (path/'checked.json').exists():return read(path/'checked.json')
        write_json(path/'input.json',dict(system=system,user=user,schema=schema));events=[]
        try:
            with execution_scope(emit=events.append):response=model.json_prompt(user,system_prompt=system,json_schema=schema,schema_name='reflect_diagnostic')
        finally:write_json(path/'events.json',events)
        write_json(path/'response.json',{k:response.get(k) for k in ('status','value','raw_response','error')})
        errors=[];value=response.get('value')
        try:
            if response.get('status')!='ok':raise ValueError(response.get('error') or 'Model invalid output')
            validate_json_schema(value,schema);validator(value)
        except (ValueError,TypeError,KeyError,StopIteration) as exc:errors.append(str(exc))
        result=dict(value=value,errors=errors);write_json(path/'checked.json',result);return result
    def job(key,repeat):
        model=ModelFactory.create_model(EvolutionModelConfig(model_type='glm53_flash_optimizer'),config)
        payload=read(out/'inputs'/f'{key}.json');directory=out/'runs'/key/str(repeat)
        schema=reflect.build_schema(payload['cases'],payload['library']);validate=lambda v:reflect.validate(v,payload['cases'],payload['library'])
        text=context(payload);base=prompts.build_system_prompt('reflect')
        try:
            mixed=call(model,directory/'mixed',base,text,schema,validate)
            analyses={}
            for name,system,want_success in [('failure',FAILURE,False),('success',SUCCESS,True)]:
                subset=[c for c in payload['cases'] if (c['offline_feedback']['score']>=1)==want_success]
                if not subset:analyses[name]=dict(value=dict(patterns=[],limitations='No cases in this category'),errors=[]);continue
                pattern=dict(type='object',additionalProperties=False,required=['claim','case_ids','steps','evidence','card_id'],properties=dict(claim=dict(type='string'),case_ids=dict(type='array',minItems=1,uniqueItems=True,items=dict(type='string',enum=[c['sample_id'] for c in subset])),steps=dict(type='array',items=dict(type='integer',minimum=1)),evidence=dict(type='string'),card_id=dict(anyOf=[dict(type='string'),dict(type='null')])) )
                analysis_schema=dict(type='object',additionalProperties=False,required=['patterns','limitations'],properties=dict(patterns=dict(type='array',maxItems=3,items=pattern),limitations=dict(type='string')))
                analyses[name]=call(model,directory/name,system,context(dict(payload,cases=subset)),analysis_schema,lambda v:None)
            split=call(model,directory/'split',base+'\n\n'+MERGE,text+'\n\n## Separate analyses\n'+json.dumps(analyses,ensure_ascii=False),schema,validate)
            row=dict(batch=key,repeat=repeat,mixed=mixed,split=split,analysis_invalid={k:bool(v['errors']) for k,v in analyses.items()})
            write_json(directory/'result.json',row);return row
        finally:model.close()
    jobs=[(k,r) for k in protocol['batches_order'] for r in range(2)];rows=[]
    status(state='running',completed=0,total=len(jobs))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            for f in as_completed([executor.submit(job,k,r) for k,r in jobs]):
                rows.append(f.result());status(state='running',completed=len(rows),total=len(jobs))
        summary={}
        for arm in ('mixed','split'):
            def signature(v):return tuple(v.get(k) for k in ('status','target_skill_id','sample_id','step'))
            by={r['batch']:[] for r in rows}
            for r in rows:by[r['batch']].append(r[arm])
            valid=[r for r in rows if not r[arm]['errors']]
            summary[arm]=dict(outputs=len(rows),structural_valid=len(valid),routing_repeat_agreement=sum(v[0]['value']['status']==v[1]['value']['status'] and v[0]['value']['target_skill_id']==v[1]['value']['target_skill_id'] for v in by.values() if all(not x['errors'] for x in v)),exact_anchor_repeat_agreement=sum(signature(v[0]['value'])==signature(v[1]['value']) for v in by.values() if all(not x['errors'] for x in v)),valid_repeat_pairs=sum(all(not x['errors'] for x in v) for v in by.values()))
        write_json(out/'structural_summary.json',summary)
        queue=[dict(batch=k,repeat=r,arm=a,path=str(out/'runs'/k/str(r)/a/'checked.json'),semantic_verdict=None,evidence_notes=None) for k,r in jobs for a in ('mixed','split')]
        write_json(out/'manual_audit_queue.json',queue)
        status(state='awaiting_semantic_review',completed=len(rows),total=len(jobs),note='Calls complete; accuracy unmeasured until evidence audit. No production changes.')
    except BaseException as exc:status(state='failed',completed=len(rows),total=len(jobs),error=str(exc));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run']);parser.add_argument('--output',required=True);args=parser.parse_args();out=Path(args.output).resolve()
    if args.mode=='run':sys.path.insert(0,str(out/'src'));run(out)
    else:sys.path.insert(0,str(Path.cwd()/'src'));prepare(out)
