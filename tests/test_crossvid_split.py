"""Small, standard-library-only checks for the public ten-task split CLI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_crossvid_train_cal_gate_split import ALL_TASKS, components, source_keys


class CrossVidSplitTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.qa = self.root / 'QA'
        self.qa.mkdir()
        for task in ALL_TASKS:
            rows = [{'id': i, **({'vid': f'{task}-{i}'} if task in ('MOC', 'MSR')
                                else {'videos': [f'{task}-{i}.mp4']})} for i in range(6)]
            (self.qa / f'{task}.json').write_text(json.dumps(rows))
        self.panel = self.root / 'panel.json'
        self.panel.write_text(json.dumps({'version': 2, 'samples': [
            {'sample_id': f'crossvid:{task}:0'} for task in ALL_TASKS]}))

    def run_cli(self, name='split.json', quota='1,1,1'):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/prepare_crossvid_train_cal_gate_split.py'),
            '--qa-dir', str(self.qa), '--exclude-panel', str(self.panel), '--per-task', quota,
            '--output', str(self.root / name)], capture_output=True, text=True)

    def test_complete_deterministic_disjoint_and_no_overwrite(self):
        # Cross-task shared media must stay in one partition when both questions are sampled.
        rows = json.loads((self.qa / 'CCQA.json').read_text())
        for row in rows:
            row['videos'] = [f"BU-{row['id']}.mp4"]
        (self.qa / 'CCQA.json').write_text(json.dumps(rows))
        for name in ('split.json', 'same.json'):
            result = self.run_cli(name)
            self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / 'split.json'
        original = path.read_bytes()
        self.assertEqual(original, (self.root / 'same.json').read_bytes())
        manifest = json.loads(original)
        self.assertEqual(manifest['seed'], 0)
        samples = manifest['samples']
        self.assertEqual(len(samples), 30)
        self.assertEqual(len({sample['sample_id'] for sample in samples}), 30)
        groups = {}
        for sample in samples:
            self.assertFalse(sample['sample_id'].endswith(':0'))
            groups.setdefault(sample['group_id'], set()).add(sample['split'])
        self.assertTrue(all(len(partitions) == 1 for partitions in groups.values()))
        for partition in ('train', 'cal', 'eval'):
            self.assertEqual({sample['sample_id'].split(':')[1] for sample in samples
                              if sample['split'] == partition}, set(ALL_TASKS))
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_inputs_and_unfillable_quota_write_nothing(self):
        for quota in ('1,1', '1,1,0', 'a,1,1', '1,1,1,1', '10,10,10'):
            with self.subTest(quota=quota):
                self.assertNotEqual(self.run_cli(quota=quota).returncode, 0)
                self.assertFalse((self.root / 'split.json').exists())
        path = self.qa / 'BU.json'
        rows = json.loads(path.read_text())
        path.write_text(json.dumps([*rows, rows[0]]))
        self.assertIn('Duplicate question ID', self.run_cli().stderr)
        path.write_text(json.dumps(rows))
        self.panel.write_text(json.dumps({'version': 2, 'samples': [{'sample_id': 'crossvid:BU:missing'}]}))
        self.assertIn('unknown or duplicate', self.run_cli().stderr)
        self.assertFalse((self.root / 'split.json').exists())

    def test_source_components_include_transitive_and_uav_links(self):
        groups = components({'a': ['video:x'], 'bridge': ['video:x', 'video:y'],
                             'c': ['video:y'], 'other': ['video:z']})
        self.assertEqual(groups['a'], groups['c'])
        self.assertNotEqual(groups['a'], groups['other'])
        self.assertEqual(source_keys('MOC', {'vid': 42}), source_keys('MSR', {'vid': 42}))


if __name__ == '__main__':
    unittest.main()
