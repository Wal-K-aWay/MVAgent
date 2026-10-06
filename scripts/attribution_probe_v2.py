#!/usr/bin/env python3
"""Two-stage cascade attribution probe (v2).

Stage 1 (Global view): the judge sees exactly what the GlobalAgent saw —
question, durations, its decisions, instructions sent, returned summaries,
watch texts, final answer. It judges global_decision / global_instruction /
watch-perception, runs a derivability check (quote facts from summaries that
entail the GT, else the summaries were insufficient), and lists suspect
videos for drill-down.

Stage 2 (per-video forensics, only for suspects): the judge sees one video
agent's internals — duration, received instruction, every observe step
(what/where/fps + raw observation), returned summary, plus what Global needed
and the GT. It judges video_observe / video_summary / perception / clean.

Merge (deterministic code): stage-1 points + stage-2 points; the residual
case "Global used its summaries correctly, instructions were sound, every
drilled video is clean, yet the needed facts never arrived" is classified as
interface (contract mismatch).

Run with an interpreter that has cv2 (durations), e.g.
/home/kww/miniconda3/envs/MVAgent/bin/python scripts/attribution_probe_v2.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

from attribution_probe import (
    API_KEY,
    API_URL,
    MODEL,
    OBSERVE_FRAME_CAP,
    _where_summary,
    parse_json_loose,
    probe_duration,
    select_samples,
)

STAGE1_PROMPT = """You are a failure-attribution judge (Stage 1: Global view) for a two-layer
multi-video question-answering system:

- A GlobalAgent coordinator sees the full question and chooses actions:
  analyze_videos (sends one instruction per selected video to per-video agents
  and receives one summary per video), watch_videos (observes clips from
  several videos itself), and answer (final answer, ends the episode).
- The GlobalAgent NEVER sees video agents' internals — only the summaries
  they return. You are judging from exactly the GlobalAgent's viewpoint: the
  episode below contains everything it ever saw.

You will be given ONE failed episode: the question, the ground-truth answer,
the final answer, and the GlobalAgent's full action history — every decision
with its reason, the instructions sent, the summaries that came back, the
watch observations, and the video durations.

Judge in this order:

1. Derivability check: could the ground-truth answer be derived from the
   returned summaries and watch texts ALONE? If you conclude the GlobalAgent
   made a decision error, you MUST quote the exact facts from the
   summaries/watch texts that entail the GT. If you cannot quote them, the
   available evidence was insufficient — say so and list suspect videos.

2. Decision errors (global_decision): wrong action, wrong video set, wrong
   clips to watch, answered too early (while uncertain summaries or empty
   watch texts were on record), answered too late, or failed synthesis
   (wrong arithmetic, wrong option mapping, ignored contradicting evidence,
   cited empty watch results as confirmation).
   Subtypes: premature_answer, wrong_video_selection, wrong_clip, late_answer,
   synthesis_error.

3. Instruction errors (global_instruction), judged on the instruction text
   alone against the question: vague, missing needed context, aimed at the
   wrong goal/facet, or leaking the expected answer into the search target.
   Subtypes: vague, missing_context, wrong_goal.

4. Watch-text anomalies: watch observations that are empty,
   self-contradictory, or implausible given other evidence may indicate
   perception problems (loc=perception, confidence low unless decisive).
   Note: the GlobalAgent treating an empty watch text as confirmation is a
   global_decision error regardless.

5. If facts needed for the GT are absent from the summaries, list the
   suspect videos in drill_down with what exactly was missing. This triggers
   a per-video forensic inspection in Stage 2. Do NOT guess whether the
   video agent or its observation was at fault — that is Stage 2's job.

Rules:
- Ground every failure point in a concrete quote from the episode.
- 1-3 failure points, ordered by causal importance (first = root cause).
- Mark confidence "high" only when the evidence is decisive.
- Never propose skill edits; you only locate failures.
- The ground-truth answer is for judging only.

Respond ONLY with a valid JSON object (no markdown fences, no extra text):
{
  "global_failure_points": [
    {
      "id": "fp1",
      "loc": "global_decision | global_instruction | perception",
      "subtype": "<subtype>",
      "video_id": "<video id or null>",
      "round": <global round number or null>,
      "evidence": "<concrete quoted evidence>",
      "confidence": "high | low"
    }
  ],
  "summaries_sufficient_for_gt": true | false,
  "drill_down": [
    {"video_id": "<id>", "missing": "<what fact was missing>", "evidence": "<why you suspect it>"}
  ],
  "attribution_summary": "<2-4 sentences in causal order>"
}"""

STAGE2_PROMPT = """You are a failure-attribution judge (Stage 2: per-video forensics) for the
same two-layer multi-video QA system. Stage 1 has already cleared the
GlobalAgent's decisions (or handled them separately) and flagged this video as
a suspect for a missing fact.

