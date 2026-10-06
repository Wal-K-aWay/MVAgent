"""Check second-based MP4 stream copy with the installed, unchanged vLLM loader."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

import av
import cv2
import imageio_ffmpeg
from vllm.multimodal.media.image import ImageMediaIO
from vllm.multimodal.media.video import VideoMediaIO
from vllm.multimodal.video import OpenCVVideoBackend, VideoSourceMetadata, VideoTargetMetadata


def validate(path, expected_frames, fps):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        stream.codec_context.thread_count = 4
        timestamps = [float(frame.time) for frame in container.decode(stream)]
        result = {'container_frames': stream.frames, 'decoded_frames': len(timestamps),
                  'first_frame_time': timestamps[0], 'last_frame_time': timestamps[-1],
                  'container_duration': float(stream.duration * stream.time_base),
                  'expected_frames': expected_frames, 'bytes': path.stat().st_size, 'sampling': {}}
    for sampling_fps in (1, 2):
        # Matches local Runtime's media_io_kwargs={video:{fps:...}}. VideoMediaIO
        # keeps the installed default num_frames=32, as the running services do.
        loader = VideoMediaIO(ImageMediaIO(), fps=sampling_fps)
        frames, metadata = loader.load_bytes(path.read_bytes())
        expected_indices = OpenCVVideoBackend.compute_frames_index_to_sample(
            VideoSourceMetadata(expected_frames, fps, expected_frames / fps),
            VideoTargetMetadata(32, sampling_fps, 300))
        result['sampling'][str(sampling_fps)] = {
            'metadata': metadata, 'loaded_frames': len(frames),
            'expected_indices': expected_indices,
            'matches_expected_metadata': metadata['total_num_frames'] == expected_frames
                and abs(metadata['fps'] - fps) < 1e-6
                and metadata['frames_indices'] == expected_indices,
            'sample_hashes': [hashlib.sha256(f.tobytes()).hexdigest() for f in frames],
        }
        del frames
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--videos', type=Path, nargs='+', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir
    root.mkdir(parents=True, exist_ok=False)
    (root / Path(__file__).name).write_text(Path(__file__).read_text())
    binary = imageio_ffmpeg.get_ffmpeg_exe()
    results = {}
    for index, source in enumerate(args.videos):
        cap = cv2.VideoCapture(str(source))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        for start in (0, 5.37):
            begin = math.floor(start * fps)
            end = math.floor((start + 30) * fps)
            for variant, seek, duration in (
                ('literal_seconds', start, 30),
                ('runtime_frame_aligned', begin / fps, (end - begin) / fps),
            ):
                label = f'{index}_{start}_{variant}'
                output = root / f'{label}.mp4'
                command = [binary, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                    '-ss', str(seek), '-i', str(source), '-t', str(duration),
                    '-map', '0:v:0', '-an', '-sn', '-dn', '-c:v', 'copy', str(output)]
                elapsed = []
                for _ in range(3):
                    started = time.monotonic()
                    subprocess.run(command, capture_output=True, check=True, timeout=30)
                    elapsed.append(time.monotonic() - started)
                row = {'source': str(source), 'requested_start': start, 'seek_seconds': seek,
                       'command': command, 'seconds': elapsed, 'median_seconds': statistics.median(elapsed)}
                row.update(validate(output, end - begin, fps))
                results[label] = row
                (root / 'results.json').write_text(json.dumps(results, indent=2))
    (root / 'status.json').write_text(json.dumps({'status': 'finished'}))


if __name__ == '__main__':
    main()
