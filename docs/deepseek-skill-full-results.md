# MVAgent with DeepSeek-Flash skills: full three-model results

All three models completed the fixed 5,321-question evaluation: CVBench 997,
MVU-Eval 1,824 and CrossVid Lite2500 2,500. Each model has 239 completed CCQA
judgments and no missing or infrastructure-error records in the final scored
summary. This does not mean every answer is correct or every intermediate action
is valid; original responses and recoverable errors are retained.

This experiment evaluates the **same once-generated 14-card bank** (Global 6,
Video 8) with automatic selection. It is separate from the later hand-authored
skill diagnostics and rolewise evolution experiments. Actor weights are unchanged.

## Scores

All values are percentages; deltas are percentage points against the linked
historical no-skill results on the same questions.

| Actor | Benchmark | Questions | With skills | No skill | Delta |
|---|---|---:|---:|---:|---:|
| 9B | CVBench | 997 | 62.8887 | 64.4935 | −1.6048 |
| 9B | MVU-Eval | 1,824 | 48.3004 | 50.5482 | −2.2478 |
| 9B | CrossVid Lite2500 | 2,500 | 36.1005 | 35.2815 | +0.8190 |
| 27B | CVBench | 997 | 69.1073 | 70.5115 | −1.4042 |
| 27B | MVU-Eval | 1,824 | 58.4978 | 58.0044 | +0.4934 |
| 27B | CrossVid Lite2500 | 2,500 | 47.0821 | 48.1007 | −1.0186 |
| 35B-A3B | CVBench | 997 | 68.3049 | 67.5025 | +0.8024 |
| 35B-A3B | MVU-Eval | 1,824 | 52.5219 | 54.2763 | −1.7544 |
| 35B-A3B | CrossVid Lite2500 | 2,500 | 41.5146 | 41.2655 | +0.2491 |

CVBench/MVU-Eval aggregate their complete included populations. CrossVid reports
the ten-task macro, with CCQA weighted by scoring-point count within that task.
There are four positive and five negative point estimates. All four positive
95% intervals include zero; these results do not establish a consistent benefit
from this generated library. The 9B MVU-Eval delta has an exploratory interval
of approximately [−4.17, −0.44] pp. Intervals use a stratified question bootstrap
with seed 0 and do not correct for shared videos, repeated looks or multiple
comparisons. The fixed panels have been reused for development, so this is not
an independent held-out generalization test.

## Completion and provenance

Each model reuses 360 completed pilot skill records and adds 4,961 records:
14,883 new evaluations plus 1,080 pilot records, totaling 15,963 scored model/question
pairs. The no-skill comparisons reuse the previously linked final results; no
no-skill inference or additional Judge call was performed for publication.

- Frozen execution source: `0894a470b322ac0ed74744a6d3131fbdd778ca14`.
- Skill bank SHA256: `7da609f63fda7c4fb1c446b477fc5663b15c9d77487784a12fcbd27b8d52b049`.
- Result root: `devbox/deepseek_skill_full_20261021` in the Modal runs volume.
- `final_summary.json` marks all three models complete, with 5,321 valid scored
  records each; `judge_status.json` marks judging complete.
- The six GPU sandboxes were released. The original host controller encountered
  a Volume-layer limit while saving its final state, leaving no combined
  `controller_result.json`; a separate completion reconciliation verifies the
  native run completion, final scores and terminated sandboxes. The failed/stale
  metadata is preserved. It does not indicate missing model outputs.

The inference profile remains BF16, independent H100 replicas, TP1/DP1,
concurrency one per replica, seed 0, temperature 0, thinking disabled, 512-frame
and 2,048-output-token limits, and disabled prefix/MM processor caches. The
fixed CCQA Judge is Qwen3-30B-A3B-Instruct-2507. See
[the experiment protocol](deepseek-skill-full.md) for scheduling and reuse details.

## Result packages

The release target is
[MVAgent skill results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-skill-results-20261021).
The prior [no-skill results](https://github.com/Wal-K-aWay/MVAgent/releases/tag/mvagent-results-20261019)
and other method Releases remain unchanged.

Each model package follows the existing five-file result layout:

- `cvbench.jsonl`, `mvu_eval.jsonl`, `crossvid.jsonl`: question ID, original ground
  truth, exact final answer string, saved elapsed seconds and text trajectory.
- `ccqa_scores.jsonl`: original coverage/correctness arrays, scoring-point counts
  and normalized scores for all 239 CCQA questions.
- `statistics.md`: metrics, mean per-question time and protocol notes.

Trajectories include model text, action/repair events and the actual skill-selection
events. Media Base64 is replaced by hashes; full token ID arrays and duplicate
transport events are omitted. Original results, full token audits, media, weights
and frozen environments remain in Modal. Packages are Release attachments,
not files in Git history. Release checksums and `release_manifest.json` identify
the published artifacts and their provenance.

Publication verification is recorded below after export and upload complete.
