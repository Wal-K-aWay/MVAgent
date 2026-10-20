#!/usr/bin/env python3
"""Score CrossVid CCQA predictions with the fixed local judge and the official protocol.

Implements the pinned CrossVid official CCQA prompt, system message,
generation settings and ``<score>`` parsing, with strict response validation.
The judge is Qwen3-30B-A3B-Instruct-2507 served by vLLM (one replica per GPU, started
with ``--generation-config vllm``); one request in flight per replica keeps every batch
identical, so greedy judgements are reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SCORE_PROMPT = """
You are asked to score the output of a model, given the following information:
- Question: {QUESTION}
- Standard Answer: {ANSWER}
- Scoring Points: {POINTS}
- Model's Output: {OUTPUT}

Please perform the following two-part scoring:
Part 1: Coverage of Scoring Points
- For each scoring point, determine whether it is covered by the Model's Output.
- Mark as covered (true) **only if** the scoring point is addressed **explicitly, independently, and clearly**.
- If the mention is vague, partial, or ambiguous, consider it **not covered**.

Part 2: Accuracy of Details
- For each covered scoring point, compare the details in the Model's Output to the Standard Answer.
- Mark as correct (true) **only if** the details are **fully accurate and consistent** with the Standard Answer, without any error, omission, or ambiguity.
- If the answer is partially correct, too broad/narrow, or not strictly consistent, mark it as **not correct** (false).
- For scoring points not covered, mark as incorrect.

Format your answer in a json format as follows:
{{
    "coverage": [true, false, true, ...],
    "correctness": [true, false, false, ...]
}}
The length of 'coverage' and 'correctness' lists should match the number of scoring points.
Wrap the json output within <score></score> tags.

