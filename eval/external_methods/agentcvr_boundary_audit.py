"""Read-only audit of native AgentCVR requests against the benchmark's allowed clips."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import modal

app = modal.App('wxu-evolve-agent-agentcvr-boundary-audit-20261017')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
ROOT = '/runs/devbox/agentcvr_crossvid_20261017_r2'


def sampled_times(context, target):
    """Reconstruct the original one-interval midpoint sampling without decoding video."""
    fps, total = context['fps'], context['total_frames']
    begin = context.get('clip_begin', 0)
    start = begin + target.get('start_time', 0)
    end = begin + target.get('end_time', context['duration_seconds'])
    n = target.get('num_frames', 32)
    if end <= start:
        return []
    if n == -1:
        indices = range(int(start * fps), min(int(end * fps), total))
    elif isinstance(n, int) and n > 0:
        indices = {min(int(min(start + (end-start)*(i+.5)/n, total/fps)*fps), total-1) for i in range(n)}
    else:
        return []
    return sorted({(i if i >= 0 else total+i)/fps for i in indices if -total <= i < total})


def outside(times, allowed, fps):
    return [t for t in times if not any(a-1/fps <= t <= b+1/fps for a, b in allowed)]


def interval_outside(start, end, allowed, tolerance):
    cursor = start
    for begin, finish in sorted(allowed):
        if finish <= cursor:
            continue
        if begin > cursor + tolerance:
            return True
        cursor = max(cursor, finish)
        if cursor >= end - tolerance:
            return False
    return True


@app.function(image=modal.Image.debian_slim(python_version='3.12'), cpu=2, memory=8192,
              timeout=3600, volumes={'/runs': runs})
def audit():
    context = dict(fps=10, total_frames=1000, clip_begin=20, duration_seconds=10)
    assert not outside(sampled_times(context, {'num_frames': 10}), [[20,30]], 10)
    assert outside(sampled_times(context, {'end_time': 20, 'num_frames': 4}), [[20,30]], 10) == [32.5,37.5]
    assert outside([1.5,2.5,3.5,4.5], [[1,2],[4,5]], 10) == [2.5,3.5]
    assert interval_outside(1.5,4.5,[[1,2],[4,5]],.1)
    assert not interval_outside(1.1,1.9,[[1,2],[4,5]],.1)
    root = Path(ROOT)
    def read(path):
        return json.loads(path.read_text())
    items = {r['sample_id']: r for r in read(root / 'items.json')}
    labels = read(root / 'private_labels.json')
    paths = sorted((root / 'records').glob('*.json'))
    phase = read(root / 'progress.json')['phase']
    candidates = [p for p in paths if p.name.split('_')[1] in {'PI','PEA','PSS'}]

    def check(path):
        record = read(path); sid = record['sample_id']; item = items[sid]
        raw_path = root / 'raw' / path.name
        data = raw_path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == record['raw_sha256']
        raw = json.loads(data); contexts = raw.get('contexts', [])
        allowed = [[(s['begin'], s['end'])] for s in item['videos']]
        if item['task'] == 'PSS':
            segments = labels[sid]['row']['segments']
            allowed = [segments[k] for k in sorted(segments, key=int)]
        stats = Counter(samples=1); violations = []
        for tool in raw.get('tools', []):
            inputs = tool['inputs']
            if tool['tool_name'] == 'get_caption' and not tool.get('error') and not str(tool.get('output_raw', '')).startswith('Error'):
                index = inputs.get('video_index')
                if isinstance(index, int) and 1 <= index <= len(contexts):
                    ctx = contexts[index-1]; begin = ctx.get('clip_begin', 0); duration = ctx['duration_seconds']
                    start = begin + (inputs.get('start_time') if inputs.get('start_time') is not None else 0)
                    end = min(begin + (inputs.get('end_time') if inputs.get('end_time') is not None else duration), begin+duration)
                    if start < end:
                        stats['audio_requests'] += 1
                        if interval_outside(start,end,allowed[index-1],1/ctx['fps']):
                            stats['outside_audio_requests'] += 1
                            violations.append(dict(sample_id=sid, task=item['task'], kind='audio_interval_request',
                                turn=tool['turn'], video_index=index, requested=inputs, effective_interval=[start,end],
                                allowed=allowed[index-1], raw_sha256=record['raw_sha256']))
                continue
            if tool['tool_name'] != 'active_perception' or not tool.get('actual_prompt_sent'):
                continue
            for target in inputs.get('observation_targets', []):
                index = target.get('video_index')
                if not isinstance(index, int) or not 1 <= index <= len(contexts):
                    continue
                ctx = contexts[index-1]
                start = target.get('start_time', 0); end = target.get('end_time', ctx['duration_seconds'])
                if not isinstance(start, (int,float)) or not isinstance(end, (int,float)):
                    continue
                mapping = f'are from Video {index} ({start:.1f}s to {end:.1f}s)'
                if mapping not in str(tool['actual_prompt_sent']):
                    stats['unmatched_mapping_targets'] += 1
                    continue
                stats['visual_targets'] += 1
                times = sampled_times(ctx, target)
                bad = outside(times, allowed[index-1], ctx['fps'])
                stats['sampled_frames_reconstructed'] += len(times)
                if bad:
                    violations.append(dict(sample_id=sid, task=item['task'], kind='reconstructed_visual_frames', turn=tool['turn'],
                        video_index=index, requested=target, allowed=allowed[index-1],
                        outside_frame_times=bad, raw_sha256=record['raw_sha256']))
                    stats['outside_targets'] += 1; stats['outside_frames'] += len(bad)
        return stats, violations

    counts = Counter(); violations = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for stats, rows in pool.map(check, candidates):
            counts.update(stats); violations.extend(rows)
    result = dict(updated=time.time(), phase_at_start=phase, records_at_start=len(paths),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        counts=dict(counts), affected_samples=len({v['sample_id'] for v in violations}),
        affected_by_task=dict(Counter(v['task'] for v in violations)), violations=violations,
        limits='Visual sample times reconstructed from frozen native sampling and successful frame mappings, with one-frame tolerance; audio checks effective requested intervals only. No media re-decoding/content audit. PSS allowed intervals are the original disjoint segments, not the native continuous envelope. Original inference and scores are unchanged.')
    name = 'boundary_audit.json' if phase == 'completed' else 'boundary_audit_partial.json'
    (root / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    runs.commit()
    return {k:v for k,v in result.items() if k != 'violations'} | {'examples': violations[:3]}


@app.local_entrypoint()
def main(after_pid: int = 0):
    if after_pid:
        process = Path(f'/proc/{after_pid}/cmdline')
        print(f'Waiting for existing inference controller {after_pid}; no new inference submitted.', flush=True)
        while process.exists():
            try:
                command = process.read_bytes()
            except FileNotFoundError:
                break
            if b'agentcvr_crossvid_modal.py' not in command:
                break
            time.sleep(60)
    print(json.dumps(audit.remote(), ensure_ascii=False, indent=2), flush=True)
