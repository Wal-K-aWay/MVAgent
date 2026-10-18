"""Small, isolated System-only ablation; production src/configs stay frozen."""
import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'eval/e2e_eval')]
OUT = Path('/runs/devbox/system_refinements_20261018')
BASE = Path('/runs/devbox/global_short_large_20261017')
PILOT = Path('/runs/devbox/system_ablation_20261017')
MODELS = {'9B': '9b', '27B': '27b', '35B-A3B': '35b_a3b'}
ARMS = ('video_fidelity', 'global_brief')
GLOBAL = 'src/mvagent/agents/global_agent/prompts.py'
VIDEO = 'src/mvagent/agents/video_agent/prompts.py'
AGENT = 'src/mvagent/agents/video_agent/agent.py'
VIDEO_RULE = 'Keep observations, inferences, and unknowns distinct; preserve uncertainty when summarizing evidence.'
GLOBAL_RULE = 'Keep explanations brief and focus on evidence that changes the next decision.'
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temp.replace(path)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def add_system_rule(source, name, rule):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    value = ast.literal_eval(node.value)
    assert rule not in value, 'Candidate already applied'
    lines = source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = [f'{name} = {value + chr(10)*2 + rule!r}\n']
    return ''.join(lines)


def sources(arm):
    original = {p: (ROOT/p).read_text() for p in (GLOBAL, VIDEO, AGENT)}
    changed = dict(original)
    if arm == 'global_brief':
        changed[GLOBAL] = add_system_rule(original[GLOBAL], 'GLOBAL_AGENT_SYSTEM_PROMPT', GLOBAL_RULE)
    else:
        assert arm == 'video_fidelity'
        changed[VIDEO] = add_system_rule(original[VIDEO], 'VIDEO_PLANNER_SYSTEM_PROMPT', VIDEO_RULE)
        assert original[AGENT].count('system_prompt="",') == 1
        changed[AGENT] = original[AGENT].replace('system_prompt="",', f'system_prompt={VIDEO_RULE!r},')
    return {p: text for p, text in changed.items() if text != original[p]}


def select(rows):
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda r: r['sample_id']):
        groups[row['dataset'], row['task']].append(row)
    rng = random.Random(0)
    ids = []
    for dataset, count in [('cvbench', 15), ('mvu_eval', 15), ('crossvid', 20)]:
        keys = sorted(k for k in groups if k[0] == dataset)
        quota = {k: 2 if dataset == 'crossvid' else 1 for k in keys}
        weights = {k: groups[k][0]['task_population'] for k in keys}
        while sum(quota.values()) < count:
            available = [k for k in keys if quota[k] < len(groups[k])]
            k = max(available, key=lambda k: count*weights[k]/sum(weights.values())-quota[k])
            quota[k] += 1
        assert sum(quota.values()) == count
        for key in keys:
            ids.extend(r['sample_id'] for r in rng.sample(groups[key], quota[key]))
    rng.shuffle(ids)
    assert len(ids) == len(set(ids)) == 50
    return ids


