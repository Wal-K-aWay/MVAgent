#!/usr/bin/env python3
"""JST attribution-judge probe on real MVAgent failure trajectories.

Selects 10 failed samples (5 cvbench + 5 mvu_eval across task types) from the
no-skill run records, renders each into a clear text trajectory, and asks
deepseek-v4-flash to attribute the failure per the JST design (§5.2 of
analysis/skill_evolution/next_steps.md).

Results are saved incrementally under outputs/attribution_probe/<run>/.
Already-attributed samples are skipped on re-run.

Video durations are probed with cv2; run with an interpreter that has cv2
(e.g. /home/kww/miniconda3/envs/MVAgent/bin/python) or durations render as
"unknown duration".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

RECORDS_ROOT = Path(
    "/home/kww/projects/MVAgent_API/outputs/mvagent/no_skill/qwen3_5_35b_a3b_mvagent_no_skill/records"
)
API_KEY = os.environ["DEEPSEEK_API_KEY"]
API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-v4-flash"

MVU_TASKS = ["RAG", "KIR", "ICL", "TR", "Comparison"]  # one sample each
CVBENCH_COUNT = 5

# Frame cap of this run's observer model (configs/inference/local_qwen35_vllm_no_skill.yaml:
# max_video_frames_per_request: 512). watch_videos caps are recorded per clip in
# the records (video_frame_limit).
OBSERVE_FRAME_CAP = 512

SYSTEM_PROMPT = """You are a failure-attribution judge for a two-layer multi-video question-answering system:

- A GlobalAgent coordinator sees the full question and chooses actions:
  analyze_videos (send one instruction per selected video to per-video agents),
  watch_videos (directly observe clips from several videos itself), and
  answer (final answer, ends the episode).
- Per-video VideoAgents each see only their own video and the instruction they
  received. They choose observe (with what/where/fps) and finish (return a
  summary to the GlobalAgent).
- The GlobalAgent never sees VideoAgent internals (observe parameters, raw
  observations); it only receives the returned summaries.

You will be given ONE failed episode: the question, the ground-truth answer,
the final answer, and the complete two-role trajectory (with video durations
and per-observe frame estimates).

Walk the dependency chain BACKWARD: answer <- Global decisions <- returned
summaries <- Video observe choices <- instructions. Locate each failure point
and classify its loc:

- global_decision: the available summaries were sufficient, but the GlobalAgent
  chose the wrong action, wrong video set, wrong clips to watch, or answered
  too early / too late. (subtypes: premature_answer, wrong_video_selection,
  wrong_clip, late_answer, synthesis_error)
- global_instruction: the instruction sent to a VideoAgent was vague, missing
  context, mismatched to the question facet, or in a form the video agent
  could not answer. (subtypes: vague, missing_context, wrong_goal)
- video_observe: the instruction was reasonable, but the observe strategy
  (where / fps / number of passes) missed the key fact.
  (subtypes: search_failure = wrong region, sampling_failure = too sparse for
  a brief/fine event, coverage_failure = required full-video coverage missing)
- video_summary: the fact WAS observed in a raw observation but was lost or
  distorted in the returned summary, or the VideoAgent finished too early.
  (subtypes: compression_failure, distortion_failure, stopping_failure)
- interface: both sides look locally reasonable but do not fit together, e.g.
  the instruction is locally reasonable yet its answer form does not match what
  the GlobalAgent actually needed, or the summary is locally complete yet does
  not carry what the GlobalAgent's next decision required. Interface failures
  require BOTH skills to change together.
- perception: the raw observation itself is wrong (VLM misread or missed
  something in the frames it was given). NOT fixable by either skill's decision
  policy - do not invent decision-level failure points when the root cause is
  perception.

Rules:
- Ground every failure point in a concrete quote or paraphrase from the
  trajectory (the evidence field).
- Mark confidence "high" only when the evidence is decisive; use "low"
  otherwise.
- One episode usually has 1-3 failure points; order them by causal importance
  (the first entry is the root cause).
- If the root cause is perception, still list it, but do NOT invent
  decision-level points to justify skill edits.
- The judge sees the ground-truth answer for training-time attribution only;
  never propose edits that hardcode the answer.

