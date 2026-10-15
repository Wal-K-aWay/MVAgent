from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


MANUAL_OVERRIDES = {
    # Expanded CVBench review.
    **{
        ("cvbench", sample_id): label
        for sample_id, label in {
            "11": "video_agent", "115": "global_decision", "128": "global_decision",
            "162": "global_decision", "187": "global_decision", "29": "both",
            "30": "video_agent", "364": "video_agent", "4": "global_decision",
            "442": "global_decision", "45": "global_decision", "459": "global_decision",
            "483": "global_watch", "492": "global_decision", "512": "video_agent",
            "557": "global_decision", "565": "video_agent", "597": "video_agent",
            "649": "global_decision", "976": "video_agent", "979": "global_decision",
        }.items()
    },
    # Expanded MVU-Eval review.
    **{
        ("mvu-eval", sample_id): label
        for sample_id, label in {
            "1050": "video_agent", "118": "video_agent", "15": "global_watch",
            "652": "global_decision", "687": "global_decision", "731": "video_agent",
            "172": "video_agent", "389": "video_agent", "421": "both",
            "449": "video_agent", "503": "video_agent", "555": "global_watch",
            "419": "global_decision", "426": "video_agent", "1300": "video_agent",
            "1347": "video_agent", "1368": "both", "1757": "video_agent",
            "1762": "global_decision", "944": "video_agent", "988": "video_agent",
            "997": "video_agent", "1245": "global_decision", "811": "video_agent",
            "1440": "global_watch", "1477": "global_watch", "827": "global_decision",
        }.items()
    },
    # CrossVid cases where individual review changes the task-level default.
    ("crossvid", "crossvid:BU:124"): "global_decision",
    ("crossvid", "crossvid:CC:31"): "global_decision",
    ("crossvid", "crossvid:CC:345"): "both",
    ("crossvid", "crossvid:CC:397"): "global_watch",
    ("crossvid", "crossvid:CC:432"): "video_agent",
    ("crossvid", "crossvid:CC:454"): "global_watch",
    ("crossvid", "crossvid:CC:525"): "both",
    ("crossvid", "crossvid:CC:532"): "global_watch",
    ("crossvid", "crossvid:CC:601"): "video_agent",
    ("crossvid", "crossvid:CC:608"): "other_data_label",
    ("crossvid", "crossvid:CC:630"): "global_watch",
    ("crossvid", "crossvid:CC:655"): "global_decision",
    ("crossvid", "crossvid:CC:708"): "other_data_label",
    ("crossvid", "crossvid:CC:770"): "global_decision",
}


INDIVIDUALLY_REVIEWED_RULE_KEYS = {
    # All newly sampled FSA cases were individually reviewed; most confirmed the
    # task-level VideoAgent temporal-localization pattern.
    ("crossvid", f"crossvid:FSA:{sample_id}")
    for sample_id in (
        "1093", "1116", "1148", "123", "1282", "1283", "1413", "1486",
        "1560", "1575", "1609", "1612", "1638", "1640", "1647", "1712",
        "1755", "1795", "1845", "1902", "1920", "2064", "2102", "2147",
        "260", "299", "3", "324", "336", "339", "48", "540", "563",
        "606", "613", "624", "661", "673", "872", "924",
    )
} | {
    ("crossvid", sample_id)
    for sample_id in (
        "crossvid:BU:0", "crossvid:BU:165", "crossvid:BU:260",
        "crossvid:BU:263", "crossvid:BU:374", "crossvid:MOC:113",
        "crossvid:MOC:12", "crossvid:MOC:159", "crossvid:MOC:173",
        "crossvid:MOC:184", "crossvid:MOC:207",
    )
}


def _load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _task_rule(packet: dict[str, Any]) -> str:
    task = packet["task"]
    stop_reason = packet["features"]["stop_reason"]
    if task == "PSS":
        return "global_watch" if stop_reason == "watch_videos_answer" else "global_decision"
    if task == "PI":
        return "global_decision"
    if task in {"BU", "CC", "FSA", "MOC", "MSR", "NC", "PEA"}:
        return "global_watch" if stop_reason == "watch_videos_answer" else "video_agent"
    raise KeyError(f"no task rule for {packet['benchmark']}:{task}:{packet['sample_id']}")