def prepare():
    from models.vlm.local.sync_server import execution_profile
    assert not OUT.exists(), 'Use a fresh output directory'
    prior = read(BASE/'manifest.json')
    core = {p: digest for p, digest in prior['actor_source_hashes'].items()
            if p.startswith(('src/mvagent/', 'src/models/', 'configs/inference/')) and p.endswith(('.py', '.yaml'))}
    assert core and all(sha(ROOT/p) == digest for p, digest in core.items())
    assert execution_profile() == prior['profile']
    pilot_ids = set(read(PILOT/'samples.json'))
    previous = {m: [r for r in read(BASE/'analysis'/f'{m}_paired.json') if r['sample_id'] in pilot_ids] for m in MODELS}
    assert all(len(rows) == 102 for rows in previous.values())
    ids = select(previous['9B'])
    baseline = {m: [r for r in rows if r['sample_id'] in ids] for m, rows in previous.items()}
    for rows in baseline.values():
        assert len(rows) == 50
        for row in rows:
            assert sha(row['path']) == row['sha256'], row['path']
    OUT.mkdir(parents=True)
    write(OUT/'samples.json', ids)
    write(OUT/'baseline.json', baseline)
    cards = {m: read(PILOT/'global_short'/m/'startup_identity.json') for m in MODELS}
    write(OUT/'baseline_services.json', cards)
    sys.path.insert(0, str(ROOT/'eval/agent_eval'))
    from score_crossvid_ccqa import JUDGE_MODEL, SCORE_PROMPT
    qa = {int(r['id']): r for r in read('/assets/crossvid/QA/CCQA.json')}
    for model, rows in baseline.items():
        for row in rows:
            if row['task'] != 'CCQA':
                continue
            item = qa[int(row['sample_id'].rsplit(':', 1)[1])]
            prompt = SCORE_PROMPT.format(QUESTION=item['question'], ANSWER=item['answer'],
                POINTS=item['scoring_points'], OUTPUT=row['arms']['direct']['prediction'].strip())
            key = hashlib.sha256(json.dumps(dict(model=JUDGE_MODEL, prompt=prompt),
                                           ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            cached = read(Path(row['path']).parents[3]/'ccqa_judge_cache'/key[:2]/f'{key}.json')
            assert cached['status'] == 'ok'
            assert abs(cached['score']/(2*len(cached['coverage']))-row['arms']['direct']['score']) < 1e-8
            write(OUT/'judge_cache'/model/key[:2]/f'{key}.json', cached)
    for arm in ARMS:
        patches = []
        for p, text in sources(arm).items():
            target = OUT/arm/'code'/p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            patches.extend(difflib.unified_diff((ROOT/p).read_text().splitlines(True), text.splitlines(True),
                                               fromfile=p, tofile=p))
        (OUT/arm/'system.patch').write_text(''.join(patches))
    with tarfile.open(OUT/'source.tar.gz', 'w:gz', compresslevel=1) as archive:
        for name in ['src', 'scripts', 'configs', 'eval', '.git', 'requirements.txt', 'demo.py']:
            archive.add(ROOT/name, arcname=name,
                        filter=lambda t: None if {'__pycache__', '.cache'} & set(Path(t.name).parts) else t)
    commit = (ROOT/'.git/HEAD').read_text().strip()
    assert re.fullmatch(r'[0-9a-f]{40}', commit), 'Stage an immutable detached source checkout'
    manifest = dict(at=now(), commit=commit,
        baseline_commit='f61946fd9a80daeee025de28b15745605174ab61', profile=execution_profile(),
        archive_sha256=sha(OUT/'source.tar.gz'), baseline_sha256=sha(OUT/'baseline.json'),
        samples_sha256=sha(OUT/'samples.json'), baseline_services_sha256=sha(OUT/'baseline_services.json'),
        actor_hashes=core, source_changes={a: {p: sha(OUT/a/'code'/p) for p in sources(a)} for a in ARMS},
        rules=dict(video_fidelity=VIDEO_RULE, global_brief=GLOBAL_RULE),
        selection_seed=0, inference_seed=0, reused_baseline=150, new_trajectories=300,
        per_model=dict(cvbench=15, mvu_eval=15, crossvid=20),
        expected_hours=.45+1.4*2*sum(r['stats']['seconds'] for rows in baseline.values() for r in rows)/8/3600,
        selection='Task-stratified subset of the existing 102-question development panel; no outcome selection.',
        limits='Small screening; one CV sample per task. No confidence claim or universal positive-gain guarantee.')
    write(OUT/'manifest.json', manifest)
    write(OUT/'progress.json', dict(phase='prepared', at=now(), units={}, expected=300))
    print(json.dumps({k: v for k, v in manifest.items() if k not in ['actor_hashes', 'profile']}), flush=True)


def worker():
    import yaml
    manifest = read(OUT/'manifest.json')
    assert sha(OUT/'source.tar.gz') == manifest['archive_sha256']
    state = read(OUT/'progress.json')
    assert state['phase'] == 'prepared', 'Do not duplicate or silently resume a controller'
    work = Path('/work/system-refinements')
    work.mkdir(exist_ok=False)
    candidates = {}
    for arm in ARMS:
        source = work/arm
        source.mkdir()
        with tarfile.open(OUT/'source.tar.gz') as archive:
            archive.extractall(source, filter='fully_trusted')
        for p, digest in manifest['source_changes'][arm].items():
            assert sha(OUT/arm/'code'/p) == digest
            shutil.copy2(OUT/arm/'code'/p, source/p)
        candidates[arm] = source
    launcher = work/'prelaunch.py'
    launcher.write_text(Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"', repr(str(ROOT/'src'))))
    hardware = subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid', '--format=csv,noheader'], text=True)
    assert len(hardware.splitlines()) == 8 and all('H100' in line for line in hardware.splitlines())
    state.update(started_at=now(), hardware=hardware)

    def save(phase, **fields):
        state.update(phase=phase, at=now(), **fields)
        write(OUT/'progress.json', state)

    def run(args, log_name, source=ROOT, target=None):
        with (OUT/log_name).open('a') as log:
            proc = subprocess.Popen(list(map(str, args)), cwd=source, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONPATH': str(source/'src'), 'MVAGENT_PROJECT_ROOT': str(source),
                     'PYTHONDONTWRITEBYTECODE': '1'})
        while proc.poll() is None:
            if target:
                state['units'][str(target.relative_to(OUT))]['finished'] = sum(1 for _ in target.glob('records/*/*/result.json'))
            save(state['phase'])
            time.sleep(15)
        if proc.returncode:
            raise RuntimeError(f'{log_name}: rc={proc.returncode}')

    try:
        for arm, source in candidates.items():
            run([sys.executable, source/'scripts/test_direct_answer.py'], f'{arm}_contract.log', source)
        for index, (model, slug) in enumerate(MODELS.items()):
            cfg = yaml.safe_load((ROOT/f'configs/inference/modal_qwen35_{slug}_no_skill.yaml').read_text())
            exname = 'modal_h200x8.yaml' if model == '35B-A3B' else f'modal_h200x8_qwen35_{slug}.yaml'
            ex = yaml.safe_load((ROOT/'configs/inference/execution'/exname).read_text())
            cfg['runtime']['cache_dir'] = str(OUT/'services'/model)
            ex['media_cache']['root'] = str(work/'media'/model)
            pool = next(iter(cfg['models']))
            replicas = ex['model_pools'][pool]['replicas']
            assert len(replicas) == 8 and all(r['max_inflight'] == 1 and len(r['gpus']) == 1 for r in replicas)
            ports = list(range(8100+100*index, 8108+100*index))
            for replica, port in zip(replicas, ports):
                replica['endpoint'] = f'http://127.0.0.1:{port}/v1'
            service = OUT/'services'/model
            service.mkdir(parents=True)
            for name, value in [('config.yaml', cfg), ('execution.yaml', ex)]:
                (service/name).write_text(yaml.safe_dump(value, sort_keys=False))
            save('loading', model=model, arm=None)
            run([sys.executable, launcher, '--replace', service/'config.yaml', service/'execution.yaml', pool], f'{model}_startup.log')
            from models.vlm.local.sync_server import validate_card
            cards = []
            previous = read(OUT/'baseline_services.json')[model][0]
            for port in ports:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=15) as response:
                    card = json.load(response)['data'][0]
                validate_card(card)
                assert card['execution'] == manifest['profile']
                for field in ['id', 'weights_manifest']:
                    assert card[field] == previous[field], (model, field)
                cards.append(card)
            assert len({c['worker']['gpu_uuid'] for c in cards}) == 8
            write(service/'startup_identity.json', cards)
            # Alternate order across models; do not attribute warm-cache timing to the System text.
            for arm in (ARMS if index % 2 == 0 else ARMS[::-1]):
                source = candidates[arm]
                target = OUT/arm/model
                state['units'][str(target.relative_to(OUT))] = dict(expected=50, finished=0)
                save('inference', model=model, arm=arm)
                run([sys.executable, source/'eval/agent_eval/run.py', '--config', service/'config.yaml',
                     '--execution-config', service/'execution.yaml', '--dataset-root', '/assets',
                     '--sample-ids-file', OUT/'samples.json', '--output', target, '--defer-open-qa-judge'],
                    f'{arm}_{model}_inference.log', source, target)
                rows = [read(p) for p in target.glob('records/*/*/result.json')]
                assert {r['sample_id'] for r in rows} == set(read(OUT/'samples.json'))
                errors = [r['sample_id'] for r in rows if r['status'] != 'ok']
                state['units'][str(target.relative_to(OUT))].update(finished=50, valid=50-len(errors), errors=errors)
                (target/'ccqa_judge_cache').symlink_to(OUT/'judge_cache'/model, target_is_directory=True)
                save('unit_completed')
        save('judge_loading', arm=None, model=None)
        subprocess.run(['pkill', '-f', '[s]ync_server.py'], check=False)
        deadline = time.monotonic()+600
        while time.monotonic() < deadline:
            used = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).split()
            if used and all(int(n) < 2048 for n in used):
                break
            time.sleep(5)
        else:
            raise TimeoutError('Actor GPU memory did not release')
        os.environ['JUDGE_LOG_DIR'] = str(OUT/'judge_servers')
        run(['bash', ROOT/'eval/agent_eval/serve_ccqa_judge.sh', '0-7', '8400'], 'judge_startup.log')
        for arm in ARMS:
            for model in MODELS:
                save('judging', arm=arm, model=model)
                run([sys.executable, ROOT/'eval/agent_eval/score_crossvid_ccqa.py', '--output', OUT/arm/model,
                     '--endpoints', '8400-8407'], f'{arm}_{model}_judge.log')
                assert not read(OUT/arm/model/REPORT)['failed_ids']
        save('inference_and_judge_completed', finished_at=now())
    except BaseException as exc:
        save('failed', error=repr(exc), traceback=traceback.format_exc())
        raise


