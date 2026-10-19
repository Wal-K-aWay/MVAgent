"""Complete the frozen no-skill baseline, reusing the 4,500 validated rollouts."""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request

from run_full_e2e import now, read, write, sha

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'eval/e2e_eval')]
TAG = 'frozen_full_final_20261019'
PARENT = Path('/runs/devbox/frozen_full_20261018')
OTHER = Path('/runs/devbox/frozen_full_recovery_20261019')
OUT = Path('/runs/devbox')/TAG
BASE = Path('/runs/devbox/global_short_large_20261017')
PILOT = Path('/runs/devbox/system_ablation_20261017')
ARCHIVES = Path('/runs/devbox/video_context_storage_20261018')
MODELS = {'9B': '9b', '27B': '27b', '35B-A3B': '35b_a3b'}
EXPECTED = dict(cvbench=997, mvu_eval=1824, crossvid=2500)
E2E = {m: Path('/runs/devbox')/('e2e_full_20261012' if m == '9B' else 'e2e_full_20261013_timeout')/m for m in MODELS}
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'


def partitions(ids, reused):
    assert len(ids) == len(set(ids)) and set(reused) <= set(ids)
    pending = [sid for sid in ids if sid not in set(reused)]
    random.Random(0).shuffle(pending)
    return [pending[::2], pending[1::2]]


def prepare():
    from concurrent.futures import ThreadPoolExecutor
    from models.vlm.local.sync_server import execution_profile
    assert not OUT.exists(), 'Never overwrite an existing recovery'
    prior = read(PARENT/'manifest.json')
    assert read(PARENT/'shard0/progress.json')['phase'] == 'failed'
    media = 'src/mvagent/utils/media.py'
    changed = {p for p, digest in prior['actor_hashes'].items() if sha(ROOT/p) != digest}
    assert changed == {media} and execution_profile() == prior['profile']
    OUT.mkdir(parents=True)
    for name in ['samples.json', 'selection.json', 'baseline.json', 'baseline_services.json', 'known_unavailable.json']:
        shutil.copy2(PARENT/name, OUT/name)
        assert sha(OUT/name) == sha(PARENT/name)
    # The running shard keeps its own source, results and GPU owner.
    (OUT/'shard1').symlink_to(OTHER/'shard1', target_is_directory=True)
    group = OUT/'shard0'
    group.mkdir()
    shutil.copy2(PARENT/'shard0/samples.json', group/'samples.json')
    ids = set(read(group/'samples.json'))
    inherited, failed = [], []
    def inspect(path):
        data = path.read_bytes()
        raw = json.loads(data)
        assert raw['sample_id'] in ids
        if raw['status'] == 'ok':
            stats(raw)
        return path, raw['sample_id'], raw['status'], hashlib.sha256(data).hexdigest()
    files = [p for m in MODELS for p in (PARENT/'shard0'/m).glob('records/*/*/result.json')]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for path, sid, status, digest in pool.map(inspect, files):
            rel = path.relative_to(PARENT/'shard0')
            row = dict(sample_id=sid, model=rel.parts[0], source=str(path), sha256=digest)
            if status != 'ok':
                failed.append(row)
                continue
            target = group/rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(path)
            inherited.append(row)
    counts = Counter(r['model'] for r in inherited)
    assert counts == {'9B': 1911, '27B': 1910}, counts
    assert [r['sample_id'] for r in failed] == ['crossvid:MOC:552'], failed
    write(OUT/'inheritance.json', dict(inherited=inherited, original_failures=failed,
        prior_progress=read(PARENT/'shard0/progress.json'),
        policy='Only status=ok reused, including wrong/format-invalid model answers. Original files stay unchanged.'))
    write(group/'progress.json', dict(phase='prepared', models={
        '9B': dict(expected=1911, finished=1911, valid=1911, errors=[], inference_done=True)},
        expected=5733, at=now()))
    with tarfile.open(OUT/'source.tar.gz', 'w:gz', compresslevel=1) as archive:
        for name in ['src', 'scripts', 'configs', 'eval', '.git', 'requirements.txt', 'demo.py']:
            archive.add(ROOT/name, arcname=name, filter=lambda t: None if {'__pycache__', '.cache'} & set(Path(t.name).parts) else t)
    manifest = dict(prior, at=now(), commit=(ROOT/'.git/HEAD').read_text().strip(),
        archive_sha256=sha(OUT/'source.tar.gz'), baseline_sha256=sha(OUT/'baseline.json'),
        actor_hashes={p: sha(ROOT/p) for p in prior['actor_hashes']}, parent=str(PARENT),
        parent_manifest_sha256=sha(PARENT/'manifest.json'), inherited_shard0=len(inherited),
        changes={media: 'Keep the two-encoded-frame fix; transcode stream copies only when sampled frames cannot decode.'},
        shard_sources={'0': str(OUT/'source.tar.gz'), '1': str(OTHER/'source.tar.gz')},
        other_manifest_sha256=sha(OTHER/'manifest.json'))
    manifest['parent_free_inodes_at_original_prepare'] = manifest.pop('free_inodes')
    manifest['parent_expected_hours_at_original_prepare'] = manifest.pop('expected_hours')
    write(OUT/'manifest.json', manifest)
    write(OUT/'progress.json', dict(phase='prepared', at=now(), inherited_panel=4500, inherited_shard0=len(inherited), expected=15963))
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['actor_hashes','profile']}), flush=True)


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