def _weighted_summary(
    labels: list[dict[str, Any]], metadata: dict[str, Any]
) -> dict[str, Any]:
    population = {
        (row["benchmark"], row["task"]): int(row["population"])
        for row in metadata["allocation"]
    }
    sample = {
        (row["benchmark"], row["task"]): int(row["sample"])
        for row in metadata["allocation"]
    }
    n_total = sum(population.values())
    categories = sorted({row["attribution"] for row in labels})
    by_stratum: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in labels:
        by_stratum[(row["benchmark"], row["task"])][row["attribution"]] += 1

    estimates: dict[str, Any] = {}
    for category in categories:
        estimate = 0.0
        variance = 0.0
        for key, n_h in sample.items():
            N_h = population[key]
            x_h = by_stratum[key][category]
            p_h = x_h / n_h
            estimate += N_h * p_h
            if n_h > 1:
                sample_variance = p_h * (1.0 - p_h) * n_h / (n_h - 1)
                variance += (N_h / n_total) ** 2 * (1.0 - n_h / N_h) * sample_variance / n_h
        share = estimate / n_total
        margin = 1.96 * math.sqrt(max(variance, 0.0))
        estimates[category] = {
            "estimated_count": estimate,
            "estimated_share": share,
            "ci95_low": max(0.0, share - margin),
            "ci95_high": min(1.0, share + margin),
        }

    return {
        "population": n_total,
        "sample_size": len(labels),
        "sample_fraction": len(labels) / n_total,
        "unweighted_counts": dict(Counter(row["attribution"] for row in labels)),
        "weighted_estimates": estimates,
        "label_basis": dict(Counter(row["label_basis"] for row in labels)),
        "confidence": dict(Counter(row["confidence"] for row in labels)),
        "by_benchmark": {
            benchmark: dict(Counter(row["attribution"] for row in labels if row["benchmark"] == benchmark))
            for benchmark in sorted({row["benchmark"] for row in labels})
        },
        "by_task": {
            f"{benchmark}:{task}": dict(
                Counter(
                    row["attribution"]
                    for row in labels
                    if row["benchmark"] == benchmark and row["task"] == task
                )
            )
            for benchmark, task in sorted({(row["benchmark"], row["task"]) for row in labels})
        },
    }


def _population_metrics(path: Path) -> dict[str, Any]:
    rows = _load_tsv(path)
    return {
        "count": len(rows),
        "uses_watch_count": sum(row["uses_watch"] == "True" for row in rows),
        "uses_watch_share": sum(row["uses_watch"] == "True" for row in rows) / len(rows),
        "max_steps_count": sum(row["stop_reason"] == "max_steps" for row in rows),
        "max_steps_share": sum(row["stop_reason"] == "max_steps" for row in rows) / len(rows),
        "failed_video_run_records": sum(int(row["failed_video_runs"]) > 0 for row in rows),
        "mean_global_decisions": mean(float(row["global_decisions"]) for row in rows),
        "mean_video_runs": mean(float(row["video_runs"]) for row in rows),
        "mean_observe_steps": mean(float(row["observe_steps"]) for row in rows),
        "stop_reasons": dict(Counter(row["stop_reason"] for row in rows)),
    }


def _broad_label(label: str) -> str:
    if label in {"video_agent", "global_watch"}:
        return "visual_evidence_layer"
    if label == "global_decision":
        return "global_reasoning_layer"
    if label == "both":
        return "both_layers"
    return "data_or_label"


