# MVU-Eval: move the official instruction after the options

Requested on 2026-10-14 (Asia/Shanghai): repeat all 1,824 MVU-Eval questions for
Qwen3.5-9B, 27B and 35B-A3B, moving the unchanged official answer instruction
after the options. This is an experiment-specific change; default prompts stay as
they are. Scores and comparisons will be added after actual inference completes.

The controller `scripts/run_mvu_instruction_after.py` reuses the frozen runtime
and orchestration helpers from `/runs/devbox/e2e_full_20261013_timeout/frozen_repo`.
It copies that source into a new run, changes only the MVU adapter, and records
the baseline and launcher commits plus source hashes. Resume uses this new frozen
copy. It reuses the previous eight GPU shards and frame cache, while recording
new request hashes. Every request must reproduce its old input hash before the
instruction is moved, covering the images, text and generation settings.

Protocol: 8 independent H100 workers, BF16, TP1/DP1/concurrency1, v2 profile with
prefix and multimodal processor caches disabled, seed0, temperature0, thinking
disabled, at most 512 image frames, maximum image side 448, max_tokens8192.
Report official first-character accuracy, format compliance and robust accuracy,
both overall and by task, paired against the previous completed official-order
results. MVU-Eval uses its closed-form scorer and needs no Judge.

Previous results: 9B in `devbox/e2e_full_20261012/9B`; 27B and 35B-A3B in
`devbox/e2e_full_20261013_timeout/`. New run: `devbox/mvu_instruction_after_20261014/`.
All raw results and frozen runtime remain in Modal volume
`wxu-evolve-agent-runs-20261006`; local files contain only code and Markdown.

Launch after CPU preparation, through the project's devbox tool:

```bash
python scripts/run_mvu_instruction_after.py --output /runs/devbox/mvu_instruction_after_20261014 --prepare-only
python /runs/devbox/mvu_instruction_after_20261014/frozen_repo/scripts/run_mvu_instruction_after.py --output /runs/devbox/mvu_instruction_after_20261014
```

Status at 2026-10-14 11:11 Asia/Shanghai: CPU preparation and checks passed;
9B loading in Sandbox `sb-zuVtvMSQ9UZuBFint9zR4q`, job PID43, started 11:08.
The source audit confirmed only the existing MVU adapter changed; all 1,824
original request hashes match across the three baseline models. Full remote
compileall and instruction relocation / changed-input rejection checks passed.
The eight allocated GPUs are NVIDIA H100 80GB HBM3. No new responses yet.

Launcher commit: `0485741`; paired analysis script and its timeout-only comparison
correction: `f2ea20e`. Both are backed up on `codex/mvu-instruction-after`.
The original shared checkout contains unrelated uncommitted runtime changes and
local notes, which are outside this branch's backup.

After completion, run `scripts/analyze_mvu_instruction_after.py --output
/runs/devbox/mvu_instruction_after_20261014` on Modal. It checks paired coverage,
model/config identity, media metadata, full output token logs and server request
logs, then writes `analysis/analysis.json` and `analysis/report.md` on the volume.


## Background handoff — 2026-10-14 11:28 Asia/Shanghai

The user requested ending the conversation once inference was healthy, leaving
the program running. At 11:27:49 the controller recorded 476/1,824 successful 9B
responses and zero request errors; all eight workers have produced results.
27B and 35B-A3B are pending automatic model switching. First real responses
include Counting:5 → `B` (2 output tokens); some questions still produce analysis.
Eight actual service manifests confirm v2, prefix caching disabled, TP1 and
max_num_seqs1 on eight different H100s. Original input hashes are checked before
each inference, and a real client/server token-log comparison passed.

Estimated remaining time at 11:28: **3–5 hours**, approximately **14:30–16:30
Asia/Shanghai**. 9B has completed about 476 questions in 16 minutes, with an
observed mean 15.37 seconds/question; the prior full 27B/35B MVU runs required
about 1.25/1.35 hours of ideal eight-GPU work. The estimate allows model loading,
slower questions and uneven shard completion. It is not a completion deadline.

The detached controller performs model switching, per-model official scoring,
paired per-task comparisons, result persistence and normal GPU release. It has
bounded in-sandbox inference retries, but no cross-sandbox recovery after
preemption. A failure is recorded in progress.json and does not become a zero
score. The sandbox has a 12-hour limit, ending around 23:05 Asia/Shanghai.

Independent Luna checks stop when this conversation ends; the program's own
30-second progress updates, bounded failure handling and sandbox watchdog
continue. Do not describe the independent agent as still monitoring afterward.
The optional final audit/report script has been copied to the run root and its
self-check and real log-schema check passed; it can be run on Modal CPU after
completion. The controller itself already produces scored results, paired
comparison JSON and report.md without that extra analysis step.

Read-only progress commands from the main project directory:

```bash
DEVBOX_NAME=mvagent-mvu-after-20261014 .agents/skills/mvagent-environment/devbox/devbox.sh cat devbox/mvu_instruction_after_20261014/progress.json
DEVBOX_NAME=mvagent-mvu-after-20261014 .agents/skills/mvagent-environment/devbox/devbox.sh log mvu_instruction_after_20261014
```
