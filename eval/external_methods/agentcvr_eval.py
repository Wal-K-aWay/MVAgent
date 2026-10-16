"""Official CVBench/MVU prompts and scores around the published AgentCVR executor."""
import argparse
from collections import Counter
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO), str(REPO / 'src')]
from common import write, sha256


def read(path):
    return json.loads(Path(path).read_text())


def official_inputs():
    from eval.e2e_eval.harness.cvbench import CVBench
    from eval.e2e_eval.harness.common import MVU_SOURCE, official_function
    cv = CVBench(data_root=Path('/assets'), frames=512, max_side=360)
    builder = official_function(MVU_SOURCE / 'inference/main.py', 'build_messages_base',
                                {'logging': logging, 'os': os, 'encode_video': lambda *a, **kw: []})
    items, labels = [], {}
    for item in cv.items:
        if item['sample_id'] in {'cvbench:64', 'cvbench:65', 'cvbench:66'}:
            continue
        row = item['row']
        items.append(dict(sample_id=item['sample_id'], dataset='cvbench',
            query=cv.doc_to_text(row, cv.prompt_kwargs), system=cv.system,
            videos=[str(Path('/assets/cvbench') / row[f'video_{i}'])
                    for i in range(1, 5) if row[f'video_{i}'] is not None]))
        labels[item['sample_id']] = item
    for key, row in read('/assets/mvu-eval/MVU_Eval_QAs.json').items():
        sid = f'mvu_eval:{row["task"]}:{key}'
        # Empty video list executes the original question/instruction/options branch verbatim.
        content = builder('/assets/mvu-eval', row, [], 0, 360)
        assert len(content) == 3 and all(x['type'] == 'text' for x in content)
        query = '\n'.join(x['text'] for x in content)
        assert content[0]['text'] == row['question'] and content[2]['text'] == '\n'.join(row['options'])
        items.append(dict(sample_id=sid, dataset='mvu_eval', query=query, system='',
            videos=[str(Path('/assets/mvu-eval') / x) for x in row['video_paths']]))
        labels[sid] = dict(sample_id=sid, task=row['task'], row=row)
    assert Counter(x['dataset'] for x in items) == {'cvbench': 997, 'mvu_eval': 1824}
    assert len(labels) == len(items) == 2821
    assert all(set(x) == {'sample_id', 'dataset', 'query', 'videos', 'system'} for x in items)
    random.Random(0).shuffle(items)
    return items, labels


def protocol_prompt():
    source = Path('/opt/AgentCVR/agent_system/prompts/master_CC.prompt').read_text()
    # Keep the original tool protocol/examples; benchmark Query supplies task and answer format.
    prompt = source.split('\n\n', 1)[1]
    prompt = prompt.replace('`video_index`: int (1, 2, 3, or 4)',
                            '`video_index`: int (1 through the number of provided videos)')
    original = 'If it\'s a multiple-choice question, the final_answer field must contain only one uppercase letter (such as "A", "B", "C", "D").'
    assert prompt.count(original) == 1
    return prompt.replace(original, 'The final_answer field must follow the answer format specified in the Query.')


