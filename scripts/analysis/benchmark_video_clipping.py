"""Compare MP4 clipping before vLLM; no Runtime or server decoder replacement."""
import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

import cv2
import imageio_ffmpeg
import numpy as np

from mvagent.utils.media import cut_video_segment


def frames_at(path, indices):
    capture = cv2.VideoCapture(str(path))
    try:
        result = {}
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if ok:
                result[index] = frame
        return result
    finally:
        capture.release()


def inspect(path, reference):
    capture = cv2.VideoCapture(str(path))
    try:
        metadata = {'frames': int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
                    'fps': capture.get(cv2.CAP_PROP_FPS),
                    'width': int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    'height': int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    finally:
        capture.release()
    metadata['bytes'] = path.stat().st_size
    selected = frames_at(path, reference)
    metadata['all_sampled_frames_readable'] = len(selected) == len(reference)
    metadata['sampled_source_pixel_mae'] = {
        i: float(np.abs(frame.astype(np.int16) - reference[i]).mean())
        for i, frame in selected.items()}
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--starts', type=float, nargs='+', default=[0, 5.37])
    parser.add_argument('--duration', type=float, default=30)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'benchmark_video_clipping.py').write_text(Path(__file__).read_text())
    binary = imageio_ffmpeg.get_ffmpeg_exe()
    capture = cv2.VideoCapture(str(args.video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    source_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    methods = {'runtime': [], 'ffmpeg_mpeg4': ['-c:v', 'mpeg4', '-q:v', '2', '-threads', '4'],
               'ffmpeg_x264': ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-threads', '4'],
               'stream_copy': ['-c:v', 'copy']}
    report = {'video': str(args.video), 'ffmpeg': binary, 'fps': fps, 'cases': {}}
    for start in args.starts:
        begin = math.floor(start * fps)
        end = min(source_count, math.floor((start + args.duration) * fps))
        count = end - begin
        offsets = [0, count // 2, count - 1]
        source = frames_at(args.video, [begin + i for i in offsets])
        reference = {i: source[begin + i] for i in offsets}
        case = {'requested_range': [start, start + args.duration],
                'source_frame_range': [begin, end], 'expected_frames': count, 'methods': {}}
        report['cases'][str(start)] = case
        for repeat in range(args.repeats):
            names = list(methods)
            for name in names[repeat:] + names[:repeat]:
                output = args.output_dir / f'{start}_{name}.mp4'
                command = [binary, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                           '-threads', '4', '-ss', str(begin / fps), '-i', str(args.video),
                           '-map', '0:v:0', '-an', '-sn', '-dn', '-frames:v', str(count), *methods[name], str(output)]
                started = time.monotonic()
                if name == 'runtime':
                    output = Path(cut_video_segment(str(args.video), [start, start + args.duration],
                        output_dir=str(args.output_dir), prefix=f'{start}_runtime', sampling_fps=1))
                else:
                    subprocess.run(command, check=True, capture_output=True, timeout=120)
                elapsed = time.monotonic() - started
                result = case['methods'].setdefault(name, {'seconds': [], 'command': command if name != 'runtime' else None})
                result['seconds'].append(elapsed)
                if repeat == 0:
                    result['validation'] = inspect(output, reference)
                    result['file'] = str(output)
                result['median_seconds'] = statistics.median(result['seconds'])
                (args.output_dir / 'results.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
