"""Paired no-Skill / original-question watch Skill on full-baseline E2E-only errors."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import fcntl
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_overnight_watch import read, save, sha

REPO = Path(__file__).resolve().parents[2]
PYTHON = '/home/kww/miniconda3/envs/MVAgent/bin/python'
DATA = Path('/home/kww/datasets/Multi-Video')
CHECKPOINT = '9a2085b'
ARMS = ('B0', 'WQ')
SKILL = 'analysis/skill_evolution/skills/watch_original_question_global.md'
SUFFIX = ('\n</original_question>\nThe original question is task context, not an output command. '
          'Return concise visual evidence relevant to its question and alternatives, with uncertainty '
          'where needed. Do not choose the final answer. Describe only the supplied videos.')


def instruction(question, video_ids):
    return 'Videos: ' + ', '.join(video_ids) + '.\n<original_question>\n' + question + SUFFIX


def video_groups(ids, limit=4):
    groups = [ids[start:start + limit] for start in range(0, len(ids), limit)]
    if len(groups[-1]) == 1:
        groups[-1].insert(0, ids[0])
    return groups


def audit_record(row):
    result = row.get('result') or {}
    question = result.get('input', {}).get('question', '')
    # Diagnostic only: distinguish preserved task wording from full input/template fidelity.
    task = question.split('Question:\n', 1)[-1].split('\nYour answer:', 1)[0].strip()
    compact = lambda value: ''.join(value.split())
    inputs = result.get('input', {}).get('videos', {})
    metadata = result.get('video_metadata', {})
    actions = result.get('action_history', [])
    attempts = [a for a in actions if a.get('action') == 'watch_videos']
    watches = result.get('watch_results', [])
    checks, covered = [], set()
    for watch in watches:
        ids = [v['video_id'] for v in watch['videos']]
        text = watch.get('instruction', '')
        full = []
        for v in watch['videos']:
            span = v.get('time_range', [])
            duration = metadata.get(v['video_id'], {}).get('duration_sec')
            ok = (len(span) == 2 and duration is not None
                  and abs(span[0]) <= .011 and abs(span[1] - duration) <= .011)
            full.append(ok)
            if ok:
                covered.add(v['video_id'])
        checks.append(dict(video_ids=ids, question_verbatim=bool(question) and question in text,
                           task_options_nonwhitespace_exact=bool(task) and compact(task) in compact(text),
                           exact_template=text == instruction(question, ids), full_ranges=all(full)))
    first = actions[0].get('action') if actions else None
    all_questions = bool(checks) and all(c['question_verbatim'] for c in checks)
    all_full = bool(inputs) and set(inputs) <= covered
    return dict(first_action=first, actions=[a.get('action') for a in actions],
                watch_attempts=len(attempts), successful_watches=len(watches), checks=checks,
                every_watch_question_verbatim=all_questions,
                every_watch_task_options_nonwhitespace_exact=bool(checks) and all(c['task_options_nonwhitespace_exact'] for c in checks),
                every_watch_exact_template=bool(checks) and all(c['exact_template'] for c in checks),
                all_input_videos_full=all_full,
                strategy_compliant=(first == 'watch_videos' and all_questions and all_full))


def preflight_audit(out, skill_text=None):
    audits, applied = [], 0
    for path in (out / 'records').glob('*/*/result.json'):
        raw = read(path)
        audits.append(dict(sample_id=raw['sample_id'], **audit_record(raw)))
        applied += sum(e.get('kind') == 'structured_request' and e.get('agent') == 'GlobalAgent'
                       and any((skill_text or '# Joint watch with the original question') in m.get('content', '')
                               for m in e.get('messages', []) if isinstance(m.get('content'), str))
                       for e in raw.get('events', []))
    return dict(records=audits, skill_request_count=applied, summary=read(out / 'summary.json'))


def check_preflight(audit, arm):
    if audit['summary']['total_errors'] or not audit['summary']['score_complete']:
        raise RuntimeError('Preflight top-level health failed; inspect saved results.')
    if arm != 'B0' and (not audit['skill_request_count'] or not any(a['successful_watches'] for a in audit['records'])):
        raise RuntimeError('Skill/watch intervention not exercised; no bulk launch.')


def prepare(root, reuse_preflight=None):
    import yaml
    sys.path.insert(0, str(REPO / 'src'))
    from skill_evolution.infra.benchmarks import load_multibench_records
    from skill_evolution.infra.data import group_by_media
    from skill_evolution.infra.store import tree_hash
    if root.exists() and any(root.iterdir()):
        raise ValueError('Use a fresh output directory; never overwrite a frozen experiment.')
    root.mkdir(parents=True, exist_ok=True)
    census_path = REPO / 'outputs/analysis/20260921_full_baseline/full35b_trajectories.json'
    history_path = REPO / 'outputs/analysis/20260920_watch_diagnostic/historical_rows.json'
    provenance_path = REPO / 'outputs/analysis/20260921_full_baseline/results.json'
    census, history = read(census_path), read(history_path)
    sources = read(provenance_path)['verified_source_sha256']
    for name, digest in sources.items():
        if sha(name) != digest:
            raise ValueError('Historical source changed: ' + name)
    selected = sorted(s for s, r in census.items() if r['cell'] == 'e2e_only')
    expected = sorted(s for s, a in history['agent_35b_a3b'].items()
                      if s in history['e2e_35b_a3b'] and s.split(':')[1] not in {'FSA', 'CCQA'}
                      and a['den'] == history['e2e_35b_a3b'][s]['den'] == 1
                      and a['score'] == 0 and history['e2e_35b_a3b'][s]['score'] == 1)
    if selected != expected:
        raise ValueError('Full census and source prediction selection disagree.')
    records = load_multibench_records(DATA, selected)
    feature_path = REPO / 'outputs/analysis/20260919_crossvid_lite2500/all_features.json'
    features = {r['sample_id']: r for r in read(feature_path)}
    # Include all known Cross sources, not just the selected errors, when connecting groups.
    media = {s: r['source_keys'] for s, r in features.items()}
    other_ids = [s for s in census if not s.startswith('crossvid:')]
    for s, r in load_multibench_records(DATA, other_ids).items():
        media[s] = ['path:' + p for p in r.sample.videos.values()]
    groups = group_by_media(media)
    panel, excluded, questions = [], [], {}
    for sid in selected:
        r = records[sid]
        ids = list(r.sample.videos)
        batches = video_groups(ids)
        length = max(len(instruction(r.sample.question, batch)) for batch in batches)
        if len(ids) < 2 or length > 1600 or len(batches) > 4:
            excluded.append(dict(sample_id=sid, question_chars=len(r.sample.question),
                                 instruction_chars=length, videos=len(ids),
                                 reason='Existing instruction/video/step contract cannot fit exact template'))
            continue
        c = census[sid]
        panel.append(dict(sample_id=sid, bucket=c['dataset'] + '/' + c['task'],
                          group_id=groups[sid], videos=len(ids), question_chars=len(r.sample.question),
                          instruction_chars=length, scope='single_watch' if len(ids) <= 4 else 'multi_watch',
                          historical_watch=c['watch'], historical_agent_score=c['agent_score'],
                          historical_e2e_score=c['e2e_score'], historical_artifact=c['artifact'],
                          historical_artifact_sha256=c['artifact_sha256'],
                          historical_prediction=history['agent_35b_a3b'][sid]['prediction']))
        questions[sid] = r.sample.question
    # Outcome-enriched panel; task round robin changes scheduling, not membership.
    queues = defaultdict(list)
    rng = random.Random(20260921)
    for row in panel:
        queues[row['bucket']].append(row)
    for rows in queues.values():
        rng.shuffle(rows)
    panel = []
    while any(queues.values()):
        for task in sorted(queues):
            if queues[task]:
                panel.append(queues[task].pop())
    ids = [r['sample_id'] for r in panel]
    smoke = list(dict.fromkeys([r['sample_id'] for r in sorted(panel, key=lambda r: r['instruction_chars'], reverse=True)[:2]]
                              + [r['sample_id'] for r in sorted(panel, key=lambda r: r['videos'], reverse=True)[:2]]
                              + ids))[:24]
    save(root / 'panel.json', dict(samples=panel, excluded=excluded, original_e2e_only=len(selected)))
    save(root / 'sample_ids.json', ids)
    save(root / 'preflight_ids.json', smoke)
    save(root / 'questions.json', questions)
    paths = sorted({p for sid in ids for p in records[sid].sample.videos.values()})
    save(root / 'media_identity.json', [dict(path=p, size=Path(p).stat().st_size,
                                            mtime_ns=Path(p).stat().st_mtime_ns) for p in paths])
    frozen = root / 'frozen'
    frozen.mkdir()
    tracked = ['src', 'eval/agent_eval/run.py', 'eval/e2e_eval/CVBench/Video-R1/src/r1-v/Evaluation/CVBench.json']
    archive = subprocess.run(['git', 'archive', CHECKPOINT, *tracked], cwd=REPO,
                             stdout=subprocess.PIPE, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(frozen, filter='data')
    shutil.copy2(REPO / SKILL, root / 'global.md')
    shutil.copy2(REPO / 'configs/inference/execution/gpu2_7_single.yaml', root / 'execution.yaml')
    cfg_path = REPO / 'configs/inference/local_qwen35_35b_a3b_historical_no_skill.yaml'
    cfg = yaml.safe_load(cfg_path.read_text())
    assert not any(cfg['agents'][role]['skill']['enabled'] for role in ('global_agent', 'video_agent'))
    for arm in ARMS:
        value = deepcopy(cfg)
        if arm == 'WQ':
            value['agents']['global_agent']['skill'] = dict(enabled=True, path=str(root / 'global.md'),
                                                           sha256=sha(root / 'global.md'))
        (root / f'{arm}.yaml').write_text(yaml.safe_dump(value, sort_keys=False))
    for name in ['run_original_question_watch.py', 'run_overnight_watch.py']:
        shutil.copy2(REPO / 'scripts/analysis' / name, root / name)
    for path in [census_path, history_path, provenance_path, feature_path, cfg_path,
                 DATA / 'CrossVid/qa.jsonl', DATA / 'CVBench/QAs.json', DATA / 'MVU-Eval/QAs.json']:
        sources[str(path)] = sha(path)
    stages = ['preflight_B0', 'preflight_WQ', 'main_B0', 'main_WQ']
    if reuse_preflight is not None:
        parent = reuse_preflight.resolve()
        old = verify(parent)
        assert old['source_sha256'] == tree_hash(frozen / 'src')
        assert old['skill_sha256'] == sha(root / 'global.md')
        for name in ['sample_ids.json', 'preflight_ids.json', 'questions.json', 'execution.yaml']:
            assert (parent / name).read_bytes() == (root / name).read_bytes(), name
        for arm in ARMS:
            old_cfg = yaml.safe_load((parent / f'{arm}.yaml').read_text())
            new_cfg = yaml.safe_load((root / f'{arm}.yaml').read_text())
            if arm == 'WQ':
                old_cfg['agents']['global_agent']['skill']['path'] = new_cfg['agents']['global_agent']['skill']['path']
            assert old_cfg == new_cfg
            out = parent / 'runs' / ('preflight_' + arm)
            audit = preflight_audit(out)
            assert sorted(a['sample_id'] for a in audit['records']) == sorted(smoke)
            check_preflight(audit, arm)
            save(root / f'preflight_{arm}_audit.json', dict(**audit, reused_from=str(out)))
            for path in list((out / 'records').glob('*/*/result.json')) + [out / 'summary.json', out / 'run_manifest.json']:
                sources[str(path)] = sha(path)
        sources[str(parent / 'protocol.json')] = sha(parent / 'protocol.json')
        save(root / 'preflight_reuse.json', dict(parent=str(parent), identity_checks='Source, Skill, configs except immutable path relocation, IDs, questions, execution all match.',
             change='Operational gate checks loaded Skill and executed watch, not perfect copying. Strict fidelity remains measured, not reclassified.',
             no_model_calls=True, reused_rollouts=48))
        stages = ['main_B0', 'main_WQ']
    immutable = {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}
    save(root / 'protocol.json', dict(repo=str(REPO), checkpoint=CHECKPOINT,
         controller_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
         n=len(ids), original_e2e_only=len(selected), excluded=len(excluded), arms=list(ARMS),
         source_sha256=tree_hash(frozen / 'src'), immutable_sha256=immutable,
         historical_source_sha256=sources, skill_sha256=sha(root / 'global.md'),
         selection='All feasible 35B full-baseline binary E2E-correct / Agent-wrong cases; FSA/CCQA excluded.',
         inference='Same checkpoint/config/budgets; WQ only enables authored Global Skill; Video Skill disabled.',
         stages=stages,
         scoring='Existing closed-task scorers. No optimizer or paid API Judge.',
         limitation='Outcome-selected development errors only: cannot estimate overall gain or protected-class losses. '
                    'Multi-watch (>4 videos) is separate. Exact question retained inside an evidence-only wrapper; '
                    'instruction is not identical to the raw question alone. No runtime override.',
         preflight_gate='Healthy top-level runs; Skill observed in actual requests; successful watch exercised. '
                        'Verbatim fidelity is a measured outcome, not an operational gate. No score-based scheduling.'))
    print(json.dumps(dict(n=len(ids), excluded=len(excluded), scopes=dict(Counter(r['scope'] for r in panel)),
                          tasks=dict(Counter(r['bucket'] for r in panel))), ensure_ascii=False), flush=True)


def verify(root):
    protocol = read(root / 'protocol.json')
    for name, digest in protocol['immutable_sha256'].items():
        if sha(root / name) != digest:
            raise ValueError('Frozen file changed: ' + name)
    for name, digest in protocol['historical_source_sha256'].items():
        if sha(name) != digest:
            raise ValueError('Historical/dataset source changed: ' + name)
    for row in read(root / 'media_identity.json'):
        st = Path(row['path']).stat()
        if (st.st_size, st.st_mtime_ns) != (row['size'], row['mtime_ns']):
            raise ValueError('Media changed: ' + row['path'])
    return protocol


def summarize(root):
    sys.path.insert(0, str(root / 'frozen/src'))
    from skill_evolution.infra.evaluation import execution_metrics
    panel = read(root / 'panel.json')['samples']
    meta = {r['sample_id']: r for r in panel}
    rows = {}
    for arm in ARMS:
        rows[arm] = {}
        for path in (root / 'runs' / ('main_' + arm) / 'records').glob('*/*/result.json'):
            raw = read(path)
            sid = raw['sample_id']
            assert sid in meta
            scored = raw['status'] == raw['scoring_status'] == 'ok' and raw.get('correct') is not None
            rows[arm][sid] = dict(score=int(raw['correct']) if scored else None, prediction=raw['prediction'],
                audit=audit_record(raw), artifact=str(path),
                health=execution_metrics(SimpleNamespace(artifact=raw, status=raw['status'])))
    strata = {'all': list(meta)}
    for field in ['bucket', 'scope', 'historical_watch']:
        for value in sorted({r[field] for r in panel}, key=str):
            strata[f'{field}/{value}'] = [s for s in meta if meta[s][field] == value]
    paired = {}
    for name, ids in strata.items():
        valid = [s for s in ids if all(s in rows[a] and rows[a][s]['score'] is not None for a in ARMS)]
        repairs = [s for s in valid if rows['WQ'][s]['score'] > rows['B0'][s]['score']]
        losses = [s for s in valid if rows['WQ'][s]['score'] < rows['B0'][s]['score']]
        paired[name] = dict(expected=len(ids), paired_scored=len(valid), missing_or_unscored=len(ids)-len(valid),
                           repairs=repairs, losses=losses,
                           delta_pp=100*(len(repairs)-len(losses))/len(valid) if valid else None)
    counts = {}
    for arm in ARMS:
        values = list(rows[arm].values())
        counts[arm] = dict(records=len(values), scored=sum(v['score'] is not None for v in values),
             correct=sum(v['score'] == 1 for v in values),
             first_watch=sum(v['audit']['first_action'] == 'watch_videos' for v in values),
             question_verbatim=sum(v['audit']['every_watch_question_verbatim'] for v in values),
             task_options_nonwhitespace_exact=sum(v['audit']['every_watch_task_options_nonwhitespace_exact'] for v in values),
             exact_template=sum(v['audit']['every_watch_exact_template'] for v in values),
             full_video_coverage=sum(v['audit']['all_input_videos_full'] for v in values),
             compliant=sum(v['audit']['strategy_compliant'] for v in values),
             health={k:sum(v['health'].get(k, 0) for v in values)
                     for k in ['fatal', 'invalid', 'model_errors', 'failed_video_requests']})
    counts['B0']['historical_prediction_matches'] = sum(v['prediction'] == meta[s]['historical_prediction']
                                                        for s, v in rows['B0'].items())
    save(root / 'comparison.json', dict(expected=len(meta), arms=rows, counts=counts, paired=paired))
    lines = ['# 原题完整传入 watch：错题恢复实验',
             f'开发错题 {len(meta)} 道；历史 E2E 全对、Agent 全错。只衡量恢复，不能推断总体净收益。', '',
             '|组别|已评分|正确|首次watch|成功watch均保留完整原文|题干选项非空白字符一致|精确模板|完整视频覆盖|',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm in ARMS:
        c = counts[arm]
        lines.append(f"|{arm}|{c['scored']}|{c['correct']}|{c['first_watch']}|{c['question_verbatim']}|{c['task_options_nonwhitespace_exact']}|{c['exact_template']}|{c['full_video_coverage']}|")
    lines += ['', '|范围|配对已评分|WQ修复B0|WQ损失B0|差值pp|', '|---|---:|---:|---:|---:|']
    for name, c in paired.items():
        lines.append(f"|{name}|{c['paired_scored']}|{len(c['repairs'])}|{len(c['losses'])}|{c['delta_pp']}|")
    lines += ['', '缺失/失败不记为零；遵循率分母见counts.records。超过4视频分批组单列。',
              'instruction包含原题原文及固定证据包装，不等于裸原题。原题中的候选是待分析文本，不是视觉事实。',
              '内部invalid/model/Video失败及逐条instruction检查见comparison.json。无自动部署。']
    (root / 'report.md').write_text('\n'.join(lines) + '\n')


def run(root, summarizer=None, preflight_handler=None):
    import psutil
    import yaml
    lock = (root / 'controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for proc in psutil.process_iter(['pid', 'cmdline']):
        cmd = proc.info['cmdline'] or []
        if proc.pid != os.getpid() and any(str(root) in arg for arg in cmd) and any(arg.endswith('/run.py') for arg in cmd):
            raise RuntimeError('Owning child still alive; cannot resume.')
    protocol = verify(root)
    summarizer = summarizer or summarize
    repo = Path(protocol['repo'])
    sys.path.insert(0, str(root / 'frozen/src'))
    from mvagent.batch import BatchExecutor, ExecutionConfig
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = 'localhost,127.0.0.1'
    events = []
    pool = BatchExecutor(ExecutionConfig.from_yaml(root / 'execution.yaml'), on_event=events.append)
    try:
        pool.prepare(yaml.safe_load((root / 'B0.yaml').read_text()))
        prepared = next(e for e in events if e['kind'] == 'batch_prepared')
        if prepared['question_workers'] != 6 or prepared['unavailable']:
            raise RuntimeError('Expected six verified 35B endpoints.')
    finally:
        pool.close()
        save(root / 'pool_verification.json', events)
    done = []
    start = time.time()
    for stage in protocol['stages']:
        arm = stage.split('_')[-1]
        smoke = stage.startswith('preflight')
        ids_file = root / protocol.get('stage_ids', {}).get(
            stage, 'preflight_ids.json' if smoke else 'sample_ids.json')
        out = root / 'runs' / stage
        timing = root / 'timings' / (stage + '.json')
        if timing.exists() and (out / 'summary.json').exists() and read(out / 'run_manifest.json')['status'] == 'completed':
            if smoke and preflight_handler is not None:
                preflight_handler(root, arm, out)
            done.append(stage)
            continue
        source = root / protocol.get('source_roots', {}).get(arm, 'frozen')
        env = dict(os.environ, PYTHONPATH=str(source / 'src'), MVAGENT_PROJECT_ROOT=str(source))
        cmd = [PYTHON, str(source / 'eval/agent_eval/run.py'), '--config', str(root / f'{arm}.yaml'),
               '--execution-config', str(root / 'execution.yaml'), '--sample-ids-file', str(ids_file),
               '--output', str(out), '--benchmarks', 'crossvid', 'cvbench', 'mvu_eval']
        if (out / 'run_manifest.json').exists():
            cmd.append('--resume')
        begin = time.time()
        with (root / (stage + '.log')).open('ab') as log:
            child = subprocess.Popen(cmd, cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            save(root / 'status.json', dict(stage=stage, pid=os.getpid(), child_pid=child.pid,
                 started_at=start, updated_at=time.time(), completed=done, expected=protocol['n']))
            code = child.wait()
        if code:
            raise RuntimeError(f'{stage} exited {code}; partial records retained, owning controller can resume.')
        summary = read(out / 'summary.json')
        assert summary['total_expected'] == len(read(ids_file)) and summary['total_pending'] == 0
        prepared = [e for e in map(json.loads, (out / 'execution_events.jsonl').read_text().splitlines()) if e['kind'] == 'batch_prepared']
        assert prepared and all(e['question_workers'] == 6 and not e['unavailable'] for e in prepared)
        if smoke:
            if preflight_handler is not None:
                preflight_handler(root, arm, out)
            else:
                skill_path = root / f'{arm}.md'
                audit = preflight_audit(out, skill_path.read_text().strip() if skill_path.exists() else None)
                save(root / (stage + '_audit.json'), audit)
                check_preflight(audit, arm)
        save(timing, dict(seconds=time.time()-begin, n=len(read(ids_file))))
        done.append(stage)
        if stage == 'preflight_' + protocol['arms'][-1]:
            seconds = 0
            for a in protocol['arms']:
                measured = read(root / 'timings' / f'preflight_{a}.json')
                stages = [s for s in protocol['stages'] if not s.startswith('preflight') and s.split('_')[-1] == a]
                n = sum(len(read(root / protocol.get('stage_ids', {}).get(s, 'sample_ids.json'))) for s in stages)
                seconds += measured['seconds'] * n / measured['n']
            save(root / 'estimate.json', dict(main_hours=seconds/3600,
                 note='Measured per-arm preflight throughput; approximate, not a time limit.'))
        if not smoke:
            summarizer(root)
    summarizer(root)
    save(root / 'status.json', dict(stage='completed', pid=os.getpid(), started_at=start,
         updated_at=time.time(), completed=done, expected=protocol['n']))


def launch(root, reuse_preflight=None):
    import psutil
    if not (root / 'protocol.json').exists():
        prepare(root, reuse_preflight)
    if (root / 'process.json').exists():
        pid = read(root / 'process.json')['pid']
        if psutil.pid_exists(pid) and str(root) in ' '.join(psutil.Process(pid).cmdline()):
            raise RuntimeError('Controller already running.')
    verify(root)
    with (root / 'controller.log').open('ab') as log:
        proc = subprocess.Popen([PYTHON, str(root / 'run_original_question_watch.py'), 'run', '--output', str(root)],
             cwd=read(root / 'protocol.json')['repo'], stdin=subprocess.DEVNULL,
             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    save(root / 'process.json', dict(pid=proc.pid, launched_at=time.time()))
    print('launched', proc.pid, root, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'launch', 'run', 'summarize'])
    parser.add_argument('--output', type=Path, default=REPO / 'outputs/analysis/20260921_original_question_watch')
    parser.add_argument('--reuse-preflight', type=Path, help='Completed, identical preflight in another immutable root; identity checked before reuse.')
    args = parser.parse_args()
    try:
        if args.reuse_preflight is not None and args.mode not in {'prepare', 'launch'}:
            parser.error('--reuse-preflight is only valid with prepare/launch')
        if args.mode in {'prepare', 'launch'}:
            globals()[args.mode](args.output.resolve(), args.reuse_preflight)
        else:
            globals()[args.mode](args.output.resolve())
    except BaseException as exc:
        if args.mode == 'run':
            save(args.output / 'status.json', dict(stage='failed', error=str(exc), pid=os.getpid(), updated_at=time.time()))
        raise
