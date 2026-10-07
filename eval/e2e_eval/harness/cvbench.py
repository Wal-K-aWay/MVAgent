"""CVBench through the official lmms-eval `mvr` task and its Qwen2.5-VL adapter.

Taken verbatim from the official sources at load time: the question list, `mvr_doc_to_text`
(prompt), the yaml prompt kwargs, the adapter's system message and cue sentence, and
`extract_characters_regex` (scoring). Kept from the adapter: video order (`video_1..video_4`),
start cue image -> the video's frames -> end cue image per video, cue sentence then prompt,
temperature/top_p from the yaml and the hard-coded `max_new_tokens=128`.
Changed by the unified protocol: each video's frames are sent as ordered JPEG images (the adapter
passes a video element to qwen_vl_utils), the question's frame cap is split evenly over its videos
(official 8 per video), and the longest edge is capped with the aspect ratio kept (official 448x448).
"""

from __future__ import annotations

import base64
import re
from typing import Any

from .common import CVBENCH_SOURCE, official_function, official_string, read_json
from .media import image_sizes, sample_frames

LMMS = CVBENCH_SOURCE / "lmms-eval/lmms_eval"
ADAPTER = LMMS / "models/qwen2_5_vl.py"
TASK = LMMS / "tasks/mvr"
QUESTIONS = CVBENCH_SOURCE / "Video-R1/src/r1-v/Evaluation/CVBench.json"
CUES = CVBENCH_SOURCE / "lmms-eval/res"


def _task_spec() -> dict[str, Any]:
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!function", lambda loader, node: loader.construct_scalar(node))
    return yaml.load((TASK / "mvr.yaml").read_text(encoding="utf-8"), Loader=Loader)


def _image(url: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": url}}


def _png(path) -> dict[str, Any]:
    return _image("data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii"))


class CVBench:
    name = "cvbench"

    def __init__(self, *, data_root, frames: int, max_side: int) -> None:
        spec = _task_spec()
        self.prompt_kwargs = spec["lmms_eval_specific_kwargs"]["default"]
        self.doc_to_text = official_function(TASK / "utils.py", "mvr_doc_to_text")
        self.extract = official_function(TASK / "utils.py", "extract_characters_regex", {"re": re})
        self.system = official_string(ADAPTER, "You are a helpful assistant")
        self.cue_text = official_string(ADAPTER, "Please pay close attention to the video frames")
        if "max_new_tokens=128," not in ADAPTER.read_text(encoding="utf-8"):
            raise RuntimeError("official CVBench adapter no longer hard-codes max_new_tokens=128")
        generation = spec["generation_kwargs"]
        self.generation = {"max_tokens": 128, "temperature": float(generation["temperature"]), "top_p": float(generation["top_p"])}
        self.video_root = data_root / "cvbench"
        self.frames = frames
        self.max_side = max_side
        self.items = [
            {"sample_id": f"cvbench:{row['id']}", "task": row["task_type"], "row": row}
            for row in read_json(QUESTIONS)
        ]

    def protocol(self) -> dict[str, Any]:
        return {
            "official": "lmms-eval mvr task + qwen2_5_vl adapter",
            "generation": self.generation,
            "frames_per_video": f"min({self.frames} // number_of_videos, source frames), linspace(...).round()",
            "max_side": self.max_side,
            "frame_input": "ordered JPEG images (quality 95) between each video's start and end cue images",
            "score": "extract_characters_regex(output).strip().upper() == answer.strip().upper()",
        }

    def infer(self, item: dict[str, Any], backend) -> dict[str, Any]:
        row = item["row"]
        videos = [row[f"video_{index}"] for index in range(1, 5) if row[f"video_{index}"] is not None]
        per_video = self.frames // len(videos)
        content: list[dict[str, Any]] = []
        frame_parts: list[dict[str, Any]] = []
        cue_parts: list[dict[str, Any]] = []
        media = []
        for index, relative in enumerate(videos, start=1):
            frames, meta = sample_frames(self.video_root / relative, count=per_video, max_side=self.max_side)
            parts = [_image(f"data:image/jpeg;base64,{frame}") for frame in frames]
            cues = [_png(CUES / f"video{index}.png"), _png(CUES / f"end{index}.png")]
            content += [cues[0], *parts, cues[1]]
            frame_parts += parts
            cue_parts += cues
            media.append({"video": relative, **meta})
        content += [
            {"type": "text", "text": self.cue_text},
            {"type": "text", "text": self.doc_to_text(row, self.prompt_kwargs)},
        ]
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": content}]
        text, request = backend.complete(messages, **self.generation)
        frame_sizes = image_sizes([{"content": frame_parts}])
        cue_sizes = image_sizes([{"content": cue_parts}])
        return {
            "output": text,
            "media": {
                "frames": len(frame_sizes),
                "frame_max_side": max(max(size) for size in frame_sizes),
                "videos": media,
                "cue_images": len(cue_sizes),
                "cue_image_max_side": max(max(size) for size in cue_sizes),
            },
            "request": request,
        }

    def score(self, item: dict[str, Any], output: str) -> dict[str, Any]:
        prediction = self.extract(output).strip().upper()
        answer = item["row"]["answer"].strip().upper()
        return {"prediction": prediction, "answer": answer, "score": float(prediction == answer)}
