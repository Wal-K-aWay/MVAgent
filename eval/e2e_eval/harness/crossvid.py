"""CrossVid through the ten official task scripts in `CrossVid/eval/`.

Each question runs the official `evaluate(pair, max_tries=3)`: frame allocation, sampling,
resizing, bbox/interval handling, prompt and message layout are all official. The harness only
replaces the module-level `chat()` with a backend call that uses the official generation
arguments read from `chat()` itself. Scoring mirrors each script's `main()`: exact string match
(BU against the joined answer letters), FSA interval IoU, CCQA via the `score_CCQA.py` judge.
Changed by the unified protocol: the official `--frames` / `--length` take run.py's `--frames` / `--max-side`
(official defaults 128 / 360).
"""

from __future__ import annotations

import re
import threading
from typing import Any

from .answers import option_labels, read_choice, read_interval, read_letters, read_order
from .common import CROSSVID_SOURCE, load_official_module, official_call_kwargs, read_json
from .media import image_sizes

TASKS = ("BU", "CC", "CCQA", "FSA", "MOC", "MSR", "NC", "PEA", "PI", "PSS")
EVAL_DIR = CROSSVID_SOURCE / "eval"


def official_generation() -> dict[str, Any]:
    kwargs = {task: official_call_kwargs(EVAL_DIR / f"{task}.py", "chat", "create") for task in TASKS}
    if len({tuple(sorted(value.items())) for value in kwargs.values()}) != 1:
        raise RuntimeError(f"CrossVid task scripts disagree on chat() arguments: {kwargs}")
    generation = dict(kwargs["NC"])
    generation.pop("stream", None)
    return generation


class CrossVid:
    name = "crossvid"

    def __init__(self, *, data_root, frames: int, max_side: int, tasks: tuple[str, ...] = TASKS) -> None:
        self.generation = official_generation()
        self.frames = frames
        self.max_side = max_side
        self._local = threading.local()
        self.modules = {}
        self.items = []
        root = data_root / "crossvid"
        for task in tasks:
            module = load_official_module(EVAL_DIR / f"{task}.py", f"crossvid_official_{task}", import_root=EVAL_DIR)
            module.total_frames = frames
            module.length = max_side
            module.video_root = str(root / ("uav" if task in {"MOC", "MSR"} else "videos"))
            module.chat = self._chat
            self.modules[task] = module
            self.items += [
                {"sample_id": f"crossvid:{task}:{row['id']}", "task": task, "row": row}
                for row in read_json(root / "QA" / f"{task}.json")
            ]

    def protocol(self) -> dict[str, Any]:
        return {
            "official": "eval/<TASK>.py evaluate() per question; scoring as in each script's main()",
            "generation": self.generation,
            "frames": f"--frames {self.frames} (total per question, allocated by each task script)",
            "max_side": f"--length {self.max_side}",
            "score": "exact match (BU: joined letters); FSA: interval_iou; CCQA: score_CCQA.py judge",
        }

    def _chat(self, messages: list[dict[str, Any]]) -> str:
        state = self._local
        try:
            text, state.request = state.backend.complete(messages, **self.generation)
        except Exception as exc:
            state.errors.append(f"{type(exc).__name__}: {exc}")
            raise
        state.sizes = image_sizes(messages)
        return text

    def infer(self, item: dict[str, Any], backend) -> dict[str, Any]:
        state = self._local
        state.backend, state.errors, state.request, state.sizes = backend, [], None, []
        result = self.modules[item["task"]].evaluate(item["row"], max_tries=3)
        if result is None:
            cause = f"last model error: {state.errors[-1]}" if state.errors else "it failed while preparing media or the prompt"
            raise RuntimeError(f"official evaluate() gave up after 3 tries; {cause}")
        _, answer = result
        return {
            "output": answer,
            "media": {"frames": len(state.sizes), "frame_max_side": max((max(size) for size in state.sizes), default=0)},
            "request": state.request,
        }

    def score(self, item: dict[str, Any], output: str) -> dict[str, Any]:
        """Official score as in each script's main(), plus the format-robust score (harness/answers.py)."""
        task, row = item["task"], item["row"]
        if task == "CCQA":
            raise ValueError("CCQA is scored by the judge (harness.ccqa)")
        if task == "FSA":
            official = self._interval_score(output, row)
            format_ok = official is not None
            robust_text = output if format_ok else read_interval(output)
            robust = self._interval_score(robust_text, row) if robust_text else None
            return {
                "prediction": output, "answer": row["answer"], "score": official or 0.0,
                "format_ok": format_ok, "robust_prediction": robust_text, "robust_score": robust or 0.0,
            }
        labels = option_labels(row.get("options") or [])
        if task == "BU":
            expected = "".join(row["answer"])
            format_ok = bool(re.fullmatch(rf"[{labels}]+", output))
            robust = output if format_ok else read_letters(output, labels)
            robust_score = float(robust is not None and sorted(robust) == sorted(expected))
        elif task == "PSS":
            expected = row["answer"]
            format_ok = bool(re.fullmatch(r"\d+(?:->\d+)+", output))
            robust = output if format_ok else read_order(output)
            robust_score = float(robust == expected)
        else:
            expected = row["answer"]
            format_ok = bool(re.fullmatch(rf"[{labels}]", output))
            robust = output if format_ok else read_choice(output, labels)
            robust_score = float(robust == expected)
        return {
            "prediction": output, "answer": expected, "score": float(output == expected),
            "format_ok": format_ok, "robust_prediction": robust, "robust_score": robust_score,
        }

    def _interval_score(self, text: str, row: dict[str, Any]) -> float | None:
        """FSA.py main(): "start,end" -> IoU with the reference; None when it does not parse."""
        try:
            start, end = text.split(",")
            start, end = float(start), float(end)
            return float(self.modules["FSA"].interval_iou((start, end), (row["answer"][0], row["answer"][1])))
        except Exception:  # noqa: BLE001 - FSA.py main(): any parse failure scores 0
            return None