You inspect ONE VideoAgent's internal work: the video's duration, the
instruction it received from the GlobalAgent, every observe step (what /
where / fps / estimated frames) with its raw observation, and the summary it
returned. You also know what fact the GlobalAgent needed (from Stage 1) and
the ground truth.

The VideoAgent's constraints: it sees ONLY its own video and its instruction;
each observe is capped at 512 frames.

Judge in this order:

1. Coverage (video_observe): did where/fps cover what the instruction asked,
   relative to the FULL video duration and the granularity of the requested
   event? Compare where ranges against the duration (a where range equal to
   the duration is full coverage; a small prefix is partial). Consider fps
   against event brevity (a ~1s event at 2 fps is easily missed).
   Subtypes: search_failure (wrong region), sampling_failure (too sparse for
   the event), coverage_failure (required full-video coverage missing).

2. Fidelity (video_summary): was the needed fact present in a raw observation
   but lost or distorted in the returned summary, or did the agent finish
   before completing its task?
   Subtypes: compression_failure, distortion_failure, stopping_failure.

3. Perception (perception): is the raw observation itself wrong — decisively
   contradicts the GT, is internally inconsistent, or is implausible? Only
   conclude perception when coverage was adequate: a wrong observation under
   full adequate coverage is perception; under sparse coverage it is usually
   sampling. Counting errors (one object reported as two) under full coverage
   are perception.

4. If the agent observed appropriately and summarized faithfully given its
   instruction, verdict is "clean" — it is not at fault.

Rules:
- Ground every failure point in a concrete quote.
- Mark confidence "high" only when the evidence is decisive.
- Never propose skill edits.
- The ground-truth answer is for judging only.

