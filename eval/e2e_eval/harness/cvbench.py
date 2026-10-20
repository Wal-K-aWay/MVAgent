"""CVBench through the official lmms-eval `mvr` task and its Qwen2.5-VL adapter.

Taken verbatim from the official sources at load time: the question list, `mvr_doc_to_text`
(prompt), the yaml prompt kwargs, the adapter's system message and `extract_characters_regex`
(scoring). Kept from the adapter: video order (`video_1..video_4`), all videos before the prompt,
temperature/top_p from the yaml and the hard-coded `max_new_tokens=128`.
Changed by the unified protocol: each video's frames are sent as ordered JPEG images after a
`Video k:` text label (the adapter passes a video element to qwen_vl_utils between "The video k" /
"Video k End" cue images and adds a sentence explaining those cues; both are dropped), the
question's frame cap is split evenly over its videos (official 8 per video), and the longest edge
is capped with the aspect ratio kept (official 448x448).
"""

from __future__ import annotations

import re
from typing import Any

from .answers import leads_with_choice, read_choice, read_yes_no
from .common import CVBENCH_SOURCE, official_function, official_string, read_json, video_label
from .media import image_sizes, sample_frames

LMMS = CVBENCH_SOURCE / "lmms-eval/lmms_eval"
ADAPTER = LMMS / "models/qwen2_5_vl.py"
TASK = LMMS / "tasks/mvr"
QUESTIONS = CVBENCH_SOURCE / "Video-R1/src/r1-v/Evaluation/CVBench.json"


def _task_spec() -> dict[str, Any]:
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!function", lambda loader, node: loader.construct_scalar(node))
    return yaml.load((TASK / "mvr.yaml").read_text(encoding="utf-8"), Loader=Loader)


class CVBench:
    name = "cvbench"

    def __init__(self, *, data_root, frames: int, max_side: int) -> None:
        spec = _task_spec()
        self.prompt_kwargs = spec["lmms_eval_specific_kwargs"]["default"]
        self.doc_to_text = official_function(TASK / "utils.py", "mvr_doc_to_text")
        self.extract = official_function(TASK / "utils.py", "extract_characters_regex", {"re": re})
        self.system = official_string(ADAPTER, "You are a helpful assistant")
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
            "frame_input": "per video: 'Video k:' text label, then its frames as ordered JPEG images (quality 95)",
            "score": "extract_characters_regex(output).strip().upper() == answer.strip().upper()",
        }

    def infer(self, item: dict[str, Any], backend) -> dict[str, Any]:
        row = item["row"]
        videos = [row[f"video_{index}"] for index in range(1, 5) if row[f"video_{index}"] is not None]
        per_video = self.frames // len(videos)
        content: list[dict[str, Any]] = []
        media = []
        for index, relative in enumerate(videos, start=1):
            frames, meta = sample_frames(self.video_root / relative, count=per_video, max_side=self.max_side)
            content.append({"type": "text", "text": video_label(index)})
            content += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame}"}} for frame in frames]
            media.append({"video": relative, **meta})
        content.append({"type": "text", "text": self.doc_to_text(row, self.prompt_kwargs)})
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": content}]
        text, request = backend.complete(messages, **self.generation)
        sizes = image_sizes(messages)
        return {
            "output": text,
            "media": {"frames": len(sizes), "frame_max_side": max(max(size) for size in sizes), "videos": media},
            "request": request,
        }

    def score(self, item: dict[str, Any], output: str) -> dict[str, Any]:
        """Official score, plus the format-robust score (see harness/answers.py)."""
        row = item["row"]
        prediction = self.extract(output).strip().upper()
        answer = row["answer"].strip().upper()
        # The official regex takes the first A-D/YES/NO anywhere, so it is only meaningful when the
        # output leads with its answer; otherwise read the answer the model committed to.
        yes_no = all(option.strip(".").lower() in {"yes", "no"} for option in row["options"])
        format_ok = leads_with_choice(output, "ABCD") or bool(re.match(r"\s*(?i:yes|no)\b", str(output)))
        if format_ok:
            robust = prediction
        elif yes_no:
            robust = read_yes_no(output)
        else:
            robust = read_choice(output, "ABCD") or read_yes_no(output)
        return {
            "prediction": prediction, "answer": answer, "score": float(prediction == answer),
            "format_ok": format_ok, "robust_prediction": robust, "robust_score": float(robust == answer),
        }
