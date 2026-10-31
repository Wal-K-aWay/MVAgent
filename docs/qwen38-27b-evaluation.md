# Qwen3.8-27B MVAgent evaluation

## Scope and current status (2026-10-30)

Requested: download official BF16 Qwen3.8-27B and evaluate no-skill MVAgent on
CVBench (997 available questions), MVU-Eval (1,824), and CrossVid Lite2500 (2,500),
using the historical question IDs: 5,321 questions and 239 CCQA judgments in total.
CrossVid here means Lite2500, not the complete 9,015-question dataset.

Configuration preparation is complete. Download, GPU startup, inference and scoring
have **not** started: the existing remote Modal account returns `Token not found`.
There are no new measured results. Restore that account before submitting jobs.

## Model and execution

- [Official model](https://huggingface.co/Qwen/Qwen3.8-27B), revision
  `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`.
- Hub metadata reports 18 safetensors files totaling 55,563,006,776 bytes (55.56 GB).
  Download to the remote weights volume as `/weights/Qwen3.8-27B`.
- [Official configuration](https://huggingface.co/Qwen/Qwen3.8-27B/blob/1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0/config.json)
  declares `model_type: qwen3_5` and `Qwen3_5ForConditionalGeneration`. Reuse the
  existing `qwen35-bf16-flashinfer-sync` implementation initially; the profile name
  identifies its execution settings. Qwen3.8 compatibility with the pinned runtime
  still requires a real smoke test. Its config names Transformers `5.8.0.dev0`,
  whereas the existing profile pins `4.57.6`; do not infer compatibility from the
  architecture name or silently change the validated dependency versions.
- Actor configuration: `configs/inference/qwen38_27b_no_skill.yaml`.
  Execution: `configs/inference/execution/h100x8_qwen38_27b.yaml`.
- BF16, one complete model per H100, TP1, one in-flight request per replica,
  question-sticky routing, seed 0, temperature 0, thinking disabled, 2,048 output
  tokens, and five steps per role. Both skill libraries are disabled.
- Keep the existing runtime, prompts, media processing and official scoring.
  Qwen3.8's official default enables thinking; the explicit configuration above
  disables it for comparison with the existing no-skill MVAgent runs.

For 16 H100 GPUs, use two independent eight-GPU nodes with disjoint exact-ID lists
and separate outputs. The union must equal the original 5,321-ID panel. Do not run
the complete panel twice or change each replica to TP8/TP16.

## Time estimate

Historical Qwen3.5-27B MVAgent measurements are approximately 102–122 seconds per
question ([experiment log](experiments.md)); these are proxy measurements, not
Qwen3.8 throughput. Using `5,321 * seconds_per_question / GPUs / 3,600` gives:

| Allocation | Ideal Actor inference | Planning budget including startup, scoring and tail |
|---|---:|---:|
| 8 H100 | 18.8–22.5 hours | 22–28 hours |
| 16 H100 | 9.4–11.3 hours | 12–16 hours |

These are estimates for one pass with the existing media available. Resource queues,
authorization repair and an incompatible inference environment are outside the
budget. The planning range allows roughly 0.5–1 hour for downloading and loading,
0.5–1 hour for Judge/finalization, and scheduling/media/tail variation; download
bandwidth and Qwen3.8's actual action/token counts have not been measured. Judge
can reuse the Actor GPUs after Actor inference finishes.

After authorization is restored, download the pinned revision and verify its index
and shard sizes on the remote CPU. Then run the existing evaluation entry on a
small exact-ID panel covering all three benchmarks and CCQA. This resolves the
observed version mismatch risk before the full evaluation. Use the first completed
stratified batch to replace this proxy estimate; do not wait for a large diagnostic
matrix before starting the requested measurements.

## Evaluation entry

Run inside the remote GPU container after successful model/identity verification.
`panel.json` must be the historical full panel or one disjoint node partition;
it is a JSON array of exact IDs, not a newly sampled split.

```bash
PYTHONPATH=src python eval/agent_eval/run.py \
  --config configs/inference/qwen38_27b_no_skill.yaml \
  --execution-config configs/inference/execution/h100x8_qwen38_27b.yaml \
  --dataset-root /assets --benchmarks cvbench mvu_eval crossvid \
  --sample-ids-file /runs/qwen38-27b/panel.json \
  --defer-open-qa-judge --output /runs/qwen38-27b/node0
```

Then use the existing CCQA Judge and finalization commands in
[`eval/agent_eval/README.md`](../eval/agent_eval/README.md).
Preserve raw answers before scoring, and report missing results and infrastructure
failures separately from answer-format errors. Store results on the remote runs
volume; source/configuration backup does not establish experiment completion.