def self_check():
    for arm in ARMS:
        patched = sources(arm)
        assert set(patched) == ({GLOBAL} if arm == 'global_brief' else {VIDEO, AGENT})
        for path, text in patched.items():
            original = (ROOT/path).read_text()
            if path == AGENT:
                restored = text.replace(f'system_prompt={VIDEO_RULE!r},', 'system_prompt="",')
                assert restored == original
            else:
                before, after = ast.parse(original), ast.parse(text)
                for tree in [before, after]:
                    for node in tree.body:
                        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id.endswith('SYSTEM_PROMPT') for t in node.targets):
                            node.value = ast.Constant('system')
                assert ast.dump(before) == ast.dump(after), path
    rows = [dict(sample_id=f'{dataset}:{task}:{i}', dataset=dataset, task=str(task), task_population=task+1)
            for dataset, tasks in [('cvbench', 15), ('mvu_eval', 8), ('crossvid', 10)]
            for task in range(tasks) for i in range(3)]
    chosen = select(rows)
    assert chosen == select([{**r, 'score': 1, 'prediction': 'ignored'} for r in reversed(rows)])
    assert Counter(s.split(':')[0] for s in chosen) == dict(cvbench=15, mvu_eval=15, crossvid=20)
    assert len({s.rsplit(':', 1)[0] for s in chosen}) == 33
    print('Independent candidates change only their specified System messages; User/schema/Observer unchanged')