Respond ONLY with a valid JSON object (no markdown fences, no extra text):
{
  "failure_points": [
    {
      "id": "fp1",
      "loc": "global_decision | global_instruction | video_observe | video_summary | interface | perception",
      "subtype": "<subtype>",
      "video_id": "<video id or null>",
      "round": <global round number or null>,
      "evidence": "<concrete evidence from the trajectory>",
      "confidence": "high | low"
    }
  ],
  "attribution_summary": "<2-4 sentences: what went wrong and why, in causal order>"
}"""


# ---------------------------------------------------------------- selection

def load_failed(dataset: str) -> list[dict]:
    out = []
    for f in sorted((RECORDS_ROOT / dataset).glob("*/result.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("status") == "ok" and not d.get("correct"):
            out.append(d)
    return out


def select_samples() -> list[dict]:
    picked: list[dict] = []
    cv = load_failed("cvbench")
    step = max(1, len(cv) // CVBENCH_COUNT)
    picked.extend(cv[i * step] for i in range(CVBENCH_COUNT))
    mv = load_failed("mvu_eval")
    by_task: dict[str, list[dict]] = {}
    for d in mv:
        by_task.setdefault(d["sample_id"].split(":")[1], []).append(d)
    for task in MVU_TASKS:
        if by_task.get(task):
            picked.append(by_task[task][0])
    return picked


# ---------------------------------------------------------------- rendering

_DURATION_CACHE: dict[str, float | None] = {}


def probe_duration(path: str) -> float | None:
    """Video duration in seconds, probed from the local file (cached)."""
    if path in _DURATION_CACHE:
        return _DURATION_CACHE[path]
    dur: float | None = None
    try:
        import cv2

        cap = cv2.VideoCapture(path)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        if frames > 0 and fps > 0:
            dur = frames / fps
    except Exception:
        dur = None
    _DURATION_CACHE[path] = dur
    return dur


def _where_summary(where: list) -> tuple[str, float]:
    parts = [f"[{a},{b}]" for a, b in where]
    span = sum(b - a for a, b in where)
    return ", ".join(parts), span


def render_trajectory(d: dict) -> str:
    r = d["result"]
    q = r["input"]["question"]
    videos = r["input"]["videos"]
    ans = r.get("answer") or {}
    lines: list[str] = []
    lines.append(f"VIDEOS ({len(videos)}):")
    for vid, path in videos.items():
        dur = probe_duration(path)
        dur_s = f"{dur:.1f}s" if dur is not None else "unknown duration"
        lines.append(f"  {vid}: {dur_s}")
    lines.append("")
    lines.append(f"QUESTION:\n{q}")
    lines.append("")
    lines.append("===== EPISODE TRAJECTORY =====")
    lines.append("")

    for t in r["trajectory"]:
        agent, action = t["agent"], t["action"]
        if agent == "GlobalAgent" and action == "decide":
            o = t.get("output", {})
            lines.append(f"[Global Round {t.get('round')}] decide")
            if o.get("reason"):
                lines.append(f"  Reason: {o['reason']}")
            act = o.get("action")
            lines.append(f"  Action: {act}")
            params = o.get("parameters", {}) or {}
            if act == "analyze_videos":
                for req in params.get("videoagent_request", []):
                    lines.append(f"    Instruction -> {req['video_id']}: \"{req['instruction']}\"")
            elif act == "watch_videos":
                lines.append(f"    Watch instruction: \"{params.get('instruction')}\"")
                for v in params.get("videos", []):
                    lines.append(f"    Clip -> {v['video_id']}: [{v['clip'][0]}, {v['clip'][1]}]")
            elif act == "answer":
                lines.append(f"    Answer: {params.get('answer')}")
            if act != "answer":
                lines.append("")
        elif agent == "VideoAgent" and action == "run":
            vid = t.get("video_id")
            inp = t.get("input", {})
            lines.append(f"  [VideoAgent {vid}]")
            lines.append(f"    Received instruction: \"{inp.get('instruction')}\"")
            o = t.get("output", {})
            for s in o.get("steps", []):
                if s["action"] == "observe":
                    p = s["parameters"]
                    where, span = _where_summary(p.get("where", []))
                    fps = p.get("fps")
                    est_frames = round(span * fps) if fps else None
                    lines.append(f"    Step {s['step']}: observe")
                    lines.append(f"      what: \"{p.get('what')}\"")
                    lines.append(
                        f"      where: {where}   fps: {fps}"
                        f"   (~{est_frames} frames; capped at {OBSERVE_FRAME_CAP})"
                    )
                    res = s.get("result", {})
                    if res.get("status") != "ok":
                        lines.append(f"      OBSERVE FAILED: {res}")
                    for ob in res.get("observations", []):
                        lines.append(f"      Observation: \"{ob.get('text')}\"")
                        if ob.get("uncertainty"):
                            lines.append(f"      Uncertainty: \"{ob['uncertainty']}\"")
                elif s["action"] == "finish":
                    lines.append(f"    Step {s['step']}: finish")
                    lines.append(f"      Summary returned to Global: \"{s['parameters'].get('summary')}\"")
            lines.append("")

    for w in r.get("watch_results", []):
        lines.append("[watch_videos result]")
        lines.append(f"  Instruction: \"{w.get('instruction')}\"  fps: {w.get('fps')}")
        for v in w.get("videos", []):
            tr = v.get("time_range", [None, None])
            limit = v.get("video_frame_limit")
            est = v.get("estimated_frames")
            frame_info = f"  (~{est} frames; capped at {limit})" if limit else ""
            lines.append(
                f"  Clip {v.get('video_id')}: [{tr[0]}, {tr[1]}]{frame_info}"
                f" -> \"{v.get('text', '')}\""
            )
        lines.append("")

    if ans:
        lines.append("[Final Answer]")
        lines.append(f"  Answer: {ans.get('answer')}")
        lines.append(f"  Reason: {ans.get('reason')}")
        lines.append("")
    lines.append("===== EVALUATION =====")
    lines.append(f"FINAL ANSWER: {d.get('prediction')}")
    lines.append(f"GROUND TRUTH: {d.get('ground_truth')}")
    lines.append(f"OFFICIAL RESULT: INCORRECT (score={d.get('score')})")
    return "\n".join(lines)


# ---------------------------------------------------------------- LLM call

def parse_json_loose(text: str) -> dict:
    try:
        import json_repair

        return json_repair.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in response")
    return json.loads(m.group(0))


def call_attribution(traj_text: str, sample_id: str, max_retries: int = 3) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"EPISODE TO ATTRIBUTE:\n\n{traj_text}"},
        ],
        "temperature": 0.0,
        "max_tokens": 8192,
        # Reasoning mode burns >16k tokens before emitting content on this task
        # (same failure mode as the CCQA judge); disable thinking entirely.
        "thinking": {"type": "disabled"},
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=600)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            usage = resp.json().get("usage", {})
            out = parse_json_loose(content)
            if not isinstance(out, dict) or "failure_points" not in out:
                raise ValueError(f"missing failure_points in parsed output: {str(out)[:200]}")
            out.setdefault("sample_id", sample_id)
            out["_usage"] = usage
            out["_raw"] = content
            return out
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  [{sample_id}] attempt {attempt} failed: {e}", flush=True)
            time.sleep(5 * attempt)
    raise RuntimeError(f"attribution failed after {max_retries} retries: {last_err}")


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/attribution_probe/deepseek_v4_flash_20260903")
    ap.add_argument("--limit", type=int, default=0, help="only first N samples (smoke test)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    (out_dir / "trajectories").mkdir(parents=True, exist_ok=True)
    (out_dir / "attributions").mkdir(parents=True, exist_ok=True)

    samples = select_samples()
    if args.limit:
        samples = samples[: args.limit]
    print(f"selected {len(samples)} failed samples:")
    for s in samples:
        print(f"  - {s['sample_id']}")

    summary = []
    for d in samples:
        sid = d["sample_id"].replace(":", "_").replace("/", "_")
        traj_path = out_dir / "trajectories" / f"{sid}.txt"
        attr_path = out_dir / "attributions" / f"{sid}.json"
        traj = render_trajectory(d)
        traj_path.write_text(traj, encoding="utf-8")
        if attr_path.exists():
            print(f"[{d['sample_id']}] already attributed, skip", flush=True)
            summary.append(json.loads(attr_path.read_text(encoding="utf-8")))
            continue
        print(f"[{d['sample_id']}] calling {MODEL} ...", flush=True)
        try:
            result = call_attribution(traj, d["sample_id"])
        except Exception as e:  # noqa: BLE001
            print(f"[{d['sample_id']}] FAILED: {e}", flush=True)
            summary.append({"sample_id": d["sample_id"], "error": str(e)})
            continue
        raw = result.pop("_raw", "")
        usage = result.pop("_usage", {})
        result["trajectory_chars"] = len(traj)
        result["usage"] = usage
        attr_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out_dir / "attributions" / f"{sid}.raw.txt").write_text(raw, encoding="utf-8")
        fps = "; ".join(
            f"{p.get('loc')}/{p.get('subtype')}({p.get('confidence')})"
            for p in result.get("failure_points", [])
        )
        print(f"[{d['sample_id']}] done: {fps}", flush=True)
        summary.append(result)

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {out_dir / 'summary.json'} ({len(summary)} samples)")


if __name__ == "__main__":
    sys.exit(main())
