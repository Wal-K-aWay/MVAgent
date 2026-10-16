"""Small remote checks for the only source change and the HTTP adapter."""
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import cv2
import imageio_ffmpeg
from bridge import self_check
from mvagent.utils.media import cut_video_segment

self_check()
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'source.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=4', '-t', '2',
                    '-c:v', 'mpeg4', '-threads', '1', str(source)], check=True)
    plain = cut_video_segment(str(source), [0, 1], output_dir=directory, prefix='plain')
    padded = cut_video_segment(str(source), [0, .25], output_dir=directory, prefix='padded',
                               sampling_fps=.5, minimum_sampled_frames=2)
    for path, minimum in [(plain, 4), (padded, 16)]:
        capture = cv2.VideoCapture(path)
        count = 0
        while capture.read()[0]:
            count += 1
        capture.release()
        assert count >= minimum, (path, count, minimum)
    try:
        cut_video_segment(str(source), [1, 1], output_dir=directory)
    except ValueError:
        pass
    else:
        raise AssertionError('Empty interval must fail')
print('Legacy schema translation, FFmpeg stream-copy and padded clipping passed')