Your answer:
"""

SYSTEM_PROMPT = "You are a helpful assistant."
GENERATION = {"max_tokens": 8192, "temperature": 0.0, "top_p": 0.95}
JUDGE_MODEL = "Qwen3-30B-A3B-Instruct-2507"
REPORT_NAME = "ccqa_scores_official_qwen3_30b_a3b.json"
EXTRACT_PATTERN = re.compile(r"<score>\s*(.*?)\s*</score>", re.DOTALL)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _extract(string: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", string, re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_endpoints(value: str) -> list[str]:
    """Comma-separated URLs, ports or port ranges (8100-8107) on 127.0.0.1."""
    endpoints = []
    for token in filter(None, (part.strip() for part in value.split(","))):
        if token.startswith("http"):
            endpoints.append(token.rstrip("/"))
        elif "-" in token:
            first, last = map(int, token.split("-"))
            endpoints += [f"http://127.0.0.1:{port}/v1" for port in range(first, last + 1)]
        else:
            endpoints.append(f"http://127.0.0.1:{int(token)}/v1")
    return endpoints


class LocalJudge:
    """vLLM endpoints serving JUDGE_MODEL, each used by one request at a time."""

    def __init__(self, endpoints: list[str], timeout_sec: float) -> None:
        import httpx
        from openai import OpenAI

        if not endpoints:
            raise ValueError("no judge endpoints")
        self._model = JUDGE_MODEL
        self._clients: queue.Queue = queue.Queue()
        weights = set()
        for endpoint in endpoints:
            response = httpx.get(f"{endpoint}/models", timeout=15, trust_env=False)
            response.raise_for_status()
            cards = {card["id"]: card for card in response.json()["data"]}
            if JUDGE_MODEL not in cards:
                raise RuntimeError(f"{endpoint} does not serve {JUDGE_MODEL}: {sorted(cards)}")
            weights.add(cards[JUDGE_MODEL].get("root"))
            self._clients.put(OpenAI(
                api_key="unused",
                base_url=endpoint,
                timeout=timeout_sec,
                max_retries=2,
                http_client=httpx.Client(trust_env=False, timeout=timeout_sec),
            ))
        if len(weights) != 1:
            raise RuntimeError(f"judge endpoints serve different weights: {sorted(map(str, weights))}")
        self.identity = {
            "model": JUDGE_MODEL,
            "weights": weights.pop(),
            "replicas": len(endpoints),
            "system_prompt": SYSTEM_PROMPT,
            "generation": GENERATION,
        }

    def chat(self, prompt: str):
        client = self._clients.get()
        try:
            return client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                **GENERATION,
            )
        finally:
            self._clients.put(client)


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / key[:2] / f"{key}.json"


def _load_cache(cache_dir: Path, key: str):
    path = _cache_path(cache_dir, key)
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return row if row.get("status") == "ok" else None


def _store_cache(cache_dir: Path, key: str, row: dict) -> None:
    path = _cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, row)


def _score_one(judge: LocalJudge, cache_dir: Path, item: dict, attempts: int) -> dict:
    key = hashlib.sha256(
        json.dumps(
            {"model": judge._model, "prompt": item["prompt"]},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        return {**item, **cached, "cached": True}

    last_error = ""
    for attempt in range(max(1, attempts)):
        try:
            completion = judge.chat(item["prompt"])
            response = completion.choices[0].message.content or ""
            payload = json.loads(_extract(response, "score"))
            coverage = list(payload["coverage"])
            correctness = list(payload["correctness"])
            if len(coverage) != len(correctness) or len(coverage) != item["point_count"]:
                raise ValueError("coverage/correctness length mismatch")
            if any(type(x) is not bool for x in coverage + correctness):
                raise ValueError("Judge values must be booleans")
            if any(correct and not covered for covered, correct in zip(coverage, correctness)):
                raise ValueError("Uncovered point cannot be correct")
            row = {
                "status": "ok",
                "coverage": coverage,
                "correctness": correctness,
                "score": float(sum(coverage) + sum(correctness)),
                "error": "",
                "cached": False,
                "response": response,
                "response_model": completion.model,
                "usage": completion.usage.model_dump() if completion.usage else None,
            }
            _store_cache(cache_dir, key, row)
            return {**item, **row}
        except Exception as exc:  # noqa: BLE001 - retryable judge failure (greedy: transport errors only)
            last_error = str(exc).strip() or type(exc).__name__
    return {**item, "status": "error", "error": last_error, "cached": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="CrossVid run output dir")
    parser.add_argument(
        "--qa-path",
        type=Path,
        default=Path("/assets/crossvid/QA/CCQA.json"),
    )
    parser.add_argument(
        "--endpoints",
        required=True,
        help=f"vLLM endpoints serving {JUDGE_MODEL}: URLs, ports or port ranges (8100-8107)",
    )
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=600.0)
    return parser


def main() -> None:
    args = _parser().parse_args()
    output_dir = args.output.expanduser().resolve()
    qa_rows = json.loads(args.qa_path.read_text(encoding="utf-8"))
    qa_by_id = {int(row["id"]): row for row in qa_rows}

    items = []
    for qa_id, row in sorted(qa_by_id.items()):
        record_path = output_dir / "records/crossvid" / f"crossvid:CCQA:{qa_id}" / "result.json"
        if not record_path.is_file():
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("status") != "ok":
            continue
        prediction = str(record.get("prediction") or "").strip()
        items.append(
            {
                "id": qa_id,
                "point_count": len(row["scoring_points"]),
                "prediction": prediction,
                "prompt": SCORE_PROMPT.format(
                    QUESTION=row["question"],
                    ANSWER=row["answer"],
                    POINTS=row["scoring_points"],
                    OUTPUT=prediction,
                ),
            }
        )
    if not items:
        raise SystemExit("No completed CCQA predictions found to score.")

    cache_dir = output_dir / "ccqa_judge_cache"
    endpoints = parse_endpoints(args.endpoints)
    judge = LocalJudge(endpoints, args.timeout_sec)
    results: dict[int, dict] = {}
    lock = threading.Lock()
    done = {"count": 0}

    def work(item: dict) -> None:
        row = _score_one(judge, cache_dir, item, args.attempts)
        with lock:
            results[row["id"]] = row
            done["count"] += 1
            if done["count"] % 100 == 0:
                print(f"[PROGRESS] {done['count']}/{len(items)}", flush=True)

    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        list(pool.map(work, items))

    ok_rows = [row for row in results.values() if row.get("status") == "ok"]
    failed_ids = sorted(row["id"] for row in results.values() if row.get("status") != "ok")
    sum_score = sum(row["score"] for row in ok_rows)
    all_score = sum(2 * len(row["coverage"]) for row in ok_rows)
    official_score = sum_score / all_score if all_score else None
    from collections import Counter

    distribution = Counter(round(row["score"] / (2 * len(row["coverage"])), 2) for row in ok_rows)
    report = {
        "updated_at_utc": _utc_now(),
        "task": "CCQA",
        "scoring_protocol": "CrossVid official score_CCQA.py",
        "official_source": "https://github.com/chuntianli666/CrossVid/blob/b53ada63551f9ac4a726b381b627d17ece066281/eval/score_CCQA.py",
        "judge": judge.identity,
        "qa_path": str(args.qa_path),
        "qa_sha256": hashlib.sha256(args.qa_path.read_bytes()).hexdigest(),
        "scored_answer_count": len(ok_rows),
        "failed_ids": failed_ids,
        "sum_score": sum_score,
        "all_score": all_score,
        "official_score": official_score,
        "score_ratio_distribution": {
            str(k): v for k, v in sorted(distribution.items())
        },
        "samples": [
            {
                "id": row["id"],
                "prediction": row["prediction"],
                "coverage": row.get("coverage"),
                "correctness": row.get("correctness"),
                "score": row.get("score"),
                "status": row.get("status"),
                "error": row.get("error") or "",
                "cached": row["cached"],
            }
            for row in sorted(results.values(), key=lambda item: item["id"])
        ],
    }
    save_path = output_dir / "score" / REPORT_NAME
    save_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(save_path, report)
    print(f"[DONE] official_score={official_score} scored={len(ok_rows)} failed={len(failed_ids)}")
    print(f"[DONE] saved={save_path}")


if __name__ == "__main__":
    main()
