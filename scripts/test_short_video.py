"""Exercise the accepted short-video repair through FFmpeg and vLLM's decoder (CPU)."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np
from vllm.multimodal.video import OpenCVVideoBackend

from mvagent.agents.video_agent.agent import VideoAgent
from mvagent.utils.media import cut_video_segment, probe_video_info


class ShortVideoTest(unittest.TestCase):
    def test_partial_clip_with_unreadable_container_tail(self):
        source = Path('/assets/crossvid/.mvagent_media/uav_question_boxes/MOC/552/view_B.mp4')
        self.assertTrue(source.exists(), 'Run this regression in the Modal dataset environment')
        with tempfile.TemporaryDirectory() as directory:
            for interval in ([4., 5.], [4., 8.]):
                original = Path(directory) / 'original.mp4'
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                    '-nostdin', '-y', '-ss', str(interval[0]), '-i', str(source), '-map', '0:v:0',
                    '-an', '-sn', '-dn', '-t', str(interval[1]-interval[0]), '-c:v', 'copy',
                    str(original)], check=True)
                before, _ = OpenCVVideoBackend.load_bytes(original.read_bytes(), num_frames=512, fps=2.)
                fixed = Path(cut_video_segment(str(source), interval, output_dir=directory, sampling_fps=2.))
                after, _ = OpenCVVideoBackend.load_bytes(fixed.read_bytes(), num_frames=512, fps=2.)
                self.assertGreaterEqual(len(after), 2)
                if interval == [4., 5.]:
                    self.assertEqual(len(before), 1)
                    self.assertEqual(len(after), 2)
                else:
                    self.assertGreaterEqual(len(before), 2)
                    self.assertEqual(fixed.read_bytes(), original.read_bytes())
                digest = hashlib.sha256(fixed.read_bytes()).hexdigest()
                repeated = Path(cut_video_segment(str(source), interval, output_dir=directory, sampling_fps=2.))
                self.assertEqual(hashlib.sha256(repeated.read_bytes()).hexdigest(), digest)

    def test_short_video_padding_and_ordinary_full_video_passthrough(self):
        with tempfile.TemporaryDirectory() as directory:
            for frames, source_fps in [(1, 8), (5, 30), (90, 30)]:
                path = Path(directory) / f'{frames}.mp4'
                writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), source_fps, (64, 64))
                self.assertTrue(writer.isOpened())
                try:
                    for index in range(frames):
                        writer.write(np.full((64, 64, 3), index % 256, dtype=np.uint8))
                finally:
                    writer.release()
                info = probe_video_info(str(path))
                agent = VideoAgent.__new__(VideoAgent)
                agent.video_id = 'video_1'
                agent.video_path = str(path)
                agent.duration_sec = info['duration_sec']
                agent.source_frame_count = info['frame_count']
                agent.max_video_frames_per_request = 512
                agent.cache_dir = directory
                fps = agent._effective_fps(2, agent.duration_sec)
                interval = [0, agent.duration_sec]
                fixed = agent._video_input_path(interval, fps)
                if frames == 90:
                    self.assertEqual(fixed, str(path))
                    continue
                before, _ = OpenCVVideoBackend.load_bytes(path.read_bytes(), num_frames=512, fps=fps)
                after, _ = OpenCVVideoBackend.load_bytes(Path(fixed).read_bytes(), num_frames=512, fps=fps)
                self.assertEqual(len(before), 1)
                self.assertGreaterEqual(len(after), 2)
                digest = hashlib.sha256(Path(fixed).read_bytes()).hexdigest()
                repeated = agent._video_input_path(interval, fps)
                self.assertEqual(hashlib.sha256(Path(repeated).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
