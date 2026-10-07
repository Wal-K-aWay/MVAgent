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


`client.py` only owns shared HTTP execution and response metadata. Benchmark orchestration
is the unified harness (`../run.py`, `APIBackend` in `../harness/backends.py`), so API
runs use exactly the same official prompts, message order, sampled frames and scoring as
local vLLM runs. The selected provider configuration is recorded in `manifest.json`.

## Transport

All providers receive the same sampled JPEG frames; none uploads or asks the provider to
decode a source video. All three benchmarks send ordered `image_url` parts, exactly as
for the vLLM backend. Qwen's endpoint rejects more
than 250 inline data URIs, so larger inputs are uploaded to DashScope's temporary OSS and
sent as ordered `video` frame lists. DeepSeek's 48 MiB body limit is handled by keeping at
most 24 MiB inline and replacing only the overflow frames with one-hour Files API
references. Other providers receive ordinary ordered image parts.

Native-video and asynchronous Batch APIs are provider-specific and are deliberately not
emulated. Add either only after a paid preflight proves the exact official request, usage
and result-mapping contract. The discounted estimates in `../API_COSTS.md` are planning
estimates for that future protocol, not a bill forecast for the current real-time runner.

## Run

```bash
export DASHSCOPE_API_KEY=...   # the variable named by the profile; never written to disk
python eval/e2e_eval/run.py infer --api-model qwen3.8-flash --limit 1 --output OUT
python eval/e2e_eval/run.py score --output OUT
```

`--api-base-url` and `--api-key-env` override a profile's regional endpoint or variable
name; they are not intended for silent third-party routing. All other options, the output
layout and the CCQA judge are those of `../README.md`.
