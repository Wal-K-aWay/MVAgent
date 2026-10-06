"""Train-only real Selector replay; behavior is not a gold applicability label."""
from pathlib import Path
from dataclasses import replace
import json
from concurrent.futures import ThreadPoolExecutor
from models.factory import ModelFactory
from models.execution import execution_scope
from mvagent.configs import MVAgentConfig
from mvagent.skills.selection import select_skills
from skill_evolution.configs.model_config import EvolutionModelConfig
from skill_evolution.infra.store import write_json
from skill_evolution.infra.skills import hash_json
from .evidence import _render_input

def replay_selection(executor,parent,candidate,inputs,directory):
    directory=Path(directory)
    config=MVAgentConfig.from_dict(executor.base_config)
    model_cfg=executor.base_config['agents']['global_agent']['skill']['selector']
    identity=hash_json(dict(parent=parent.to_dict(),candidate=candidate.to_dict(),inputs=inputs,config=executor.base_config))
    path=directory/'result.json'
    if path.exists():
        result=json.loads(path.read_text())
        if result['identity']!=identity:raise ValueError('Routing replay identity mismatch')
        return result['rows']
    def one(item):
        sid,inp=item;row=dict(sample_id=sid);events=[]
        row_path=directory/(sid.replace(':','_')+'.json')
        if row_path.exists():
            saved=json.loads(row_path.read_text())
            if saved['identity']!=identity:raise ValueError('Routing row identity mismatch')
            return saved['row']
        model=ModelFactory.create_model(EvolutionModelConfig(**model_cfg),config)
        try:
            for label,bank in [('before',parent),('after',candidate)]:
                cache={};videos={v['video_id']:dict(duration_sec=v['duration_sec']) for v in inp['videos']}
                with execution_scope(emit=events.append):value=select_skills(replace(bank.bank,embedding=config.global_agent.skill.embedding),role='global',has_evidence=False,task=_render_input(inp).split('\n\n',1)[1],state=dict(videos=videos,history='(none)'),selection_cache=cache,decide=model.json_prompt)
                if value['status']!='ok':raise ValueError('Train routing replay failed')
                row[label]=[c['id'] for c in cache['selected']]
            write_json(row_path,dict(identity=identity,row=row,events=events))
            return row
        finally:model.close()
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(one,inputs.items()))
    write_json(path,dict(identity=identity,rows=rows,note='Train only; changed selections are not proof improvement'))
    return rows
