"""Small isolated Modal regression for direct Global decisions and loop-limit answers."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = [('9B','9b','cvbench:664'), ('27B','27b','mvu_eval:Comparison:818'),
         ('35B-A3B','35b_a3b','crossvid:MOC:521')]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)


def command(args, log):
    with log.open('w') as stream:
        subprocess.run([str(a) for a in args],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                       env={**os.environ,'PYTHONPATH':str(ROOT/'src')},check=True)


def trace(events):
    grouped = defaultdict(list)
    calls = [e for e in events if e['kind']=='model_response']
    assert calls and len(calls)==sum(e['kind']=='model_request' for e in events)
    assert not any(e['kind']=='model_error' for e in events)
    for e in calls:
        assert len(e['token_ids'])==e['usage']['completion_tokens'] and e['worker']['forward_calls']>0
        scope = tuple(e.get(k) for k in ['agent','video_id','global_round','decision_id','schema'])
        grouped[scope].append({k:e[k] for k in ['request_sha256','prompt_token_ids_sha256','token_ids','text','finish_reason']})
    return dict(grouped)


def forced(config, execution, saved, target):
    from models.execution import execution_scope
    from models.factory import ModelFactory
    from mvagent.batch import ExecutionConfig,prepare_model_pools
    from mvagent.configs import MVAgentConfig
    from mvagent.agents.global_agent.agent import GlobalAgent
    from mvagent.engine import MVAgentEngine
    cfg=MVAgentConfig.from_dict(config)
    _,failed=prepare_model_pools(config,ExecutionConfig(**execution));assert not failed
    client=ModelFactory.create_model(cfg.global_agent.model,cfg)
    runs=[]
    try:
        for repeat in range(2):
            source=saved['result']
            coordinator=GlobalAgent(video_ids=list(source['input']['videos']),
                question=source['input']['question'],model=client,video_metadata=source['video_metadata'])
            coordinator.memory.action_history=source['action_history']
            runtime=MVAgentEngine.__new__(MVAgentEngine);runtime._log=lambda message:None
            events=[];trajectory=[]
            with execution_scope(emit=events.append):
                answer,stop=runtime._request_terminal_answer(global_agent=coordinator,trajectory=trajectory,round_index=6)
            result=dict(answer=answer,stop_reason=stop,trajectory=trajectory,events=events)
            write(target/f'forced{repeat}.json',result)
            assert answer['answer'] and answer['status']=='forced_with_gaps'
            assert trajectory[-1]['output']['answer']==answer['answer']
            assert all(e['schema']=='global_answer' for e in events if e['kind']=='model_response')
            trace(events);runs.append(result)
        assert trace(runs[0]['events'])==trace(runs[1]['events'])
        assert runs[0]['answer']==runs[1]['answer'] and runs[0]['trajectory']==runs[1]['trajectory']
    finally:
        client.close()
    return runs


def main():
    import yaml
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();output=args.output.absolute()
    assert output.resolve().is_relative_to(Path('/runs').resolve())
    output.mkdir(parents=True,exist_ok=True)
    frozen=output/'frozen_repo'
    if ROOT!=frozen.resolve():
        assert not frozen.exists(), 'Use a new output directory'
        frozen.mkdir()
        for name in ['src','scripts','eval','configs','.git']:
            shutil.copytree(ROOT/name,frozen/name,ignore=shutil.ignore_patterns('__pycache__','.cache'))
        for name in ['requirements.txt','demo.py']:
            shutil.copy2(ROOT/name,frozen/name)
        (frozen/'prelaunch.py').write_text(Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"',repr(str(frozen/'src'))))
        os.execv(sys.executable,[sys.executable,str(frozen/'scripts'/Path(__file__).name),'--output',str(output)])
    state=dict(phase='preparing',started_at=datetime.now(timezone.utc).isoformat(),models={})
    write(output/'manifest.json',dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        cases=CASES,seed=0,accuracy_scoring=False,
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').rglob('*.py')}))
    try:
        for model,slug,sid in CASES:
            target=output/model;target.mkdir()
            config=yaml.safe_load((ROOT/f'configs/inference/modal_qwen35_{slug}_no_skill.yaml').read_text())
            name=next(iter(config['models']));config['runtime']['cache_dir']=str(target/'runtime_cache')
            execution=dict(question_workers=1,max_prepared_requests=1,question_retries=0,question_timeout_sec=7200,
                media_cache=dict(root=str(output/'media'),max_bytes=10*1024**3),
                model_pools={name:dict(replicas=[dict(gpus=[0],endpoint='http://127.0.0.1:8100/v1',max_inflight=1)])})
            cfg,ex=target/'config.yaml',target/'execution.yaml'
            cfg.write_text(yaml.safe_dump(config,sort_keys=False));ex.write_text(yaml.safe_dump(execution,sort_keys=False))
            write(target/'samples.json',[sid]);state.update(phase='loading',model=model);write(output/'progress.json',state)
            command([sys.executable,ROOT/'prelaunch.py','--replace',cfg,ex,name],target/'startup.log')
            passes=[]
            for repeat in range(2):
                state.update(phase='agent',repeat=repeat);write(output/'progress.json',state)
                command([sys.executable,'eval/agent_eval/run.py','--config',cfg,'--execution-config',ex,
                    '--dataset-root','/assets','--sample-ids-file',target/'samples.json',
                    '--output',target/f'repeat{repeat}','--inference-only'],target/f'repeat{repeat}.log')
                paths=list((target/f'repeat{repeat}/records').glob('*/*/result.json'));assert len(paths)==1
                row=json.loads(paths[0].read_text());assert row['status']=='ok' and row['prediction']
                trace(row['events'])
                if row['result']['answer']['status']=='answered':
                    assert not any(e.get('schema')=='global_answer' for e in row['events'])
                passes.append(row)
            assert trace(passes[0]['events'])==trace(passes[1]['events'])
            for key in ['input','video_metadata','video_reports','watch_results','action_history','trajectory','answer','stop_reason']:
                assert passes[0]['result'][key]==passes[1]['result'][key],key
            state.update(phase='terminal_answer');write(output/'progress.json',state)
            terminals=forced(config,execution,passes[0],target)
            events=[e for row in passes for e in row['events']]+[e for row in terminals for e in row['events']]
            report=dict(sample_id=sid,answer=passes[0]['prediction'],forced_answer=terminals[0]['answer'],
                trajectories=2,forced_runs=2,paired_calls=sum(e['kind']=='model_response' for e in passes[0]['events']+terminals[0]['events']),
                actual_calls=sum(e['kind']=='model_response' for e in events),
                structured_invalid=sum(e['kind']=='structured_invalid' for e in events),
                lengths=sum(e['kind']=='model_response' and e['finish_reason']=='length' for e in events),
                differences=0,model_errors=0)
            state['models'][model]=report;write(target/'report.json',report);write(output/'progress.json',state)
            print(json.dumps(dict(model=model,**report),ensure_ascii=False),flush=True)
        state.update(phase='completed',finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        import traceback
        state.update(phase='failed',error=repr(exc),traceback=traceback.format_exc())
        raise
    finally:
        write(output/'progress.json',state)


if __name__=='__main__':
    main()