Respond ONLY with a valid JSON object (no markdown fences, no extra text):
{
  "video_id": "<id>",
  "verdict": "at_fault | clean",
  "video_failure_points": [
    {
      "id": "fp1",
      "loc": "video_observe | video_summary | perception",
      "subtype": "<subtype>",
      "evidence": "<concrete quoted evidence>",
      "confidence": "high | low"
    }
  ],
  "attribution_summary": "<2-4 sentences>"
}"""


# ---------------------------------------------------------------- LLM call

def call_llm(system: str, user: str, tag: str, max_retries: int = 3) -> tuple[dict, dict]:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 8192,
        "thinking": {"type": "disabled"},
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=600)
            resp.raise_for_status()
            j = resp.json()
            content = j["choices"][0]["message"]["content"]
            out = parse_json_loose(content)
            if not isinstance(out, dict):
                raise ValueError(f"parsed output is not a dict: {str(out)[:200]}")
            return out, j.get("usage", {})
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  [{tag}] attempt {attempt} failed: {e}", flush=True)
            time.sleep(5 * attempt)
    raise RuntimeError(f"LLM call failed after {max_retries} retries: {last_err}")


# ---------------------------------------------------------------- rendering

def render_global_view(d: dict) -> str:
    """Everything the GlobalAgent saw, in round order (no video internals)."""
    r = d["result"]
    videos = r["input"]["videos"]
    lines: list[str] = []
    lines.append(f"VIDEOS ({len(videos)}):")
    for vid, path in videos.items():
        dur = probe_duration(path)
        dur_s = f"{dur:.1f}s" if dur is not None else "unknown duration"
        lines.append(f"  {vid}: {dur_s}")
    lines.append("")
    lines.append(f"QUESTION:\n{r['input']['question']}")
    lines.append("")
    lines.append("===== GLOBAL-LEVEL TRAJECTORY =====")
    lines.append("")

    watches = list(r.get("watch_results", []))
    used_watches: set[int] = set()

    def attach_watch(instruction: str | None) -> None:
        if not instruction:
            return
        for i, w in enumerate(watches):
            if i in used_watches:
                continue
            if w.get("instruction") == instruction:
                used_watches.add(i)
                lines.append("  Watch observations received:")
                for v in w.get("videos", []):
                    tr = v.get("time_range", [None, None])
                    lines.append(
                        f"    Clip {v.get('video_id')}: [{tr[0]}, {tr[1]}]"
                        f" -> \"{v.get('text', '')}\""
                    )
                lines.append("")
                return

    for t in r["trajectory"]:
        agent, action = t["agent"], t["action"]
        if agent == "GlobalAgent" and action == "decide":
            o = t.get("output", {})
            act = o.get("action")
            lines.append(f"[Global Round {t.get('round')}] decide")
            if o.get("reason"):
                lines.append(f"  Reason: {o['reason']}")
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
            if act == "watch_videos":
                attach_watch(params.get("instruction"))
        elif agent == "VideoAgent" and action == "run":
            o = t.get("output", {})
            steps = o.get("steps", [])
            summary = next(
                (s["parameters"].get("summary") for s in steps if s["action"] == "finish"),
                None,
            )
            if summary is not None:
                lines.append(f"    Summary <- {t.get('video_id')}: \"{summary}\"")
                lines.append("")
    # any unmatched watch results (defensive)
    for i, w in enumerate(watches):
        if i not in used_watches:
            lines.append("[watch_videos result]")
            lines.append(f"  Instruction: \"{w.get('instruction')}\"  fps: {w.get('fps')}")
            for v in w.get("videos", []):
                tr = v.get("time_range", [None, None])
                lines.append(f"  Clip {v.get('video_id')}: [{tr[0]}, {tr[1]}] -> \"{v.get('text', '')}\"")
            lines.append("")

    ans = r.get("answer") or {}
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


def render_video_view(d: dict, video_id: str, missing: str) -> str:
    """One video agent's internals for Stage 2."""
    r = d["result"]
    videos = r["input"]["videos"]
    dur = probe_duration(videos[video_id]) if video_id in videos else None
    lines: list[str] = []
    lines.append(f"VIDEO: {video_id}  (duration {dur:.1f}s)" if dur else f"VIDEO: {video_id}")
    lines.append(f"GROUND TRUTH: {d.get('ground_truth')}")
    lines.append(f"WHAT THE GLOBALAGENT NEEDED (Stage 1 finding): {missing}")
    lines.append("")
    for t in r["trajectory"]:
        if t.get("agent") != "VideoAgent" or t.get("video_id") != video_id:
            continue
        inp = t.get("input", {})
        lines.append(f"[Round] Instruction received: \"{inp.get('instruction')}\"")
        o = t.get("output", {})
        for s in o.get("steps", []):
            if s["action"] == "observe":
                p = s["parameters"]
                where, span = _where_summary(p.get("where", []))
                fps = p.get("fps")
                est = round(span * fps) if fps else None
                lines.append(f"  Step {s['step']}: observe")
                lines.append(f"    what: \"{p.get('what')}\"")
                lines.append(
                    f"    where: {where}   fps: {fps}"
                    f"   (~{est} frames; capped at {OBSERVE_FRAME_CAP})"
                )
                res = s.get("result", {})
                if res.get("status") != "ok":
                    lines.append(f"    OBSERVE FAILED: {res}")
                for ob in res.get("observations", []):
                    lines.append(f"    Raw observation: \"{ob.get('text')}\"")
                    if ob.get("uncertainty"):
                        lines.append(f"    Uncertainty: \"{ob['uncertainty']}\"")
            elif s["action"] == "finish":
                lines.append(f"  Step {s['step']}: finish")
                lines.append(f"    Summary returned to Global: \"{s['parameters'].get('summary')}\"")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- merge

