"""Read-only attribution diagnostics for the completed 4500-row panel; no inference."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from statistics import mean, median
import sys

BASE=Path('/runs/devbox/direct_answer_large_20261016')
REC=Path('/runs/devbox/direct_answer_large_recovery_20261017')
OUT=Path('/runs/devbox/direct_answer_large_diagnostics_20261017')
sys.path[:0]=[str(BASE/'frozen_repo/scripts'),str(BASE/'frozen_repo/src'),str(BASE/'frozen_repo/eval/e2e_eval')]
from compare_direct_answer import read,write,sha
spec=importlib.util.spec_from_file_location('completed_panel_analysis',REC/'code/analyze_direct_answer_large.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


def weights(rows):
    groups=defaultdict(list)
    for r in rows:groups[r['task']].append(r)
    populations={t:1 if rs[0]['dataset']=='crossvid' else rs[0]['task_population'] for t,rs in groups.items()}
    total=sum(populations.values());result={}
    for task,rs in groups.items():
        units=[r['points'] if task=='CCQA' else 1 for r in rs]
        for r,u in zip(rs,units):result[r['sample_id']]=populations[task]/total*u/sum(units)
    assert abs(sum(result.values())-1)<1e-10 and len(result)==len(rows)
    return result


def partition(r,reference):
    if r['task']=='CCQA':return 'open'
    before=r['arms'][reference]['format_ok'];after=r['arms']['direct']['format_ok']
    return {(False,True):'invalid_to_valid',(True,True):'both_valid',
            (True,False):'valid_to_invalid',(False,False):'both_invalid'}[before,after]


def compare(rows,reference):
    paired=[r for r in rows if r['arms'][reference]['score'] is not None]
    w=weights(paired)
    scores={a:sum(w[r['sample_id']]*r['arms'][a]['score'] for r in paired) for a in ['direct',reference]}
    for a,value in scores.items():assert abs(value-analysis.mean_score(paired,a))<1e-10
    robust={a:sum(w[r['sample_id']]*r['arms'][a].get('robust_score',r['arms'][a]['score']) for r in paired)
            for a in ['direct',reference]}
    contributions=defaultdict(float);counts=Counter();tasks={}
    for r in paired:
        group=partition(r,reference);counts[group]+=1
        contributions[group]+=w[r['sample_id']]*(r['arms']['direct']['score']-r['arms'][reference]['score'])
    assert abs(sum(contributions.values())-(scores['direct']-scores[reference]))<1e-10
    for task in sorted({r['task'] for r in paired}):
        selected=[r for r in paired if r['task']==task]
        contribution=sum(w[r['sample_id']]*(r['arms']['direct']['score']-r['arms'][reference]['score']) for r in selected)
        tasks[task]=dict(n=len(selected),contribution=contribution,
            direct=analysis.mean_score(selected,'direct'),reference=analysis.mean_score(selected,reference))
    return dict(n=len(paired),official=scores,robust=robust,
                contributions=dict(contributions),counts=dict(counts),tasks=tasks)


def self_check():
    rows=[dict(sample_id=str(i),dataset='crossvid',task=t,task_population=1,points=p,
               arms={'direct':dict(score=a,format_ok=True),'e2e':dict(score=b,format_ok=False)})
          for i,(t,p,a,b) in enumerate([('CCQA',1,1.,0.),('CCQA',3,0.,0.),('BU',1,.5,0.)])]
    result=compare(rows,'e2e')
    assert abs(result['official']['direct']-.375)<1e-10
    assert abs(result['contributions']['open']-.125)<1e-10
    assert abs(result['contributions']['invalid_to_valid']-.25)<1e-10
    print('Official-weight contribution accounting checks passed',flush=True)


def reliability(rows,arm):
    closed=[r for r in rows if r['task']!='CCQA' and r['arms'][arm]['score'] is not None]
    return dict(n=len(closed),format_errors=sum(not r['arms'][arm]['format_ok'] for r in closed),
                braces=sum(r['arms'][arm]['brace_only'] for r in closed),empty=sum(r['arms'][arm]['empty'] for r in closed))


def timing(rows):
    times=sorted(r['stats']['seconds'] for r in rows)
    return dict(n=len(rows),mean_seconds=mean(times),median_seconds=median(times),
        p95_seconds=times[int(.95*(len(times)-1))],p99_seconds=times[int(.99*(len(times)-1))],
        time_fraction_slowest_1pct=sum(times[-max(1,len(times)//100):])/sum(times),
        calls=sum(r['stats']['calls'] for r in rows),tokens=sum(r['stats']['tokens'] for r in rows),
        questions_with_truncation=sum(r['stats']['truncations']>0 for r in rows),
        questions_with_model_errors=sum(r['stats']['model_errors']>0 for r in rows),
        structured_invalid=sum(r['stats']['structured_invalid'] for r in rows),
        repairs=sum(r['stats']['repairs'] for r in rows))


def save_case(model,row,why):
    path=Path(row['path']);assert sha(path)==row['sha256']
    raw=read(path);result=raw['result']
    case=dict(model=model,sample_id=row['sample_id'],why_selected=why,path=str(path),sha256=row['sha256'],
        arms=row['arms'],stats=row['stats'],result_keys=list(result),input=result.get('input'),
        metadata=result.get('video_metadata'),answer=result.get('answer'),
        action_history=result.get('action_history'),video_reports=result.get('video_reports'),
        watch_results=result.get('watch_results'),trajectory=result.get('trajectory'),
        outputs=[{k:e.get(k) for k in ['agent','video_id','global_round','schema','finish_reason','text','usage']}
                 for e in raw['events'] if e['kind']=='model_response'])
    write(OUT/'cases'/model/(row['sample_id']+'.json'),case)
    return dict(sample_id=row['sample_id'],why_selected=why,arms=row['arms'],answer=result.get('answer'),
                action_counts=dict(Counter(t.get('action') for t in result.get('trajectory',[]))),stats=row['stats'])


def main():
    self_check();assert not (OUT/'summary.json').exists(),'Preserve the completed diagnostic'
    OUT.mkdir(exist_ok=True);shutil.copy2(__file__,OUT/'analysis_source.py')
    summary=read(REC/'analysis/summary.json')
    all_rows={m:read(REC/f'analysis/{m}_paired.json') for m in summary['models']}
    assert all(len(rs)==1500 for rs in all_rows.values())
    by_id={m:{r['sample_id']:r for r in rs} for m,rs in all_rows.items()}
    ccqa=sorted(s for s,r in next(iter(by_id.values())).items() if r['task']=='CCQA')
    common_loss=sorted(ccqa,key=lambda sid:(sum(rs[sid]['arms']['direct']['score']-rs[sid]['arms']['e2e']['score']
                                               for rs in by_id.values()),sid))
    common_cases=[common_loss[0],common_loss[-1]]
    report=dict(at=datetime.now(timezone.utc).isoformat(),new_inference=False,new_judge=False,
        source_summary_sha256=sha(REC/'analysis/summary.json'),common_ccqa_cases=common_cases,models={},
        limits='Descriptive gain accounting, not causal attribution. Robust extraction is diagnostic, not the official score. '
               'Cases selected by observed outcomes; forced/long trajectories are not randomized. No new model or Judge calls.')
    for model,rows in all_rows.items():
        model_report=dict(paired_sha256=sha(REC/f'analysis/{model}_paired.json'),
            reliability={a:reliability(rows,a) for a in ['direct','independent','e2e']},
            timing_all=timing(rows),timing_fresh=timing([r for r in rows if not r['reused']]),benchmarks={},cases=[])
        for ds in ['cvbench','mvu_eval','crossvid']:
            selected=[r for r in rows if r['dataset']==ds]
            entry={a:compare(selected,a) for a in ['e2e','independent']}
            for arm in ['e2e','independent']:
                assert abs(entry[arm]['official']['direct']-summary['models'][model]['benchmarks'][ds]['comparisons'][arm]['direct'])<1e-10
            entry['termination_groups']={}
            for status in sorted({r['answer_status'] for r in selected}):
                group=[r for r in selected if r['answer_status']==status]
                entry['termination_groups'][status]=dict(n=len(group),score=analysis.mean_score(group,'direct'),
                    mean_seconds=mean(r['stats']['seconds'] for r in group))
            model_report['benchmarks'][ds]=entry
        judged=[]
        for base in [BASE/'shard0',BASE/'shard1',REC]:
            path=base/model/'score/ccqa_scores_official_qwen3_30b_a3b.json'
            if path.exists():
                j=read(path);assert not j['failed_ids'];judged.extend(j['samples'])
        assert len(judged)==50 and len({str(r['id']) for r in judged})==50
        model_report['ccqa_judge_sample_keys']=list(judged[0])
        model_report['ccqa_answer_length']=dict(median=median(len(r['arms']['direct']['prediction']) for r in rows if r['task']=='CCQA'),
            maximum=max(len(r['arms']['direct']['prediction']) for r in rows if r['task']=='CCQA'))
        model_report['ccqa_zero']=sum(r['arms']['direct']['score']==0 for r in rows if r['task']=='CCQA')
        candidates={sid:'largest aggregate CCQA loss/win across models' for sid in common_cases}
        rescue=sorted(r['sample_id'] for r in rows if r['task']!='CCQA' and r['arms']['independent'].get('brace_only')
                      and r['arms']['direct']['score']==1)
        if rescue:candidates[rescue[0]]='old brace answer now correct'
        regress=sorted(r['sample_id'] for r in rows if r['dataset']=='mvu_eval'
            and r['arms']['independent']['score']==1 and r['arms']['direct']['score']==0
            and r['arms']['independent']['format_ok'] and r['arms']['direct']['format_ok'])
        if regress:candidates[regress[0]]='MVU both-format-valid regression against independent'
        longest=max(rows,key=lambda r:r['stats']['seconds']);candidates[longest['sample_id']]='longest current trajectory'
        for sid,reason in candidates.items():model_report['cases'].append(save_case(model,by_id[model][sid],reason))
        report['models'][model]=model_report
        write(OUT/f'{model}_diagnostics.json',model_report)
        print(model,json.dumps({k:model_report[k] for k in ['reliability','timing_all','timing_fresh','ccqa_zero','ccqa_answer_length']}) ,flush=True)
        for ds,b in model_report['benchmarks'].items():
            print(model,ds,json.dumps({a:{k:b[a][k] for k in ['official','robust','contributions','counts']} for a in ['e2e','independent']}),flush=True)
    write(OUT/'summary.json',report)
    print('Completed read-only diagnostics',str(OUT),flush=True)


if __name__=='__main__':
    if '--self-check' in sys.argv:self_check()
    else:main()
