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
