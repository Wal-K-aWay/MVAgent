"""Frozen five-arm action/parameter screening with retained historical controls."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_original_question_watch as watch
from run_overnight_watch import read, save, sha

REPO = Path(__file__).resolve().parents[2]
PARENT = REPO / 'outputs/analysis/20260922_routing_concise'
SEED = 20260923
ARMS = {
    'C': ('global_agent', 'constraint_parameters_global.md', 'C'),
    'OG': ('global_agent', 'ordering_states_global.md', 'O'),
    'OV': ('video_agent', 'endpoint_states_video.md', 'O'),
    'T': ('video_agent', 'refine_localization_video.md', 'T'),
    'V': ('global_agent', 'conflict_verification_global.md', 'V'),
}
BINARY_CELLS = {'agent_only', 'both_correct', 'e2e_only', 'both_wrong'}
CONFLICT = re.compile(r'\b(?:conflict\w*|contradict\w*|inconsistent|ambiguous|unclear|uncertain|cannot determine)\b', re.I)
C_BUCKETS = {'crossvid/CC', 'crossvid/PI', 'mvu_eval/Comparison', 'mvu_eval/KIR',
             'mvu_eval/RAG', 'cvbench/Joint-video Spatial Navigating',
             'cvbench/Video Difference Caption', 'cvbench/Multi-view Scene Understanding'}


def score(raw):
    if raw.get('status') != 'ok' or raw.get('scoring_status') != 'ok':
        return None
    if str(raw.get('sample_id', '')).startswith('crossvid:FSA:'):
        value = raw.get('score')
    else:
        value = raw.get('correct')
        if not isinstance(value, bool):
            return None
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid score')
    return value


def draw(rows, n, used, group_counts, rng):
    """Balance task/outcome strata; prefer less represented known media groups."""
    pools = defaultdict(list)
    for row in sorted(rows, key=lambda r: r['sample_id']):
        if row['sample_id'] not in used:
            pools[(row['bucket'], row['selection_stratum'])].append(row)
    if sum(map(len, pools.values())) < n:
        raise ValueError(f'Insufficient candidates for {n}: {sum(map(len, pools.values()))}')
    for values in pools.values():
        rng.shuffle(values)
    selected = []
    while len(selected) < n:
        for key in sorted(pools):
            if not pools[key] or len(selected) == n:
                continue
            index = min(range(len(pools[key])), key=lambda i: group_counts[pools[key][i]['group_id']])
            row = pools[key].pop(index)
            selected.append(row)
            used.add(row['sample_id'])
            group_counts[row['group_id']] += 1
    return selected


def audit(raw):
    result = raw.get('result') or {}
    actions = result.get('action_history', [])
    counts = Counter()
    counts['global_evidence_actions'] = sum(a.get('action') in {'analyze_videos', 'watch_videos'} for a in actions)
    counts['global_multiple_evidence'] = int(counts['global_evidence_actions'] > 1)
    counts['successful_watch'] = len(result.get('watch_results', []))
    for w in result.get('watch_results', []):
        counts['watch_fps_below_1'] += w.get('fps', 100) < 1
        counts['watch_with_partial_clip'] += any(v['time_range'][0] > .011 or
            abs(v['time_range'][1] - result['video_metadata'][v['video_id']]['duration_sec']) > .011 for v in w['videos'])
    for t in result.get('trajectory', []):
        if t.get('agent') != 'VideoAgent' or t.get('action') != 'run':
            continue
        counts['video_requests'] += 1
        observations = [s for s in t.get('output', {}).get('steps', []) if s.get('action') == 'observe']
        successful = [s for s in observations if s.get('result', {}).get('status') == 'ok'
                      and s.get('result', {}).get('observations')]
        counts['observe_attempts'] += len(observations)
        counts['successful_observe_actions'] += len(successful)
        counts['video_requests_multiple_observe'] += len(successful) > 1
        previous = None
        for s in successful:
            p = s.get('parameters', {})
            ranges = p.get('where', [])
            width = sum(b-a for a,b in ranges)
            counts['observe_multiple_ranges'] += len(ranges) > 1
            duration = result.get('video_metadata', {}).get(t.get('video_id'), {}).get('duration_sec')
            if duration and len(ranges) >= 2:
                counts['endpoint_observe'] += abs(ranges[0][0]) <= .011 and abs(ranges[-1][1]-duration) <= .011
            if previous is not None:
                counts['later_observe_narrower'] += width < previous - .011
            previous = width
            for o in s.get('result', {}).get('observations', []):
                counts['retained_observations'] += 1
                counts['effective_fps_reduced'] += o.get('fps', 0) < p.get('fps', 0) - 1e-6
    return dict(first_action=actions[0].get('action') if actions else None, counts=dict(counts))


def extract(raw, path):
    from skill_evolution.infra.evaluation import execution_metrics
    return dict(score=score(raw), prediction=raw.get('prediction'), artifact=str(path), audit=audit(raw),
                health=execution_metrics(SimpleNamespace(artifact=raw, status=raw.get('status'))))


def prepare(root):
    import yaml
    sys.path.insert(0, str(REPO/'src'))
    from skill_evolution.infra.benchmarks import load_multibench_records
    from skill_evolution.infra.data import group_by_media
    from skill_evolution.infra.store import tree_hash
    if root.exists() and any(root.iterdir()):
        raise ValueError('Fresh output root required.')
    if read(PARENT/'status.json')['stage'] != 'completed':
        raise ValueError('Parent must be complete.')
    parent_protocol = read(PARENT/'protocol.json')
    if tree_hash(PARENT/'frozen/src') != parent_protocol['source_sha256']:
        raise ValueError('Parent runtime changed.')
    for name in ['B0.yaml', 'execution.yaml']:
        if sha(PARENT/name) != parent_protocol['immutable_sha256'][name]:
            raise ValueError('Parent configuration changed.')
    root.mkdir(parents=True, exist_ok=True)
    census_path = REPO/'outputs/analysis/20260921_full_baseline/full35b_trajectories.json'
    feature_path = REPO/'outputs/analysis/20260919_crossvid_lite2500/all_features.json'
    census = {s:r for s,r in read(census_path).items() if r['cell'] in BINARY_CELLS or r['task'] == 'FSA'}
    records = load_multibench_records(watch.DATA, sorted(census))
    features = {r['sample_id']:r for r in read(feature_path)}
    media = {s:(features[s]['source_keys'] if s.startswith('crossvid:') else
                ['path:'+p for p in records[s].sample.videos.values()]) for s in census}
    groups = group_by_media(media)
    rows, conflict_hits = [], {}
    for sid, r in census.items():
        fsa = r['task'] == 'FSA'
        level = 'zero' if r['agent_score'] == 0 else 'low' if r['agent_score'] < .5 else 'mid' if r['agent_score'] < .8 else 'high'
        rows.append(dict(sample_id=sid, bucket=r['dataset']+'/'+r['task'], dataset=r['dataset'],
            cell=r['cell'], is_fsa=fsa, selection_stratum=level if fsa else r['cell'],
            group_id=groups[sid], historical_score=r['agent_score'], artifact=r['artifact'], artifact_sha256=r['artifact_sha256']))
        if not fsa:
            raw = read(r['artifact'])
            reasons = '\n'.join(str(t.get('output', {}).get('reason', '')) for t in raw.get('result',{}).get('trajectory',[])
                if t.get('agent') == 'GlobalAgent' and t.get('action') == 'decide')
            hits = sorted(set(m.group(0).lower() for m in CONFLICT.finditer(reasons)))
            if hits:
                conflict_hits[sid] = hits
    rng = random.Random(SEED)
    used, group_counts = set(), Counter()
    pools = {'C':[r for r in rows if r['bucket'] in C_BUCKETS],
             'O':[r for r in rows if r['bucket'] == 'crossvid/PSS'],
             'T':[r for r in rows if r['is_fsa']],
             'V':[r for r in rows if r['sample_id'] in conflict_hits]}
    selection = {name:draw(values,200,used,group_counts,rng) for name,values in pools.items()}
    protection = draw([r for r in rows if not r['is_fsa'] and r['historical_score'] == 1],300,used,group_counts,rng)
    protection += draw([r for r in rows if r['is_fsa'] and r['historical_score'] >= .5],100,used,group_counts,rng)
    panel = [dict(r, scope=name) for name,values in selection.items() for r in values] + [dict(r,scope='protection') for r in protection]
    assert len(panel) == len({r['sample_id'] for r in panel}) == 1200
    sources = {str(p):sha(p) for p in [census_path, feature_path, PARENT/'protocol.json']}
    historical = {}
    for row in panel:
        sid = row['sample_id']; path=Path(row['artifact'])
        if sha(path) != row['artifact_sha256']:
            raise ValueError('Historical record changed: '+sid)
        raw=read(path)
        if score(raw) is None or abs(score(raw)-row['historical_score']) > 1e-12:
            raise ValueError('Historical score mismatch: '+sid)
        if raw['result']['input']['question'] != records[sid].sample.question:
            raise ValueError('Historical question mismatch: '+sid)
        historical[sid]=extract(raw,path)
        sources[str(path)] = row['artifact_sha256']
        source=Path(records[sid].source_record)
        if str(source) not in sources:
            sources[str(source)]=sha(source)
    save(root/'historical_baseline.json',historical)
    save(root/'panel.json',dict(samples=panel, seed=SEED, method='Task/outcome balanced, prefer less represented known media groups. Non-probability development panel; no population weights or source isolation claim.'))
    save(root/'selection_audit.json',dict(candidate_counts={k:len(v) for k,v in pools.items()}, conflict_regex=CONFLICT.pattern,
        conflict_proxy_hits={r['sample_id']:conflict_hits[r['sample_id']] for r in selection['V']},
        scopes={k:dict(n=len(v),groups=len({r['group_id'] for r in v}),strata=dict(Counter(r['selection_stratum'] for r in v))) for k,v in dict(selection,protection=protection).items()},
        note='Conflict words are a sampling proxy, not verified contradictory evidence. Correct and incorrect cases included. All labels/GT remain offline.'))
    save(root/'questions.json',{r['sample_id']:records[r['sample_id']].sample.question for r in panel})
    paths=sorted({p for r in panel for p in records[r['sample_id']].sample.videos.values()})
    save(root/'media_identity.json',[dict(path=p,size=Path(p).stat().st_size,mtime_ns=Path(p).stat().st_mtime_ns) for p in paths])
    shutil.copytree(PARENT/'frozen',root/'frozen',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(PARENT/'execution.yaml',root/'execution.yaml')
    shutil.copy2(PARENT/'B0.yaml',root/'B0.yaml')
    base=yaml.safe_load((root/'B0.yaml').read_text())
    stages=[];stage_ids={};arm_ids={};skill_specs={}
    for arm,(role,file,scope) in ARMS.items():
        ids=[r['sample_id'] for pair in zip(selection[scope],protection[:200],protection[200:]) for r in pair]
        arm_ids[arm]=ids
        smoke=[r['sample_id'] for r in selection[scope][:16]]+[r['sample_id'] for r in protection[:6]+protection[-2:]]
        save(root/f'preflight_{arm}_ids.json',smoke)
        stage='preflight_'+arm;stages.append(stage);stage_ids[stage]=f'preflight_{arm}_ids.json'
        path=root/f'{arm}.md';shutil.copy2(REPO/'analysis/skill_evolution/skills'/file,path)
        cfg=deepcopy(base)
        cfg['agents'][role]['skill']=dict(enabled=True,path=str(path),sha256=sha(path))
        (root/f'{arm}.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
        skill_specs[arm]=dict(role=role,path=path.name,sha256=sha(path),scope=scope)
    for block in range(6):
        for arm in ARMS:
            stage=f'b{block:03}_{arm}';file=f'blocks/{stage}.json'
            save(root/file,arm_ids[arm][block*100:(block+1)*100]);stages.append(stage);stage_ids[stage]=file
    for file in ['run_action_parameter_validation.py','run_original_question_watch.py','run_overnight_watch.py']:
        shutil.copy2(REPO/'scripts/analysis'/file,root/file)
    save(root/'protocol.json',dict(repo=str(REPO),checkpoint=watch.CHECKPOINT,
        controller_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        n=1200,total_rollouts=3000,arms=list(ARMS),arm_ids=arm_ids,skill_specs=skill_specs,stages=stages,stage_ids=stage_ids,
        source_sha256=tree_hash(root/'frozen/src'),historical_source_sha256=sources,
        immutable_sha256={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()},
        primary='Per-arm target-task scores and shared protection, FSA IoU separate from binary accuracy. No pooled official total or automated promotion. Per-scope99% source-cluster intervals are exploratory, not a guarantee across all slices.',
        baseline='Verified retained historical B0, no new B0/WQ inference, no paid API. Historical rather than contemporaneous control.',
        preflight='Top-level health and exact Skill in correct role requests; OV must exercise endpoints, T repeated observe, V extra evidence. These are execution proxies, not semantic correctness. No score-based scheduling.',
        stopping='All five preflights before six blocks per arm. Fixed3000 new main rollouts; no score-based stopping; no automatic combination/deployment.',
        scope='Mechanism-enriched development panel, no independent Test claim. Frozen Runtime; exactly one role Skill per arm. No node replay or state restoration.'))
    print(json.dumps(dict(unique_questions=1200,main_rollouts=3000,preflight_rollouts=120,arms=list(ARMS)),ensure_ascii=False),flush=True)


def preflight(root,arm,out):
    spec=read(root/'protocol.json')['skill_specs'][arm]
    text=(root/spec['path']).read_text().strip()
    role='GlobalAgent' if spec['role']=='global_agent' else 'VideoAgent'
    requests=0;counts=Counter();records=[]
    for path in (out/'records').glob('*/*/result.json'):
        raw=read(path);a=audit(raw);counts.update(a['counts']);records.append(dict(sample_id=raw['sample_id'],**a))
        for event in raw.get('events',[]):
            if event.get('kind')=='structured_request' and event.get('agent')==role:
                requests += any(isinstance(m.get('content'),str) and text in m['content'] for m in event.get('messages',[]))
    summary=read(out/'summary.json')
    gate=dict(role=role,skill_request_count=requests,summary=summary,behavior_counts=dict(counts),records=records,
        note='Multiple observe/partial clips are execution proxies; conflict recognition and instruction fidelity need semantic audit.')
    save(root/f'preflight_{arm}_audit.json',gate)
    if summary['total_errors'] or not summary['score_complete'] or not requests:
        raise RuntimeError(f'{arm} preflight failed top-level health or exact role Skill loading.')
    required = {'OV':'endpoint_observe', 'T':'video_requests_multiple_observe', 'V':'global_multiple_evidence'}.get(arm)
    if required and not counts[required]:
        raise RuntimeError(f'{arm} preflight did not exercise {required}; inspect before bulk inference.')


def paired(ids,baseline,candidate,meta):
    valid=[s for s in ids if s in candidate and candidate[s]['score'] is not None]
    complete=len(valid)==len(ids) and bool(ids)
    delta={s:candidate[s]['score']-baseline[s]['score'] for s in valid}
    interval=None
    if complete:
        import numpy as np
        groups=defaultdict(lambda:[0.,0.])
        for s,d in delta.items():
            groups[meta[s]['group_id']][0]+=d;groups[meta[s]['group_id']][1]+=1
        if len(groups)>1:
            values=np.array(list(groups.values()));n=len(values)
            draws=np.random.default_rng(SEED).multinomial(n,np.ones(n)/n,size=4000)
            x=100*(draws@values[:,0])/(draws@values[:,1])
            interval=[float(v) for v in np.quantile(x,[.005,.995])]
    return dict(expected=len(ids),scored=len(valid),missing=len(ids)-len(valid),
        improved=[s for s,d in delta.items() if d>1e-12],regressed=[s for s,d in delta.items() if d < -1e-12],
        baseline_mean=100*sum(baseline[s]['score'] for s in valid)/len(valid) if complete else None,
        candidate_mean=100*sum(candidate[s]['score'] for s in valid)/len(valid) if complete else None,
        delta_pp=100*sum(delta.values())/len(valid) if complete else None,cluster_99_interval_pp=interval)


def summarize(root):
    sys.path.insert(0,str(root/'frozen/src'))
    protocol=read(root/'protocol.json');meta={r['sample_id']:r for r in read(root/'panel.json')['samples']}
    baseline=read(root/'historical_baseline.json');results={};lines=['# Action与参数分项验证','历史B0直接复用；不合并FSA与闭式分数；非总体收益估计。','',
        '|臂/范围|已评分/计划|提高/降低|历史均分|新均分|差值pp|','|---|---:|---:|---:|---:|---:|']
    for arm in protocol['arms']:
        rows={};completed=[];partial={}
        for stage in protocol['stages']:
            if stage.startswith('preflight') or stage.split('_')[-1]!=arm:continue
            ids=read(root/protocol['stage_ids'][stage]);out=root/'runs'/stage;block={}
            for path in (out/'records').glob('*/*/result.json'):
                raw=read(path);sid=raw['sample_id']
                if sid not in ids or sid in block:raise ValueError('Unexpected/duplicate record')
                block[sid]=extract(raw,path)
            if len(block)==len(ids) and (out/'summary.json').exists():rows.update(block);completed.append(stage)
            elif block:partial[stage]=len(block)
        ids=protocol['arm_ids'][arm];scopes={}
        for label,predicate in [('target_binary',lambda r:r['scope']!='protection' and not r['is_fsa']),
             ('target_fsa',lambda r:r['scope']!='protection' and r['is_fsa']),
             ('protection_binary',lambda r:r['scope']=='protection' and not r['is_fsa']),
             ('protection_fsa',lambda r:r['scope']=='protection' and r['is_fsa'])]:
            group=[s for s in ids if predicate(meta[s])]
            if group:scopes[label]=paired(group,baseline,rows,meta)
        for bucket in sorted({meta[s]['bucket'] for s in ids}):
            scopes['task/'+bucket]=paired([s for s in ids if meta[s]['bucket']==bucket],baseline,rows,meta)
        counts=Counter();health=Counter()
        for r in rows.values():
            counts.update(r['audit']['counts'])
            health.update({k:r['health'].get(k,0) for k in ['fatal','invalid','model_errors','failed_video_requests','model_calls','total_tokens']})
        results[arm]=dict(rows=rows,completed_blocks=completed,partial_blocks=partial,paired=scopes,
            first_actions=dict(Counter(r['audit']['first_action'] for r in rows.values())),behavior=dict(counts),health=dict(health))
        for name,v in scopes.items():
            if name.startswith('task/'):continue
            fmt=lambda x:'—' if x is None else f'{x:.3f}'
            lines.append(f"|{arm}/{name}|{v['scored']}/{v['expected']}|{len(v['improved'])}/{len(v['regressed'])}|{fmt(v['baseline_mean'])}|{fmt(v['candidate_mean'])}|{fmt(v['delta_pp'])}|")
    save(root/'comparison.json',dict(arms=results,note='Enriched development panel; FSA continuous IoU. Missing/unscored never zero; only complete planned scopes get mean scores.99% cluster intervals exploratory, not universal familywise guarantee across all slices.'))
    lines+=['','评分完整才输出范围均分。FSA提高/降低不是闭式修复/损失；分任务、实际取证、健康及近似99%区间见comparison.json。','不自动部署，不按中途准确率改队列。']
    (root/'report.md').write_text('\n'.join(lines)+'\n')


def launch(root):
    import psutil
    if not (root/'protocol.json').exists():prepare(root)
    watch.verify(root)
    if (root/'process.json').exists():
        pid=read(root/'process.json')['pid']
        if psutil.pid_exists(pid) and str(root) in ' '.join(psutil.Process(pid).cmdline()):
            raise RuntimeError('Controller already running.')
    with (root/'controller.log').open('ab') as log:
        p=subprocess.Popen([watch.PYTHON,str(root/'run_action_parameter_validation.py'),'run','--output',str(root)],
            cwd=REPO,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    save(root/'process.json',dict(pid=p.pid,launched_at=time.time()))
    print('launched',p.pid,root,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','launch','run','summarize'])
    parser.add_argument('--output',type=Path,default=REPO/'outputs/analysis/20260922_action_parameter_validation')
    args=parser.parse_args();root=args.output.resolve()
    try:
        if args.mode=='run':watch.run(root,summarizer=summarize,preflight_handler=preflight)
        else:globals()[args.mode](root)
    except BaseException as exc:
        if args.mode=='run':save(root/'status.json',dict(stage='failed',error=str(exc),pid=os.getpid(),updated_at=time.time()))
        raise