def measure(text, record, scorer):
    from harness.answers import leads_with_choice, option_labels, read_choice, read_interval, read_letters, read_order, read_yes_no
    text = str(text or '').strip()
    options = record.sample.options
    embedded = re.findall(r'(?:^|[,;\n])\s*\(?([A-Z])[.):]\s', '\n'.join(options))
    labels = ''.join(dict.fromkeys(embedded)) if embedded else option_labels(options)
    task = record.native_task
    if task == 'FSA' and record.dataset == 'crossvid':
        try:
            bounds = [float(x) for x in text.split(',')]
            valid = len(bounds) == 2 and all(math.isfinite(x) for x in bounds)
        except ValueError:
            valid = False
        parsed = text if valid else read_interval(text)
    elif task == 'PSS' and record.dataset == 'crossvid':
        valid = bool(re.fullmatch(r'\d+(?:->\d+)+', text))
        parsed = text if valid else read_order(text)
    elif task == 'BU' and record.dataset == 'crossvid':
        valid = bool(re.fullmatch(rf'[{re.escape(labels)}]+', text))
        parsed = read_letters(text, labels)
    else:
        valid = (bool(re.fullmatch(rf'[{re.escape(labels)}]', text)) if record.dataset == 'crossvid'
                 else leads_with_choice(text, labels))
        parsed = read_choice(text, labels)
        if record.dataset == 'cvbench':
            valid = valid or bool(re.match(r'(?i:yes|no)\b', text))
            parsed = parsed or read_yes_no(text)
    return dict(prediction=text, empty=not text, brace_only=text == '}', format_ok=valid,
                score=scorer.score_prediction(record.sample_id, text).score,
                robust_score=scorer.score_prediction(record.sample_id, parsed or '').score)


