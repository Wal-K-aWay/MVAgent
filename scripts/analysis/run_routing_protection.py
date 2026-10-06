"""Conditional routing versus retained no-Skill records; protection and net gain."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_original_question_watch as watch
from run_overnight_watch import read, save, sha

REPO = Path(__file__).resolve().parents[2]
PARENT = REPO / 'outputs/analysis/20260921_original_question_watch_revision1'
ARMS = ['RQ']
QUOTAS = {'agent_only': 600, 'both_correct': 600, 'e2e_only': 400, 'both_wrong': 400}
SEED = 20260922
SKILLS = {'WQ': 'watch_original_question_global.md', 'RQ': 'conditional_original_question_global.md'}


def sample_panel(population, quotas=QUOTAS):
    rng = random.Random(SEED)
    pools = defaultdict(list)
    for row in sorted(population, key=lambda r: r['sample_id']):
        pools[(row['cell'], row['bucket'])].append(row)
    for rows in pools.values():
        rng.shuffle(rows)
    allocation = {}
    selected = defaultdict(list)
    for cell, quota in quotas.items():
        keys = sorted(k for k in pools if k[0] == cell)
        counts = {k: 0 for k in keys}
        if sum(len(pools[k]) for k in keys) < quota:
            raise ValueError('Insufficient population for ' + cell)
        while sum(counts.values()) < quota:
            for k in keys:
                if sum(counts.values()) == quota:
                    break
                if counts[k] < len(pools[k]):
                    counts[k] += 1
        for key, n in counts.items():
            total = len(pools[key])
            allocation['|'.join(key)] = dict(population=total, selected=n, probability=n/total)
            for row in pools[key][:n]:
                selected[key].append(dict(row, weight=total/n, stratum='|'.join(key)))
    panel = []
    while any(selected.values()):
        for key in sorted(selected):
            if selected[key]:
                panel.append(selected[key].pop())
    return panel, allocation


def paired(parent, candidate, ids, meta, macro=False, bootstrap=False):
    valid = [s for s in ids if s in parent and s in candidate
             and parent[s]['score'] is not None and candidate[s]['score'] is not None]
    weights = {s: meta[s]['weight'] / (meta[s]['bucket_population'] if macro else 1) for s in valid}
    ds = {s: candidate[s]['score'] - parent[s]['score'] for s in valid}
    total = sum(weights.values())
    complete = len(valid) == len(ids) and bool(ids)
    delta = 100*sum(weights[s]*ds[s] for s in valid)/total if complete else None
    interval = None
    if complete and bootstrap:
        import numpy as np
        clusters = defaultdict(lambda: [0., 0.])
        for sid in valid:
            v = clusters[meta[sid]['group_id']]
            v[0] += weights[sid]*ds[sid]
            v[1] += weights[sid]
        values = np.array(list(clusters.values()))
        n = len(values)
        draws = np.random.default_rng(SEED).multinomial(n, np.ones(n)/n, size=4000)
        distribution = 100*(draws @ values[:, 0])/(draws @ values[:, 1])
        interval = [float(v) for v in np.quantile(distribution, [.025, .975])]
    return dict(expected=len(ids), paired_scored=len(valid), missing_or_unscored=len(ids)-len(valid),
        repairs=[s for s in valid if ds[s] > 0], losses=[s for s in valid if ds[s] < 0],
        raw_delta_pp=100*sum(ds.values())/len(valid) if valid else None,
        weighted_delta_pp=delta, weighted_parent_accuracy=100*sum(weights[s]*parent[s]['score'] for s in valid)/total if complete else None,
        weighted_candidate_accuracy=100*sum(weights[s]*candidate[s]['score'] for s in valid)/total if complete else None,
        cluster_95_interval_pp=interval,
        population_weight=sum(meta[s]['weight'] for s in ids),
        note='Weighted estimate only when all planned paired scores exist. Cluster ratio bootstrap is approximate; not source-independent confirmation.')


def prepare(root, global_skill=None):
    import yaml
    sys.path.insert(0, str(REPO / 'src'))
    from skill_evolution.infra.benchmarks import load_multibench_records
    from skill_evolution.infra.data import group_by_media
    from skill_evolution.infra.store import tree_hash
    from skill_evolution.infra.evaluation import execution_metrics
    if root.exists() and any(root.iterdir()):
        raise ValueError('Fresh output root required.')
    old = watch.verify(PARENT)
    if read(PARENT / 'status.json')['stage'] != 'completed':
        raise ValueError('Previous experiment must be complete.')
    root.mkdir(parents=True, exist_ok=True)
    census_path = REPO / 'outputs/analysis/20260921_full_baseline/full35b_trajectories.json'
    census = read(census_path)
    ids = sorted(s for s, r in census.items() if r['cell'] in QUOTAS)
    records = load_multibench_records(watch.DATA, ids)
    feature_path = REPO / 'outputs/analysis/20260919_crossvid_lite2500/all_features.json'
    features = {r['sample_id']: r for r in read(feature_path)}
    media = {s: r['source_keys'] for s, r in features.items()}
    for sid, record in records.items():
        if not sid.startswith('crossvid:'):
            media[sid] = ['path:' + p for p in record.sample.videos.values()]
    groups = group_by_media(media)
    population, excluded = [], []
    for sid in ids:
        sample, row = records[sid].sample, census[sid]
        video_ids = list(sample.videos)
        batches = watch.video_groups(video_ids)
        length = max(len(watch.instruction(sample.question, batch)) for batch in batches)
        if len(video_ids) < 2 or len(batches) > 4 or length > 1600:
            excluded.append(dict(sample_id=sid, cell=row['cell'], instruction_chars=length))
            continue
        population.append(dict(sample_id=sid, cell=row['cell'], bucket=row['dataset']+'/'+row['task'],
             dataset=row['dataset'], group_id=groups[sid], videos=len(video_ids),
             scope='single_watch' if len(video_ids) <= 4 else 'multi_watch',
             historical_correct=int(row['agent_score']), historical_watch=row['watch'],
             historical_artifact=row['artifact'], historical_artifact_sha256=row['artifact_sha256']))
    panel, allocation = sample_panel(population)
    task_sizes = Counter(r['bucket'] for r in population)
    sources = dict(old['historical_source_sha256'])
    historical = {}
    for row in panel:
        row['bucket_population'] = task_sizes[row['bucket']]
        raw_path = Path(row['historical_artifact'])
        if sha(raw_path) != row['historical_artifact_sha256']:
            raise ValueError('Historical raw record changed: ' + row['sample_id'])
        raw = read(raw_path)
        assert raw['status'] == raw['scoring_status'] == 'ok'
        assert int(raw['correct']) == row['historical_correct']
        assert raw['result']['input']['question'] == records[row['sample_id']].sample.question
        row['historical_prediction'] = raw['prediction']
        historical[row['sample_id']] = dict(score=int(raw['correct']), prediction=raw['prediction'],
             artifact=str(raw_path), artifact_sha256=row['historical_artifact_sha256'],
             audit=watch.audit_record(raw), health=execution_metrics(SimpleNamespace(artifact=raw,status=raw['status'])))
        sources[str(raw_path)] = row['historical_artifact_sha256']
    save(root / 'historical_baseline.json', historical)
    save(root / 'panel.json', dict(samples=panel, allocation=allocation, quotas=QUOTAS))
    save(root / 'population.json', dict(binary_paired=len(ids), eligible=len(population),
         cells=dict(Counter(r['cell'] for r in population)), tasks=dict(task_sizes), excluded=excluded,
         method='Question-level SRS within task x historical outcome cell, exact inclusion probabilities. Known-source clusters retained; no Train/Test isolation claim.'))
    save(root / 'sample_ids.json', [r['sample_id'] for r in panel])
    save(root / 'questions.json', {r['sample_id']: records[r['sample_id']].sample.question for r in panel})
    # Balanced outcome cells plus tasks requiring local counting/order and joint comparison.
    smoke = []
    for cell in QUOTAS:
        smoke += [r['sample_id'] for r in panel if r['cell'] == cell][:3]
    for task in ['mvu_eval/Counting', 'mvu_eval/TR', 'mvu_eval/Comparison', 'mvu_eval/KIR',
                 'crossvid/PSS', 'crossvid/NC', 'cvbench/Joint-video Spatial Navigating']:
        smoke += [r['sample_id'] for r in panel if r['bucket'] == task][:1]
    smoke += [r['sample_id'] for r in sorted(panel, key=lambda r:r['videos'], reverse=True)[:2]]
    smoke = list(dict.fromkeys(smoke + [r['sample_id'] for r in panel]))[:24]
    save(root / 'preflight_ids.json', smoke)
    paths = sorted({p for row in panel for p in records[row['sample_id']].sample.videos.values()})
    save(root / 'media_identity.json', [dict(path=p, size=Path(p).stat().st_size,
                                           mtime_ns=Path(p).stat().st_mtime_ns) for p in paths])
    shutil.copytree(PARENT / 'frozen', root / 'frozen', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(PARENT / 'execution.yaml', root / 'execution.yaml')
    base = yaml.safe_load((PARENT / 'B0.yaml').read_text())
    # This file is used only for pool identity verification, never as an inference arm.
    (root / 'B0.yaml').write_text(yaml.safe_dump(base, sort_keys=False))
    skill_hashes = {}
    for arm in ARMS:
        cfg = deepcopy(base)
        if arm != 'B0':
            path = root / f'{arm}.md'
            shutil.copy2(global_skill or REPO / 'analysis/skill_evolution/skills' / SKILLS[arm], path)
            cfg['agents']['global_agent']['skill'] = dict(enabled=True, path=str(path), sha256=sha(path))
            skill_hashes[arm] = sha(path)
        (root / f'{arm}.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False))
    assert sha(REPO / 'analysis/skill_evolution/skills' / SKILLS['WQ']) == old['skill_sha256']
    previous = read(PARENT / 'comparison.json')['arms']['WQ']
    save(root / 'previous_watch_overlap.json', {r['sample_id']:previous[r['sample_id']]
         for r in panel if r['sample_id'] in previous})
    for name in ['run_routing_protection.py', 'run_original_question_watch.py', 'run_overnight_watch.py']:
        shutil.copy2(REPO / 'scripts/analysis' / name, root / name)
    blocks, stage_ids = [], {}
    stages = ['preflight_' + a for a in ARMS]
    for index, start in enumerate(range(0, len(panel), 100)):
        names = [r['sample_id'] for r in panel[start:start+100]]
        file = f'blocks/{index:03}.json'
        save(root / file, names)
        order = ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)]
        blocks.append(dict(index=index, ids=names, order=order))
        for arm in order:
            stage = f'b{index:03}_{arm}'
            stages.append(stage)
            stage_ids[stage] = file
    for path in [census_path, feature_path, PARENT / 'protocol.json', PARENT / 'comparison.json']:
        sources[str(path)] = sha(path)
    save(root / 'protocol.json', dict(repo=str(REPO), checkpoint=watch.CHECKPOINT,
         controller_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
         n=len(panel), arms=ARMS, blocks=blocks, stages=stages, stage_ids=stage_ids,
         source_sha256=tree_hash(root / 'frozen/src'), skill_sha256=skill_hashes,
         historical_source_sha256=sources,
         immutable_sha256={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()},
         primary='One planned contrast RQ-B0 on eligible binary question population; source-cluster approximate95% interval. Also CV/MVU micro and Cross8 closed-task macro, never Cross10 official score.',
         baseline='Retained no-Skill raw records, verified by ID/hash/question; no new B0 inference or preflight. Historical rather than contemporaneous control.',
         stopping='Fixed2000 RQ only; no B0/WQ reruns. Engineering health/loaded Skill only in preflight; actual routing and copying are outcomes. No score-based stopping/promotion.',
         scope='Development probability sample; all four outcome cells included. No independent Test/source-isolation claim. No Runtime/Video Skill/paid API/optimizer changes.'))
    print(json.dumps(dict(n=len(panel), population=len(population), excluded=len(excluded),
         cells=dict(Counter(r['cell'] for r in panel)), stages=len(stages)), ensure_ascii=False), flush=True)


def summarize(root):
    sys.path.insert(0, str(root / 'frozen/src'))
    from skill_evolution.infra.evaluation import execution_metrics
    protocol = read(root / 'protocol.json')
    meta = {r['sample_id']:r for r in read(root / 'panel.json')['samples']}
    rows = {a:{} for a in ['B0'] + ARMS}
    historical = read(root / 'historical_baseline.json')
    complete, partial = [], {}
    for block in protocol['blocks']:
        raw_rows = {a:{} for a in ARMS}
        for arm in ARMS:
            out = root / 'runs' / f"b{block['index']:03}_{arm}"
            for path in (out / 'records').glob('*/*/result.json'):
                raw = read(path)
                sid = raw['sample_id']
                assert sid in block['ids']
                scored = raw['status'] == raw['scoring_status'] == 'ok' and raw.get('correct') is not None
                raw_rows[arm][sid] = dict(score=int(raw['correct']) if scored else None,
                     prediction=raw['prediction'], audit=watch.audit_record(raw), artifact=str(path),
                     health=execution_metrics(SimpleNamespace(artifact=raw, status=raw['status'])))
        if all(len(raw_rows[a]) == len(block['ids']) and (root / 'runs' / f"b{block['index']:03}_{a}" / 'summary.json').exists() for a in ARMS):
            complete.append(block['index'])
            for arm in ARMS:
                rows[arm].update(raw_rows[arm])
            rows['B0'].update({s:historical[s] for s in block['ids']})
        elif any(raw_rows.values()):
            partial[str(block['index'])] = {a:len(v) for a,v in raw_rows.items()}
    all_ids = list(meta)
    scopes = {'all_eligible_binary_micro':all_ids,
              'protection_historical_correct':[s for s in meta if meta[s]['historical_correct']],
              'recovery_historical_wrong':[s for s in meta if not meta[s]['historical_correct']]}
    for field in ['dataset', 'bucket', 'cell']:
        for value in sorted({r[field] for r in meta.values()}):
            scopes[field+'/'+value] = [s for s in meta if meta[s][field] == value]
    scopes['crossvid_closed8_macro'] = scopes['dataset/crossvid']
    comparisons = {}
    for parent, candidate in [('B0', 'RQ')]:
        comparisons[candidate+'-'+parent] = {name:paired(rows[parent], rows[candidate], ids, meta,
              macro=name == 'crossvid_closed8_macro', bootstrap=name == 'all_eligible_binary_micro')
              for name, ids in scopes.items()}
    counts = {}
    for arm in ['B0'] + ARMS:
        values = list(rows[arm].values())
        counts[arm] = dict(records=len(values), correct=sum(r['score'] == 1 for r in values),
              unscored=sum(r['score'] is None for r in values),
              first_actions=dict(Counter(r['audit']['first_action'] for r in values)),
              health={k:sum(r['health'].get(k,0) for r in values) for k in ['fatal','invalid','model_errors','failed_video_requests']},
              task_options_nonwhitespace_exact=sum(r['audit']['every_watch_task_options_nonwhitespace_exact'] for r in values),
              full_question_exact=sum(r['audit']['every_watch_question_verbatim'] for r in values))
    counts['B0']['historical_prediction_matches'] = sum(r['prediction'] == meta[s]['historical_prediction'] for s,r in rows['B0'].items())
    previous = read(root / 'previous_watch_overlap.json')
    overlap = paired(previous, rows['RQ'], list(previous), meta)
    save(root / 'comparison.json', dict(complete_blocks=complete, partial_blocks=partial,
         planned=len(meta), paired_completed=len(rows['B0']), counts=counts, paired=comparisons, arms=rows,
         previous_watch_overlap=dict(result=overlap, note='Existing WQ on overlapping E2E-only errors only; no WQ protection results or new WQ inference. Auxiliary descriptive comparison.')))
    lines = ['# 保护性与条件路由对照',
             f"条件路由已完成 {len(rows['B0'])}/{len(meta)}；B0直接引用历史结果，B0/WQ均未重新推理。只汇总完整块，未完成块见comparison.json。",
             '样本富集原本正确题，原始微平均不是总体估计；全部计划配对评分完整后才报告加权净收益。', '',
             '|组别|已配对题数|正确|首次action分布|', '|---|---:|---:|---|']
    for arm,c in counts.items():
        lines.append(f"|{arm}|{c['records']}|{c['correct']}|{c['first_actions']}|")
    lines += ['', '|对比/范围|修复|损失|加权差值pp|', '|---|---:|---:|---:|']
    for pair, values in comparisons.items():
        for name in ['all_eligible_binary_micro','protection_historical_correct','recovery_historical_wrong',
                     'dataset/cvbench','dataset/mvu_eval','crossvid_closed8_macro']:
            v = values[name]
            lines.append(f"|{pair}/{name}|{len(v['repairs'])}|{len(v['losses'])}|{v['weighted_delta_pp']}|")
    lines += ['', '逐类别、原对错组合、内部错误和指令遵循见comparison.json。',
              'FSA/CCQA和模板超限题不在估计总体内。唯一主要对比RQ-B0报告近似来源簇95%区间；不自动部署。',
              '已有WQ只在重叠E2E-only错题上作辅助比较，不能据此估计WQ的保护性损失。']
    (root / 'report.md').write_text('\n'.join(lines)+'\n')


def launch(root, global_skill=None):
    import psutil
    if not (root / 'protocol.json').exists():
        prepare(root, global_skill)
    elif global_skill is not None and sha(global_skill) != sha(root / 'RQ.md'):
        raise ValueError('Requested Skill differs from frozen Skill.')
    watch.verify(root)
    if (root / 'process.json').exists():
        pid = read(root / 'process.json')['pid']
        if psutil.pid_exists(pid) and str(root) in ' '.join(psutil.Process(pid).cmdline()):
            raise RuntimeError('Controller already running.')
    with (root / 'controller.log').open('ab') as log:
        p = subprocess.Popen([watch.PYTHON, str(root / 'run_routing_protection.py'), 'run', '--output', str(root)],
             cwd=read(root / 'protocol.json')['repo'], stdin=subprocess.DEVNULL,
             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    save(root / 'process.json', dict(pid=p.pid, launched_at=time.time()))
    print('launched', p.pid, root, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare','launch','run','summarize'])
    parser.add_argument('--output', type=Path, default=REPO/'outputs/analysis/20260922_routing_protection')
    parser.add_argument('--global-skill', type=Path, help='Authored Global Skill for a fresh experiment; frozen before launch.')
    args = parser.parse_args()
    try:
        if args.global_skill is not None and args.mode not in {'prepare', 'launch'}:
            parser.error('--global-skill requires prepare or launch')
        if args.mode == 'run':
            watch.run(args.output.resolve(), summarizer=summarize)
        elif args.mode in {'prepare', 'launch'}:
            globals()[args.mode](args.output.resolve(), args.global_skill.resolve() if args.global_skill else None)
        else:
            globals()[args.mode](args.output.resolve())
    except BaseException as exc:
        if args.mode == 'run':
            save(args.output/'status.json', dict(stage='failed', error=str(exc), pid=os.getpid(), updated_at=time.time()))
        raise
