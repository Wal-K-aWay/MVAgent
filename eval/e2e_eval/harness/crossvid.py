"""CrossVid through the ten official task scripts in `CrossVid/eval/`.

Each question runs the official `evaluate(pair, max_tries=3)`: frame allocation, sampling,
resizing, bbox/interval handling, prompt and message layout are all official. The harness only
replaces the module-level `chat()` with a backend call that uses the official generation
arguments read from `chat()` itself. Scoring mirrors each script's `main()`: exact string match
(BU against the joined answer letters), FSA interval IoU, CCQA via the `score_CCQA.py` judge.
Changed by the unified protocol: `--frames 512 --length 448` (official defaults 128 / 360).
"""

from __future__ import annotations

import threading
from typing import Any

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
        task, row = item["task"], item["row"]
        if task == "CCQA":
            raise ValueError("CCQA is scored by the judge (harness.ccqa)")
        if task == "FSA":
            try:
                start, end = output.split(",")
                start, end = float(start), float(end)
                iou = self.modules["FSA"].interval_iou((start, end), (row["answer"][0], row["answer"][1]))
                return {"prediction": [start, end], "answer": row["answer"], "score": float(iou)}
            except Exception:  # noqa: BLE001 - FSA.py main(): any parse failure scores 0
                return {"prediction": output, "answer": row["answer"], "score": 0.0}
        expected = "".join(row["answer"]) if task == "BU" else row["answer"]
        return {"prediction": output, "answer": expected, "score": float(output == expected)}
