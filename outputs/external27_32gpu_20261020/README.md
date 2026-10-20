# 27B external-method expansion

LensWalk and Video-RSI each expand from two to four groups of eight H100 GPUs. The controller lets started inference finish under the original question budget, verifies committed records on a fresh CPU mount, and assigns every question to exactly one new group. Saved failures and unfinished answers remain final outcomes. Only preparation that has not started inference can restart.

The original model implementation, prompts, inference settings and question budgets are preserved. Each group references its immutable old frozen source; old run directories must be retained. Pending work is balanced using saved 35B question timing, without using historical answers in inference.

- New runs: `devbox/lenswalk_27b_32gpu_20261020`, `devbox/rsi_27b_32gpu_20261020`, each with `-shard0` through `-shard3`.
- Controller: `scripts/expand_external27.py`, running on the Modal dev box in `/tmp/external27-expand-32gpu-20261020/`.
- Existing nodes are reused; each method adds two eight-GPU nodes. Total allocation for these two methods becomes 64 H100s.
- Remote CPU checks passed: source compilation, four-way ownership, failed-outcome preservation, weighted work allocation, and the original LensWalk 1800-second / Video-RSI 7200-second question budgets.

At 12:16 UTC on 2026-10-20, the additional nodes were allocated and the old dispatchers were deliberately paused while started clients drained. The running controller uses commit `e6df3b9`; a temporary dev-box keeper writes `/work/heartbeat` on the new nodes during this transition. The checked-in controller now performs that heartbeat directly. Neither changes model behavior. Startup verification and measured throughput are pending; allocation alone is not evidence of a twofold speedup.
