"""Check the frozen call path, then smoke-test RSI's approved 600-second wait."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

BASE = Path('/runs/devbox/external_original_images_20261015')
ROOT = Path('/runs/devbox/external_call_audit_20261015')
SUPPORT = Path('/runs/devbox/external_methods_20261014/support')
ADAPTERS = Path(__file__).resolve().parents[2]


def save(name, value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))


def prepare():
    ROOT.mkdir(exist_ok=False)
    frozen = ROOT/'frozen_repo'
    shutil.copytree(BASE/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ADAPTERS, frozen/'eval/external_methods', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    save('source_manifest.json', {str(p.relative_to(frozen)):hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in frozen.rglob('*') if p.is_file()})
    env = dict(os.environ,PYTHONPATH=f'{SUPPORT}/deps:{frozen}/src')
    for command in ([sys.executable,'-m','compileall','-q','src','eval/agent_eval','eval/external_methods'],
                    [sys.executable,'eval/external_methods/test_rsi_timeout.py',str(frozen/'external_sources/Video-RSI')]):
        subprocess.run(command,cwd=frozen,env=env,check=True)
    # Check VAM's actual timeout factory; its client implementation is unchanged.
    check = '''import sys
sys.path.insert(0,sys.argv[1])
from vam.llm.openrouter import _read_timeout_env
assert _read_timeout_env("DASHSCOPE_REQUEST_TIMEOUT_S","SILICONFLOW_REQUEST_TIMEOUT_S","240")==240
assert _read_timeout_env("DASHSCOPE_CONNECT_TIMEOUT_S","SILICONFLOW_CONNECT_TIMEOUT_S","60")==60
print("VAM chat timeout remains 240 seconds, connect timeout 60")
'''
    subprocess.run([sys.executable,'-c',check,str(frozen/'external_sources/Visual-Agentic-Memory')],env=env,check=True)
    sys.path[:0]=[str(frozen/'src'),str(frozen/'eval/external_methods'),
                  str(frozen/'external_sources/Video-RSI/artifacts/final_harness')]
    from native_server import configure
    from tools import _bound_visual_response, _extract_json_object
    from transformers import AutoTokenizer
    from vllm import SamplingParams
    runtime = configure()
    weights = Path('/weights/Qwen3.5-35B-A3B')
    tokenizer = AutoTokenizer.from_pretrained(weights)
    card = json.loads((BASE/'servers/8100/manifest.json').read_text())
    assert all(hashlib.sha256((weights/name).read_bytes()).hexdigest()==digest
               for name,digest in card['weights_manifest']['files'].items())
    base_manifest = json.loads((BASE/'frozen_repo/source_manifest.json').read_text())['files']
    for name in ('src/models/vlm/local/sync_server.py','eval/external_methods/native_server.py',
                 'external_sources/Video-RSI/artifacts/final_harness/tools.py'):
        assert hashlib.sha256((frozen/name).read_bytes()).hexdigest()==base_manifest[name], name
    generations, end_reasons, lengths = Counter(), Counter(), []
    for file in (BASE/'servers').glob('*/requests.jsonl'):
        for line in file.open():
            row=json.loads(line)
            generations[json.dumps(row['generation'],sort_keys=True)]+=1
            end_reasons[row['finish_reason']]+=1
            lengths.append(row['usage']['prompt_tokens'])
    formats, missing_instruction, examples = Counter(), [], []
    for file in (BASE/'rsi').glob('*/result.json'):
        result=json.loads(file.read_text())
        frames={}
        for entry in result['service_trace']:
            if entry['service']=='sample_frames' and isinstance(entry.get('result'),list):
                frames.update({f['id']:f for f in entry['result']})
            if entry['service']!='qwen' or 'result' not in entry:
                continue
            prompt=entry['arguments']['prompt']
            if 'Return one JSON object using this format:' not in prompt:
                missing_instruction.append(result['sample_id'])
            parsed=_bound_visual_response(entry['result'],[frames[f] for f in entry['arguments']['frames']])
            obj=_extract_json_object(entry['result']['text'])
            reason=('no_json_object' if obj is None else 'missing_observations_list'
                    if not isinstance(obj.get('observations'),list) else parsed['status'])
            formats[reason]+=1
            if parsed['status']!='grounded' and len(examples)<4:
                examples.append(dict(sample=result['sample_id'],reason=reason,text=entry['result']['text'][:220]))
    assert not missing_instruction
    selected=[]
    for sid,index in [('cvbench:722',5),('cvbench:764',1)]:
        path=BASE/'rsi'/sid.replace(':','_')/'requests.jsonl'
        with path.open() as stream:
            row=next(json.loads(line) for i,line in enumerate(stream) if i==index)
        response=row['response']
        runtime.token_audit(response,json.dumps(row['request']).encode())
        prompt=tokenizer.decode(response['prompt_token_ids'],skip_special_tokens=False)
        output=tokenizer.decode(response['choices'][0]['token_ids'],skip_special_tokens=True)
        assert output==response['choices'][0]['message']['content']
        assert 'Return one JSON object using this format:' in prompt
        rendered=tokenizer.apply_chat_template(row['request']['messages'],tokenize=False,
                                               add_generation_prompt=True,enable_thinking=False)
        suffix=rendered[rendered.rfind('<|im_start|>assistant'):]
        assert prompt.endswith(suffix) and '</think>' in suffix and '<think>' in suffix
        selected.append(dict(sample=sid,call=index,prompt_suffix=suffix,
            output_head=output[:200],output_tokens=response['usage']['completion_tokens'],
            finish_reason=response['choices'][0]['finish_reason']))
        save(sid.replace(':','_')+'_request.json',row)
    defaults=SamplingParams(temperature=0,top_p=1,max_tokens=8192,seed=0)
    summary=dict(rsi_http_seconds=600,vam_http_seconds=240,
        generations=dict(generations),finish_reasons=dict(end_reasons),max_input_tokens=max(lengths),
        model_context_limit=card['execution']['config']['max_model_len'],
        sampling_defaults={name:getattr(defaults,name) for name in
            ('top_k','min_p','presence_penalty','frequency_penalty','repetition_penalty','ignore_eos','stop','stop_token_ids')},
        tokenizer_eos_token_id=tokenizer.eos_token_id, tokenizer_eos_token=tokenizer.eos_token,
        generation_config=json.loads((weights/'generation_config.json').read_text()),
        visual_formats=dict(formats),missing_json_instruction=missing_instruction,
        examples=examples,template_checks=selected)
    save('audit.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


def check_ends():
    audit=json.loads((ROOT/'audit.json').read_text())
    end_ids=set(audit['generation_config']['eos_token_id'])
    counts, affected = Counter(), []
    for path in (BASE/'servers').glob('*/requests.jsonl'):
        for line in path.open():
            row=json.loads(line)
            found=[t for t in row['token_ids'] if t in end_ids]
            counts[(row['finish_reason'],bool(found))]+=1
            if row['finish_reason']=='length' and found:
                affected.append(dict(id=row['id'],end_ids=found))
    result=dict(eos_ids=sorted(end_ids),counts={str(k):v for k,v in counts.items()},
                capped_responses_with_eos=affected)
    save('end_token_audit.json',result)
    print(json.dumps(result),flush=True)
    assert not affected, 'A capped response contained a model end token'


def smoke():
    frozen=ROOT/'frozen_repo'
    scripts=frozen/'eval/external_methods'
    env=dict(os.environ,PYTHONPATH=f'{SUPPORT}/deps:{frozen}/src')
    sys.path[:0]=[str(scripts),str(frozen/'src'),str(frozen/'external_sources/Video-RSI')]
    from native_server import configure
    runtime=configure()
    with (ROOT/'server.log').open('w') as log:
        proc=subprocess.Popen([sys.executable,str(scripts/'native_server.py'),'--worker',
            '--model','/weights/Qwen3.5-35B-A3B','--port','8100','--log-dir',str(ROOT/'server')],
            env={**env,**runtime.ENVIRONMENT,'CUDA_VISIBLE_DEVICES':'0'},stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.monotonic()+1200
        while True:
            if proc.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('Model did not start; inspect server.log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8100/v1/models',timeout=2) as response:
                    card=json.load(response)['data'][0]
                break
            except OSError:
                time.sleep(5)
        from solver_full_workspace.engine.services import PinnedProvider
        from transport_audit import audit_urllib
        from unittest.mock import patch
        old=json.loads((ROOT/'cvbench_722_request.json').read_text())
        config=json.loads((frozen/'external_sources/Video-RSI/config.example.json').read_text())['services']
        config['timeout_seconds']=600
        config['qwen']['request_model']=card['id']
        provider=object.__new__(PinnedProvider)
        provider.config,provider.meter,provider.key,provider.endpoint=config,None,'local-no-auth','http://127.0.0.1:8100/v1'
        audit_urllib(ROOT/'replay_requests.jsonl')
        original=urllib.request.urlopen
        observed=[]
        def request(req,*args,**kwargs):
            observed.append(kwargs.get('timeout'))
            return original(req,*args,**kwargs)
        with patch('urllib.request.urlopen',request):
            response=provider.chat('qwen',old['request']['messages'])
        assert observed==[600]
        actual=json.loads((ROOT/'replay_requests.jsonl').read_text())
        runtime.token_audit(response,json.dumps(actual['request']).encode())
        replay=dict(timeout=observed[0],request_equal=actual['request']==old['request'],
            input_equal=response['audit']['input_sha256']==old['response']['audit']['input_sha256'],
            tokens_equal=response['choices'][0]['token_ids']==old['response']['choices'][0]['token_ids'],
            text=response['choices'][0]['message']['content'],seconds=actual['seconds'])
        save('replay.json',replay)
        assert replay['request_equal'] and replay['input_equal'] and replay['tokens_equal'], replay
        client_env=dict(env,PYTHONPATH=f'{SUPPORT}/upstream_clients_20261015/rsi:'+env['PYTHONPATH'])
        with (ROOT/'rsi_smoke.log').open('w') as log:
            subprocess.run([sys.executable,str(scripts/'rsi.py'),'--source',str(frozen/'external_sources/Video-RSI'),
                '--item',str(BASE/'prepared/items/cvbench_764.json'),'--output',str(ROOT/'rsi_smoke'),
                '--endpoint','http://127.0.0.1:8100/v1'],env=client_env,stdout=log,stderr=subprocess.STDOUT,
                timeout=1800,check=True)
        result=json.loads((ROOT/'rsi_smoke/result.json').read_text())
        effective=json.loads((ROOT/'rsi_smoke/effective_config.json').read_text())
        assert effective['config']['services']['timeout_seconds']==600
        calls=[]
        for line in (ROOT/'rsi_smoke/requests.jsonl').open():
            row=json.loads(line)
            runtime.token_audit(row['response'],json.dumps(row['request']).encode())
            calls.append(row['response']['usage'])
        save('smoke.json',dict(sample=result['sample_id'],answer=result['answer'],seconds=result['seconds'],
            calls=len(calls),output_tokens=sum(c['completion_tokens'] for c in calls),
            timeout=effective['config']['services']['timeout_seconds'],replay=replay))
        print((ROOT/'smoke.json').read_text(),flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__=='__main__':
    {'prepare':prepare,'smoke':smoke,'check_ends':check_ends}[sys.argv[1]]()
