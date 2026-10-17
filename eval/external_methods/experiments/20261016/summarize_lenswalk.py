"""Summarize saved integration evidence without generating or judging new answers."""
import json
from pathlib import Path
import statistics
import sys

root=Path(sys.argv[1])
progress=json.loads((root/'progress.json').read_text())
assert progress['phase'] in ('completed','completed_with_errors')
scores=json.loads((root/'lenswalk/scores.json').read_text())
by_id={r['sample_id']:r['score'] for r in scores['rows']}
server=[json.loads(line) for line in (root/'server/requests.jsonl').open()]
server_by_id={r['id']:r for r in server}
rows=[]
for execution in progress['samples']:
    directory=root/'lenswalk'/execution['sample_id'].replace(':','_')
    result=json.loads((directory/'result.json').read_text()) if (directory/'result.json').exists() else {}
    requests=visual=images=failures=prompt_tokens=output_tokens=0
    for line in (directory/'requests.jsonl').open():
        call=json.loads(line); requests+=1
        count=sum(1 for message in call['request']['messages']
            if isinstance(message.get('content'),list) for part in message['content']
            if part.get('type')=='image_url')
        images+=count; visual+=bool(count)
        failures+=bool(call['error'] or call['http_status']!=200)
        usage=(call.get('response') or {}).get('usage',{})
        prompt_tokens+=usage.get('prompt_tokens',0); output_tokens+=usage.get('completion_tokens',0)
        if call['http_status']==200:
            actual=server_by_id[call['response']['id']]['generation']
            assert actual['temperature']==call['request'].get('temperature',1.0)
            assert actual['top_p']==call['request'].get('top_p',1.0)
            assert 'max_tokens' not in call['request'] and 'max_completion_tokens' not in call['request']
            assert actual['max_tokens']==131072-usage['prompt_tokens']
    row=dict(execution,finished_with_tool=result.get('finished_with_tool'),
        visual_tools=result.get('visual_tool_calls'),tool_errors=result.get('tool_errors',[]),
        requests=requests,visual_requests=visual,image_inputs=images,http_errors=failures,
        prompt_tokens=prompt_tokens,output_tokens=output_tokens,score=by_id.get(execution['sample_id']))
    row['terminal_kind']='finish' if result.get('finished_with_tool') else 'failed'
    if execution['success']:
        assert visual>0 and isinstance(result['answer'],str) and result['answer'].strip()
        transcript=json.loads(Path(result['transcript']).read_text().splitlines()[0])
        assert transcript['answer']==result['answer']
        if not result['finished_with_tool']:
            final=next(m for m in reversed(transcript['chat_history']) if m['role']=='assistant')
            row['natural_answer_matches_last_response']=final['content']==result['answer']
            row['terminal_kind']='unfinished_tool_plan' if final.get('tool_calls') else 'natural_text'
    rows.append(row)
assert all(r['usage']['prompt_tokens_details']['cached_tokens']==0 for r in server)
assert all(r['generation']['seed']==0 for r in server)
assert len({r['worker']['gpu_uuid'] for r in server})==1
assert len(server)==json.loads((root/'audit.json').read_text())['responses']
elapsed=[r['seconds'] for r in rows]
summary=dict(samples=rows,process_successes=sum(r['success'] for r in rows),
    completed_answers=sum(r['terminal_kind'] in ('finish','natural_text') for r in rows),
    unfinished_tool_plans=sum(r['terminal_kind']=='unfinished_tool_plan' for r in rows),
    finished_with_tool=sum(bool(r['finished_with_tool']) for r in rows),
    http_errors=sum(r['http_errors'] for r in rows),tool_errors=sum(len(r['tool_errors']) for r in rows),
    audited_responses=len(server),truncated_responses=sum(r['finish_reason']=='length' for r in server),
    startup_seconds=progress['startup_seconds'],total_question_seconds=sum(elapsed),
    mean_question_seconds=statistics.mean(elapsed),median_question_seconds=statistics.median(elapsed),
    elapsed_seconds=progress['elapsed_seconds'],pending_judge=scores['pending_judge'],
    limitation='Six development integration cases; not full benchmark accuracy or a paper reproduction')
(root/'integration_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
