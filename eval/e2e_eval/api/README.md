# Official multimodal API benchmark adapter

This directory owns remote model transport for all three vendored benchmarks. The
benchmark directories retain upstream prompts, preprocessing and scorers; provider
code is intentionally not copied into each snapshot.

## Supported official profiles

| `--model` | Official endpoint | Credential variable |
|---|---|---|
| `qwen3.8-flash` | Alibaba Cloud Model Studio | `DASHSCOPE_API_KEY` |
| `mimo-v2.6-flash` | Xiaomi MiMo | `MIMO_API_KEY` |
| `glm-5.3-flash` | Z.ai | `ZAI_API_KEY` |
| `MiniMax-M3` | MiniMax China | `MINIMAX_API_KEY` |
| `deepseek-flash` | DeepSeek | `DEEPSEEK_API_KEY` |

Keys are read only from the environment and are never written to manifests.
The profiles explicitly disable thinking for Qwen, MiMo, MiniMax M3 and DeepSeek.
GLM-5.3-Flash cannot disable thinking, so its profile requests the lowest supported
reasoning effort (`low`). These controls and the provider-specific output-token field
are recorded in `run_manifest.json`. GLM also enforces a 512-token minimum output budget:
a real 512-frame preflight showed that the local E2E 16/64-token limits can be consumed
entirely by its mandatory reasoning before a final answer is emitted.

Each platform owns one invocation script under `providers/`:

| Platform | Script | Owns |
|---|---|---|
| Alibaba Cloud | `providers/qwen.py` | endpoint, thinking control and temporary OSS frame-list transport |
| Xiaomi | `providers/mimo.py` | endpoint, credential name, token field and thinking control |
| Z.ai | `providers/glm.py` | endpoint, credential name, lowest reasoning effort and output floor |
| MiniMax | `providers/minimax.py` | endpoint, credential name, token field and thinking control |
| DeepSeek | `providers/deepseek.py` | endpoint, thinking control and Files API overflow transport |

`client.py` only owns shared HTTP execution and response metadata. `run.py` only owns
benchmark orchestration. The selected provider script is hashed into every manifest.

## Current protocol

The runner reuses the existing model-independent media cache and preserves the exact
ordered JPEG frames. Defaults are 512 total video frames per question and a 720-pixel
longest edge. Qwen's endpoint rejects more than 250 inline data URIs, so larger inputs
are uploaded to DashScope's temporary OSS and sent as ordered `video` frame lists.
DeepSeek's 48 MiB body limit is handled by retaining at most 24 MiB inline and replacing
only the overflow frames with one-hour official Files API references. Other providers
receive ordinary ordered image parts. CrossVid calls the retained official task
`evaluate()` functions, so its bbox, frame, video-ID, range and scoring logic remains
in the upstream snapshot.

Compatibility with the retained local-vLLM E2E protocol is explicit:

| Benchmark | Prompt, roles, video order and frame order | Final request-part format |
|---|---|---|
| CVBench | Identical; it calls the same `cv_messages()` builder | The local-only JPEG sequence is expanded without reordering; Qwen uses ordered temporary-OSS frame lists, DeepSeek may use Files references, and other providers use `image_url` parts |
| MVU-Eval | Identical; it calls the same `mvu_messages()` builder | Identical ordered `image_url` parts |
| CrossVid | Identical; it calls the same official task modules and `evaluate()` functions | Identical interleaved text and `image_url` parts |

Thus CVBench is content- and order-equivalent but not byte-for-byte JSON-equivalent at
the transport envelope. Claiming literal format identity there would be incorrect.
The retained 35B E2E runner snapshot is byte-identical to the current shared runner;
the ten CrossVid task files and its video/range/bbox preprocessors also match that run.

All enabled transports carry the same sampled JPEGs; none uploads or asks the provider
to decode the source video. Native-video and asynchronous Batch APIs are
provider-specific and are deliberately not emulated through an unverified common
request shape. Add either only after a paid preflight proves the exact official
request, usage and result-mapping contract.
Consequently, the discounted estimates in `API_COSTS.md` are planning estimates for
that future target protocol, not a bill forecast for the current real-time multi-image
runner.

## Run

One retained smoke result from each selected dataset/task:

```bash
export DASHSCOPE_API_KEY='...'
/home/kww/miniconda3/envs/MVAgent/bin/python eval/e2e_eval/api/run.py \
  --model qwen3.8-flash \
  --frames 512 \
  --max-side 720 \
  --workers 1 \
  --limit 1 \
  --output outputs/e2e/api/qwen3_8_flash_smoke
```

Full selected run:

```bash
/home/kww/miniconda3/envs/MVAgent/bin/python eval/e2e_eval/api/run.py \
  --model mimo-v2.6-flash \
  --benchmarks cvbench,mvu-eval,crossvid \
  --frames 512 --max-side 720 --workers 1 \
  --output outputs/e2e/api/mimo_v2_6_flash
```

Useful options:

- `--benchmarks cvbench,mvu-eval` selects benchmark families.
- `--crossvid-tasks MOC,MSR,FSA,PSS` selects CrossVid tasks.
- `--base-url` and `--api-key-env` are explicit overrides for regional official
  endpoints; they are not intended for silent third-party routing.
- `--no-media-cache` disables the shared `.cache/e2e_media` frame cache.

Results use the same benchmark layout as local E2E runs:
`cvbench/raw/cvbench_predictions.jsonl`,
`mvu_eval/raw/mvu_eval_predictions.jsonl`, and
`crossvid/raw/<TASK>_result.json`, with per-benchmark `summary.json` files.
`run_manifest.json` pins the model, official base URL, credential-variable name,
sampling policy, Git state and adapter hashes. Provider response IDs, usage, finish
reasons and transport timings are additive fields on the shared local record schema.
CCQA still
requires the retained official Judge pass. Pricing and the intended future
native-video/Batch protocol are documented in [`../API_COSTS.md`](../API_COSTS.md).
