"""Audit original Video-RSI outputs without repairing model answers."""
import json
from pathlib import Path


def inspect(directory,card):
    from native_server import configure
    runtime=configure();directory=Path(directory)
    path=directory/'result.json'
    result=json.loads(path.read_text()) if path.exists() else {}
    status=result.get('status','missing_result')
    row=dict(answer=result.get('answer') or '',terminal='finish' if status=='answered' else status,
             calls=0,visual_calls=0,input_tokens=0,output_tokens=0,http_errors=0,truncated=0,
             tool_errors=[step['observation'] for step in result.get('trace',[])
                          if isinstance(step.get('observation'),dict) and step['observation'].get('error')],
             error=result.get('error'))
    requests=directory/'requests.jsonl'
    if requests.exists():
        with requests.open() as stream:
            for line in stream:
                try:call=json.loads(line)
                except json.JSONDecodeError:
                    row['http_errors']+=1;continue
                row['calls']+=1
                if call.get('error') or call.get('http_status')!=200:
                    row['http_errors']+=1;continue
                request,response=call['request'],call['response']
                assert request['temperature']==0 and request['max_tokens']==8192
                audit=runtime.token_audit(response,json.dumps(request).encode())
                assert audit['worker']['gpu_uuid']==card['worker']['gpu_uuid']
                assert audit['worker']['pid']==card['worker']['pid']
                assert response['usage']['prompt_tokens_details']['cached_tokens']==0
                row['input_tokens']+=response['usage']['prompt_tokens']
                row['output_tokens']+=response['usage']['completion_tokens']
                row['truncated']+=response['choices'][0]['finish_reason']=='length'
                row['visual_calls']+=any(isinstance(m.get('content'),list) and any(
                    p.get('type')=='image_url' for p in m['content']) for m in request['messages'])
    row['infrastructure_error']=status not in ('answered','invalid_decision') or row['http_errors']>0
    if status=='answered':assert isinstance(row['answer'],str) and row['answer'].strip()
    return row
