"""MVU-Eval through the official `inference/main.py`.

Messages come from the official `build_messages_base` (its `encode_video` does the sampling,
resizing and JPEG encoding; the harness only caches its return value). Scoring is the
`analyze.py` rule: first character of the stripped, upper-cased output equals `ground_truth`.
Changed by the unified protocol: `nframes` is the question cap split evenly over the videos
(official 32 per video), `max_pixels` (longest edge) is run.py's `--max-side` (official 720), and
each official `[Video k] <file name>` label becomes `Video k:`. File names are not shown to the
model: in 68 TR questions the clip number in the name alone gives the answer, and MVAgent only ever
sees positional IDs.
"""

from __future__ import annotations

import re
from typing import Any

from .answers import leads_with_choice, option_labels, read_choice
from .common import MVU_SOURCE, load_official_module, read_json, video_label
from .media import cached, image_sizes, source_identity

MAIN = MVU_SOURCE / "inference/main.py"
# main.py sends no generation parameters (server defaults). Greedy decoding makes runs repeatable.
# The official prompt makes models explain before answering (Qwen3.5-9B: 53/64 outputs), so the cap
# matches CrossVid's official 8192 and only stops runaway output; it cannot change the first character.
GENERATION = {"max_tokens": 8192, "temperature": 0.0, "top_p": 1.0}


class MVUEval:
    name = "mvu_eval"

    def __init__(self, *, data_root, frames: int, max_side: int) -> None:
        self.module = load_official_module(MAIN, "mvu_eval_official_main", import_root=MVU_SOURCE / "inference")
        official_encode = self.module.encode_video

        def encode_video(video_path, max_pixels, max_frames=32):
            identity = {"version": 1, "source": source_identity(video_path), "max_pixels": max_pixels, "max_frames": max_frames}
            return cached("mvu_eval_frames", identity, lambda: official_encode(video_path, max_pixels=max_pixels, max_frames=max_frames))

        self.module.encode_video = encode_video  # build_messages_base resolves it from module globals
        self.generation = GENERATION
        self.data_root = data_root / "mvu-eval"
        self.frames = frames
        self.max_side = max_side
        payload = read_json(self.data_root / "MVU_Eval_QAs.json")
        self.items = [
            {"sample_id": f"mvu_eval:{row['task']}:{key}", "task": row["task"], "row": row}
            for key, row in sorted(payload.items(), key=lambda pair: int(pair[0]))
        ]

    def protocol(self) -> dict[str, Any]:
        return {
            "official": "inference/main.py build_messages_base + analyze.py first-character score",
            "generation": self.generation,
            "frames_per_video": f"min({self.frames} // number_of_videos, source frames)",
            "max_side": self.max_side,
            "video_label": "official '[Video k] <file name>' replaced by 'Video k:'",
            "score": "output.strip().upper()[:1] == ground_truth",
        }

    def infer(self, item: dict[str, Any], backend) -> dict[str, Any]:
        row = item["row"]
        videos = row["video_paths"]
        per_video = self.frames // len(videos)
        content = self.module.build_messages_base(str(self.data_root), row, videos, per_video, self.max_side)
        labels = [
            index for index, part in enumerate(content)
            if part["type"] == "text" and re.fullmatch(r"\[Video \d+\] .+", part["text"])
        ]
        if [content[index]["text"] for index in labels] != [f"[Video {k}] {name}" for k, name in enumerate(videos, 1)]:
            raise RuntimeError("official build_messages_base no longer labels videos as '[Video k] <file name>'")
        for k, index in enumerate(labels, 1):
            content[index] = {"type": "text", "text": video_label(k)}
        messages = [{"role": "user", "content": content}]
        text, request = backend.complete(messages, **self.generation)
        sizes = image_sizes(messages)
        return {
            "output": text,
            "media": {"frames": len(sizes), "frame_max_side": max(max(size) for size in sizes), "videos": len(videos), "frames_per_video": per_video},
            "request": request,
        }

    def score(self, item: dict[str, Any], output: str) -> dict[str, Any]:
        """Official first-character score, plus the format-robust score (see harness/answers.py)."""
        prediction = str(output).strip().upper()[:1]
        answer = item["row"]["ground_truth"]
        labels = option_labels(item["row"]["options"])
        format_ok = leads_with_choice(output, labels)
        robust = prediction if format_ok else read_choice(output, labels)
        return {
            "prediction": prediction, "answer": answer, "score": float(prediction == answer),
            "format_ok": format_ok, "robust_prediction": robust, "robust_score": float(robust == answer),
        }
