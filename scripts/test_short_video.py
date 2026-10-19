"""Exercise the accepted short-video repair through FFmpeg and vLLM's decoder (CPU)."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from vllm.multimodal.video import OpenCVVideoBackend

from mvagent.agents.video_agent.agent import VideoAgent
from mvagent.utils.media import probe_video_info


class ShortVideoTest(unittest.TestCase):
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
