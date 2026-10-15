# Pairwise decision comparison

Compare the two role-local traces under the same task and execution context. Judge only the quality attributable to the {{role}} decision strategy. Do not override an official correctness failure or infer facts unavailable to this role.

## Immutable role contract
{{role_contract}}

## Paired trajectories
{{comparisons}}

For every numbered comparison, judge the role-local decision and its first real downstream effect separately. Use `invalid` for a dimension that the visible evidence cannot support. Candidate ordering is intentionally opaque; do not assume either position is the new strategy. Do not infer hidden scores, reference answers, or private state.

## Output contract
Return one JSON object containing only:

```json
{
  "comparisons": [
    {
      "sample_number": 1,
      "local_winner": "candidate_a | candidate_b | tie | invalid",
      "lookahead_winner": "candidate_a | candidate_b | tie | invalid"
    }
  ],
  "reason": "<brief evidence-based comparison across the numbered samples>"
}
```

Return exactly one comparison object for every numbered comparison, in the same order.
