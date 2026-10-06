"""Run instrumented Eval rollouts and identify their observed completion path.

HTTP spans are client latency, not pure inference. vLLM histogram deltas provide
batch-level server timing; they cannot assign server phases to individual calls.
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

import yaml


REPO = Path(__file__).resolve().parents[2]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def service_metrics(endpoints):
    result = {}
    for endpoint in endpoints:
        url = endpoint.removesuffix('/v1') + '/metrics'
        with OPENER.open(url, timeout=3) as response:
            lines = response.read().decode().splitlines()
        result[endpoint] = {line.split('{')[0]: float(line.rsplit(' ', 1)[1])
                            for line in lines if line.startswith('vllm:') and
                            ('_sum{' in line or '_count{' in line or 'num_requests_' in line)}
    return result


def question_profile(events, start, done):
    # Global awaits every requested VideoAgent. At each barrier, the latest
    # finishing branch determines when Global can continue, not the longest sum.
    winners = {}
    for event in events:
        if event['kind'] == 'video_run_end':
            winners[event['global_round']] = max(
                winners.get(event['global_round'], (0, '')),
                (event['time'], event['video_id']))
    critical, all_work, spans = Counter(), Counter(), []
    clips = []
    for event in events:
        kind = event['kind']
        parts = {}
        if kind == 'media_clip_profile':
            keys = (('open_metadata_seconds', 'ffmpeg_seconds') if 'ffmpeg_seconds' in event else
                    ('open_metadata_seconds', 'seek_seconds', 'read_decode_seconds',
                     'encode_write_seconds', 'writer_open_seconds', 'writer_close_seconds'))
            parts = {key: event[key] for key in keys}
            parts['clip_other_seconds'] = max(0, event['seconds'] - sum(parts.values()))
            clips.append(event)
        elif kind == 'media_payload':
            parts = {'payload_read_seconds': event['read_seconds'],
                     'payload_base64_seconds': event['base64_seconds']}
        elif kind == 'request_prepared':
            parts = {'request_prepare_seconds': event['seconds']}
        elif kind == 'http_end':
            parts = {'http_seconds': event['seconds']}
        elif kind == 'request_admitted':
            parts = {'client_queue_seconds': event['queue_seconds']}
        elif kind == 'media' and event['operation'] == 'metadata':
            parts = {'metadata_seconds': event['seconds']}
        all_work.update(parts)
        selected = event.get('agent') != 'VideoAgent' or (
            winners.get(event.get('global_round'), (None, None))[1] == event.get('video_id'))
        if selected:
            critical.update(parts)
        if kind in ('http_end', 'media_clip_profile'):
            spans.append({'kind': kind, 'start': event['started_at'],
                          'end': event['started_at'] + event['seconds']})
    wall = done['time'] - start['time']
    critical['unclassified_seconds'] = wall - sum(critical.values())
    return {'wall_seconds': wall, 'critical_seconds': dict(critical),
            'all_work_seconds': dict(all_work), 'critical_video_branches': winners,
            'clips': clips, 'spans': spans}


def analyze(run, before, after):
    events = [json.loads(line) for line in (run / 'rollout_events.jsonl').read_text().splitlines()]
    starts = {e['sample_id']: e for e in events if e['kind'] == 'question_start'}
    ends = {e['sample_id']: e for e in events if e['kind'] == 'question_done'}
    grouped = defaultdict(list)
    for event in events:
        if 'sample_id' in event:
            grouped[event['sample_id']].append(event)
    questions = {sid: question_profile(grouped[sid], starts[sid], end) for sid, end in ends.items()}
    last = max(ends, key=lambda sid: ends[sid]['time'])
    worker = starts[last]['worker_pid']
    # For the observed fixed worker assignment, earlier jobs on the last worker
    # also delay the final job. This is not a counterfactual scheduler simulation.
    chain = sorted((sid for sid in ends if starts[sid]['worker_pid'] == worker),
                   key=lambda sid: starts[sid]['time'])
    critical = Counter()
    all_work = Counter()
    for sid, question in questions.items():
        all_work.update(question['all_work_seconds'])
        if sid in chain:
            critical.update(question['critical_seconds'])
    first_time = min(e['time'] for e in starts.values())
    last_time = ends[last]['time']
    deltas = {endpoint: {key: value - before[endpoint].get(key, 0)
                         for key, value in metrics.items() if key.endswith(('_sum', '_count'))}
              for endpoint, metrics in after.items()}
    calls = Counter(e['endpoint'].removesuffix('/chat/completions')
                    for e in events if e['kind'] == 'http_end')
    # Time during the final single-question tail with no outstanding HTTP calls
    # anywhere and at least one CPU clipping call. This establishes visible idle
    # opportunities, not the amount a hypothetical decoder would save.
    tail_start = sorted(e['time'] for e in ends.values())[-2]
    media = [(max(tail_start, s['start']), min(last_time, s['end']))
             for s in questions[last]['spans'] if s['kind'] == 'media_clip_profile'
             and s['end'] > tail_start]
    http = [(s['start'], s['end']) for q in questions.values() for s in q['spans']
            if s['kind'] == 'http_end']
    points = sorted({tail_start, last_time, *(max(tail_start, min(last_time, t))
                    for pair in media + http for t in pair)})
    idle_media = sum(b - a for a, b in zip(points, points[1:])
                     if any(l <= (a + b) / 2 < r for l, r in media)
                     and not any(l <= (a + b) / 2 < r for l, r in http))
    clips = [clip for question in questions.values() for clip in question['clips']]
    return {'completed': len(ends), 'batch_seconds': last_time - first_time,
            'clip_calls': len(clips), 'encoded_frames': sum(
                c['selected_frames'] + c['padding_frames'] if c.get('method') == 'padded_transcode'
                else c.get('frames_written', 0) for c in clips),
            'stream_copy_calls': sum(c.get('method') == 'stream_copy' for c in clips),
            'padded_transcode_calls': sum(c.get('method') == 'padded_transcode' for c in clips),
            'clip_output_bytes': sum(c['output_bytes'] for c in clips),
            'accounting_note': 'Critical totals include the latest-finishing branch per barrier; '
                'time before that branch starts (including earlier work queued on its Video thread) '
                'is unclassified. HTTP is not pure inference. This is an observed-path attribution, '
                'not a full server dependency DAG or a predicted speedup.',
            'last_question': last, 'observed_worker_chain': chain,
            'critical_seconds': dict(critical), 'all_work_seconds': dict(all_work),
            'worker_dispatch_gap_seconds': last_time - first_time - sum(questions[s]['wall_seconds'] for s in chain),
            'single_question_tail_seconds': last_time - tail_start,
            'tail_clipping_without_http_seconds': idle_media,
            'server_metric_deltas': deltas, 'client_http_calls': dict(calls), 'questions': questions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 2])
    parser.add_argument('--limit', type=int, default=24)
    parser.add_argument('--execution-config', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'profile_rollout.py').write_text(Path(__file__).read_text())
    config = yaml.safe_load(args.config.read_text())
    execution = yaml.safe_load(args.execution_config.read_text())
    manifest = json.loads((REPO / config['split_manifest']).read_text())
    manifest['samples'] = [s for s in manifest['samples'] if s['split'] == 'eval'][:args.limit]
    (root / 'split.json').write_text(json.dumps(manifest, indent=2))
    config['split_manifest'] = str(root / 'split.json')
    config['runtime']['cache_dir'] = str(root / 'cache')
    execution.update(media_cache=None, question_timeout_sec=600, question_retries=0)
    replicas = [r for pool in execution['model_pools'].values() for r in pool['replicas']]
    endpoints = [r['endpoint'] for r in replicas]
    gpus = ','.join(str(g) for r in replicas for g in r['gpus'])
    reports = {}
    for workers in args.workers:
        label = f'workers{workers}'
        execution['question_workers'] = workers
        resource_path = root / f'{label}_execution.yaml'
        resource_path.write_text(yaml.safe_dump(execution, sort_keys=False))
        path = root / f'{label}.yaml'
        path.write_text(yaml.safe_dump(config, sort_keys=False))
        before = service_metrics(endpoints)
        (root / f'{label}_before.json').write_text(json.dumps(before, indent=2))
        started = time.time()
        with (root / f'{label}.log').open('w') as log, (root / f'{label}_metrics.jsonl').open('w') as metrics:
            process = subprocess.Popen([sys.executable, '-u', 'scripts/run_skill_evolution.py',
                '--config', str(path), '--execution-config', str(resource_path), '--output-dir', str(root / label), '--mode', 'evaluate',
                '--repeat-id', label], cwd=REPO, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            (root / 'progress.json').write_text(json.dumps({'arm': label, 'pid': process.pid, 'started': started}))
            while process.poll() is None:
                gpu = subprocess.run(['nvidia-smi', '-i', gpus,
                    '--query-gpu=index,utilization.gpu,utilization.encoder,utilization.decoder,memory.used',
                    '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
                row = {'time': time.time(), 'gpus': gpu.stdout.splitlines()}
                try:
                    row['services'] = service_metrics(endpoints)
                except (OSError, TimeoutError) as exc:
                    row['metrics_error'] = str(exc)  # Monitoring must not abandon a live rollout.
                metrics.write(json.dumps(row) + '\n')
                metrics.flush()
                if time.time() - started > 1200:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                    raise TimeoutError(label)
                time.sleep(1)
        after = service_metrics(endpoints)
        (root / f'{label}_after.json').write_text(json.dumps(after, indent=2))
        if process.returncode:
            raise RuntimeError(f'{label} exited {process.returncode}; inspect {log.name}')
        reports[label] = analyze(root / label, before, after)
        (root / 'profile.json').write_text(json.dumps(reports, indent=2))
    (root / 'progress.json').write_text(json.dumps({'status': 'finished'}))


if __name__ == '__main__':
    main()
