#!/usr/bin/env python3
"""Export a finished agent-eval run into compact, analysis-ready tables (standard library only).

Reads <run>/records/*/*/result.json and <run>/summary.json; never changes them. Writes <run>/tables/:
  answers.jsonl      one row per question: identity, prediction, reference, score, outcome, answer validity,
                     evidence actions, stop status, time, token usage and the Global skill selection
  cases.jsonl.gz     public trajectories in the exporter case format: question without
                     the generic benchmark wrapper, options, video durations, evidence steps with instructions
                     and VideoAgent summaries, final and correct answer, outcome
  scores.json        official score per benchmark (from summary.json) and per-task counts, mean score,
                     pass/partial/fail and answer-validity rates
Usage: python eval/agent_eval/export_results.py RUN_DIR
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

# Outcome thresholds mirror eval.benchmarks.scoring.OUTCOME_THRESHOLDS (pass_at, fail_below).
# Records name the FSA family "temporal"; SampleTask names it "temporal_localization".
THRESHOLDS = {"temporal_localization": (0.5, 0.1), "temporal": (0.5, 0.1), "open_qa": (2 / 3, 1 / 3)}
INTERVAL = r"\d+(\.\d+)?\s*,\s*\d+(\.\d+)?"
VALID = {"ordering": r"\d+(\s*->\s*\d+)+", "temporal_localization": INTERVAL, "temporal": INTERVAL,
         "open_qa": r"[\s\S]*\S[\s\S]*", "choice": r"[A-H]{1,4}\.?|yes\.?|no\.?"}


def outcome(family: str, score: float | None) -> str | None:
    if score is None:
        return None
    pass_at, fail_below = THRESHOLDS.get(family, (1.0, 1.0))
    return "pass" if score >= pass_at - 1e-9 else "fail" if score < fail_below - 1e-9 else "partial"


def question_text(raw: str) -> str:
    """Drop the generic benchmark wrapper; keep its first line, which states the answer form."""
    text = raw.replace("\n\nYour answer:", "").strip()
    if "Question:\n" in text:
        head, core = text.split("Question:\n", 1)
        first = head.strip().splitlines()[0] if head.strip() else ""
        return (first + " " + core.split("\n\nOptions:")[0]).strip()
    return " ".join(line for line in text.splitlines() if not line.startswith("Watch the"))


def options_of(raw: str) -> list[str]:
    if "\n\nOptions:\n" not in raw:
        return []
    block = raw.split("\n\nOptions:\n", 1)[1].split("\n\nYour answer:")[0]
    return [line.strip() for line in block.splitlines() if line.strip()]


def steps(result: dict) -> list[dict]:
    out = []
    for action in result.get("action_history") or []:
        if action.get("action") == "analyze_videos":
            requests = []
            for o in action.get("outcomes") or []:
                report = str(o.get("report") or "")
                report = report.rsplit("Summary:", 1)[-1].strip() if o.get("status") == "ok" else f"(request failed: {o.get('status')})"
                requests.append({"video_id": o["video_id"], "instruction": o.get("instruction", ""), "report": report})
            if requests:
                out.append({"action": "analyze_videos", "requests": requests})
        elif action.get("action") == "watch_videos" and action.get("status") == "ok":
            res = action.get("results") or {}
            out.append({"action": "watch_videos", "instruction": res.get("instruction", ""),
                        "clips": [{"video_id": v["video_id"], "start": v["time_range"][0], "end": v["time_range"][1]}
                                  for v in res.get("videos", [])],
                        "result": res.get("text", "")})
    return out


def usage(events: list[dict]) -> tuple[int, int]:
    tin = tout = 0
    for e in events:
        if e.get("kind") == "model_response" and isinstance(e.get("usage"), dict):
            tin += int(e["usage"].get("prompt_tokens") or 0)
            tout += int(e["usage"].get("completion_tokens") or 0)
    return tin, tout


def global_selection(events: list[dict]):
    for e in events:
        if e.get("kind") == "skill_selection" and e.get("role") == "global":
            return [s["id"] for s in e.get("selected", [])]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    args = ap.parse_args()
    run = args.run_dir
    out = run / "tables"
    out.mkdir(exist_ok=True)

    per_task = defaultdict(lambda: dict(n=0, scored=0, score_sum=0.0, valid=0, outcomes=defaultdict(int)))
    with (out / "answers.jsonl").open("w") as answers, gzip.open(out / "cases.jsonl.gz", "wt") as cases:
        for path in sorted(run.glob("records/*/*/result.json")):
            r = json.loads(path.read_text())
            res, family = r.get("result") or {}, r.get("task_family") or "choice"
            raw_q = (res.get("input") or {}).get("question", "")
            score = r.get("score") if r.get("score") is not None else (
                None if r.get("correct") is None else float(bool(r["correct"])))
            pred = str(r.get("prediction") or "").strip()
            valid = bool(re.fullmatch(VALID.get(family, VALID["choice"]), pred, re.I))
            acts = [a.get("action") for a in res.get("action_history") or []]
            answer = res.get("answer") if isinstance(res.get("answer"), dict) else {}
            tin, tout = usage(r.get("events") or [])
            gt = r.get("ground_truth")
            row = dict(sample_id=r["sample_id"], dataset=r["dataset"], task=r.get("native_task"), family=family,
                       status=r.get("status"), error=r.get("error") or "", prediction=pred, ground_truth=gt,
                       score=score, correct=r.get("correct"), outcome=outcome(family, score), answer_valid=valid,
                       evidence_actions=acts, n_evidence_actions=len(acts), first_action=acts[0] if acts else None,
                       stop=answer.get("status"), time_sec=res.get("time"), prompt_tokens=tin, completion_tokens=tout,
                       global_skill=global_selection(r.get("events") or []))
            answers.write(json.dumps(row, ensure_ascii=False) + "\n")
            meta = res.get("video_metadata") or {}
            case = dict(sample_id=r["sample_id"], dataset=r["dataset"], task=r.get("native_task"),
                        question=question_text(raw_q), options=options_of(raw_q),
                        durations=[m.get("duration_sec") for m in meta.values()], steps=steps(res),
                        final_answer=pred, correct_answer=",".join(map(str, gt)) if isinstance(gt, list) else str(gt or r.get("reference_answer") or ""),
                        outcome=row["outcome"], score=score, valid_answer=valid)
            cases.write(json.dumps(case, ensure_ascii=False) + "\n")
            t = per_task[(r["dataset"], r.get("native_task"))]
            t["n"] += 1; t["valid"] += valid
            if score is not None:
                t["scored"] += 1; t["score_sum"] += score; t["outcomes"][row["outcome"]] += 1

    summary = json.loads((run / "summary.json").read_text()) if (run / "summary.json").exists() else {}
    scores = {}
    for ds, block in (summary.get("datasets") or {}).items():
        scores[ds] = dict(official_score=block.get("official_score"), official_policy=block.get("official_policy"),
                          completed=block.get("completed"), errors=block.get("errors"), tasks={})
    for (ds, task), t in sorted(per_task.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        scores.setdefault(ds, dict(tasks={}))["tasks"][str(task)] = dict(
            n=t["n"], scored=t["scored"], mean_score=round(t["score_sum"] / t["scored"], 4) if t["scored"] else None,
            outcomes=dict(t["outcomes"]), answer_valid_rate=round(t["valid"] / t["n"], 4))
    (out / "scores.json").write_text(json.dumps(scores, indent=1, ensure_ascii=False) + "\n")
    print(f"{sum(t['n'] for t in per_task.values())} questions -> {out}")
    for ds, block in scores.items():
        print(ds, "official", block.get("official_score"), {k: v["mean_score"] for k, v in block["tasks"].items()})


if __name__ == "__main__":
    main()
