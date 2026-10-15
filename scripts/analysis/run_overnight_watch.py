"""Freeze and run a bounded, unattended paired watch-strategy experiment.

One command: python scripts/analysis/run_overnight_watch.py launch --output PATH
No runtime edits, API judge, optimizer, service replacement, or score-based scheduling.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
PYTHON = '/home/kww/miniconda3/envs/MVAgent/bin/python'
DATA = Path('/home/kww/datasets/Multi-Video')
PREVIOUS = REPO / 'outputs/analysis/20260920_watch_diagnostic'
SEED = 20260921
ARMS = ['N0', 'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7', 'N8']
OWNS_LOCK = False
CONDITIONAL = '''# Choose evidence by the relation the question requires
For a question whose decisive evidence is a visible difference or edit between matched scenes, a relative spatial relation across views, or fine appearance/identity distinctions between candidate videos, begin with watch_videos on the relevant videos together. Include all input videos when within the action limit and use their full valid durations for the first inspection.
For questions requiring exhaustive counts, locating an event in a long sequence, or reconstructing temporal order, retain separate analyze_videos when separate local inspection is needed. Do not force a joint view merely because multiple videos were supplied. If local reports leave the decisive relationship unresolved, jointly inspect that specific relationship before answering. Route only from the visible question and video metadata, never assumed correctness or task labels.
'''
SEPARATE = '''# Local evidence before cross-video comparison
Begin evidence collection with analyze_videos for the input videos, giving each a self-contained instruction about the same answer-relevant attributes. After these reports, if the question requires a visual difference/edit, cross-view spatial relationship, or fine appearance/identity comparison, perform watch_videos to verify that relationship before answering. Use valid reported ranges when clearly supported; otherwise use the full duration. Do not repeat an already resolved local observation merely to fill steps. Respect the existing action and step limits.
'''
VERIFY = '''# Verify exact evidence support, not a nearby description
Before answering, check every attribute that distinguishes the plausible alternatives against retained observations: entity, location, motion versus camera motion, temporal phase, comparison direction, and stated absence. Do not silently equate door with window, low with high, moving with stationary, or missing detail with absence. Alternatives are hypotheses, not observations.
If the decisive distinction is ambiguous or contradicted and steps remain, make at most one focused verification using watch_videos for a cross-video relationship or analyze_videos for local detail. Phrase it neutrally around the disputed observation and request visible support; do not ask the model to confirm a favored answer. If it remains unresolved, preserve the uncertainty in reasoning and choose the best supported answer under the required answer contract; do not fabricate certainty or introduce an abstention action.
'''
WEAK = {'crossvid/CC', 'crossvid/PI', 'mvu_eval/Comparison', 'mvu_eval/KIR',
        'cvbench/Joint-video Spatial Navigating', 'cvbench/Video Difference Caption'}


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def import_source(root=None):
    source = root / 'frozen/src' if root else REPO / 'src'
    sys.path.insert(0, str(source))


def prepare(root):
    if (root / 'protocol.json').exists():
        raise ValueError('Protocol already frozen; use launch/run to resume unchanged inputs.')
    root.mkdir(parents=True, exist_ok=True)
    import_source()
    import yaml
    from mvagent.utils.snapshot import ensure_source_snapshot
    from skill_evolution.infra.benchmarks import load_multibench_records
    from skill_evolution.infra.data import group_by_media
    from skill_evolution.infra.store import tree_hash

    features_path = REPO / 'outputs/analysis/20260919_crossvid_lite2500/all_features.json'
    features = {r['sample_id']: r for r in read(features_path)}
    cv_rows = read(DATA / 'CVBench/QAs.json')
    mv_rows = read(DATA / 'MVU-Eval/QAs.json')
    cv_meta_path = REPO / 'eval/e2e_eval/CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json'
    cv_tasks = {'cvbench:' + str(r['id']): r['task_type'] for r in read(cv_meta_path)}
    ids = list(features) + ['cvbench:' + str(r['id']) for r in cv_rows]
    ids += ['mvu_eval:' + r['task'] + ':' + str(r['id']) for r in mv_rows]
    records = load_multibench_records(DATA, ids)
    media = {s: features[s]['source_keys'] if s in features else
             ['path:' + p for p in r.sample.videos.values()] for s, r in records.items()}
    groups = group_by_media(media)  # Full catalog before exclusions: retain transitive links.
    train_path = REPO / 'outputs/mvagent/skill/20260916_evolution_redesign/train130_gate300.json'
    train_gate = {r['sample_id'] for r in read(train_path)['samples']}
    previous = set(read(PREVIOUS / 'sample_ids.json'))
    blocked_ids = train_gate | previous
    blocked_groups = {groups[s] for s in blocked_ids}
    cross_panel = set(read(REPO / 'eval/crossvid_2500.json'))
    pools = defaultdict(list)
    all_rows = {}
    for sid, record in sorted(records.items()):
        if sid in blocked_ids or not 2 <= len(record.sample.videos) <= 4:
            continue
        if record.dataset == 'crossvid' and (sid not in cross_panel or record.native_task in {'FSA', 'CCQA'}):
            continue
        task = cv_tasks[sid] if record.dataset == 'cvbench' else record.native_task
        bucket = record.dataset + '/' + task
        scope = 'source_isolated' if groups[sid] not in blocked_groups else 'shared_source_diagnostic'
        # Supplement only the weak families and count/order protection, not arbitrary extra easy tasks.
        if scope == 'shared_source_diagnostic' and bucket not in WEAK | {'mvu_eval/Counting', 'mvu_eval/TR', 'cvbench/Joint-video Counting'}:
            continue
        row = dict(sample_id=sid, dataset=record.dataset, task=task, bucket=bucket,
                   scope=scope, group_id=groups[sid], weak=bucket in WEAK,
                   video_count=len(record.sample.videos), media=media[sid])
        all_rows[sid] = row
        pools[(scope, bucket)].append(sid)
    rng = random.Random(SEED)
    queues = defaultdict(list)
    availability = {}
    for (scope, bucket), members in sorted(pools.items()):
        rng.shuffle(members)
        used = set()
        for sid in members:
            if groups[sid] in used:
                continue
            used.add(groups[sid])
            queues[scope].append((bucket, sid))
        availability[scope + '/' + bucket] = dict(questions=len(members), source_groups=len(used))
    # Round-robin task-stratified ordering; weak families get two slots per pass.
    def order_scope(scope):
        by_task = defaultdict(list)
        for bucket, sid in queues[scope]:
            by_task[bucket].append(sid)
        order = sorted(by_task)
        rng.shuffle(order)
        schedule = order + [b for b in order if b in WEAK]
        ordered = []
        while any(by_task.values()):
            for bucket in schedule:
                if by_task[bucket]:
                    ordered.append(by_task[bucket].pop())
        return ordered
    clean, shared = order_scope('source_isolated'), order_scope('shared_source_diagnostic')
    # One question per known component per scope, including components spanning task labels.
    def distinct(sequence):
        used, out = set(), []
        for sid in sequence:
            if groups[sid] not in used:
                used.add(groups[sid]); out.append(sid)
        return out
    clean, shared = distinct(clean), distinct(shared)
    ordered = []
    while clean or shared:
        for source in [clean, clean, shared]:
            if source:
                ordered.append(source.pop(0))
    panel = [all_rows[s] for s in ordered]
    assert len(panel) >= 650, len(panel)
    assert not set(ordered) & blocked_ids
    assert len({r['group_id'] for r in panel}) == len(panel)
    assert not {r['group_id'] for r in panel if r['scope'] == 'source_isolated'} & blocked_groups
    save(root / 'panel.json', dict(seed=SEED, samples=panel, availability=availability,
         exclusions=sorted(blocked_ids), excluded_source_groups=sorted(blocked_groups),
         scope='Development evaluation, not independent Test; shared_source_diagnostic is not source-isolated.',
         selection='Outcome-blind task-stratified random ordering, one question per known media component; 2 clean : 1 shared until exhausted.'))
    save(root / 'sample_ids.json', ordered)
    # Inputs to Actor still flow through normal runner; labels stay offline in dataset/scorer.
    paths = sorted({p for s in ordered for p in records[s].sample.videos.values()})
    media_identity = []
    for p in paths:
        stat = Path(p).stat()
        media_identity.append(dict(path=p, size=stat.st_size, mtime_ns=stat.st_mtime_ns))
    save(root / 'media_identity.json', dict(method='path-size-mtime_ns; not content-hash or whole-film isolation', files=media_identity))
    frozen = root / 'frozen'
    ensure_source_snapshot(frozen)
    for relative in ['eval/agent_eval/run.py', str(cv_meta_path.relative_to(REPO))]:
        target = frozen / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, target)
    shutil.copy2(Path(__file__), root / 'controller.py')
    shutil.copy2(REPO / 'configs/inference/execution/gpu2_7_single.yaml', root / 'execution.yaml')
    base = yaml.safe_load((REPO / 'configs/inference/local_qwen35_35b_a3b_historical_no_skill.yaml').read_text())
    route = (PREVIOUS / 'skills/W1/global.md').read_text()
    route_context = (PREVIOUS / 'skills/W2/global.md').read_text()
    assert route_context.startswith(route)
    context = route_context[len(route):]
    e3_path = REPO / 'outputs/mvagent/skill/20260916_evolution_redesign/runs/E3/selected_skill_set/video.md'
    e3 = e3_path.read_text()
    specs = {
        'N0': ('no_skill', '', ''),
        'N1': ('forced_joint', route, ''),
        'N2': ('forced_joint_context', route_context, ''),
        'N3': ('context_only', context, ''),
        'N4': ('conditional_joint_context', CONDITIONAL + context, ''),
        'N5': ('separate_then_joint_context', SEPARATE + context, ''),
        'N6': ('conditional_context_verification', CONDITIONAL + context + VERIFY, ''),
        'N7': ('forced_context_verification', route_context + VERIFY, ''),
        'N8': ('historical_E3_video_only', '', e3),
    }
    arms = {}
    for arm, (label, global_text, video_text) in specs.items():
        cfg = deepcopy(base)
        hashes = {}
        for role, value in [('global', global_text), ('video', video_text)]:
            if value:
                path = root / 'skills' / arm / (role + '.md')
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
                hashes[role] = sha(path)
                cfg['agents'][role + '_agent']['skill'] = dict(enabled=True, path=str(path), sha256=sha(path))
        path = root / (arm + '.yaml'); path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        arms[arm] = dict(label=label, config_sha256=sha(path), skill_sha256=hashes)
    blocks = []
    for index, offset in enumerate(range(0, len(ordered), 24)):
        members = ordered[offset:offset + 24]
        path = root / 'blocks' / f'{index:03d}.json'; save(path, members)
        # Baseline first, rotate intervention order to limit time-of-night confounding.
        k = index % 8
        arm_order = ['N0'] + ARMS[1:][k:] + ARMS[1:][:k]
        blocks.append(dict(index=index, ids_file=str(path), n=len(members), order=arm_order))
    smoke = ordered[:6]
    save(root / 'smoke_ids.json', smoke)
    source_files = [features_path, train_path, PREVIOUS / 'protocol.json', PREVIOUS / 'sample_ids.json',
                    e3_path, cv_meta_path, REPO / 'eval/crossvid_2500.json', DATA / 'CrossVid/qa.jsonl',
                    DATA / 'CVBench/QAs.json', DATA / 'MVU-Eval/QAs.json']
    protocol = dict(seed=SEED, created_at=time.time(), git_commit=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(), repo=str(REPO),
        runtime_source_sha256=tree_hash(frozen / 'src'), arms=arms, blocks=blocks,
        target_seconds=8.5*3600, ceiling_seconds=9*3600, min_seconds=8*3600,
        primary_pairs=[['N0', a] for a in ARMS[1:]],
        mechanistic_pairs=[['N1','N2'], ['N0','N3'], ['N3','N4'], ['N4','N5'], ['N4','N6'], ['N2','N7'], ['N0','N8']],
        scheduling='Predefined order, elapsed time only. Complete paired blocks before target; final partial block reported separately. No outcome-based promotion or early stop.',
        stopping='No new child after 9h; normally stop at complete block >=8.5h. Finish in-flight child; never kill resident services. Runtime deadlines bound exceptional overrun.',
        inference=dict(actor='Qwen3.5-35B-A3B',temperature=0,top_p=1,thinking=False,max_tokens=2048,
            max_frames_per_visual_call=512,global_steps=5,video_steps=5,video_concurrency=2,endpoint_cap=1),
        judge=None,optimizer=None,training=False,smoke_ids=smoke,
        source_sha256={str(p):sha(p) for p in source_files},
        historical_e3_note='Copied existing Video skill without editing; its Train/Gate shared-source diagnostic results may benefit from source familiarity.',
        data_limit='Known source/path components, not full content-hash or whole-film/session isolation. Only 2-4 input videos and closed tasks; no full-benchmark score claim.')
    # Hash all executable/configuration/selection inputs; exclude runtime logs/outputs.
    immutable = [root / 'controller.py', root / 'panel.json', root / 'sample_ids.json',
                 root / 'media_identity.json', root / 'execution.yaml', root / 'smoke_ids.json',
                 frozen / 'eval/agent_eval/run.py', frozen / cv_meta_path.relative_to(REPO)]
    immutable += list((root / 'blocks').glob('*.json')) + [root / (a + '.yaml') for a in ARMS]
    immutable += list((root / 'skills').glob('*/*.md'))
    protocol['immutable_sha256'] = {str(p.relative_to(root)):sha(p) for p in immutable}
    save(root / 'protocol.json', protocol)
    save(root / 'prepared.json', dict(panel=len(panel), scopes=dict(Counter(r['scope'] for r in panel)),
        task_counts=dict(Counter(r['scope']+'/'+r['bucket'] for r in panel)), blocks=len(blocks),
        potential_main_rollouts=len(panel)*9, smoke_rollouts=54))
    print(json.dumps(read(root / 'prepared.json'), ensure_ascii=False), flush=True)


def verify(root):
    p = read(root / 'protocol.json')
    for relative, expected in p['immutable_sha256'].items():
        if sha(root / relative) != expected:
            raise ValueError('Frozen input changed: ' + relative)
    import_source(root)
    from skill_evolution.infra.store import tree_hash
    if tree_hash(root / 'frozen/src') != p['runtime_source_sha256']:
        raise ValueError('Frozen runtime source changed')
    for item in read(root / 'media_identity.json')['files']:
        stat = Path(item['path']).stat()
        if (stat.st_size, stat.st_mtime_ns) != (item['size'], item['mtime_ns']):
            raise ValueError('Media changed: ' + item['path'])
    for path, expected in p['source_sha256'].items():
        if sha(path) != expected:
            raise ValueError('Dataset/provenance source changed: ' + path)
    return p


def pool_check(root):
    import yaml
    from mvagent.batch import BatchExecutor, ExecutionConfig
    events = []
    executor = BatchExecutor(ExecutionConfig.from_yaml(root / 'execution.yaml'), on_event=events.append)
    try:
        executor.prepare(yaml.safe_load((root / 'N0.yaml').read_text()))
        event = next(e for e in events if e.get('kind') == 'batch_prepared')
        if event['question_workers'] != 6 or event['unavailable'] or sum(map(len, event['model_pools'].values())) != 6:
            raise RuntimeError('Six verified endpoints required; inspect pool_verification.json')
    finally:
        executor.close()
        save(root / 'pool_verification.json', events)


def paired(parent, candidate, ids, groups):
    present = [s for s in ids if s in parent and s in candidate]
    scored = [s for s in present if parent[s]['score'] is not None and candidate[s]['score'] is not None]
    ds = [candidate[s]['score']-parent[s]['score'] for s in scored]
    repair = [s for s,d in zip(scored,ds) if d > 0]
    regress = [s for s,d in zip(scored,ds) if d < 0]
    result = dict(expected=len(ids), paired=len(present), scored=len(scored), missing_or_unscored=len(ids)-len(scored),
        repairs=repair, regressions=regress, delta_pp=100*sum(ds)/len(ds) if ds else None)
    by_group = defaultdict(list)
    for s,d in zip(scored,ds):
        by_group[groups[s]].append(d)
    if by_group:
        import numpy as np
        # Panel guarantees one question per known component; multinomial resampling
        # is the exact same bootstrap distribution without a large Python loop.
        assert all(len(values)==1 for values in by_group.values())
        counts = [sum(d==v for d in ds) for v in [-1,0,1]]
        samples = np.random.default_rng(SEED).multinomial(len(ds), np.array(counts)/len(ds), size=4000)
        draws = np.sort(100*(samples[:,2]-samples[:,0])/len(ds))
        result['cluster_bootstrap_95_pp'] = [float(draws[100]),float(draws[3899])]
        # Exact two-sided sign/McNemar test on discordant pairs. One question per source group.
        import math
        n = len(repair)+len(regress)
        result['mcnemar_exact_p'] = min(1., 2*sum(math.comb(n,k) for k in range(min(len(repair),len(regress))+1))/2**n) if n else 1.
    return result


def summarize(root):
    import_source(root)
    from skill_evolution.infra.evaluation import execution_metrics
    protocol = read(root / 'protocol.json')
    panel = read(root / 'panel.json')['samples']
    metadata = {r['sample_id']:r for r in panel}
    rows = {a:{} for a in ARMS}
    complete_blocks = []
    raw_blocks = {}
    for block in protocol['blocks']:
        index = block['index']; raw_blocks[index] = {}
        for arm in ARMS:
            base = root / 'runs' / f'b{index:03d}_{arm}'
            arm_rows = {}
            for path in (base/'records').glob('*/*/result.json'):
                r = read(path); sid = r['sample_id']
                if sid not in read(block['ids_file']):
                    raise ValueError('Unexpected record ID: '+sid)
                result = r.get('result') or {}
                actions = [a for a in result.get('action_history',[]) if a['action'] in {'analyze_videos','watch_videos'}]
                metrics = execution_metrics(SimpleNamespace(artifact=r,status=r['status']))
                arm_rows[sid] = dict(score=float(r['correct']) if r['status']==r['scoring_status']=='ok' and r['correct'] is not None else None,
                    prediction=r['prediction'],first=actions[0]['action'] if actions else None,
                    actions=[a['action'] for a in actions],metrics=metrics,artifact=str(path))
            raw_blocks[index][arm] = arm_rows
        if all(len(raw_blocks[index][a])==block['n'] and (root/'runs'/f'b{index:03d}_{a}'/'summary.json').exists() for a in ARMS):
            complete_blocks.append(index)
            for a in ARMS:
                rows[a].update(raw_blocks[index][a])
    common_ids = [r['sample_id'] for r in panel if r['sample_id'] in rows['N0']]
    strata = {'all_diagnostic':common_ids}
    for scope in ['source_isolated','shared_source_diagnostic']:
        strata[scope] = [s for s in common_ids if metadata[s]['scope']==scope]
        for family in ['weak','protection']:
            strata[scope+'/'+family] = [s for s in strata[scope] if metadata[s]['weak']==(family=='weak')]
        for bucket in sorted({metadata[s]['bucket'] for s in strata[scope]}):
            strata[scope+'/'+bucket] = [s for s in strata[scope] if metadata[s]['bucket']==bucket]
    comparisons = {}
    pairs = list(dict.fromkeys(tuple(x) for x in protocol['primary_pairs']+protocol['mechanistic_pairs']))
    for parent,candidate in pairs:
        for label,ids in strata.items():
            if ids:
                comparisons[candidate+'-'+parent+'/'+label] = paired(rows[parent],rows[candidate],ids,
                    {s:metadata[s]['group_id'] for s in ids})
    # Holm adjustment only for the eight preregistered main source-isolated comparisons.
    main = [comparisons[a+'-N0/source_isolated'] for a in ARMS[1:] if a+'-N0/source_isolated' in comparisons]
    running = 0.
    for rank,item in enumerate(sorted(main,key=lambda p:p.get('mcnemar_exact_p',1.))):
        running = max(running,min(1.,(len(main)-rank)*item.get('mcnemar_exact_p',1.)))
        item['holm_primary_p'] = running
    unfinished = {str(i):{a:len(v) for a,v in by_arm.items()} for i,by_arm in raw_blocks.items()
                  if i not in complete_blocks and any(by_arm.values())}
    result = dict(updated_at=time.time(),complete_blocks=complete_blocks,main_questions_per_arm=len(common_ids),
        partial_blocks_excluded_from_main=unfinished,arms=rows,paired=comparisons,
        note='All nine assigned arms on complete blocks only. Failures missing, never silently scored zero. Development panels; task mixture is not official benchmark macro. Intervals conditional on executed source groups; no automatic winner.')
    save(root/'comparison.json',result)
    lines = ['# 夜间策略对照自动汇总','',result['note'],'',
             f'完成配对块：{len(complete_blocks)}；正式每臂题数：{len(common_ids)}；未完整块：{unfinished}', '',
             '|组别|已评分/分配|正确率|首先watch|fatal/invalid/model_errors|','|---|---:|---:|---:|---:|']
    for a in ARMS:
        valid=[v for v in rows[a].values() if v['score'] is not None]
        rate=f"{100*sum(v['score'] for v in valid)/len(valid):.2f}%" if valid else '—'
        health='/'.join(str(sum(v['metrics'].get(k,0) for v in rows[a].values())) for k in ['fatal','invalid','model_errors'])
        lines.append(f"|{a} {protocol['arms'][a]['label']}|{len(valid)}/{len(rows[a])}|{rate}|{sum(v['first']=='watch_videos' for v in rows[a].values())}|{health}|")
    lines += ['', '|对照/分层|配对已评分|修复/退化|差值pp|来源组区间pp|','|---|---:|---:|---:|---|']
    for key,p in comparisons.items():
        if p['delta_pp'] is not None:
            lines.append(f"|{key}|{p['scored']}|{len(p['repairs'])}/{len(p['regressions'])}|{p['delta_pp']:+.2f}|{p.get('cluster_bootstrap_95_pp')}|")
    lines += ['','缺失、逐题轨迹、健康和Holm校正见comparison.json。smoke不计入正式结果；N8来源重叠层不能排除历史训练素材熟悉效应。',
              '只按时间停止，不根据成绩选择实验；时间截断也可能偏向较快素材，本报告只描述实际执行的冻结前缀。','']
    tmp=root/'report.md.tmp';tmp.write_text('\n'.join(lines));tmp.replace(root/'report.md')


def run(root):
    global OWNS_LOCK
    lock = (root/'controller.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    OWNS_LOCK = True
    import psutil
    # Refuse resume while an orphaned child still uses this frozen root.
    for proc in psutil.process_iter(['pid','cmdline']):
        cmd=proc.info['cmdline'] or []
        if proc.pid != os.getpid() and any(str(root) in arg for arg in cmd) and any(arg.endswith('/run.py') for arg in cmd):
            raise RuntimeError(f'Previous runner still alive: {proc.pid}')
    protocol=verify(root)
    env=dict(os.environ,PYTHONPATH=str(root/'frozen/src'),MVAGENT_PROJECT_ROOT=str(root/'frozen'))
    env['NO_PROXY']=env['no_proxy']='127.0.0.1,localhost'
    os.environ['NO_PROXY']=os.environ['no_proxy']='127.0.0.1,localhost'
    pool_check(root)
    session=read(root/'session.json') if (root/'session.json').exists() else dict(started_at=time.time())
    save(root/'session.json',session)
    start=session['started_at']; completed=[];durations=[]
    def status(stage,**kw):
        save(root/'status.json',dict(stage=stage,pid=os.getpid(),updated_at=time.time(),started_at=start,
            elapsed_hours=(time.time()-start)/3600,target_end_at=start+protocol['target_seconds'],
            completed=completed,**kw))
    def execute(stage,arm,ids_file):
        output=root/'runs'/stage
        manifest=output/'run_manifest.json'
        if manifest.exists() and read(manifest).get('status')=='completed' and (output/'summary.json').exists():
            completed.append(stage);return
        command=[PYTHON,str(root/'frozen/eval/agent_eval/run.py'),'--config',str(root/(arm+'.yaml')),
            '--execution-config',str(root/'execution.yaml'),'--sample-ids-file',str(ids_file),
            '--output',str(output),'--benchmarks','crossvid','mvu_eval','cvbench']
        begin=time.time()
        for attempt in range(2):
            cmd=command+(['--resume'] if manifest.exists() else [])
            with (root/(stage+'.log')).open('ab') as log:
                child=subprocess.Popen(cmd,cwd=REPO,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
                status(stage,child_pid=child.pid,attempt=attempt,ids_file=str(ids_file))
                code=child.wait()
            if code==0:break
            if attempt==0:
                pool_check(root)  # Standard verification only; never clear locks/quarantine.
        if code:
            raise RuntimeError(f'{stage} failed after bounded resume; exit={code}')
        summary=read(output/'summary.json')
        # Persist and report scored health failures; never make performance look better by dropping an arm.
        if summary['total_expected']!=len(read(ids_file)) or summary['total_pending']!=0:
            raise RuntimeError(f'{stage} incomplete sample count')
        events=[json.loads(line) for line in (output/'execution_events.jsonl').read_text().splitlines()]
        prepared=[e for e in events if e.get('kind')=='batch_prepared']
        if not prepared or any(e['question_workers']!=6 or e['unavailable'] for e in prepared):
            raise RuntimeError(f'{stage} did not run with six verified workers')
        completed.append(stage)
        save(root/'stage_timings'/f'{stage}.json',dict(seconds=time.time()-begin,n=len(read(ids_file)),arm=arm,
            errors=summary.get('total_errors'),score_complete=summary.get('score_complete')))
        status(stage+'_completed')
    for arm in ARMS:
        execute('smoke_'+arm,arm,root/'smoke_ids.json')
    for block in protocol['blocks']:
        elapsed=time.time()-start
        if elapsed>=protocol['target_seconds']:
            break
        # No score-dependent decisions. A short final partial block remains separate in reporting.
        begin=time.time()
        for arm in block['order']:
            if time.time()-start>=protocol['ceiling_seconds']:
                summarize(root);status('completed_time_budget_partial_block',partial_block=block['index']);return
            execute(f"b{block['index']:03d}_{arm}",arm,Path(block['ids_file']))
        summarize(root)
        durations.append(time.time()-begin)
        status('paired_block_completed',block=block['index'],last_block_seconds=durations[-1])
    summarize(root)
    status('completed_time_budget' if time.time()-start>=protocol['target_seconds'] else 'completed_queue')


def launch(root):
    if not (root/'protocol.json').exists():
        prepare(root)
    import psutil
    if (root/'process.json').exists():
        saved=read(root/'process.json')
        if psutil.pid_exists(saved['pid']):
            proc=psutil.Process(saved['pid'])
            if abs(proc.create_time()-saved['create_time'])<1:
                raise RuntimeError('Controller already running')
    with (root/'controller.log').open('ab') as log:
        proc=subprocess.Popen([PYTHON,str(root/'controller.py'),'run','--output',str(root)],cwd=REPO,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    save(root/'process.json',dict(pid=proc.pid,create_time=psutil.Process(proc.pid).create_time(),root=str(root)))
    print(json.dumps(dict(launched_pid=proc.pid,root=str(root))),flush=True)


def self_check():
    p={'a':{'score':0},'b':{'score':1},'c':{'score':None}}
    q={'a':{'score':1},'b':{'score':0},'c':{'score':1}}
    r=paired(p,q,['a','b','c','missing'],{'a':'g1','b':'g2','c':'g3'})
    assert r['scored']==2 and r['missing_or_unscored']==2 and r['delta_pp']==0
    assert r['repairs']==['a'] and r['regressions']==['b'] and r['mcnemar_exact_p']==1
    assert len(set(ARMS))==9
    print('self-check passed: paired missingness, repairs/regressions, exact test')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','launch','run','summarize','check'])
    parser.add_argument('--output',type=Path,default=REPO/'outputs/analysis/20260920_overnight_watch')
    args=parser.parse_args();root=args.output.resolve()
    if (root/'protocol.json').exists():
        REPO=Path(read(root/'protocol.json')['repo'])
    if args.mode=='check':self_check()
    else:
        try:
            globals()[args.mode](root)
        except BaseException as error:
            if args.mode=='run' and OWNS_LOCK:
                save(root/'status.json',dict(stage='stopped_on_error',pid=os.getpid(),updated_at=time.time(),error=str(error)))
            raise
