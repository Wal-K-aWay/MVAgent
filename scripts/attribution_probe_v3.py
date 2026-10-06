#!/usr/bin/env python3
"""Two-stage cascade attribution probe (v3) = v2 + two fixes.

Fix 1 (Stage-1 decision-time evidence gating): "should have kept verifying"
verdicts (premature_answer / late_answer / wrong_clip) must cite a suspicion
signal that was visible to the GlobalAgent AT DECISION TIME (uncertainty
qualifier, contradicting summaries, empty watch text, admitted non-finding,
question scope broader than what was analyzed). Confident-but-wrong summaries
must NOT be blamed on the GlobalAgent — that failure lies upstream, so the
judge must drill down instead of inventing decision errors.

Fix 2 (merge ordered by evidence sufficiency): when Stage 1 says the
summaries were insufficient for the GT and Stage 2 finds a drilled video at
fault, video-side points become the root cause and Global points are demoted
to secondary; when Stage 1 says the summaries were sufficient (with quoted
facts), Global points lead. The interface residual (insufficient + all
drilled videos clean) is emitted as the ROOT point instead of being appended.

Stage-2 prompt and both view renderers are reused unchanged from v2 (their
quality was validated in the v2 run). Run with an interpreter that has cv2,
e.g. /home/kww/miniconda3/envs/MVAgent/bin/python attribution_probe_v3.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from attribution_probe import select_samples
from attribution_probe_v2 import (
    STAGE2_PROMPT,
    call_llm,
    render_global_view,
    render_video_view,
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
   returned summaries and watch texts ALONE?
   - If YES: quote the exact facts that entail the GT. Only then may you
     judge synthesis-level decision errors (step 2).
   - If NO: the failure lies upstream of the GlobalAgent's final decision.
     Set summaries_sufficient_for_gt=false and list suspect videos in
     drill_down (step 5). Do NOT compensate by inventing decision errors.

2. Decision errors (global_decision) — allowed ONLY if the derivability
   check passed, or a decision-time suspicion signal was ignored:
   - synthesis_error / wrong option mapping / wrong arithmetic: you MUST
     quote the summary facts that entail the GT and show how the GlobalAgent
     misused them.
   - premature_answer / late_answer / wrong_clip ("should have kept
     verifying"): you MUST cite a suspicion signal that was visible to the
     GlobalAgent AT DECISION TIME: an uncertainty qualifier in a summary,
     two summaries in direct contradiction, an empty watch text, a summary
     that admits the fact was not found, or a question scope clearly broader
     than what was analyzed. Knowing only now that the answer turned out
     wrong is NOT evidence: if the summaries were confident, consistent, and
     complete-looking, trusting them was reasonable and the failure lies
     upstream — drill down instead of blaming the GlobalAgent.
   - wrong_video_selection: only when the question, read at face value,
     required analyzing videos the GlobalAgent never touched.
   Subtypes: premature_answer, wrong_video_selection, wrong_clip, late_answer,
   synthesis_error.

3. Instruction errors (global_instruction), judged on the instruction text
   alone against the question: vague, missing needed context, aimed at the
   wrong goal/facet, or leaking the expected answer into the search target.
   Subtypes: vague, missing_context, wrong_goal.

4. Watch-text anomalies: empty, self-contradictory, or implausible watch
   observations may indicate perception problems (loc=perception, low
   confidence unless decisive). Note: the GlobalAgent treating an empty
   watch text as confirmation is a global_decision error — an empty watch
   text IS a decision-time suspicion signal.

5. If facts needed for the GT are absent from the summaries, list the
   suspect videos in drill_down with what exactly was missing. This triggers
   a per-video forensic inspection in Stage 2. Do NOT guess whether the
   video agent or its observation was at fault — that is Stage 2's job.

Rules:
- Ground every failure point in a concrete quote from the episode.
- 0-3 failure points, ordered by causal importance (first = root cause).
  ZERO points is a valid outcome: when everything the GlobalAgent did was
  reasonable given what it saw, return an empty list and let drill_down
  carry the case.
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


# ---------------------------------------------------------------- merge (fix 2)

def merge(stage1: dict, stage2_results: list[dict], sample_id: str) -> dict:
    s1_points: list[dict] = []
    for p in stage1.get("global_failure_points", []):
        q = dict(p)
        q.setdefault("video_id", None)
        q.setdefault("round", None)
        s1_points.append(q)
    video_points: list[dict] = []
    for s2 in stage2_results:
        for p in s2.get("video_failure_points", []):
            q = dict(p)
            q["video_id"] = s2.get("video_id")
            q.setdefault("round", None)
            video_points.append(q)

    suff = stage1.get("summaries_sufficient_for_gt")
    drill = stage1.get("drill_down", [])
    notes: list[str] = []

    points: list[dict]
    if suff is False and video_points:
        # Upstream failure: video-side points are the root cause; the
        # GlobalAgent could not have known better (no derivable GT).
        points = video_points + s1_points
        notes.append("root=video-side (summaries insufficient, stage2 at fault)")
    else:
        points = s1_points + video_points

    if (
        drill
        and suff is False
        and stage2_results
        and all(s.get("verdict") == "clean" for s in stage2_results)
    ):
        vids = ", ".join(dd.get("video_id", "?") for dd in drill)
        missing = "; ".join(dd.get("missing", "") for dd in drill)
        points.insert(
            0,
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
                    f"(missing: {missing})."
                ),
                "confidence": "low",
            },
        )
        notes.append("interface residual applied as root")

    for i, p in enumerate(points):
        p["id"] = f"fp{i + 1}"

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
            "summaries_sufficient_for_gt": suff,
            "drill_down": drill,
        },
        "stage2_verdicts": [
            {"video_id": s.get("video_id"), "verdict": s.get("verdict")}
            for s in stage2_results
        ],
        "merge_notes": notes,
    }


# ---------------------------------------------------------------- main

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    default_out = repo_root / "outputs" / "attribution_probe" / "deepseek_v4_flash_20260903_v3cascade"
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(default_out))
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
