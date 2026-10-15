#!/usr/bin/env python3
"""Historical compatible CCQA scoring for saved CrossVid runs using MiniMax-M3.

Replicates the official ``eval/score_CCQA.py`` SCORE prompt and metric. New official
evaluations must execute the vendored upstream scorer under ``eval/e2e_eval/CrossVid``;
this file remains only so historical result manifests stay reproducible.
(``sum(coverage + correctness) / (2 * num_scoring_points)``) exactly, and swaps
the official local-endpoint transport for an OpenAI-compatible MiniMax-M3 call.

Reads ``QA/CCQA.json`` and ``raw/CCQA_result.json``; writes ``raw/CCQA_score.json``
plus a key-free protocol manifest. Requires ``MINIMAX_API_KEY`` (or ``--api-key``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M3"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 1.0
SYSTEM_PROMPT = "You are a helpful assistant."

SCORE = """
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


def build_prompt(question: str, answer: str, points: list[str], output: str) -> str:
    return SCORE.format(
        QUESTION=question,
        ANSWER=answer,
        POINTS=json.dumps(points, ensure_ascii=False),
        OUTPUT=output,
    )


def chat_completion(
    endpoint: str,
    model: str,
    api_key: str,
    prompt: str,
    max_tokens: int,
    timeout: float,
    temperature: float,
    top_p: float,
) -> str:
    url = endpoint.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request failed: {exc}") from exc
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("no choices in response")
    content = (choices[0].get("message") or {}).get("content")
    if not content or not str(content).strip():
        raise RuntimeError("empty assistant content")
    return str(content).strip()


def extract_score_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    elif text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
    lower = text.lower()
    if "<score>" in lower and "</score>" in lower:
        start = lower.index("<score>") + len("<score>")
        end = lower.index("</score>", start)
        text = text[start:end].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        payload = None
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            payload = candidate
            break
        if payload is None:
            raise
    if not isinstance(payload, dict) or set(payload) != {"coverage", "correctness"}:
        raise ValueError("score JSON must contain exactly coverage and correctness")
    return payload


