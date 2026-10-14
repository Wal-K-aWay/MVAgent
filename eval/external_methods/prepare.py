"""Prepare answer-free, concatenated inputs on Modal; keep labels separate."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import subprocess

from common import sha256, write


def select(root):
    groups = defaultdict(list)
    lite_path = root / 'configs/skill_evolution/splits/crossvid_lite2500_eval_seed20260919.json'
    lite = {r['sample_id'] for r in json.loads(lite_path.read_text())['samples']}
    for dataset, path in [('crossvid', '/assets/crossvid/qa.jsonl'),
                          ('cvbench', '/assets/cvbench/QAs.json'),
                          ('mvu_eval', '/assets/mvu-eval/QAs.json')]:
        content = Path(path).read_text()
        rows = [json.loads(line) for line in content.splitlines()] if path.endswith('jsonl') else json.loads(content)
        for row in rows:
            task = row['task_type'] if dataset == 'cvbench' else row['task']
            sid = (row['id'] if dataset == 'crossvid' else f'cvbench:{row["id"]}'
                   if dataset == 'cvbench' else f'mvu_eval:{task}:{row["id"]}')
            if sid in {'cvbench:64', 'cvbench:65', 'cvbench:66'} or (dataset == 'crossvid' and sid not in lite):
                continue
            groups[dataset, task].append(sid)
    rng = random.Random(0)
    chosen = [rng.choice(sorted(groups[key])) for key in sorted(groups)]
    assert len(chosen) == len(set(chosen)) == 33
    return chosen


def probe(path):
    result = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,duration', '-of', 'json', str(path)], text=True)
    info = json.loads(result)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    duration = float(video.get('duration') or info['format']['duration'])
    assert duration > 0
    return duration


def timeline(segments):
    lines = ['The supplied file concatenates the original videos in the order below. '
             'Use the original video identities when answering. Tool timestamps refer to '
             'the concatenated file. Times in the original question and in your final '
             'answer refer to the named original video; subtract its start offset when '
             'converting a concatenated-file time back. No audio is provided.']
    for i, s in enumerate(segments, 1):
        lines.append(f'Video {i} ({s["video_id"]}): starts at {s["start"]:.6f} seconds, '
                     f'ends at {s["end"]:.6f} seconds; original duration {s["original_duration"]:.6f} seconds.')
    return '\n'.join(lines)


def prepare(record, output):
    target = output / 'media' / record.sample_id.replace(':', '_')
    target.mkdir(parents=True, exist_ok=True)
    parts, segments, offset = [], [], 0.0
    for i, (video_id, source) in enumerate(record.sample.videos.items()):
        destination = target / f'{i}.mp4'
        original_duration = probe(source)
        subprocess.run(['ffmpeg', '-v', 'error', '-threads', '1', '-i', source, '-an',
            '-vf', 'scale=448:448:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=448:448:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-threads', '1', '-n', str(destination)], check=True, timeout=1200)
        duration = probe(destination)
        segments.append(dict(video_id=video_id, start=offset, end=offset+duration,
            original_duration=original_duration, source=source, source_sha256=sha256(source)))
        offset += duration
        parts.append(destination)
    listing = target / 'concat.txt'
    listing.write_text(''.join(f"file '{p.name}'\n" for p in parts))
    video = target / 'concatenated.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', str(listing),
                    '-c', 'copy', '-an', '-n', str(video)], check=True, timeout=120)
    duration = probe(video)
    assert abs(duration-offset) < .1, (duration, offset)
    item = dict(sample_id=record.sample_id, video_path=str(video), duration=duration,
        question=timeline(segments) + '\n\nOriginal question:\n' + record.sample.question,
        options={chr(65+i): value for i, value in enumerate(record.sample.options)})
    write(target / 'timeline.json', dict(segments=segments, duration=duration,
        video_sha256=sha256(video), preprocessing='448x448 letterbox, 30fps, x264 CRF18, visual only'))
    for part in parts:
        part.unlink()
    write(output / 'items' / (record.sample_id.replace(':', '_')+'.json'), item)
    print('prepared', record.sample_id, round(duration, 2), flush=True)
    return item


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    ids = select(root)
    records = load_multibench_records('/assets', ids)
    write(args.output / 'selection.json', dict(seed=0, sample_ids=ids,
        selection='one seeded random question per native task; CrossVid restricted to existing Lite2500'))
    write(args.output / 'private_labels.json', {sid: dict(dataset=r.dataset, task=r.native_task,
        sample=r.sample.to_dict(), reference_answer=r.reference_answer, judge_question=r.judge_question,
        task_population=r.task_population) for sid, r in records.items()})
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(lambda sid: prepare(records[sid], args.output), ids))
    write(args.output / 'items.json', items)


if __name__ == '__main__':
    main()
