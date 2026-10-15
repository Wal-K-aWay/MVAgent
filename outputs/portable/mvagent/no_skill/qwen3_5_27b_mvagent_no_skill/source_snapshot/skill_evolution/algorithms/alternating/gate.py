"""Single paired full-system acceptance; no local rewards or model judgments."""
import math

GATE_REPEATS = 1
GATE_RULE = "single-positive-health-v1"


def summarize_gate(pairs):
    if len(pairs) != GATE_REPEATS:
        raise ValueError(f"Gate requires {GATE_REPEATS} paired repeats")
    repeats = []
    membership = set(pairs[0][0]["health"])
    if not membership:
        raise ValueError("Gate requires nonempty evaluation samples")
    for parent, candidate in pairs:
        if set(parent["health"]) != membership or set(candidate["health"]) != membership:
            raise ValueError("Gate repeats require identical question membership")
        if not all(math.isfinite(r["score"]) for r in (parent, candidate)):
            raise ValueError("Gate scores must be finite")
        regressions = [sid for sid in sorted(membership) if any(
            candidate["health"][sid][metric] > parent["health"][sid][metric]
            for metric in ("fatal", "invalid"))]
        repeats.append({"parent_score": parent["score"], "candidate_score": candidate["score"],
            "score_delta": candidate["score"] - parent["score"],
            "reliability_regressions": regressions})
    parent_score = sum(r["parent_score"] for r in repeats) / GATE_REPEATS
    candidate_score = sum(r["candidate_score"] for r in repeats) / GATE_REPEATS
    regressions = sum(len(r["reliability_regressions"]) for r in repeats)
    score_delta = candidate_score - parent_score
    return {"accepted": score_delta > 0 and not regressions,
            "gate_rule": GATE_RULE,
            "parent_score": parent_score, "candidate_score": candidate_score,
            "score_delta": score_delta,
            "repeat_deltas": [r["score_delta"] for r in repeats],
            "new_reliability_regressions": regressions, "repeats": repeats}
