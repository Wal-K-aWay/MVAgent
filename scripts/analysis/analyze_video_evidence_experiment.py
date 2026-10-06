"""Read-only paired development analysis; no model calls or candidate selection."""
import argparse
from collections import defaultdict, Counter
import json
from pathlib import Path
import random
import sys

REPO = next(p for p in Path(__file__).resolve().parents if (p / "AGENTS.md").is_file())
sys.path.insert(0, str(REPO / "src"))
from skill_evolution.infra.benchmarks import load_multibench_records
from skill_evolution.infra.benchmarks.aggregation import HierarchicalScoreAggregator
from skill_evolution.infra.store import write_json, file_fingerprint


def read(path):
    return json.loads(Path(path).read_text())


def paired(left, right, ids, aggregator, draws):
    # Average executions within a question before resampling source groups.
    means = [{s: sum(r["samples"][s]["score"] for r in runs) / len(runs) for s in ids}
             for runs in (left, right)]
    def delta(selected):
        return (aggregator.aggregate(sample_ids=selected, scores=means[1], buckets={}).official_score -
                aggregator.aggregate(sample_ids=selected, scores=means[0], buckets={}).official_score)
    bootstrap = sorted(delta(selected) for selected in draws)
    return {"delta": delta(ids), "repeat_deltas": [r["score"] - l["score"] for l, r in zip(left, right)],
            "group_bootstrap_95_percentile": [bootstrap[int(.025 * len(bootstrap))], bootstrap[int(.975 * len(bootstrap))]],
            "improved_questions": sum(means[1][s] > means[0][s] for s in ids),
            "regressed_questions": sum(means[1][s] < means[0][s] for s in ids),
            "question_deltas": {s: means[1][s] - means[0][s] for s in ids}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    manifest = read(root / "manifest.json")
    usage = Counter()
    calls = []
    for path in sorted((root / "proposals").glob("*/optimizer_events/*.json")):
        data = read(path)
        responses = [e for e in data["events"] if e["kind"] == "model_response"]
        for e in responses:
            u = e.get("usage") or {}
            usage["input"] += u.get("prompt_tokens", 0)
            usage["output"] += u.get("completion_tokens", 0)
            usage["cached_input"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            usage["reasoning"] += (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        calls.append({"stage": data["stage"], "seconds": data["seconds"], "responses": len(responses),
            "invalid_outputs": sum(e["kind"] == "structured_invalid" for e in data["events"]),
            "repairs": sum(e["kind"] == "structured_repair" for e in data["events"])})
    results = {"manifest_sha256": file_fingerprint(root / "manifest.json"), "optimizer_calls": len(calls),
        "optimizer_api_responses": sum(c["responses"] for c in calls),
        "optimizer_invalid_outputs": sum(c["invalid_outputs"] for c in calls),
        "optimizer_repairs": sum(c["repairs"] for c in calls),
        "optimizer_usage": dict(usage), "optimizer_details": calls,
        "estimated_cny": ((usage["input"] - usage["cached_input"]) * .8 + usage["cached_input"] * .23 + usage["output"] * 2.8) / 1e6,
        "price_basis": "BigModel official pricing 2026-09-10; estimate, not account invoice",
        "candidates": [read(p) for p in sorted((root / "proposals").glob("*/candidate.json"))]}
    results["screening"] = read(root / "screening.json") if (root / "screening.json").exists() else []
    results["parent_screening_scores"] = [read(p)["score"] for p in sorted(
        (root / "evaluations").glob("screen_parent_*/summary.json")) if read(p).get("status") == "completed"]
    confirmation = defaultdict(list)
    for path in sorted((root / "evaluations").glob("confirm_*/summary.json")):
        data = read(path)
        if data.get("status") == "completed":
            confirmation[path.parent.name.split("_")[1]].append(data)
    if len(confirmation.get("parent", [])) == 2:
        ids = list(confirmation["parent"][0]["samples"])
        records = load_multibench_records("/home/kww/datasets/Multi-Video", ids)
        aggregator = HierarchicalScoreAggregator(dataset_of={s: records[s].dataset for s in ids},
            category_of={s: records[s].native_task for s in ids}, sample_weights={s: records[s].sample_weight for s in ids})
        groups_path = Path(manifest["archive"]) / "data_audit.json"
        groups = read(groups_path)["media_groups"]
        members = defaultdict(list)
        for sid in ids:
            members[groups[sid]].append(sid)
        strata = defaultdict(list)
        for group, selected in members.items():
            signature = tuple(sorted({(records[s].dataset, records[s].native_task) for s in selected}))
            strata[signature].append(group)
        rng = random.Random(20260910)
        draws = [[sid for signature in sorted(strata) for group in rng.choices(strata[signature], k=len(strata[signature]))
                  for sid in members[group]] for _ in range(2000)]
        results["bootstrap"] = {"seed": 20260910, "draws": 2000, "groups": len(members),
            "strata": len(strata), "single_group_strata": sum(len(g) == 1 for g in strata.values()),
            "group_audit_sha256": file_fingerprint(groups_path),
            "method": "Resample complete media groups within dataset/native-task signature strata; use the same draws for every paired contrast. Average the two executions per question first. Single-group strata have no estimable between-group variance. Conditional on selected Skills, excludes optimizer selection/training-seed uncertainty."}
        summaries = {}
        for arm, runs in confirmation.items():
            if len(runs) != 2:
                continue
            assert all(set(r["samples"]) == set(ids) for r in runs)
            for r in runs:
                value = aggregator.aggregate(sample_ids=ids, scores={s: r["samples"][s]["score"] for s in ids}, buckets={}).official_score
                assert abs(value - r["score"]) < 1e-10
            summaries[arm] = {"scores": [r["score"] for r in runs], "mean": sum(r["score"] for r in runs) / 2,
                "seconds": [r["seconds"] for r in runs], "generated": [r["generated"] for r in runs],
                "repeat_score_changed_questions": sum(runs[0]["samples"][s]["score"] != runs[1]["samples"][s]["score"] for s in ids),
                "bucket_means": {k: sum(r["bucket_scores"][k] for r in runs) / 2 for k in runs[0]["bucket_scores"]},
                "execution_totals": {k: sum(s.get(k, 0) or 0 for r in runs for s in r["samples"].values())
                    for k in ("fatal", "invalid", "invalid_model_outputs", "invalid_text_outputs", "invalid_visual_outputs",
                              "model_errors", "structured_repairs", "failed_video_requests", "observe", "watch", "total_tokens", "model_calls")}}
        results["confirmation"] = summaries
        results["comparisons"] = {}
        for left, right in (("parent", "V0"), ("parent", "V1"), ("parent", "V2"), ("V0", "V1"), ("V0", "V2")):
            if len(confirmation.get(left, [])) == 2 and len(confirmation.get(right, [])) == 2:
                results["comparisons"][f"{right}-{left}"] = paired(confirmation[left], confirmation[right], ids, aggregator, draws)
    write_json(root / "analysis.json", results)
    compact = {k: v for k, v in results.items() if k not in ("candidates", "optimizer_details", "comparisons")}
    compact["comparisons"] = {k: {a: b for a, b in v.items() if a != "question_deltas"} for k, v in results.get("comparisons", {}).items()}
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
