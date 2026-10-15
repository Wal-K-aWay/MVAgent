# Vendored official benchmark evaluation sources

Current official-API pricing and the 5324-question cost estimate are documented in
[`API_COSTS.md`](API_COSTS.md).

These files are tracked directly by the MVAgent repository. They are reduced snapshots
of the official repositories, not nested Git repositories.

| Benchmark | Official repository | Imported commit | Retained scope |
|---|---|---|---|
| CVBench | `https://github.com/Hokhim2/CVBench` | `f8dc8f752fb8e7a3a05ac90e9ff9b3a9e90d79ed` | CVBench/MVR evaluation data and prompts, Video-R1 evaluation entry, lmms-eval runtime, MVR task, Qwen2.5-VL/OpenAI-compatible adapters, and required cue images |
| MVU-Eval | `https://github.com/NJU-LINK/MVU-Eval` | `a5937adea78e9649af53cd9a4e30a91ed7fd3df2` | `inference/`, root README files, and license |
| CrossVid | `https://github.com/chuntianli666/CrossVid` | `b53ada63551f9ac4a726b381b627d17ece066281` | `eval/`, root README, and license |

Omitted content includes documentation images, CrossVid QA-generation utilities,
CVBench training code/configurations, saved evaluation results, unrelated lmms-eval
tasks and model adapters, examples, documentation, and developer tools. CVBench's
lmms-eval model registry is reduced to the two retained adapters. Dataset media remains external
under `/home/kww/datasets/Multi-Video/`.

Do not describe the reduced directory itself as a complete clone. Report the MVAgent
commit and the imported upstream commit when publishing benchmark results.

## Official multimodal API adapter

`api/run.py` is the tracked official-API adapter for all three snapshots. It defaults
to a 512-video-frame question cap and a 720-pixel longest edge. Provider profiles and
credentials are centralized in `api/client.py`; benchmark prompts and scorers remain
in their official snapshots. See `api/README.md` for the supported models, current
ordered-image transport, commands, cache behavior and explicit native-video/Batch
boundary.
