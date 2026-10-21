"""Shared evaluation remains usable after removing optimizer infrastructure."""
import json
from pathlib import Path
import tempfile
import unittest

from evaluation.benchmarks import EvaluationSample, OrderingScorer, TemporalLocalizationScorer
from evaluation.data import DataSplitManifest, SplitSample, group_by_media
from evaluation.store import write_json


class EvaluationUtilitiesTests(unittest.TestCase):
    def test_grouping_preserves_transitive_source_isolation(self):
        groups = group_by_media({"a": ["x"], "b": ["x", "y"], "c": ["y"], "d": ["z"]})
        self.assertEqual(groups["a"], groups["c"])
        manifest = DataSplitManifest.from_groups(dataset="synthetic", sample_groups=groups)
        self.assertEqual(len({s.split for s in manifest.samples if s.sample_id != "d"}), 1)
        with self.assertRaises(ValueError):
            DataSplitManifest("synthetic", 0, (SplitSample("a", "train", "x"), SplitSample("b", "eval", "x")))

    def test_atomic_json_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            write_json(path, {"value": "previous"})
            with self.assertRaises(TypeError):
                write_json(path, {"value": object()})
            self.assertEqual(json.loads(path.read_text()), {"value": "previous"})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_official_closed_form_scores(self):
        ordering = EvaluationSample(task="ordering", question="Order clips", videos={"v": "v.mp4"}, ground_truth=[1, 2, 3])
        temporal = EvaluationSample(task="temporal_localization", question="Locate event", videos={"v": "v.mp4"}, ground_truth=[2, 6])
        self.assertEqual(OrderingScorer().score(sample=ordering, prediction="1->2->3").score, 1.0)
        self.assertEqual(TemporalLocalizationScorer().score(sample=temporal, prediction="4,8").score, 1 / 3)


if __name__ == "__main__":
    unittest.main()