def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    items, labels = official_inputs()
    inputs = output / 'items.json'
    if inputs.exists():
        assert read(inputs) == items and (output / 'agent_system.prompt').read_text() == protocol_prompt()
        return
    write(inputs, items)
    write(output / 'private_labels.json', labels)
    asset_manifest = read('/runs/devbox/agentcvr_20261016/assets.json')
    assert asset_manifest['stage'] == 'completed'
    write(output / 'assets_manifest.json', asset_manifest)
    (output / 'agent_system.prompt').write_text(protocol_prompt())
    sources = {str(p.relative_to(REPO)): sha256(p) for directory in ('src', 'eval', 'configs')
               for p in (REPO / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    with tarfile.open(output / 'frozen_source.tar.gz', 'w:gz') as tar:
        for name in sources:
            tar.add(REPO / name, arcname=name)
        tar.add('/opt/AgentCVR', arcname='upstream/AgentCVR',
                filter=lambda info: None if '__pycache__' in Path(info.name).parts else info)
    write(output / 'manifest.json', dict(source_hashes=sources, input_sha256=sha256(inputs),
        project_commit=(REPO / '.source_commit').read_text().strip(),
        protocol_sha256=sha256(output / 'agent_system.prompt'),
        source_archive_sha256=sha256(output / 'frozen_source.tar.gz'),
        assets_manifest_sha256=sha256(output / 'assets_manifest.json'),
        upstream_commit='568b402c51254a04149d49d0bc4ad7c9d2fcf2f1',
        master_revision='0ca8538758507589a5bada39d2377847649adc09',
        master='author released Qwen3-8B RL; differs from paper Qwen3-VL description',
        vision='Qwen3-VL-8B-Thinking', audio='Whisper large-v3', gpu='H200:8',
        replicas=8, max_turns=20, temperature=.5, max_tokens=8192, seed=0, question_timeout_seconds=3600,
        benchmark_prompts='Verbatim CVBench mvr_doc_to_text; MVU question/instruction/options original order',
        protocol_adaptation='CC role paragraph removed; video-index bound generalized; final format follows Query',
        media='Original independent videos/time axes; upstream decord sampling/JPEG/longest edge360; audio enabled',
        excluded=['cvbench:64', 'cvbench:65', 'cvbench:66'],
        assets_sha256={p: sha256(Path('/assets') / p) for p in
                       ('cvbench/QAs.json', 'mvu-eval/MVU_Eval_QAs.json')}))
    write(output / 'progress.json', dict(phase='prepared', completed=0, expected=2821))


def summarize(output):
    from eval.e2e_eval.harness.cvbench import CVBench
    from eval.e2e_eval.harness.mvu_eval import MVUEval
    cv = CVBench(data_root=Path('/assets'), frames=512, max_side=360)
    labels = read(output / 'private_labels.json')
    totals = {d: dict(completed=0, valid=0, correct=0, errors=0, no_answer=0, seconds=0,
                     prompt_tokens=0, completion_tokens=0) for d in ('cvbench', 'mvu_eval')}
    rows = []
    for path in sorted((output / 'records').glob('*.json')):
        raw = read(path); sid = raw['sample_id']; dataset = sid.split(':')[0]
        stats = totals[dataset]; stats['completed'] += 1; stats['seconds'] += raw['seconds']
        for key in ('prompt_tokens', 'completion_tokens'):
            stats[key] += raw['usage'].get(key, 0)
        if raw['status'] == 'infrastructure_error':
            stats['errors'] += 1
            continue
        scored = (cv.score(labels[sid], raw['answer']) if dataset == 'cvbench'
                  else MVUEval.score(None, labels[sid], raw['answer']))
        if raw['status'] != 'answered':
            scored['score'] = 0.0
            stats['no_answer'] += 1
        stats['valid'] += 1; stats['correct'] += scored['score']
        rows.append(dict(sample_id=sid, status=raw['status'], **scored))
    for stats in totals.values():
        stats['accuracy'] = stats['correct'] / stats['valid'] if stats['valid'] else None
    write(output / 'scores.json', dict(datasets=totals, rows=rows))
    return totals


def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def run(output, smoke_only=False):
    manifest = read(output / 'manifest.json')
    assert sha256(output / 'items.json') == manifest['input_sha256']
    for path, digest in manifest['source_hashes'].items():
        assert sha256(REPO / path) == digest, path
    episode = output / 'episodes' / str(time.time_ns()); episode.mkdir(parents=True)
    processes, workers = [], []
    started = time.monotonic()
    def progress(phase, **extra):
        write(output / 'progress.json', dict(phase=phase, expected=2821, updated=time.time(), **extra))
    worker_command = [sys.executable, str(HERE / 'agentcvr_worker.py'), '--output', str(output)]
    try:
        progress('starting_models', ready_servers=0)
        for rank in range(1 if smoke_only else 8):
            for kind, name, port, memory, length in [
                ('master', 'AgentCVR-8B-merged', 8100+rank*2, '.35', '40960'),
                ('vision', 'Qwen3-VL-8B-Thinking', 8101+rank*2, '.50', '131072')]:
                command = [sys.executable, '-m', 'vllm.entrypoints.openai.api_server',
                    '--model', '/weights/'+name, '--served-model-name', 'agentcvr-'+kind,
                    '--host', '127.0.0.1', '--port', str(port), '--dtype', 'bfloat16',
                    '--seed', '0', '--tensor-parallel-size', '1', '--max-num-seqs', '1',
                    '--gpu-memory-utilization', memory, '--max-model-len', length,
                    '--no-enable-prefix-caching', '--mm-processor-cache-gb', '0',
                    '--enforce-eager', '--no-enable-log-requests']
                if kind == 'vision':
                    command += ['--limit-mm-per-prompt', '{"image":4096,"video":0}']
                with (episode / f'{rank}-{kind}.log').open('w') as log:
                    proc = subprocess.Popen(command, env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(rank)),
                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                processes.append(proc)
                write(episode / f'{rank}-{kind}-command.json', command)
                deadline = time.monotonic()+1200
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(f'{kind} {rank} exited during startup')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=2) as response:
                            write(episode / f'{rank}-{kind}-models.json', json.load(response))
                        progress('starting_models', ready_servers=len(processes))
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise TimeoutError(f'{kind} {rank} startup')
                        time.sleep(2)
            if rank == 0 and not (output / 'smoke_completed.json').exists():
                progress('smoke')
                with (episode / 'smoke.log').open('w') as log:
                    subprocess.run(worker_command+['--rank', '0', '--smoke'], env=dict(os.environ, CUDA_VISIBLE_DEVICES='0'),
                                   stdout=log, stderr=subprocess.STDOUT, check=True, timeout=7200)
                write(output / 'smoke_completed.json', summarize(output))
        if smoke_only:
            return
        for rank in range(8):
            with (episode / f'worker{rank}.log').open('w') as log:
                workers.append(subprocess.Popen(worker_command+['--rank', str(rank)],
                    env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(rank)), stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True))
        while any(proc.poll() is None for proc in workers):
            if any(proc.poll() not in (None, 0) for proc in workers) or any(proc.poll() is not None for proc in processes):
                raise RuntimeError('A worker or model server exited unexpectedly')
            totals = summarize(output)
            write(output / 'progress.json', dict(phase='inference', expected=2821,
                completed=sum(x['completed'] for x in totals.values()), datasets=totals, updated=time.time()))
            if time.monotonic()-started > 22*3600:
                for proc in workers:
                    stop(proc)
                progress('resume_required', completed=sum(x['completed'] for x in totals.values()), datasets=totals)
                return
            time.sleep(30)
        assert all(proc.returncode == 0 for proc in workers)
        totals = summarize(output)
        assert sum(x['completed'] for x in totals.values()) == 2821
        write(output / 'progress.json', dict(phase='completed', expected=2821, completed=2821,
            datasets=totals, updated=time.time()))
    except BaseException as exc:
        progress('failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        for proc in workers+processes:
            stop(proc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'run', 'smoke', 'score'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare(args.output)
    elif args.mode == 'score':
        print(json.dumps(summarize(args.output)), flush=True)
    else:
        run(args.output, smoke_only=args.mode == 'smoke')
