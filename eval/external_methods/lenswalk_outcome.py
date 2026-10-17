"""Audit saved calls and distinguish terminal answers from unfinished tool plans."""
import json
from pathlib import Path


def inspect(directory, card):
    from lenswalk_server import configure
    directory=Path(directory)
    result=json.loads((directory/'result.json').read_text()) if (directory/'result.json').exists() else {}
    row=dict(answer=result.get('answer',''),terminal='missing_result',calls=0,visual_calls=0,
             input_tokens=0,output_tokens=0,http_errors=0,truncated=0,tool_errors=result.get('tool_errors',[]))
    path=directory/'requests.jsonl'
    runtime=configure()
    if path.exists():
        with path.open() as stream:
            for line in stream:
                try: call=json.loads(line)
                except json.JSONDecodeError:
                    row['http_errors']+=1
                    continue
                row['calls']+=1
                response=call.get('response') or {}
                if call['error'] or call['http_status']!=200:
                    row['http_errors']+=1
                    continue
                wire=json.dumps(call['request'],ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
                audit=runtime.token_audit(response,wire)
                assert audit['worker']['gpu_uuid']==card['worker']['gpu_uuid']
                assert audit['worker']['pid']==card['worker']['pid']
                assert response['usage']['prompt_tokens_details']['cached_tokens']==0
                row['input_tokens']+=response['usage']['prompt_tokens']
                row['output_tokens']+=response['usage']['completion_tokens']
                row['truncated']+=response['choices'][0]['finish_reason']=='length'
                row['visual_calls']+=any(isinstance(m.get('content'),list) and any(
                    p.get('type')=='image_url' for p in m['content']) for m in call['request']['messages'])
    if result:
        row['terminal']='empty_answer'
        if result.get('finished_with_tool'):
            row['terminal']='finish'
        elif result.get('answer'):
            transcript=json.loads(Path(result['transcript']).read_text().splitlines()[0])
            assert transcript['answer']==result['answer'], 'Adapter changed the upstream answer'
            last=next((m for m in reversed(transcript['chat_history']) if m['role']!='tool'), {})
            # Upstream retains earlier output_text when subsequent turns only call tools.
            row['terminal']=('natural_text' if last.get('role')=='assistant'
                and last.get('content')==result['answer'] and not last.get('tool_calls')
                else 'unfinished_tool_plan')
    row['infrastructure_error']=not result or row['http_errors']>0
    return row
