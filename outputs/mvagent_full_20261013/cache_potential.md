# MVAgent 请求前缀复用分析（2026-10-14，北京时间）

本次只读现有结果并在 Modal 上进行 CPU 分词，不新增推理、不修改运行中的冻结 固定配置 或本地运行时代码。

## 请求结构

- Global 决策每轮重新生成 system + user。user 顺序为问题、视频元信息、History、动作说明、规则和策略。
  History 按事件追加，但位于其后的固定规则不是可独立命中的前缀；正常决策 reason 不在公开 History 中原样回放。
- Video Planner 同样重建 system + user，同一 instruction 内 Memory 累积。
  新 instruction 以及 Current request/Request N 的重新渲染会提前造成前缀分歧。
- Global 终答使用独立 system 与模板；与本题决策的长 History 不能直接共享 KV 前缀。
- 视觉请求顺序为视频标记、视频内容、观察指令，不附完整决策 History。
  改变片段、采样或帧内容会影响多模态前缀；同源视频不等于相同多模态输入。

源码：`src/models/utils.py:build_chat_messages`、Global/Video 的 `prompts.py` 与 `memory.py`、
`src/models/vlm/api/client.py:query_videos`。

## 一个实际长轨迹的 token 前缀上限

样例：9B，`crossvid:BU:63`。这是用于展示机制的单个长轨迹，不是随机代表性样本。
原始轨迹保留于 runs volume `devbox/mvagent_full_20261013/9B/records/crossvid/crossvid:BU:63/result.json`。
计算结果：同根目录 `analysis/prefix_potential_example.json`，37 个纯文本请求的逐请求结果。

对保存的 messages 使用原 `/weights/Qwen3.5-9B` tokenizer/chat template，thinking=false。
37 个文本请求重建的完整 prompt token 数量及 SHA256 均与服务实际记录相同。
逐请求取与本轨迹之前已完成文本请求（含已生成输出）的最长公共 token 前缀，除以当前 prompt token 数。
假设题目开始时缓存为空、缓存容量无限、不淘汰；忽略块对齐和 GDN 状态检查点限制。
这是该条件下的逻辑 token 前缀上限，不是实际启用 APC 后的缓存命中率；未计跨题预热和视觉请求复用。

| 请求 | 输入 token | 最长公共前缀 token | 前缀比例 |
|---|---:|---:|---:|
| Global 决策 1 | 1756 | 0 | 0% |
| Global 决策 2 | 2112 | 434 | 20.55% |
| Global 决策 3 | 2176 | 794 | 36.49% |
| Global 决策 4 | 2240 | 858 | 38.30% |
| Global 决策 5 | 2304 | 922 | 40.02% |
| Video 2 / request 1 / step 2 | 618 | 132 | 21.36% |
| Video 2 / request 1 / step 5 | 831 | 348 | 41.88% |
| Video 2 / request 5 / step 5 | 2371 | 1888 | 79.63% |
| Global 独立终答 | 1179 | 4 | 0.34% |

Global 决策 1→2 只匹配到 History 的起点；决策 2→3 可以包含旧事件，但不能跨过新增事件继续命中尾部规则。
本例决策 3 的 2176 token 中，只有 794 token 处于共享前缀，而不是上一请求全部 2112 token 都可复用。
终答仅有 4 token 模板开头相同，通常不足一个可缓存块。

## 实际指标及限制

实际每请求命中率 = `usage.prompt_tokens_details.cached_tokens / usage.prompt_tokens`。
整体 token 命中率应以 `sum(cached_tokens) / sum(prompt_tokens)` 计算，不能直接平均请求百分比。

vLLM 按完整块缓存，缓存键包含父前缀与多模态哈希；混合模型还受状态缓存边界约束。
因此以上比例不能直接当作实际命中率，不能假定统一块大小为16，也不能从前缀命中比例直接推算端到端提速。
当前全量任务冻结 固定配置 的跨请求 prefix cache 关闭；这些数据用于分析 开启 prefix cache 的实验配置 的复用潜力，未测 开启 prefix cache 的实验配置 的实际命中或数值一致性。

参考：[vLLM 0.19.1 Prefix caching](https://docs.vllm.ai/en/v0.19.1/design/prefix_caching/)、
[Hybrid KV cache manager](https://docs.vllm.ai/en/v0.19.1/design/hybrid_kv_cache_manager/)。
