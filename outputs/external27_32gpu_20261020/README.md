# LensWalk and Video-RSI 27B: 32 H100s each

Both methods now run four independent groups of eight H100 GPUs, expanding each method from 16 to 32 H100s. Startup verification confirmed 64 distinct GPU UUIDs across the two methods, the original 27B weights and execution settings, and disjoint ownership of all 5,321 questions per method. The background supervisors continue inference, saved CCQA judging, final CPU merging and GPU release.

| Method | New run under `devbox/` | Preserved results | Processed at 12:50 UTC, 2026-10-20 |
|---|---|---:|---:|
| LensWalk 27B | `lenswalk_27b_32gpu_20261020` | 2,929 | 3,103 / 5,321 |
| Video-RSI 27B | `rsi_27b_32gpu_20261020` | 440 | 524 / 5,321 |

These totals include failed or unfinished outcomes, not just correct answers. Each parent has `-shard0` through `-shard3`. Pending work is balanced using saved 35B timing without using its answers in inference. The model implementation, prompts, inference settings and question budgets are unchanged. Per-question Agent execution, media preparation and archive times remain separate.

The handoff stopped old dispatchers, let started clients finish under the original budgets, and verified committed records and archive hashes from a fresh CPU mount before repartitioning. Both methods recorded zero handoff inference retries. Saved negative outcomes are retained and skipped; only media preparation that had not started inference can restart. Each group references the existing immutable frozen source, so the old run directories must be retained. Disjoint ownership does not guarantee that unsaved work can never repeat after an unexpected failure or lease renewal.

The startup audits are stored as `startup_audit.json` in each new parent. LensWalk's audit covered 13 new processed questions with zero new infrastructure failures; Video-RSI's covered 80 new questions, 307 calls and zero new infrastructure failures. Every group produced new model output. For example, LensWalk `mvu_eval:RAG:884` returned `C` in 217.38 Agent seconds after 26.33 seconds of preparation. These are execution checks, not newly computed accuracy scores. Later outcomes continue to accumulate, and existing failures remain included.

Three observed handoff issues were fixed: idle nodes are kept alive while the other group drains; the CPU reader waits for committed drain receipts; old model servers are located by their current process and old run directory because their startup PIDs can become obsolete after automatic restarts. One expired idle RSI node was replaced with eight H100s. The reused RSI node's eight old native servers were closed and its volume reload passed; three already-running new groups were adopted without restarting their inference.

Source compilation and remote CPU checks passed for disjoint ownership, preserved failures, work balancing, original frozen budgets, delayed receipt visibility and idle-node replacement. Actual GPU runs verified model identity and new outputs from all eight groups. A temporary shared-volume layer limit affected only saving the final audit metadata; the retry succeeded and the saved receipt was verified. No dependency was installed for the recovery tests.

Operational references on `modal-gpu`:

- Controller and logs: `/tmp/external27-expand-32gpu-20261020/`.
- Current LensWalk master: 848678; children 848689, 848690, 848691, 848692.
- Current Video-RSI master: 860451; children 857606, 860454, 857608, 857609.
- Code: `scripts/expand_external27.py`, `eval/external_methods/expand_external.py`, `eval/external_methods/drain_external.py`.
- The original expansion owner, temporary keepers and one-shot startup checker have finished; do not restart the old paused owners. Historical tracebacks preceding the recovery markers are not current model failures.

Stable throughput and final scores have not yet been measured for the enlarged runs. GPU count doubling is not evidence that remaining wall-clock time halves: media preparation and long questions still affect utilization. Raw results remain on Modal; this report contains no media, weights, full token arrays or raw result bundles.