def stats(raw):
    events = raw.get('events') or []
    calls = [e for e in events if e['kind'] == 'model_response']
    for e in calls:
        assert len(e['token_ids']) == e['usage']['completion_tokens']
        assert e['usage']['prompt_tokens_details']['cached_tokens'] == 0
        assert e['request_sha256'] and e['prompt_token_ids_sha256']
    assert len({(e['worker']['pid'], e['worker']['gpu_uuid']) for e in calls}) <= 1
    return dict(calls=len(calls), tokens=sum(len(e['token_ids']) for e in calls),
                seconds=(raw.get('result') or {}).get('time'),
                model_errors=sum(e['kind'] == 'model_error' for e in events),
                structured_invalid=sum(e['kind'] == 'structured_invalid' for e in events),
                repairs=sum(e['kind'] == 'structured_repair' for e in events),
                truncations=sum(e['finish_reason'] == 'length' for e in calls))


def analyze():
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer
    from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator
    baseline = read(OUT/'baseline.json')
    ids = read(OUT/'samples.json')
    records = load_multibench_records('/assets', ids)
    scorer, identity = build_official_scorer(records, {})
    meta = {r['sample_id']: r for r in baseline['9B']}
    aggregator = HierarchicalScoreAggregator(dataset_of={s: meta[s]['dataset'] for s in ids},
        category_of={s: meta[s]['task'] for s in ids},
        task_population={(r['dataset'], r['task']): r['task_population'] for r in meta.values()},
        sample_weights={s: meta[s]['points'] for s in ids})
    result = dict(at=now(), scorer=identity, models={}, complete=True,
                  limits='Development screening; small strata, no confidence-interval or universal gain claim.')
    for model in MODELS:
        old = {r['sample_id']: r for r in baseline[model]}
        all_rows = []
        missing = []
        for sid in ids:
            original = old[sid]
            assert sha(original['path']) == original['sha256']
            row = {k: original[k] for k in ['sample_id', 'dataset', 'task', 'task_population', 'points']}
            row['arms'] = {'baseline': dict(original['arms']['direct'])}
            row['stats'] = {'baseline': stats(read(original['path']))}
            if row['task'] != 'CCQA':
                row['arms']['baseline'] = measure(row['arms']['baseline']['prediction'], records[sid], scorer)
                assert abs(row['arms']['baseline']['score']-original['arms']['direct']['score']) < 1e-8
            for arm in ARMS:
                path = OUT/arm/model/'records'/row['dataset']/sid/'result.json'
                if not path.exists():
                    missing.append(dict(arm=arm, sample_id=sid, reason='missing'))
                    continue
                raw = read(path)
                if raw['status'] != 'ok':
                    missing.append(dict(arm=arm, sample_id=sid, reason=raw.get('error') or raw['status']))
                    continue
                row['stats'][arm] = stats(raw)
                if row['task'] == 'CCQA':
                    report = read(OUT/arm/model/REPORT)
                    assert not report['failed_ids']
                    j = next(r for r in report['samples'] if r['id'] == int(sid.rsplit(':', 1)[1]))
                    assert j['status'] == 'ok' and j['prediction'] == raw['prediction'].strip()
                    score = j['score']/(2*len(j['coverage']))
                    row['arms'][arm] = dict(prediction=raw['prediction'], score=score, format_ok=None,
                        empty=not raw['prediction'].strip(), brace_only=raw['prediction'].strip() == '}')
                    if raw['prediction'].strip() == row['arms']['baseline']['prediction'].strip():
                        assert abs(score-row['arms']['baseline']['score']) < 1e-8, 'Shared Judge cache failed'
                else:
                    row['arms'][arm] = measure(raw['prediction'], records[sid], scorer)
                    assert abs(row['arms'][arm]['score']-raw['score']) < 1e-8
            all_rows.append(row)
        report = dict(missing_or_errors=missing, benchmarks={}, stability={})
        result['complete'] &= not missing
        for dataset in ['cvbench', 'mvu_eval', 'crossvid']:
            paired = [r for r in all_rows if r['dataset'] == dataset and len(r['arms']) == 3]
            if not paired:
                continue
            scores = {}
            robust = {}
            for arm in ['baseline', *ARMS]:
                values = {r['sample_id']: r['arms'][arm]['score'] for r in paired}
                scores[arm] = aggregator.aggregate(sample_ids=list(values), scores=values, buckets={}).official_score
                values = {r['sample_id']: r['arms'][arm].get('robust_score', r['arms'][arm]['score']) for r in paired}
                robust[arm] = aggregator.aggregate(sample_ids=list(values), scores=values, buckets={}).official_score
            report['benchmarks'][dataset] = dict(n=len(paired), scores=scores, robust_scores=robust,
                paired={a: dict(wins=sum(r['arms'][a]['score'] > r['arms']['baseline']['score'] for r in paired),
                                losses=sum(r['arms'][a]['score'] < r['arms']['baseline']['score'] for r in paired)) for a in ARMS})
        for arm in ['baseline', *ARMS]:
            rows = [r for r in all_rows if arm in r['arms']]
            report['stability'][arm] = dict(n=len(rows),
                format_errors=sum(r['arms'][arm].get('format_ok') is False for r in rows),
                closed_n=sum(r['task'] != 'CCQA' for r in rows),
                empty=sum(r['arms'][arm]['empty'] for r in rows), braces=sum(r['arms'][arm]['brace_only'] for r in rows),
                **{k: sum(r['stats'][arm][k] or 0 for r in rows) for k in
                   ['calls', 'tokens', 'seconds', 'model_errors', 'structured_invalid', 'repairs', 'truncations']})
        write(OUT/'analysis'/f'{model}_paired.json', all_rows)
        result['models'][model] = report
    write(OUT/'analysis/summary.json', result)
    print(json.dumps(result), flush=True)
    assert result['complete'], 'Missing/error records are reported separately, never silently scored zero'


