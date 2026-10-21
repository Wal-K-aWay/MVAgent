"""Evaluation resumes from its frozen code after leaving src/."""
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class EvaluationSnapshotTest(unittest.TestCase):
    def test_resume_uses_frozen_evaluation_and_rejects_snapshot_changes(self):
        # Isolate module-cache changes made by the real snapshot loader.
        code = textwrap.dedent('''
            import importlib.util
            import json
            from pathlib import Path
            import shutil
            import sys
            import tempfile

            repo = Path(sys.argv[1])
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace, output = root / "workspace", root / "run"
                workspace.mkdir()
                (workspace / "src").symlink_to(repo / "src", target_is_directory=True)
                shutil.copytree(repo / "eval", workspace / "eval")
                sys.path.insert(0, str(workspace))
                import eval.benchmarks
                assert Path(eval.benchmarks.__file__).is_relative_to(workspace)
                source = workspace / "eval/agent_eval/run.py"
                spec = importlib.util.spec_from_file_location("snapshot_runner", source)
                runner = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(runner)
                data = root / "assets/cvbench"
                data.mkdir(parents=True)
                (data / "QAs.json").write_text(json.dumps([dict(
                    id=1, task_type="synthetic", question="Which color?",
                    videos={"video_1": "one.mp4"}, options=["A. red", "B. blue"], answer="A")]))
                kwargs = dict(output_dir=output,
                    config_path=repo / "configs/inference/modal_qwen35_35b_a3b_no_skill.yaml",
                    dataset_root=root / "assets", sample_ids=("cvbench:1",), judge_model=None)
                result = runner._prepare_output(**kwargs, resume=False)
                identity = result[-1]["identity"]
                assert "evaluation_snapshot_sha256" in identity
                assert not (output / "src/evaluation").exists()
                assert Path(sys.modules["eval.benchmarks"].__file__).is_relative_to(output)
                from eval.benchmarks import build_official_scorer
                scorer, _ = build_official_scorer(result[3], {})
                assert scorer.score_prediction("cvbench:1", "A").score == 1.0

                (workspace / "eval/benchmarks/scoring.py").write_text("raise RuntimeError('live workspace used')")
                resumed = runner._prepare_output(**kwargs, resume=True)
                assert resumed[-1]["identity"] == identity
                assert Path(sys.modules["eval.benchmarks.scoring"].__file__).is_relative_to(output)

                scoring = output / "eval/benchmarks/scoring.py"
                scoring.write_text(scoring.read_text() + "\\n# modified snapshot\\n")
                try:
                    runner._prepare_output(**kwargs, resume=True)
                except RuntimeError as exc:
                    assert "Resume identity differs" in str(exc)
                else:
                    raise AssertionError("modified evaluation snapshot accepted")
                print("Frozen evaluation: load, score, resume and tamper rejection passed.")
        ''')
        result = subprocess.run([sys.executable, "-c", code, str(Path(__file__).resolve().parents[1])],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