def score_one(
    item: dict,
    endpoint: str,
    model: str,
    api_key: str,
    max_tokens: int,
    timeout: float,
    max_attempts: int,
    temperature: float,
    top_p: float,
) -> dict:
    prompt = build_prompt(item["question"], item["answer"], item["scoring_points"], item["output"])
    errors = []
    for attempt in range(1, max_attempts + 1):
        try:
            content = chat_completion(
                endpoint,
                model,
                api_key,
                prompt,
                max_tokens,
                timeout,
                temperature,
                top_p,
            )
            payload = extract_score_json(content)
            coverage = payload["coverage"]
            correctness = payload["correctness"]
            if not isinstance(coverage, list) or not isinstance(correctness, list):
                raise ValueError("coverage/correctness must be lists")
            if len(coverage) != len(item["scoring_points"]) or len(correctness) != len(item["scoring_points"]):
                raise ValueError(
                    f"length mismatch: coverage={len(coverage)} correctness={len(correctness)} "
                    f"expected={len(item['scoring_points'])}"
                )
            if not all(isinstance(value, bool) for value in coverage + correctness):
                raise ValueError("coverage/correctness values must be JSON booleans")
            if any(c and not cov for cov, c in zip(coverage, correctness)):
                raise ValueError("correctness true while coverage false")
            return {
                "id": item["id"],
                "answer": item["output"],
                "coverage": coverage,
                "correctness": correctness,
                "score": sum(coverage) + sum(correctness),
                "max_score": 2 * len(coverage),
                "attempts": attempt,
                "raw_judge_output": content,
            }
        except Exception as exc:
            errors.append(f"attempt {attempt}: {exc}")
            time.sleep(1.0)
    return {
        "id": item["id"],
        "answer": item["output"],
        "error": "; ".join(errors),
        "max_score": 2 * len(item["scoring_points"]),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa", type=Path, default=Path("/home/kww/datasets/Multi-Video/CrossVid/QA/CCQA.json"))
    parser.add_argument("--answers", type=Path, default=Path("outputs/qwen36_official_crossvid/raw/CCQA_result.json"))
    parser.add_argument("--save", type=Path, default=Path("outputs/qwen36_official_crossvid/raw/CCQA_score.json"))
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--top-p", type=float, default=DEFAULT_TOP_P)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    if args.max_tokens <= 0 or args.timeout <= 0 or args.max_attempts <= 0 or args.workers <= 0:
        parser.error("max-tokens, timeout, max-attempts, and workers must be positive")
    if args.temperature < 0:
        parser.error("temperature must be non-negative")
    if not 0 < args.top_p <= 1:
        parser.error("top-p must be in (0, 1]")

    api_key = args.api_key.strip() or os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        print("error: set MINIMAX_API_KEY or pass --api-key", file=sys.stderr)
        return 2

    manifest = {
        "script": {
            "path": "scripts/official_crossvid/score_ccqa_m3.py",
            "sha256": sha256(Path(__file__)),
        },
        "input": {
            "qa_path": str(args.qa.resolve()),
            "qa_sha256": sha256(args.qa),
            "answers_path": str(args.answers.resolve()),
            "answers_sha256": sha256(args.answers),
        },
        "judge": {
            "endpoint": args.endpoint,
            "model": args.model,
            "prompt_sha256": hashlib.sha256(
                (SYSTEM_PROMPT + "\n" + SCORE).encode("utf-8")
            ).hexdigest(),
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "timeout_seconds": args.timeout,
            "max_attempts": args.max_attempts,
            "workers": args.workers,
        },
        "aggregation": "sum(score) / sum(max_score)",
    }
    manifest_path = args.save.with_suffix(args.save.suffix + ".manifest.json")
    if args.save.exists() and not manifest_path.exists():
        raise RuntimeError(
            f"Existing score has no protocol manifest: {args.save}. Use a new --save path."
        )
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise RuntimeError(
            f"Judge protocol differs from existing manifest: {manifest_path}. "
            "Use a new --save path."
        )
    write_json_atomic(manifest_path, manifest)

    qa = json.load(open(args.qa))
    answers = json.load(open(args.answers))
    qa_by_id = {int(item["id"]): item for item in qa}
    items = []
    for answer in answers:
        item_id = int(answer["id"])
        pair = qa_by_id.get(item_id)
        if pair is None:
            print(f"warning: no QA row for id {item_id}", file=sys.stderr)
            continue
        items.append({
            "id": item_id,
            "question": pair["question"],
            "answer": pair["answer"],
            "scoring_points": pair["scoring_points"],
            "output": answer["answer"],
        })

    done = {}
    if args.save.exists():
        for row in json.load(open(args.save)):
            if "error" not in row:
                done[int(row["id"])] = row
    todo = [item for item in items if int(item["id"]) not in done]
    print(f"total={len(items)} done={len(done)} todo={len(todo)}", file=sys.stderr)

    results = list(done.values())
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                score_one,
                item,
                args.endpoint,
                args.model,
                api_key,
                args.max_tokens,
                args.timeout,
                args.max_attempts,
                args.temperature,
                args.top_p,
            ): item["id"]
            for item in todo
        }
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            results.append(row)
            if index % 25 == 0 or index == len(futures):
                write_json_atomic(args.save, results)
                print(f"progress {index}/{len(futures)} elapsed={time.time()-start:.0f}s", file=sys.stderr)

    results.sort(key=lambda row: int(row["id"]))
    write_json_atomic(args.save, results)

    scored = [row for row in results if "error" not in row]
    failed = [row for row in results if "error" in row]
    if scored:
        sum_score = sum(row["score"] for row in scored)
        all_score = sum(row["max_score"] for row in scored)
        print(f"CCQA official score: {sum_score / all_score:.6f}  (scored={len(scored)} failed={len(failed)})")
    else:
        print("no scored items")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
