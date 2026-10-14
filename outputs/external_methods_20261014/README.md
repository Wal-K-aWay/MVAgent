# 外部视频 Agent 多视频小批评测

2026-10-14，北京时间。用户确认使用本地 Qwen3.5-35B-A3B，先跑 Video-RSI、MetaVideoAgent、Visual-Agentic-Memory（VAM）× CrossVid、CVBench、MVU-Eval 九个组合；Meta 由本地 Qwen 生成初始 agent，不做进化。

## 后台运行（12:49 状态；12:48 起按用户要求停止持续监控）

九个组合均已有真实端到端输出。每个方法使用相同的 33 道开发题：CrossVid 10、CVBench 15、MVU-Eval 8，每个原生 task 一题，抽样 seed=0。

| 方法 | 已完成尝试 | 有效终答 | 当前阶段 |
|---|---:|---:|---|
| Video-RSI | 33/33 | 32 | 等 CCQA Judge；PSS341 决策 JSON 失败 |
| MetaVideoAgent 初始 agent | 10/33 | 10 | 其余 23 题运行 |
| VAM | 27/33 | 23 | 其余 6 题运行；MSR361、PSS341、CVBench689/274 失败 |

Video-RSI 的 CVBench 15/15 有效、按全集 task 数量加权的小样本估计为 **52.20%**；MVU-Eval 8/8 有效、加权估计 **40.30%**。CrossVid 仍待 CCQA Judge，且 PSS 缺失，不能报告完整十任务 macro。这些数字不等于完整 benchmark 成绩，样本很少，不用于给方法排名。

## 来源、模型与输入

