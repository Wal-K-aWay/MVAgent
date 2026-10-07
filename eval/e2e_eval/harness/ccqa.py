"""CrossVid CCQA judge: the official `score_CCQA.py` prompt, `<score>` JSON and aggregation.

The judge client is shared with MVAgent's CCQA scoring (`eval/agent_eval/score_crossvid_ccqa.py`:
fixed DeepSeek model, official system prompt and sampling, strict validation, response cache), so
E2E and MVAgent CCQA numbers come from the same judge. Failed judgements are reported as errors,
never as zero scores. Official aggregation: sum(covered + correct) / sum(2 * scoring points).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .common import CROSSVID_SOURCE, PROJECT_ROOT, load_official_module, official_constant

AGENT_JUDGE = PROJECT_ROOT / "eval/agent_eval/score_crossvid_ccqa.py"


def judge_outputs(
    pending: list[tuple[dict[str, Any], str]],
    *,
    cache_dir: Path,
    model: str,
    api_base: str,
    workers: int,
    attempts: int,
    timeout: float,
) -> dict[str, dict[str, Any]]:
    """Judge (item, raw model output) pairs; returns sample_id -> score row (status ok|error)."""
    judge_module = load_official_module(AGENT_JUDGE, "agent_eval_ccqa_judge", import_root=AGENT_JUDGE.parent)
    official_prompt = official_constant(CROSSVID_SOURCE / "eval/score_CCQA.py", "SCORE")
    if judge_module.SCORE_PROMPT != official_prompt:
        raise RuntimeError("MVAgent CCQA judge prompt differs from CrossVid score_CCQA.py SCORE")
    judge = judge_module.DeepSeekJudge(api_base, model, timeout)

    def work(pair: tuple[dict[str, Any], str]) -> dict[str, Any]:
        item, output = pair
        row = item["row"]
        request = {
            "id": item["sample_id"],
            "point_count": len(row["scoring_points"]),
            "prediction": output,
            "prompt": official_prompt.format(
                QUESTION=row["question"], ANSWER=row["answer"], POINTS=row["scoring_points"], OUTPUT=output
            ),
        }
        judged = judge_module._score_one(judge, cache_dir, request, attempts)
        if judged["status"] != "ok":
            return {"sample_id": item["sample_id"], "status": "error", "error": judged["error"]}
        points = len(judged["coverage"])
        return {
            "sample_id": item["sample_id"],
            "status": "ok",
            "prediction": output,
            "answer": row["answer"],
            "coverage": judged["coverage"],
            "correctness": judged["correctness"],
            "points": points,
            "score": judged["score"] / (2 * points),
            "judge_model": judged.get("response_model"),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return {row["sample_id"]: row for row in pool.map(work, pending)}
