#!/usr/bin/env python3
"""K1 probe input: Train cases from the historical 35B no-Skill CrossVid baseline (standard library only).

Samples a Train set T from src/skill_evolution/crossvid_clean_pool.json (equal per task, MOC/MSR by whole UAV
sequence), converts the exported baseline trajectories into scope/views.py cases, and draws K1
pattern-finder samples (failures + successes, at most one per video source). Task labels are used
only for sampling and are kept out of rendered text.
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_crossvid_clean_pool import TASKS, sources  # noqa: E402

PASS_FAIL = {"FSA": (0.5, 0.1), "CCQA": (2 / 3, 1 / 3)}
VALID = {"PSS": r"\d+(->\d+)+", "FSA": r"\d+(\.\d+)?\s*,\s*\d+(\.\d+)?", "CCQA": r"[\s\S]+"}


def question_text(raw: str) -> str:
    text = raw.replace("\n\nYour answer:", "").strip()
    if "Question:\n" in text:
        head, core = text.split("Question:\n", 1)
        first = head.strip().splitlines()[0] if head.strip() else ""
        return (first + " " + core.split("\n\nOptions:")[0]).strip()
    return " ".join(line for line in text.splitlines() if not line.startswith("Watch the"))


def durations(task: str, row: dict) -> list[float] | None:
    if task in ("MOC", "MSR"):
        return None
    if task == "PSS":
        return [sum(e - s for s, e in spans) for _, spans in sorted(row["segments"].items(), key=lambda kv: int(kv[0]))]
    if task == "PI":
        return [row["beginning"][1] - row["beginning"][0], row["ending"][1] - row["ending"][0]]
    if task == "PEA":
        return [e - b for b, e in zip(row["begin"], row["end"])]
    d = row.get("duration")
    return list(d) if isinstance(d, list) else [d]


def outcome(task: str, score: float) -> str:
    pass_at, fail_below = PASS_FAIL.get(task, (1.0, 1.0))
    return "pass" if score >= pass_at - 1e-9 else "fail" if score < fail_below - 1e-9 else "partial"


def steps(record: dict) -> list[dict]:
    out = []
    for action in record.get("action_history") or []:
        if action.get("action") == "analyze_videos":
            requests = []
            for o in action.get("outcomes") or []:
                report = str(o.get("report") or "")
                report = report.rsplit("Summary:", 1)[-1].strip() if o.get("status") == "ok" else f"(request failed: {o.get('status')})"
                requests.append({"video_id": o["video_id"], "instruction": o.get("instruction", ""), "report": report})
            if requests:
                out.append({"action": "analyze_videos", "requests": requests})
        elif action.get("action") == "watch_videos":
            res = action.get("results") or {}
            if action.get("status") != "ok" or not isinstance(res, dict):
                continue
            out.append({"action": "watch_videos", "instruction": res.get("instruction", ""),
                        "clips": [{"video_id": v["video_id"], "start": v["time_range"][0], "end": v["time_range"][1]}
                                  for v in res.get("videos", [])],
                        "result": res.get("text", "")})
    return out


def sample_train(clean: list[str], raw: dict, per_task: int, rng: random.Random) -> list[str]:
    by_task = defaultdict(list)
    for sid in clean:
        by_task[sid.split(":")[1]].append(sid)
    train = []
    for task in TASKS:
        ids = sorted(by_task[task])
        rng.shuffle(ids)
        if task in ("MOC", "MSR"):
            by_seq = defaultdict(list)
            for sid in ids:
                by_seq[raw[sid]["vid"]].append(sid)
            chosen = []
            for vid in sorted(by_seq, key=lambda v: rng.random()):
                if len(chosen) >= per_task:
                    break
                chosen += by_seq[vid]
            train += chosen[:per_task]
        else:
            train += ids[:per_task]
    return train


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path, required=True, help="/runs/lightsail_outputs/mvagent/no_skill/qwen3_5_35b_a3b (runs Volume, read inside Modal)")
    ap.add_argument("--qa-jsonl", type=Path, required=True, help="prepared CrossVid qa.jsonl (Runtime question text)")
    ap.add_argument("--raw-qa", type=Path, required=True, help="official CrossVid QA/ directory")
    ap.add_argument("--clean-pool", type=Path, default=Path("src/skill_evolution/crossvid_clean_pool.json"))
    ap.add_argument("--per-task", type=int, default=65)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--failures", type=int, default=40)
    ap.add_argument("--successes", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    raw = {}
    for task in TASKS:
        for row in json.loads((args.raw_qa / f"{task}.json").read_text()):
            raw[f"crossvid:{task}:{row['id']}"] = row
    qa = {r["id"]: r for r in map(json.loads, args.qa_jsonl.read_text().splitlines()) if r.get("id")}
    rng = random.Random(args.seed)
    train = set(sample_train(json.loads(args.clean_pool.read_text()), raw, args.per_task, rng))

    answers = {}
    with gzip.open(args.baseline / "answers.jsonl.gz", "rt") as f:
        for line in f:
            r = json.loads(line)
            if r["sample_id"] in train:
                answers[r["sample_id"]] = r
    ccqa = json.loads((args.baseline / "score_ccqa_scores_official_deepseek_v4_flash.json").read_text())
    ccqa = {f"crossvid:CCQA:{s['id']}": s["score"] / (2 * len(s["coverage"])) for s in ccqa["samples"] if s.get("coverage")}

    cases = []
    with gzip.open(args.baseline / "trajectories.jsonl.gz", "rt") as f:
        for line in f:
            r = json.loads(line)
            sid = r["sample_id"]
            if sid not in train:
                continue
            task, a, q = sid.split(":")[1], answers[sid], qa[sid]
            score = ccqa.get(sid) if task == "CCQA" else a.get("score")
            if score is None:
                score = float(bool(a.get("correct")))
            pred = str(a.get("prediction") or "").strip()
            valid = bool(re.fullmatch(VALID.get(task, r"[A-H]{1,4}"), pred))
            gt = q.get("answer")
            cases.append({
                "sid": sid, "task": task, "sources": sorted(sources(task, raw[sid])),
                "question": question_text(q["question"]), "options": q.get("options") or [],
                "durations": durations(task, raw[sid]), "steps": steps(r),
                "final_answer": pred, "correct_answer": ",".join(map(str, gt)) if isinstance(gt, list) else str(gt),
                "outcome": outcome(task, float(score)), "score": float(score), "valid_answer": valid,
            })
    cases.sort(key=lambda c: c["sid"])
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "t_cases.jsonl").open("w") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    for k in range(1, args.samples + 1):
        pick = random.Random(args.seed + k)
        order = cases[:]
        pick.shuffle(order)
        used, fails, wins = set(), [], []
        for c in order:
            if used & set(c["sources"]):
                continue
            if c["outcome"] != "pass" and c["valid_answer"] and len(fails) < args.failures:
                fails.append(c["sid"]); used |= set(c["sources"])
            elif c["outcome"] == "pass" and len(wins) < args.successes:
                wins.append(c["sid"]); used |= set(c["sources"])
        chosen = fails + wins
        pick.shuffle(chosen)
        labels = {f"case_{i}": sid for i, sid in enumerate(chosen, 1)}
        (args.out / f"k1_sample_{k}.json").write_text(json.dumps(labels, indent=1) + "\n")

    count = lambda pred: sum(1 for c in cases if pred(c))
    print(f"T={len(cases)} pass={count(lambda c: c['outcome'] == 'pass')} partial={count(lambda c: c['outcome'] == 'partial')} "
          f"fail={count(lambda c: c['outcome'] == 'fail')} invalid_answer={count(lambda c: not c['valid_answer'])}")
    print("per task:", {t: count(lambda c, t=t: c["task"] == t) for t in TASKS})


if __name__ == "__main__":
    main()
