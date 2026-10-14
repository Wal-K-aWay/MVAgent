"""Prepare answer-free, concatenated inputs on Modal; keep labels separate."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
from itertools import zip_longest
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


def video_info(path):
    result = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,codec_name,pix_fmt,width,height,time_base,avg_frame_rate,duration,nb_frames',
        '-of', 'json', str(path)], text=True)
    info = json.loads(result)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    video['duration'] = float(video.get('duration') or info['format']['duration'])
    assert video['duration'] > 0
    return video


def packet_clock(path):
    import av
    with av.open(str(path)) as container:
        return [(float(packet.pts * packet.time_base), float(packet.duration * packet.time_base))
                for packet in container.demux(video=0) if packet.pts is not None]


def frame_signatures(path, offset=0.0):
    import av
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'NONE'
        for frame in container.decode(stream):
            if frame.pts is None:
                raise ValueError(f'{path}: decoded frame has no timestamp')
            yield (float(frame.pts * frame.time_base) + offset,
                   frame.width, frame.height, frame.format.name,
                   hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest())


def verify_frames(expected, actual, label):
    count = 0
    for before, after in zip_longest(expected, actual):
        if before is None or after is None:
            raise ValueError(f'{label}: decoded frame count changed at frame {count}')
        if abs(before[0] - after[0]) >= .000002 or before[1:] != after[1:]:
            raise ValueError(f'{label}: frame {count} pixels, format, size or timestamp changed')
        count += 1
    if not count:
        raise ValueError(f'{label}: no decoded video frames')
    return count


def timeline(segments):
    lines = ['This is a multi-video understanding task. The original videos have been '
             'concatenated into one complete video in the order listed below.',
             'The start and end times of each original video in the concatenated video are:']
    for i, s in enumerate(segments, 1):
        lines.append(f'Video {i} ({s["video_id"]}): starts at {s["start"]:.2f} seconds, '
                     f'ends at {s["end"]:.2f} seconds; original duration {s["original_duration"]:.2f} seconds.')
    lines.append('Use the original video identities when answering. Tool timestamps refer to '
                 'the concatenated video. Times in the original question and in your final '
                 'answer refer to the named original video; subtract its start offset when '
                 'converting a concatenated-video time back. No audio is provided.')
    return '\n'.join(lines)


def prepare(record, output):
    target = output / 'media' / record.sample_id.replace(':', '_')
    target.mkdir(parents=True, exist_ok=True)
    parts, segments, clocks, offset = [], [], [], 0.0
    sources = [(video_id, source, video_info(source)) for video_id, source in record.sample.videos.items()]
    codecs = {info['codec_name'] for _, _, info in sources}
    # Only these codecs have been checked for native-size stream-copy concatenation.
    transcode = len(codecs) != 1 or not codecs <= {'h264', 'mpeg4'}
    for i, (video_id, source, original) in enumerate(sources):
        destination = target / f'{i}.mp4'
        source_clock = packet_clock(source)
        source_start = min(t for t, _ in source_clock)
        # A common container clock lets concat preserve the source frame timing.
        command = ['ffmpeg', '-v', 'error', '-copyts', '-itsoffset', f'{-source_start:.6f}',
                   '-noautorotate', '-i', source, '-map', '0:v:0', '-an',
                   '-avoid_negative_ts', 'disabled', '-video_track_timescale', '1000000']
        if transcode:
            # '+' rejects unsupported pixel formats instead of silently converting them.
            command += ['-c:v', 'libx264', '-qp', '0', '-preset', 'fast', '-pix_fmt', '+',
                        '-vsync', '0', '-enc_time_base', '1:1000000',
                        '-bf', '0', '-threads', '1', '-noautoscale']
        else:
            command += ['-c:v', 'copy']
        if not transcode and original['codec_name'] == 'mpeg4':
            command += ['-bsf:v', 'dump_extra=freq=keyframe']
        command += ['-n', str(destination)]
        subprocess.run(command, check=True, timeout=1200)
        remuxed = video_info(destination)
        clock = packet_clock(destination)
        verified_frames = None
        if transcode:
            verified_frames = verify_frames(frame_signatures(source, -source_start),
                                            frame_signatures(destination), str(source))
            source_duration = max(t+d for t, d in source_clock) - source_start
            if abs(max(t+d for t, d in clock) - source_duration) >= .000002:
                raise ValueError(f'{source}: video duration changed during lossless encoding')
        else:
            assert len(clock) == len(source_clock), source
            assert all(abs(t-(original_t-source_start)) < .000002
                       for (t, _), (original_t, _) in zip(clock, source_clock)), source
        duration = max(t+d for t, d in clock)
        assert duration > 0 and abs(min(t for t, _ in clock)) < .000002
        assert (remuxed['width'], remuxed['height']) == (original['width'], original['height'])
        clocks.extend(t+offset for t, _ in clock)
        segments.append(dict(video_id=video_id, start=offset, end=offset+duration,
            original_duration=duration, source=source, source_sha256=sha256(source),
            source_start_time=source_start, original_stream=original, remuxed_stream=remuxed,
            packet_count=len(clock), processing='lossless_h264' if transcode else 'stream_copy',
            preparation_command=command, verified_decoded_frames=verified_frames))
        offset += duration
        parts.append(destination)
    listing = target / 'concat.txt'
    listing.write_text(''.join(f"file '{p.name}'\nduration {s['end']-s['start']:.6f}\n"
                              for p, s in zip(parts, segments)))
    video = target / 'concatenated.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', str(listing),
                    '-map', '0:v:0', '-c:v', 'copy', '-an', '-video_track_timescale', '1000000',
                    '-n', str(video)], check=True, timeout=120)
    combined_clock = packet_clock(video)
    assert len(combined_clock) == len(clocks)
    assert all(abs(t-expected) < .000002 for (t, _), expected in zip(combined_clock, clocks))
    duration = max(t+d for t, d in combined_clock)
    assert abs(duration-offset) < .000002, (duration, offset)
    if transcode:
        expected_frames = (frame for segment in segments
                           for frame in frame_signatures(segment['source'],
                               segment['start']-segment['source_start_time']))
        verify_frames(expected_frames, frame_signatures(video), str(video))
    item = dict(sample_id=record.sample_id, video_path=str(video), duration=duration,
        question=timeline(segments) + '\n\nOriginal question:\n' + record.sample.question,
        options={chr(65+i): value for i, value in enumerate(record.sample.options)})
    write(target / 'timeline.json', dict(segments=segments, duration=duration,
        video_sha256=sha256(video), preprocessing=(
            ('lossless H.264 normalization; ' if transcode else '') +
            'stream-copy concat; native dimensions and frame timing; visual only'),
        container_time_base='1/1000000'))
    for part in parts:
        part.unlink()
    write(output / 'items' / (record.sample_id.replace(':', '_')+'.json'), item)
    print('prepared', record.sample_id, round(duration, 2), flush=True)
    return item


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--selection', type=Path, help='Reuse an existing sample manifest without resampling')
    args = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    from skill_evolution.infra.benchmarks.catalog import load_multibench_records
    ids = json.loads(args.selection.read_text())['sample_ids'] if args.selection else select(root)
    assert ids and len(ids) == len(set(ids))
    records = load_multibench_records('/assets', ids)
    write(args.output / 'selection.json', dict(seed=0, sample_ids=ids,
        selection='one seeded random question per native task; CrossVid restricted to existing Lite2500',
        reused_from=str(args.selection) if args.selection else None))
    write(args.output / 'private_labels.json', {sid: dict(dataset=r.dataset, task=r.native_task,
        sample=r.sample.to_dict(), reference_answer=r.reference_answer, judge_question=r.judge_question,
        task_population=r.task_population) for sid, r in records.items()})
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(lambda sid: prepare(records[sid], args.output), ids))
    write(args.output / 'items.json', items)


if __name__ == '__main__':
    main()