def host():
    """Dev-box-only lifecycle owner for this one Sandbox."""
    import fcntl
    import modal
    sys.path.insert(0, str(Path.home()/'wxu-evolve-agent/devbox'))
    import devbox
    name = 'mvagent-system-refinements-20261018'
    devbox.REPO = str(ROOT)
    devbox.NAME = name
    devbox.STATE = str(Path(devbox.HERE)/f'state-{name}.json')
    lock = (Path(devbox.HERE)/f'{name}.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not Path(devbox.STATE).exists(), 'Do not replace another controller'
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    sandbox = None
    try:
        sys.argv = ['devbox.py', 'up', '--gpu', 'H100!:8', '--no-pool', '--hours', '3', '--idle', '15']
        devbox.main()
        sandbox = devbox._sandbox()
        print('OWNED_SANDBOX', sandbox.object_id, flush=True)
        devbox.start_job(sandbox, 'system_refinements_20261018', 'python /repo/scripts/system_refinements.py worker')
        deadline = time.monotonic()+10200
        while time.monotonic() < deadline:
            state = json.loads(b''.join(volume.read_file('devbox/system_refinements_20261018/progress.json')))
            print(now(), json.dumps(state), flush=True)
            if state['phase'] in ['inference_and_judge_completed', 'failed'] or sandbox.poll() is not None:
                break
            time.sleep(45)
        assert state['phase'] == 'inference_and_judge_completed', state
    finally:
        if sandbox is None and Path(devbox.STATE).exists():
            sandbox = devbox._sandbox()
        if sandbox is not None and sandbox.poll() is None:
            sandbox.terminate(wait=True)
        Path(devbox.STATE).unlink(missing_ok=True)
        print('OWNED_GPU_RELEASED', now(), flush=True)
    import cpujob
    command = ('mkdir -p /tmp/system-refinements-analysis && '
               'tar xzf /runs/devbox/system_refinements_20261018/source.tar.gz -C /tmp/system-refinements-analysis && '
               'python /tmp/system-refinements-analysis/scripts/system_refinements.py analyze')
    with cpujob.app.run(environment_name='zheng-dev'):
        rc, out, err = cpujob.job.remote(command)
    print(out, err, flush=True)
    assert rc == 0, rc
    print('ANALYSIS_COMPLETED', now(), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['self-check', 'prepare', 'worker', 'analyze', 'host'])
    args = parser.parse_args()
    globals()[args.mode.replace('-', '_')]()