def score(rows, arm):
    if not rows:
        return None
    if rows[0]['dataset'] != 'crossvid':
        return sum(r['arms'][arm]['score'] for r in rows)/len(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[row['task']].append(row)
    if len(groups) != 10:
        return None
    return sum(sum(r['arms'][arm]['score']*(r['points'] if task == 'CCQA' else 1) for r in group)/
               sum(r['points'] if task == 'CCQA' else 1 for r in group) for task, group in groups.items())/10


def analyze():
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records, build_official_scorer
    manifest = read(OUT/'manifest.json')
    assert sha(OUT/'baseline.json') == manifest['baseline_sha256']
    selection = read(OUT/'selection.json')
    records = load_multibench_records('/assets', selection['ids'])
    scorer, scorer_identity = build_official_scorer(records, {})
    baseline = read(OUT/'baseline.json')
    summary = dict(at=now(), complete=True, models={}, scorer=scorer_identity,
        note='Full available evaluation; includes 1500 reused development questions per model, not independent Test.')
    for model in MODELS:
        old = {r['sample_id']: r for r in baseline[model]}
        e2e = {r['sample_id']: r for ds in EXPECTED for r in read(E2E[model]/'scored'/f'{ds}.json')}
        mvu = {r['sample_id']: r for r in map(json.loads, (Path('/runs/devbox/mvu_instruction_after_20261014')/model/'raw/mvu_eval.jsonl').read_text().splitlines())}
        rows, errors, missing = [], [], []
        for sid, original in old.items():
            rows.append(dict(original, arms=dict(agent=original['arms']['direct'], e2e=original['arms']['e2e']), reused=True))
        for shard, part in enumerate(selection['partitions']):
            target = OUT/f'shard{shard}'/model
            report = read(target/REPORT) if (target/REPORT).exists() else dict(samples=[], failed_ids=[])
            assert not report['failed_ids'], 'Judge failure is not a zero score'
            judges = {f"crossvid:CCQA:{r['id']}": r for r in report['samples']}
            for sid in part:
                record = records[sid]
                path = target/'records'/record.dataset/sid/'result.json'
                if not path.exists():
                    missing.append(sid); continue
                raw = read(path)
                if raw['status'] != 'ok':
                    errors.append(dict(sample_id=sid, path=str(path), error=raw.get('error'))); continue
                measured = stats(raw)
                if record.native_task == 'CCQA':
                    if sid not in judges:
                        missing.append(sid+' (Judge)'); continue
                    j = judges[sid]
                    assert j['status'] == 'ok' and j['prediction'] == raw['prediction'].strip()
                    agent = dict(prediction=raw['prediction'], score=j['score']/(2*len(j['coverage'])),
                        format_ok=None, empty=not raw['prediction'].strip(), brace_only=raw['prediction'].strip() == '}')
                    before = dict(prediction=e2e[sid]['prediction'], score=e2e[sid]['score'])
                else:
                    agent = measure(raw['prediction'], record, scorer)
                    assert abs(agent['score']-raw['score']) < 1e-8
                    before = measure(mvu[sid]['output'] if record.dataset == 'mvu_eval' else e2e[sid]['prediction'], record, scorer)
                rows.append(dict(sample_id=sid, dataset=record.dataset, task=record.native_task,
                    points=len(raw['ground_truth']), arms=dict(agent=agent, e2e=before), stats=measured,
                    path=str(path), sha256=sha(path), reused=False))
        assert len(rows) == len({r['sample_id'] for r in rows})
        metrics = {}
        for ds, expected in EXPECTED.items():
            group = [r for r in rows if r['dataset'] == ds]
            fresh = [r for r in group if not r['reused']]
            metrics[ds] = dict(n=len(group), expected=expected, agent=score(group, 'agent'), e2e=score(group, 'e2e'),
                new_only=dict(n=len(fresh), agent=score(fresh, 'agent'), e2e=score(fresh, 'e2e')))
        result = dict(valid=len(rows), reused=1500, missing=missing, errors=errors, benchmarks=metrics,
            format_errors=sum(r['arms']['agent'].get('format_ok') is False for r in rows),
            empty=sum(r['arms']['agent']['empty'] for r in rows), braces=sum(r['arms']['agent']['brace_only'] for r in rows),
            statistics={k: sum(r['stats'].get(k, 0) or 0 for r in rows) for k in
                ['calls', 'tokens', 'seconds', 'model_errors', 'structured_invalid', 'repairs', 'truncations']})
        summary['models'][model] = result
        summary['complete'] &= len(rows) == 5321 and not missing and not errors
        write(OUT/'analysis'/f'{model}_paired.json', rows)
    write(OUT/'analysis/summary.json', summary)
    write(OUT/'progress.json', dict(phase='completed' if summary['complete'] else 'incomplete',
        reused=4500, new=sum(r['valid']-1500 for r in summary['models'].values()), expected=15963, at=now()))
    print(json.dumps(summary), flush=True)
    assert summary['complete'], 'Missing/failed work remains; see saved analysis, never score infrastructure failures zero'


def self_check():
    parts = partitions(['a', 'b', 'c', 'd', 'e'], ['a', 'c'])
    assert parts == partitions(['a', 'b', 'c', 'd', 'e'], ['a', 'c'])
    assert set(parts[0]).isdisjoint(parts[1]) and set(sum(parts, [])) == {'b', 'd', 'e'}
    try:
        partitions(['a', 'a'], [])
    except AssertionError:
        pass
    else:
        raise AssertionError('Duplicate IDs accepted')
    cross = [dict(dataset='crossvid', task=str(i), points=1, arms={'agent': {'score': 1}}) for i in range(9)]
    cross += [dict(dataset='crossvid', task='CCQA', points=p, arms={'agent': {'score': s}}) for p,s in [(1,1), (3,0)]]
    assert score(cross, 'agent') == .925 and score(cross[:9], 'agent') is None
    print('Disjoint missing-only partitions and official CCQA point weighting passed')


def worker(shard):
    import yaml
    from models.vlm.local.sync_server import validate_card
    manifest = read(OUT/'manifest.json')
    assert sha(OUT/'source.tar.gz') == manifest['archive_sha256']
    source = Path('/work/frozen-full-source')
    source.mkdir()
    with tarfile.open(OUT/'source.tar.gz') as archive:
        archive.extractall(source, filter='fully_trusted')
    group = OUT/f'shard{shard}'
    ids = read(group/'samples.json')
    state = read(group/'progress.json')
    assert state['phase'] not in ('completed', 'failed'), 'Do not silently retry a terminal run'
    launcher = source/'prelaunch.py'
    launcher.write_text(Path('/devtools/prelaunch.py').read_text().replace('"/repo/src"', repr(str(source/'src'))))
    hardware = subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,uuid', '--format=csv,noheader'], text=True)
    assert len(hardware.splitlines()) == 8 and all('H100' in line for line in hardware.splitlines())
    state.update(started_at=now(), hardware=hardware)
    process = None

    def save(phase, **fields):
        state.update(phase=phase, at=now(), **fields)
        write(group/'progress.json', state)

    def run(args, log_name, model=None):
        nonlocal process
        with (group/log_name).open('a') as log:
            process = subprocess.Popen(list(map(str, args)), cwd=source, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONPATH': str(source/'src'), 'MVAGENT_PROJECT_ROOT': str(source),
                     'PYTHONDONTWRITEBYTECODE': '1'}, start_new_session=True)
        while process.poll() is None:
            if model:
                state['models'][model]['finished'] = sum(1 for _ in (group/model).glob('records/*/*/result.json'))
            save(state['phase'])
            time.sleep(30)
        code = process.returncode
        process = None
        if code:
            raise RuntimeError(f'{log_name}: rc={code}')

    def interrupt(signum, frame):
        raise InterruptedError(f'Interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupt)
    try:
        for index, (model, slug) in enumerate(MODELS.items()):
            unit = state['models'].setdefault(model, dict(expected=len(ids), finished=0))
            if unit.get('inference_done'):
                continue
            target = group/model
            service = group/'services'/model
            service.mkdir(parents=True, exist_ok=True)
            cfg = yaml.safe_load((source/f'configs/inference/modal_qwen35_{slug}_no_skill.yaml').read_text())
            exname = 'modal_h200x8.yaml' if model == '35B-A3B' else f'modal_h200x8_qwen35_{slug}.yaml'
            ex = yaml.safe_load((source/'configs/inference/execution'/exname).read_text())
            cfg['runtime']['cache_dir'] = str(service/'cache')
            ex['media_cache']['root'] = f'/work/frozen-full-media/{model}'
            pool = next(iter(cfg['models']))
            replicas = ex['model_pools'][pool]['replicas']
            assert len(replicas) == 8 and all(r['max_inflight'] == 1 and len(r['gpus']) == 1 for r in replicas)
            ports = list(range(8100+100*index, 8108+100*index))
            for replica, port in zip(replicas, ports):
                replica['endpoint'] = f'http://127.0.0.1:{port}/v1'
            for name, value in [('config.yaml', cfg), ('execution.yaml', ex)]:
                path = service/name
                if path.exists():
                    assert yaml.safe_load(path.read_text()) == value
                else:
                    path.write_text(yaml.safe_dump(value, sort_keys=False))
            save('loading', model=model)
            run([sys.executable, launcher, '--replace', service/'config.yaml', service/'execution.yaml', pool], f'{model}_startup.log')
            cards = []
            previous = read(OUT/'baseline_services.json')[model][0]
            for port in ports:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=15) as response:
                    card = json.load(response)['data'][0]
                validate_card(card)
                assert card['execution'] == manifest['profile']
                assert all(card[field] == previous[field] for field in ['id', 'weights_manifest'])
                cards.append(card)
            assert len({c['worker']['gpu_uuid'] for c in cards}) == 8
            write(service/'identities'/f'{time.time_ns()}.json', cards)
            write(service/'startup_identity.json', cards)
            command = [sys.executable, source/'eval/agent_eval/run.py', '--config', service/'config.yaml',
                '--execution-config', service/'execution.yaml', '--dataset-root', '/assets',
                '--sample-ids-file', group/'samples.json', '--output', target, '--defer-open-qa-judge']
            if (target/'run_manifest.json').exists():
                # Keep failed attempts before the standard resume interface retries unfinished questions.
                for path in target.glob('records/*/*/result.json'):
                    if read(path)['status'] != 'ok':
                        dest = target/'attempts'/path.parent.name/f'{time.time_ns()}.json'
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, dest)
                command.append('--resume')
            save('inference', model=model)
            run(command, f'{model}_inference.log', model)
            rows = [read(p) for p in target.glob('records/*/*/result.json')]
            assert {r['sample_id'] for r in rows} == set(ids)
            errors = [r['sample_id'] for r in rows if r['status'] != 'ok']
            for row in rows:
                if row['status'] == 'ok':
                    stats(row)
            unit.update(finished=len(rows), valid=len(rows)-len(errors), errors=errors, inference_done=True)
            save('inference_done')
        save('judge_loading', model=None)
        subprocess.run(['pkill', '-f', '[s]ync_server.py'], check=False)
        deadline = time.monotonic()+600
        while time.monotonic() < deadline:
            used = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).split()
            if used and all(int(n) < 2048 for n in used):
                break
            time.sleep(5)
        else:
            raise TimeoutError('Actor GPU memory did not release')
        os.environ['JUDGE_LOG_DIR'] = str(group/'judge_servers')
        run(['bash', source/'eval/agent_eval/serve_ccqa_judge.sh', '0-7', '8400'], 'judge_startup.log')
        for model in MODELS:
            if state['models'][model].get('judged'):
                continue
            save('judging', model=model)
            run([sys.executable, source/'eval/agent_eval/score_crossvid_ccqa.py', '--output', group/model,
                 '--endpoints', '8400-8407'], f'{model}_judge.log')
            report = read(group/model/REPORT)
            assert not report['failed_ids']
            expected = sum(s.startswith('crossvid:CCQA:') and s not in state['models'][model]['errors'] for s in ids)
            assert len(report['samples']) == expected
            state['models'][model]['judged'] = True
        save('completed', finished_at=now())
    except BaseException as exc:
        save('interrupted' if isinstance(exc, InterruptedError) else 'failed', error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def host(shard):
    """One dev-box owner per shard; restart only after preemption or the 23-hour boundary."""
    import fcntl
    import modal
    sys.path.insert(0, str(Path.home()/'wxu-evolve-agent/devbox'))
    import devbox
    name = f'mvagent-frozen-full-final-20261019-shard{shard}'
    devbox.REPO = str(ROOT)
    devbox.NAME = name
    devbox.STATE = str(Path(devbox.HERE)/f'state-{name}.json')
    lock = (Path(devbox.HERE)/f'{name}.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not Path(devbox.STATE).exists(), 'Existing owner/state requires inspection'
    volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
    sandbox, recoveries = None, 0
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped:
            sys.argv = ['devbox.py', 'up', '--gpu', 'H100!:8', '--no-pool', '--hours', '24', '--idle', '15']
            devbox.main()
            sandbox = devbox._sandbox()
            print('OWNED_SANDBOX', shard, sandbox.object_id, flush=True)
            assert devbox.start_job(sandbox, f'{TAG}_shard{shard}', f'python /repo/scripts/run_full_mvagent.py worker --shard {shard}') == 0
            started = time.monotonic()
            while not stopped:
                state = json.loads(b''.join(volume.read_file(f'devbox/{TAG}/shard{shard}/progress.json')))
                print(now(), shard, json.dumps(state), flush=True)
                alive = sandbox.poll() is None
                if state['phase'] in ('completed', 'failed'):
                    assert state['phase'] == 'completed', state
                    return
                if not alive or time.monotonic()-started > 23*3600:
                    if not alive:
                        recoveries += 1
                        assert recoveries <= 2, 'Unexpected Sandbox restart budget exhausted'
                    else:
                        devbox._sh(sandbox, f"kill -TERM $(cat /work/jobs/{TAG}_shard{shard}.pid)", timeout=20)
                        time.sleep(45)
                    if sandbox.poll() is None:
                        sandbox.terminate(wait=True)
                    Path(devbox.STATE).unlink(missing_ok=True)
                    break
                time.sleep(45)
        raise RuntimeError('Owner explicitly stopped; no automatic resubmission')
    finally:
        if sandbox is None and Path(devbox.STATE).exists():
            sandbox = devbox._sandbox()
        if sandbox is not None and sandbox.poll() is None:
            sandbox.terminate(wait=True)
        Path(devbox.STATE).unlink(missing_ok=True)
        print('OWNED_GPU_RELEASED', shard, now(), flush=True)


def launch():
    import fcntl
    here = Path('/tmp/mvagent-frozen-full-final-20261019')
    here.mkdir(mode=0o700, exist_ok=True)
    lock = (here/f'watch-{TAG}.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    children = []
    def stop(signum, frame):
        for child in children:
            child.terminate()
        raise InterruptedError('Controller stopped')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for shard in [0]:
            with (here/f'watch-{TAG}-shard{shard}.log').open('a') as log:
                children.append(subprocess.Popen([sys.executable, __file__, 'host', '--shard', str(shard)],
                    stdout=log, stderr=subprocess.STDOUT))
        codes = [p.wait() for p in children]
        print('SHARDS_FINISHED', codes, flush=True)
        import modal
        volume = modal.Volume.from_name('wxu-evolve-agent-runs-20261006', environment_name='zheng-dev')
        while True:
            state = json.loads(b''.join(volume.read_file('devbox/frozen_full_recovery_20261019/shard1/progress.json')))
            if state['phase'] == 'completed':
                break
            assert state['phase'] != 'failed', state
            marker = Path.home()/'wxu-evolve-agent/devbox/state-mvagent-frozen-full-recovery-20261019-shard1.json'
            assert marker.exists(), 'Unfinished other shard has no live controller'
            time.sleep(45)
        sys.path.insert(0, str(Path.home()/'wxu-evolve-agent/devbox'))
        import frozen_full_final_cpu as cpujob
        with cpujob.app.run(environment_name='zheng-dev'):
            rc, out, err = cpujob.job.remote('python scripts/run_full_mvagent.py analyze')
        print(out, err, flush=True)
        assert rc == 0 and codes == [0], (rc, codes)
        print('COMPLETE', now(), flush=True)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            child.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['self-check', 'prepare', 'worker', 'host', 'launch', 'analyze'])
    parser.add_argument('--shard', type=int, choices=[0, 1])
    args = parser.parse_args()
    if args.mode in ('worker', 'host'):
        assert args.shard is not None
        globals()[args.mode](args.shard)
    else:
        globals()[args.mode.replace('-', '_')]()
