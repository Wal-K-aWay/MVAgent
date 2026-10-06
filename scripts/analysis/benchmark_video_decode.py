"""Compare existing CPU decoders and PyAV CUDA decoding to host BGR frames.

This is an isolated microbenchmark, not a Runtime decoder replacement. Restrict
CUDA_VISIBLE_DEVICES to the intended physical GPU before invoking this script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time

import av
from av.codec.hwaccel import HWAccel
import cv2
import numpy as np


def read_file(path):
    started = time.monotonic()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            size += len(block)
    return {'bytes': size, 'seconds': time.monotonic() - started}


def buffered_write(size):
    block = bytes(4 * 1024 * 1024)
    started = time.monotonic()
    with tempfile.TemporaryFile() as stream:
        remaining = size
        while remaining:
            written = stream.write(block[:min(len(block), remaining)])
            remaining -= written
    return {'bytes': size, 'seconds': time.monotonic() - started, 'fsync': False}


def decode(path, method, count):
    selected, frames = {}, 0
    started = time.monotonic()
    if method == 'opencv_cpu':
        container = cv2.VideoCapture(str(path))
        if not container.isOpened():
            raise ValueError(path)
        def next_frame():
            ok, frame = container.read()
            return frame if ok else None
        close = container.release
        hardware = False
    else:
        hwaccel = HWAccel(device_type='cuda', device='0', allow_software_fallback=False) if method == 'pyav_cuda' else None
        container = av.open(str(path), hwaccel=hwaccel)
        hardware = container.streams.video[0].codec_context.is_hwaccel
        if method == 'pyav_cuda' and not hardware:
            raise RuntimeError('Requested CUDA but decoder is not hardware accelerated')
        iterator = iter(container.decode(video=0))
        def next_frame():
            frame = next(iterator, None)
            return frame.to_ndarray(format='bgr24') if frame is not None else None
        close = container.close
    opened = time.monotonic()
    try:
        for index in range(count):
            frame = next_frame()
            if frame is None:
                break
            frames += 1
            if index in (0, count // 2, count - 1):
                selected[index] = frame.copy()
    finally:
        close()
    ended = time.monotonic()
    return {'frames': frames, 'open_seconds': opened - started,
            'decode_to_host_bgr_seconds': ended - opened, 'total_seconds': ended - started,
            'hardware': hardware,
            'sample_hashes': {i: hashlib.sha256(f.tobytes()).hexdigest() for i, f in selected.items()}}, selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    with av.open(str(args.video)) as container:
        stream = container.streams.video[0]
        metadata = {'codec': stream.codec_context.name, 'width': stream.width,
                    'height': stream.height, 'fps': float(stream.average_rate), 'frames': stream.frames}
    count = min(metadata['frames'], int(args.seconds * metadata['fps']))
    report = {'source': str(args.video), 'metadata': metadata, 'requested_frames': count,
              'versions': {'av': av.__version__, 'cv2': cv2.__version__},
              'file_reads': [read_file(args.video) for _ in range(args.repeats)], 'methods': {}}
    report['buffered_writes'] = [buffered_write(args.video.stat().st_size) for _ in range(args.repeats)]
    reference = None
    # Rotate execution order across repetitions to expose warm-up/order effects.
    methods = ['opencv_cpu', 'pyav_cpu', 'pyav_cuda']
    for repeat in range(args.repeats):
        for method in methods[repeat % 3:] + methods[:repeat % 3]:
            try:
                result, samples = decode(args.video, method, count)
                if reference is None:
                    reference = samples
                result['vs_opencv_samples'] = {i: {
                    'equal': bool(np.array_equal(frame, reference[i])),
                    'mean_absolute_pixel_difference': float(np.abs(frame.astype(np.int16) - reference[i]).mean()),
                    'max_absolute_pixel_difference': int(np.abs(frame.astype(np.int16) - reference[i]).max())}
                    for i, frame in samples.items()}
            except Exception as exc:
                result = {'error': str(exc)}
            report['methods'].setdefault(method, []).append(result)
            args.output.write_text(json.dumps(report, indent=2))
    report['median_seconds'] = {method: statistics.median(r['total_seconds'] for r in rows)
                                for method, rows in report['methods'].items() if all('error' not in r for r in rows)}
    args.output.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
