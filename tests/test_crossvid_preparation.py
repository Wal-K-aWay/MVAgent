"""Exercise relocated worker/finalizer entry points on a tiny CPU-only video."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.data_preparation import crossvid_batch


class CrossVidPreparationTest(unittest.TestCase):
    def test_worker_and_finalizer_preserve_prepared_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'QA').mkdir()
            source = root / 'videos/assembly/tiny.mp4'
            source.parent.mkdir(parents=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=32x32:r=10:d=1', '-c:v', 'mpeg4', str(source)],
                           check=True, timeout=30)
            (root / 'QA/PEA.json').write_text(json.dumps([{
                'id': 1, 'videos': ['assembly/tiny.mp4', 'assembly/tiny.mp4'],
                'begin': [0, 0.2], 'end': [0.5, 0.7],
                'question': 'Which video shows the error?', 'options': ['A', 'B'], 'answer': 'A',
            }]))
            shard = root / 'shard.jsonl'
            subprocess.run(crossvid_batch._worker_command(root, 'pea', ['crossvid:PEA:1'], shard),
                           cwd=root, env=crossvid_batch._python_env(), check=True, timeout=60)
            row = json.loads(shard.read_text())
            self.assertEqual(row['id'], 'crossvid:PEA:1')
            clips = [root / value for value in row['videos'].values()]
            self.assertEqual(len(clips), 2)
            before = [(path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                      for path in clips]
            state_dir = root / 'state'
            state_dir.mkdir()
            # The finalizer launches the same relocated CLI with full-manifest settings.
            crossvid_batch._run_finalizer(root, state_dir, {})
            self.assertEqual(shard.read_bytes(), (root / 'qa.jsonl').read_bytes())
            metadata = json.loads((root / 'qa.meta.json').read_text())
            self.assertEqual(metadata['scope'], 'full')
            self.assertEqual(metadata['sample_count'], 1)
            self.assertEqual(before, [(path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                                      for path in clips])
            self.assertEqual(crossvid_batch._manifest_sha256([row]), metadata['manifest_sha256'])


if __name__ == '__main__':
    unittest.main()