def merge(stage1: dict, stage2_results: list[dict], sample_id: str) -> dict:
    points: list[dict] = []
    for p in stage1.get("global_failure_points", []):
        q = dict(p)
        q.setdefault("video_id", None)
        q.setdefault("round", None)
        points.append(q)
    for s2 in stage2_results:
        for p in s2.get("video_failure_points", []):
            q = dict(p)
            q["video_id"] = s2.get("video_id")
            q.setdefault("round", None)
            points.append(q)
    drill = stage1.get("drill_down", [])
    notes: list[str] = []
    if (
        drill
        and not stage1.get("global_failure_points")
        and stage2_results
        and all(s2.get("verdict") == "clean" for s2 in stage2_results)
    ):
        vids = ", ".join(dd.get("video_id", "?") for dd in drill)
        points.append(
            {
                "id": "fp-if",
                "loc": "interface",
                "subtype": "contract_mismatch",
                "video_id": vids,
                "round": None,
                "evidence": (
                    "Global used its summaries correctly, instructions were "
                    "sound, every drilled video agent executed faithfully, yet "
                    "the facts needed for the GT never reached the GlobalAgent "
                    f"(missing: {'; '.join(dd.get('missing', '') for dd in drill)})."
                ),
                "confidence": "low",
            }
        )
        notes.append("interface residual applied")
    summary_parts = [stage1.get("attribution_summary", "")]
    for s2 in stage2_results:
        if s2.get("attribution_summary"):
            summary_parts.append(f"[{s2.get('video_id')}] {s2['attribution_summary']}")
    if notes:
        summary_parts.append("(" + "; ".join(notes) + ")")
    return {
        "sample_id": sample_id,
        "failure_points": points,
        "attribution_summary": " ".join(p for p in summary_parts if p).strip(),
        "stage1": {
            "summaries_sufficient_for_gt": stage1.get("summaries_sufficient_for_gt"),
            "drill_down": drill,
        },
        "stage2_verdicts": [
            {"video_id": s.get("video_id"), "verdict": s.get("verdict")}
            for s in stage2_results
        ],
    }


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/attribution_probe/deepseek_v4_flash_20260903_v2cascade")
    args = ap.parse_args()

    out_dir = Path(args.out)
    (out_dir / "trajectories_stage1").mkdir(parents=True, exist_ok=True)
    (out_dir / "trajectories_stage2").mkdir(parents=True, exist_ok=True)
    (out_dir / "stage1").mkdir(parents=True, exist_ok=True)
    (out_dir / "stage2").mkdir(parents=True, exist_ok=True)
    (out_dir / "attributions").mkdir(parents=True, exist_ok=True)

    samples = select_samples()
    print(f"selected {len(samples)} failed samples", flush=True)

    final_all = []
    for d in samples:
        sid = d["sample_id"].replace(":", "_").replace("/", "_")
        final_path = out_dir / "attributions" / f"{sid}.json"
        if final_path.exists():
            print(f"[{d['sample_id']}] already done, skip", flush=True)
            final_all.append(json.loads(final_path.read_text(encoding="utf-8")))
            continue

        # ---- Stage 1
        s1_text = render_global_view(d)
        (out_dir / "trajectories_stage1" / f"{sid}.txt").write_text(s1_text, encoding="utf-8")
        s1_path = out_dir / "stage1" / f"{sid}.json"
        if s1_path.exists():
            stage1 = json.loads(s1_path.read_text(encoding="utf-8"))
            print(f"[{d['sample_id']}] stage1 cached", flush=True)
        else:
            print(f"[{d['sample_id']}] stage1 ...", flush=True)
            stage1, usage1 = call_llm(STAGE1_PROMPT, s1_text, f"{d['sample_id']}/s1")
            stage1["usage"] = usage1
            s1_path.write_text(json.dumps(stage1, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # ---- Stage 2 per drill-down video
        stage2_results: list[dict] = []
        known_videos = set(d["result"]["input"]["videos"].keys())
        analyzed = {
            t.get("video_id")
            for t in d["result"]["trajectory"]
            if t.get("agent") == "VideoAgent"
        }
        for dd in stage1.get("drill_down", []):
            vid = dd.get("video_id")
            if vid not in known_videos or vid not in analyzed:
                print(f"[{d['sample_id']}] drill {vid}: not analyzed by any VideoAgent, skip", flush=True)
                continue
            s2_text = render_video_view(d, vid, dd.get("missing", ""))
            safe_vid = vid.replace(":", "_").replace("/", "_")
            (out_dir / "trajectories_stage2" / f"{sid}__{safe_vid}.txt").write_text(s2_text, encoding="utf-8")
            s2_path = out_dir / "stage2" / f"{sid}__{safe_vid}.json"
            if s2_path.exists():
                s2 = json.loads(s2_path.read_text(encoding="utf-8"))
                print(f"[{d['sample_id']}] stage2 {vid} cached", flush=True)
            else:
                print(f"[{d['sample_id']}] stage2 {vid} ...", flush=True)
                s2, usage2 = call_llm(STAGE2_PROMPT, s2_text, f"{d['sample_id']}/s2/{vid}")
                s2["usage"] = usage2
                s2.setdefault("video_id", vid)
                s2_path.write_text(json.dumps(s2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            stage2_results.append(s2)

        final = merge(stage1, stage2_results, d["sample_id"])
        final_path.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fps = "; ".join(
            f"{p.get('loc')}/{p.get('subtype')}({p.get('confidence')})" for p in final["failure_points"]
        )
        print(f"[{d['sample_id']}] done: {fps}", flush=True)
        final_all.append(final)

    (out_dir / "summary.json").write_text(
        json.dumps(final_all, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {out_dir / 'summary.json'} ({len(final_all)} samples)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
