from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analyze_agent_error_attribution import (
    _score_details,
    _trajectory_features,
)


def _stable_key(row: dict[str, Any]) -> str:
    identity = "\0".join(
        (str(row["benchmark"]), str(row.get("task") or "Unknown"), str(row["id"]))
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _allocate_stratified_sample(
    strata: dict[tuple[str, str], list[dict[str, Any]]],
    target: int,
) -> dict[tuple[str, str], int]:
    population = sum(len(rows) for rows in strata.values())
    raw = {key: target * len(rows) / population for key, rows in strata.items()}
    allocation = {key: min(len(strata[key]), math.floor(value)) for key, value in raw.items()}
    remaining = target - sum(allocation.values())
    order = sorted(
        strata,
        key=lambda key: (raw[key] - allocation[key], len(strata[key]), key),
        reverse=True,
    )
    while remaining:
        progressed = False
        for key in order:
            if allocation[key] >= len(strata[key]):
                continue
            allocation[key] += 1
            remaining -= 1
            progressed = True
            if not remaining:
                break
        if not progressed:
            raise ValueError("sample target exceeds the available population")
    return allocation


def _load_existing_audit(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            (row["benchmark"], row["sample_id"]): row
            for row in csv.DictReader(handle, delimiter="\t")
        }


def _public_action_history(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    compact: list[dict[str, Any]] = []
    for item in result.get("action_history") or []:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "action": item.get("action"),
                "status": item.get("status"),
                "parameters": item.get("parameters"),
                "results": item.get("results"),
                "result": item.get("result"),
                "error": item.get("error"),
            }
        )
    return compact


def build_review(
    output_dir: Path,
    audit_path: Path,
    sample_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    population: list[dict[str, Any]] = []
    for detail in _score_details(output_dir):
        if detail.get("status") != "ok" or detail.get("score") is None:
            continue
        if float(detail["score"]) != 0.0:
            continue
        source_path = Path(str(detail["source_path"]))
        features = _trajectory_features(str(source_path))
        population.append({**detail, **features})

    if sample_size > len(population):
        raise ValueError(
            f"sample size {sample_size} exceeds score-zero population {len(population)}"
        )

    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in population:
        strata[(str(row["benchmark"]), str(row.get("task") or "Unknown"))].append(row)
    allocation = _allocate_stratified_sample(strata, sample_size)
    prior = _load_existing_audit(audit_path)

    selected: list[dict[str, Any]] = []
    for key, rows in sorted(strata.items()):
        quota = allocation[key]
        prior_rows = [row for row in rows if (row["benchmark"], str(row["id"])) in prior]
        if len(prior_rows) > quota:
            prior_rows = sorted(prior_rows, key=_stable_key)[:quota]
        selected_keys = {(row["benchmark"], str(row["id"])) for row in prior_rows}
        candidates = sorted(
            [
                row
                for row in rows
                if (row["benchmark"], str(row["id"])) not in selected_keys
            ],
            key=_stable_key,
        )
        selected.extend(prior_rows + candidates[: quota - len(prior_rows)])

    packets: list[dict[str, Any]] = []
    for row in sorted(selected, key=lambda item: (item["benchmark"], item.get("task") or "", str(item["id"]))):
        payload = json.loads(Path(str(row["source_path"])).read_text(encoding="utf-8"))
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        answer = result.get("answer") if isinstance(result.get("answer"), dict) else {}
        prior_label = prior.get((str(row["benchmark"]), str(row["id"])))
        packets.append(
            {
                "benchmark": row["benchmark"],
                "sample_id": str(row["id"]),
                "task": str(row.get("task") or "Unknown"),
                "ground_truth": row.get("answer"),
                "prediction": row.get("prediction"),
                "question": payload.get("question"),
                "options": payload.get("options"),
                "final_reason": answer.get("reason"),
                "video_reports": result.get("video_reports"),
                "watch_results": result.get("watch_results"),
                "action_history": _public_action_history(payload),
                "features": {
                    "uses_watch": row["uses_watch"],
                    "global_decisions": row["global_decisions"],
                    "video_runs": row["video_runs"],
                    "observe_steps": row["observe_steps"],
                    "failed_video_runs": row["failed_video_runs"],
                    "stop_reason": row["stop_reason"],
                },
                "prior_attribution": prior_label["attribution"] if prior_label else None,
                "prior_confidence": prior_label["confidence"] if prior_label else None,
                "prior_note": prior_label["note"] if prior_label else None,
                "source_path": str(row["source_path"]),
            }
        )

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "score_zero_population": len(population),
        "sample_size": len(selected),
        "sample_fraction": len(selected) / len(population),
        "existing_labels_retained": sum(packet["prior_attribution"] is not None for packet in packets),
        "allocation": [
            {
                "benchmark": benchmark,
                "task": task,
                "population": len(strata[(benchmark, task)]),
                "sample": allocation[(benchmark, task)],
            }
            for benchmark, task in sorted(strata)
        ],
        "population_by_benchmark": dict(Counter(row["benchmark"] for row in population)),
        "sample_by_benchmark": dict(Counter(row["benchmark"] for row in selected)),
    }
    return population, packets, metadata


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "benchmark",
        "id",
        "task",
        "prediction",
        "answer",
        "uses_watch",
        "global_decisions",
        "video_runs",
        "observe_steps",
        "failed_video_runs",
        "stop_reason",
        "source_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--sample-size", type=int, default=229)
    parser.add_argument("--population-tsv", required=True, type=Path)
    parser.add_argument("--packets-jsonl", required=True, type=Path)
    parser.add_argument("--metadata-json", required=True, type=Path)
    args = parser.parse_args()

    population, packets, metadata = build_review(
        args.output_dir.resolve(), args.audit.resolve(), args.sample_size
    )
    for path in (args.population_tsv, args.packets_jsonl, args.metadata_json):
        path.parent.mkdir(parents=True, exist_ok=True)
    _write_tsv(args.population_tsv, population)
    with args.packets_jsonl.open("w", encoding="utf-8") as handle:
        for packet in packets:
            handle.write(json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n")
    args.metadata_json.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