| 上游 | 固定 commit |
|---|---|
| [Video-RSI](https://github.com/bingjunluo/Video-RSI) | `5ad014499a5e009b75e3ef05ac83595b78adda09` |
| [MetaVideoAgent](https://github.com/Alibaba-VELLDEPTH/MetaVideoAgent) | `c4c1279dca07c5dd7b1a28a2121dd5d27c5c1a70` |
| [Visual-Agentic-Memory](https://github.com/yiliu-li/Visual-Agentic-Memory) | `4f759407945674e0b296ecee22bd53cf910ae39b` |

前两仓库为浅克隆；VAM 的 Git TLS 重试失败后通过 GitHub API 取得同一固定 commit 的源码归档。来源记录见 `eval/external_methods/sources.json`。

- 用户明确采用 **v2 / prefix cache 关闭**，覆盖会话开始时的 v3 约定。Actor：35B-A3B、BF16、seed=0、temperature=0、thinking 关闭、单卡 TP1/DP1/并发1、整题固定副本。
- 独立 Modal 8×H100；启动时核验 8 个实际 v2 服务 manifest。随后 GPU7 改作 VAM 原始 Qwen3-VL-Embedding-8B（HF revision `2c4565515e0f265c6511776e7193b22c0968ddc7`），其余七卡分配 Actor。
- 多视频按原顺序拼接，448×448 留边、30fps、无音频。Prompt 列出原视频编号与实测编码起止时间；问题和最终答案的时间仍以题目指定的原视频为准。单题拼接长度 7.03–1680.6 秒。
- CrossVid 从现有 Lite2500 选题；CVBench 先排除已知损坏的 64–66 三题。三个方法共用输入，标签单独保存，仅离线评分可读取。
- Meta 原始 `result.json` 中 `gt_answer` 为空，所派生的 `is_correct=false` **不是成绩**。正式成绩只来自独立 `scores.json`；首题标签映射已在 `score_protocol_audit.json` 核实。

## 方法保留部分与适配差异

**Video-RSI** 使用发布的 `artifacts/final_harness`，11 步、256 总帧曝光、每次模型调用 8192 输出 token；语言和视觉角色均换成本地 35B。上游仅支持单选字母的答案边界放宽为非空字符串，以接受多选、排序、时间段和开放回答。Modal 不支持 Landlock，保留候选 seccomp 与外层 Modal 隔离；不声称复现上游完整文件系统隔离。

**MetaVideoAgent** 使用上游三条无标签视频概况、代码生成上下文、五模块 ABI、注入与执行器。本地 Qwen 生成初始 bundle，并按实际接口错误修复；无标签、无正确率反馈、无演化轮次。三条 profile 输入也在本开发面板内，不能称为独立测试。LLM/VLM/OCR 使用本地 Qwen，ASR/embedding 在此无音频初始配置中声明不可用。有效输出还必须通过上游行为检查。早期三个硬编码 A 的伪成功已排除。

**VAM** 保留原始 0.5fps、适应性帧过滤、视觉 embedding、层级记忆、事件归纳和检索。更换模型传输层、修复跨文件系统临时视频 rename，以及上游漏写的 `import re`。Embedding 图像先解为 PIL，拒绝缺失视觉张量和批量长度变化，防止官方工具静默回退成 NULL 文本 embedding。保留 planner 原始 500-token 预算，截断解析失败照实记录。其原生 `video_url` 输入沿用服务端媒体处理，未声称与项目 E2E 图片帧协议一致。

## 结果保存与复核

所有媒体、权重、冻结源码、请求/响应、轨迹、评分与失败记录均在 Modal runs volume `wxu-evolve-agent-runs-20261006` 的 `devbox/external_methods_20261014/`。本机只保留代码和 Markdown 报告。

| 内容 | runs 根下路径 |
|---|---|
| 输入、标签、抽样及数据来源 | `items.json`、`items/`、`media/*/timeline.json`、`private_labels.json`、`selection.json`、`data_provenance.json` |
| RSI 接受协议 | `r4/frozen_repo`；`rsi_smoke` + `rsi_remaining` → `rsi_combined` |
| VAM 接受协议 | `r7/frozen_repo`；`vam_smoke_r4` + `vam_remaining` → `vam_combined` |
| Meta 接受协议 | `r9/frozen_repo`；`meta_repair_r3/bundle.json`；`meta_one_r3` + `meta_two_r3` + `meta_early_run` + `meta_rest_run` → `meta_combined` |
| Embedding 修复与自检 | `r5/frozen_repo`、`embedding_r2/self_check.json` |
| 模型服务身份与调用审计 | 各批 `service_cards.json`、各题 `requests.jsonl` |
| Meta 标签隔离核对 | `score_protocol_audit.json` |
| 跨卡调用复核 | `repeat/comparison.json` |

冻结目录保留项目原 commit、工作区源码/配置 SHA256、上游 commit 和补丁。RSI、VAM、Meta 分别在上述冻结源码执行；同一方法的扩展批次不改变已接受协议。

项目基础 commit 为 `4eb309ba973856ac4ae4b2dcb067535d143bdac7`，另有工作区改动，精确身份以冻结 manifest 为准：R4 `c62db03662c92451c2094b7cb5e5c412951df65af32d14bdbe39d94a30900c1f`；R7 `bb72c69ba8a5781fb9277c22e9dae00494fdc9a9efb59abe3a693614df074f88`；R9 `3afa6614de577f0f287bf58a1dc99e3dada50a3df2f471205039fa4a0ef43287`。采用的 Meta bundle SHA256 为 `0ada5ec7859f15dac7226f6e35151e3b47940d4304b4e01ca457efb0ea5f180f`。

实际依赖另存 `runtime_versions.json`：vLLM 0.19.1、torch 2.10.0、transformers 4.57.6、qwen-vl-utils 0.0.14、NumPy 2.2.6；新增依赖只装在 Modal 的 `support/deps`，未修改本机环境。

远端完整语法检查及适配器契约测试通过。新 HTTP 调用路径做了 1 条文本 + 1 条视觉跨卡重放：2/2 输入哈希、prompt token 哈希和完整输出 token 一致。这只是有限样本复核，不证明任意输入或 VAM 原生视频解码的确定性。

## 保留的负结果

- 前两次 GPU 启动被 watchdog 的初始时间戳误判闲置，均 0 推理。改为单调时钟且仅按心跳 mtime 变化刷新后，远端小测试与真实启动通过。两实例已释放。
- Meta 初始 bundle 曾发生 memory 字符串/字典 ABI 错误；第一次修复虽返回三个 A，但工具全部失败、没有真实回答 LLM，故三个结果均无效。后续修复过程只使用无标签工程错误；原文件保留在 `meta_smoke*` 与 `meta_repair*`。
- VAM 早期暴露 data URI/NULL embedding、跨卷 rename、错误终态识别和缺失 re 导入；失败批次保留，最终采用 R7。
- RSI FSA386 回答 `517,533` 超出题目目标原视频长度；即使事后减去拼接偏移，仍与标注无重叠。保留官方零分，不替模型改答案。

## 下一项可执行工作

收尾任务 `external_methods_20261014_finalize`（PID8563，runs 根 `finalize.py`）已启动：等 VAM 全部完成后复用 GPU4 启动固定本地 Qwen3-30B-A3B-Instruct-2507 Judge，先评分 RSI/VAM，再等 Meta 完成评分；写出 `final_summary.json`。按用户后续要求，主对话和独立检查代理均不再持续监控。modal-gpu 上已启动一次性结束处理器 `external_methods_autoclose_20261014.py`（PID1712766，已脱离SSH会话）：等待现有推理与收尾任务退出，归档服务日志，写入 `completion.json`，从 volume 外读取并校验汇总/评分 SHA256 后仅释放本任务 Sandbox，不停止共享 app。如果收尾失败，会保留失败状态和日志；Sandbox 另有既有6小时最大寿命。没有重跑整个 benchmark，也没有复现三个方法的论文训练/演化流程。

以12:49的实际队列与吞吐估计：VAM剩约10–20分钟，Meta约60–90分钟，Judge启动评分约5–10分钟、可重叠；整体约1–1.5小时，保守留2小时。此本地Markdown不会随后台结果自动更新；最终数据以runs根的final_summary.json和completion.json为准。