def _weighted_by_benchmark(
    labels: list[dict[str, Any]], metadata: dict[str, Any]
) -> dict[str, Any]:
    allocation = {
        (row["benchmark"], row["task"]): (int(row["population"]), int(row["sample"]))
        for row in metadata["allocation"]
    }
    output: dict[str, Any] = {}
    for benchmark in sorted({row["benchmark"] for row in labels}):
        benchmark_population = sum(
            N_h for (name, _), (N_h, _) in allocation.items() if name == benchmark
        )
        estimates: Counter[str] = Counter()
        for (name, task), (N_h, n_h) in allocation.items():
            if name != benchmark:
                continue
            counts = Counter(
                row["attribution"]
                for row in labels
                if row["benchmark"] == benchmark and row["task"] == task
            )
            for category, count in counts.items():
                estimates[category] += N_h * count / n_h
        output[benchmark] = {
            "population": benchmark_population,
            "estimated_shares": {
                category: count / benchmark_population
                for category, count in sorted(estimates.items())
            },
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True, type=Path)
    parser.add_argument("--prior-audit", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--population", required=True, type=Path)
    parser.add_argument("--output-tsv", required=True, type=Path)
    parser.add_argument("--summary-json", required=True, type=Path)
    args = parser.parse_args()

    prior = {
        (row["benchmark"], row["sample_id"]): row
        for row in _load_tsv(args.prior_audit)
    }
    packets = [json.loads(line) for line in args.packets.read_text(encoding="utf-8").splitlines()]
    labels: list[dict[str, Any]] = []
    for packet in packets:
        key = (packet["benchmark"], packet["sample_id"])
        if key in prior:
            attribution = prior[key]["attribution"]
            confidence = prior[key]["confidence"]
            basis = "prior_individual_review"
            note = prior[key]["note"]
        elif key in MANUAL_OVERRIDES:
            attribution = MANUAL_OVERRIDES[key]
            confidence = "medium"
            basis = "expanded_individual_review"
            note = "Individually reviewed from the frozen question, reports, watch result, final reason, and action history."
        else:
            attribution = _task_rule(packet)
            if key in INDIVIDUALLY_REVIEWED_RULE_KEYS:
                confidence = "medium"
                basis = "expanded_individual_review"
                note = "Individually reviewed from the frozen question, reports, watch result, final reason, and action history."
            else:
                confidence = "low"
                basis = "crossvid_task_rule"
                note = "Assigned by a task-specific ownership rule after individual review established the dominant failure mechanism for this task/path."
        labels.append(
            {
                "benchmark": packet["benchmark"],
                "sample_id": packet["sample_id"],
                "task": packet["task"],
                "attribution": attribution,
                "confidence": confidence,
                "label_basis": basis,
                "uses_watch": packet["features"]["uses_watch"],
                "stop_reason": packet["features"]["stop_reason"],
                "note": note,
            }
        )

    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    fields = list(labels[0])
    with args.output_tsv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(labels)

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    broad_labels = [
        {**row, "attribution": _broad_label(row["attribution"])} for row in labels
    ]
    crossvid_prior = [
        packet
        for packet in packets
        if packet["benchmark"] == "crossvid" and packet["prior_attribution"]
    ]
    rule_exact = sum(
        _task_rule(packet) == packet["prior_attribution"] for packet in crossvid_prior
    )
    rule_broad = sum(
        _broad_label(_task_rule(packet)) == _broad_label(packet["prior_attribution"])
        for packet in crossvid_prior
    )
    mapping_pattern = re.compile(
        r"clip ends|outside the duration|not available|does not contain the requested time range|inaccessible",
        re.IGNORECASE,
    )
    sampled_fsa = [
        packet for packet in packets if packet["benchmark"] == "crossvid" and packet["task"] == "FSA"
    ]
    mapping_cases = [
        packet["sample_id"]
        for packet in sampled_fsa
        if mapping_pattern.search(json.dumps(packet["video_reports"], ensure_ascii=False))
    ]
    summary = {
        "snapshot_generated_at": metadata["generated_at"],
        "scope": metadata,
        "attribution": _weighted_summary(labels, metadata),
        "broad_ownership": _weighted_summary(broad_labels, metadata),
        "by_benchmark_weighted": _weighted_by_benchmark(labels, metadata),
        "wrong_population_trajectory": _population_metrics(args.population),
        "validation": {
            "crossvid_task_rule_holdout_n": len(crossvid_prior),
            "crossvid_task_rule_exact_agreement": rule_exact / len(crossvid_prior),
            "crossvid_task_rule_broad_layer_agreement": rule_broad / len(crossvid_prior),
            "sampled_fsa_temporal_mapping_issue_count": len(mapping_cases),
            "sampled_fsa_count": len(sampled_fsa),
            "sampled_fsa_temporal_mapping_issue_ids": mapping_cases,
        },
        "important_caveat": (
            "Confidence intervals quantify sampling error only. They do not include systematic "
            "error from subjective individual labels or CrossVid task-rule labels."
        ),
    }
    args.summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
