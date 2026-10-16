"""Score saved legacy rollouts using the same frozen scorer as the comparison panel."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

from run import ROOT, SIZE, SHARDS
FROZEN = Path('/runs/devbox/direct_answer_random_20261015/frozen_repo')
sys.path[:0] = [str(FROZEN/'scripts'), str(FROZEN/'src'), str(FROZEN/'eval/e2e_eval')]
import compare_direct_answer as core
from expand_direct_answer import interval
from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer


def mean_score(rows, arm):
    groups = defaultdict(list)
    for r in rows:
        groups[r['task']].append(r)
    weights = {k: 1 if v[0]['dataset']=='crossvid' else v[0]['task_population'] for k,v in groups.items()}
    return sum(weights[k]*sum(r['arms'][arm]['score'] for r in v)/len(v) for k,v in groups.items())/sum(weights.values())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partial',action='store_true')
    args=parser.parse_args()
    selection=core.read(ROOT/'selection.json')
    records=load_multibench_records('/assets',selection['closed_ids'])
    scorer,identity=build_official_scorer(records,{})
    history={r['sample_id']:r for r in core.read(Path('/runs/devbox/pro6000_protocol_effects_20261016')/f'{SIZE}_paired.json')}
    rows=[];errors=[];calls=0;lengths=0;cache_hits=0;bad_requests=0
    diagnostics=[];workers=set();length_stages=Counter()
    for job in core.read(ROOT/'jobs.json'):
        p=ROOT/SIZE/'records'/job['dataset']/job['sample_id']/'result.json'
        if not p.exists():continue
        saved=core.read(p)
        if saved['status']!='ok':errors.append({'sample_id':job['sample_id'],'error':saved['error']});continue
        assert saved['result']['input']==job['inputs'],job['sample_id']
        worker_ids=set();truncated=[];http_errors=[]
        with ThreadPoolExecutor(max_workers=8) as readers:
            events=list(readers.map(core.read,map(Path,saved['call_files'])))
        for name,event in zip(saved['call_files'],events):
            assert event['sample_id']==job['sample_id'],name
            if event['status']!=200:
                bad_requests+=1;http_errors.append(name);continue
            body,answer=event['translated'],event['response']
            assert body['temperature']==0 and body['seed']==0 and body['max_tokens']==2048
            assert body['chat_template_kwargs']=={'enable_thinking':False}
            assert body['messages']==event['request']['messages']
            assert body.get('structured_outputs',{}).get('json')==event['request'].get('response_format',{}).get('json_schema',{}).get('schema')
            assert 'grammar' not in body.get('structured_outputs',{})
            assert len(answer['choices'][0]['token_ids'])==answer['usage']['completion_tokens']
            assert len(answer['prompt_token_ids'])==answer['usage']['prompt_tokens']
            assert answer['audit']['worker']['forward_calls']>0
            worker_ids.add((answer['audit']['worker']['pid'],answer['audit']['worker']['gpu_uuid']))
            calls+=1;lengths+=answer['choices'][0]['finish_reason']=='length'
            cache_hits+=answer['usage']['prompt_tokens_details']['cached_tokens']
            if answer['choices'][0]['finish_reason']=='length':
                fields=','.join(body.get('structured_outputs',{}).get('json',{}).get('properties',{}))
                length_stages[fields]+=1;truncated.append(name)
        assert len(worker_ids)==1,job['sample_id']
        workers.update(worker_ids)
        def issues(value):
            if isinstance(value,dict):
                if value.get('status') in {'error','invalid','partial'} and value.get('error'):
                    yield str(value['error'])
                for child in value.values():yield from issues(child)
            elif isinstance(value,list):
                for child in value:yield from issues(child)
        diagnostics.append(dict(sample_id=job['sample_id'],seconds=saved['seconds'],
            answer_status=saved['result']['answer']['status'],prediction=saved['prediction'],
            calls=len(saved['call_files']),truncated_calls=truncated,http_errors=http_errors,
            trajectory_issues=sorted(set(issues(saved['result']['trajectory'])))))
        if job['task']=='CCQA':continue
        row=history[job['sample_id']]
        row['arms']['restored']=core.measure(saved['prediction'],records[job['sample_id']],scorer)
        row.update(seconds=saved['seconds'],answer_status=saved['result']['answer']['status'])
        rows.append(row)
    summary={'completed_closed':len(rows),'expected_closed':300,'actor_errors':errors,
             'calls':calls,'length_responses':lengths,'cached_tokens':cache_hits,
             'http_errors':bad_requests,'scorer':identity,'benchmarks':{}}
    summary.update(completed_total=len(diagnostics),workers=len(workers),
                   length_response_fields=dict(length_stages),
                   questions_with_trajectory_issues=sum(bool(r['trajectory_issues']) for r in diagnostics))
    assert cache_hits==0
    if not args.partial:
        assert len(rows)==300 and len(diagnostics)==330 and not errors,(len(rows),len(diagnostics),errors)
        assert len({gpu for pid,gpu in workers})==8*SHARDS
    for dataset in ['cvbench','mvu_eval','crossvid']:
        group=[r for r in rows if r['dataset']==dataset]
        if not group:continue
        stats={'n':len(group),'arms':{}}
        for arm in ['pro_agent','independent','direct','restored','e2e_after']:
            stats['arms'][arm]={'score':mean_score(group,arm),
               'format_errors':sum(not r['arms'][arm]['format_ok'] for r in group),
               'empty':sum(r['arms'][arm]['empty'] for r in group),
               'brace_only':sum(r['arms'][arm]['brace_only'] for r in group)}
        if not args.partial:
            stats['paired_ci']={arm:interval([dict(dataset=r['dataset'],task=r['task'],
                task_population=r['task_population'],old=r['arms'][arm],new=r['arms']['restored']) for r in group])
                for arm in ['pro_agent','direct','independent']}
        stats['mean_seconds']=sum(r['seconds'] for r in group)/len(group)
        stats['forced']=sum(r['answer_status']=='forced_with_gaps' for r in group)
        summary['benchmarks'][dataset]=stats
    core.write(ROOT/'analysis'/('partial.json' if args.partial else 'closed_summary.json'),summary)
    core.write(ROOT/'analysis'/('partial_paired.json' if args.partial else 'paired.json'),rows)
    core.write(ROOT/'analysis'/('partial_diagnostics.json' if args.partial else 'diagnostics.json'),diagnostics)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
