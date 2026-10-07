"""CVBench through the official lmms-eval `mvr` task and its Qwen2.5-VL adapter.

Taken verbatim from the official sources at load time: the question list, `mvr_doc_to_text`
(prompt), the yaml prompt kwargs, the adapter's system message and cue sentence, and
`extract_characters_regex` (scoring). Kept from the adapter: video order (`video_1..video_4`),
cue image -> video -> cue image per video, cue sentence then prompt, temperature/top_p from the
yaml and the hard-coded `max_new_tokens=128`. Changed by the unified protocol: frames per video
(question cap split evenly instead of 8) and an aspect-preserving longest edge instead of 448x448.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from .common import CVBENCH_SOURCE, official_function, official_string, read_json
from .media import image_sizes, video_part

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


def _png(path) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")}}


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
            "frames_per_video": f"min({self.frames} // number_of_videos, source frames)",
            "max_side": self.max_side,
            "video_transport": "vLLM: MJPEG AVI per video whose fps maps frame i to its source timestamp; "
            "APIs: ordered JPEG frames",
            "score": "extract_characters_regex(output).strip().upper() == answer.strip().upper()",
        }

    def infer(self, item: dict[str, Any], backend) -> dict[str, Any]:
        row = item["row"]
        videos = [row[f"video_{index}"] for index in range(1, 5) if row[f"video_{index}"] is not None]
        per_video = self.frames // len(videos)
        content: list[dict[str, Any]] = []
        media = []
        for index, relative in enumerate(videos, start=1):
            part, meta = video_part(
                self.video_root / relative, count=per_video, max_side=self.max_side, native_video=backend.native_video
            )
            content += [_png(CUES / f"video{index}.png"), part, _png(CUES / f"end{index}.png")]
            media.append({"video": relative, **meta})
        content += [
            {"type": "text", "text": self.cue_text},
            {"type": "text", "text": self.doc_to_text(row, self.prompt_kwargs)},
        ]
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": content}]
        # Keep every pre-sampled frame (vLLM otherwise keeps 32 / re-samples at 2 fps).
        extra = {"media_io_kwargs": {"video": {"num_frames": -1}}, "mm_processor_kwargs": {"do_sample_frames": False}}
        text, request = backend.complete(messages, **self.generation, extra_body=extra)
        cues = image_sizes(messages)
        return {
            "output": text,
            "media": {
                "videos": media,
                "video_frames": sum(item["frames"] for item in media),
                "video_max_side": max(max(item["size"]) for item in media),
                "cue_images": len(cues),
                "cue_image_max_side": max(max(size) for size in cues),
            },
            "request": request,
        }

    def score(self, item: dict[str, Any], output: str) -> dict[str, Any]:
        prediction = self.extract(output).strip().upper()
        answer = item["row"]["answer"].strip().upper()
        return {"prediction": prediction, "answer": answer, "score": float(prediction == answer)}
