# Video-RSI / VAM：本地 Qwen 评测

2026-10-15 用户确认：保留通用答案适配和两方法的 448 输入限制，其余参数恢复原项目设置。多视频拼接与两位小数时间说明继续保留。MetaVideoAgent 已取消后续测试。

## 原始设置与实际设置

`sources.json` 固定上游 commit，`upstream_settings.json` 保存原始配置、关键源文件 SHA256 和 VAM 各调用点的温度/token 上限。它是原始设置的审计基准，不能替代远端实际生效证据。

| 项目 | 当前约定 |
|---|---|
| RSI 规划 / 视觉输出上限 | 均直接读取原配置的 8192 |
| RSI 步数 / 服务调用 / 帧暴露上限 | 原版 11 / 64 / 256 |
| RSI 温度 / HTTP 超时 / provider 重试 | 原版 0 / 240 秒 / 1 次重试 |
| RSI 抽帧 | 原版串行流程；只保留用户确认的宽度 448 例外 |
| VAM 输出上限 | 原调用点的 220、300、500、700 等；不注入统一 2048 fallback |
| VAM 温度 | 原调用点的 0、0.1、0.2 |
| VAM 采样、过滤、记忆、检索 | 原版流程与默认参数；视频采样默认 0.5 fps |
| VAM 图像限制 | 用户确认的 448×448 像素面积限制；其余读取原项目设置 |
| Actor | 两方法的语言/视觉角色均替换为本地 Qwen3.5-35B-A3B |
| Embedding | 本地原 Qwen3-VL-Embedding-8B；原 VAM 请求结构与批次边界，448×448 像素面积限制；实际值写入 manifest |

RSI 复用上游 `PinnedProvider.chat`，VAM 复用上游 `OpenRouterClient._chat_impl` 与 embedding 客户端。审计钩子只记录实际请求和耗时，不改其温度、预算、重试或超时。VAM embedding 请求只改为本地端点；原云服务内部默认值并不公开，本地使用官方 Qwen embedder 的默认指令，不能声称向量与云端逐位一致。

每题保存 `effective_config.json`、`service_card.json`、`requests.jsonl`、`result.json` 和 `execution.json`。模型服务另存模型/权重/数值配置与源码身份。原始输出先落盘，再由 `score.py` 调用共享官方评分协议。正常格式错误与运行故障分开报告。

`native_server.py` 是独立的外部方法入口：保留 BF16、单卡单请求、seed=0、thinking/prefix cache 关闭和原固定数值后端，但允许原方法指定非零温度，接受 RSI 的原生 `thinking=disabled` 请求字段。它使用单独的 `qwen35-bf16-external-upstream` 身份；不是既有只接受 temperature=0 的固定评测端点，不混用旧轨迹。

## 明确保留的适配

- 多视频按题目顺序拼接为一个视频，prompt 开头明确说明多视频任务及拼接方式；各视频起止时间保留两位小数，内部记录保留完整精度。题目及最终回答的时间指向原视频坐标。
- RSI 原版只接受单个选项；用户明确保留非空字符串的通用答案适配，以支持多选、排序、定位、数字和自然语言。没有改变工具策略或技能库。
- 两方法输入图像保持已确认的 448 限制；VAM 视频帧数读取原项目配置。取消额外的四路抽帧优化，不把速度实验改动混入原方法参数测试。
- 本地模型端点、Python/OCR 路径、VAM 临时文件路径按 Modal 环境调整。Modal 缺少 Landlock，RSI 保留 candidate seccomp 与外层 Sandbox，但不具备上游相同的文件系统 fence。
- VAM 的原始缺失 `re` 导入补丁保留。这些运行环境修正均列入有效配置，不能称为逐字未改的上游代码。

## 视频准备

拼接不缩放、不补边、不改 FPS。相同 H.264 或 MPEG-4 编码走 stream copy；混合/其他编码走逐片段无损 H.264 统一，像素格式不支持时直接报错。原始音频不提供给这次视觉理解评测。

2026-10-15 扩样发现，部分 H.264 视频在串流完整、PTS 正确的情况下，拼接后随机 seek 仍会用错后续片段的解码参数。当前准备器在每段的每个关键帧重复 SPS/PPS，再拼接；CVBench432 的实际失败位置及另外五个位置已解码成功。旧 `prepared_r2` 媒体不能因包数/PTS 校验通过就当作任意 seek 已验收。

每帧 PTS 仍须匹配到 2 微秒；旧 FFmpeg 的 MP4 movie 时钟导致末尾时长元数据可以有小于 1 毫秒的舍入，单独记录，不放宽帧数或 PTS 检查。混合编码或含隐藏解码预滚帧时，以同一 PyAV 解码器逐帧无损转为 H.264，再拼接；不改变显示帧、尺寸或帧时间。5 类合成输入共 353 帧及 15 个 seek 已通过像素、尺寸、格式和时间检查。NC80 的实际长视频另行修复验证，原输入的推理结果不进入最终汇总。

`prepare.py --selection <selection.json>` 保持原抽样。原始 33 题为各原生任务一题，seed=0；扩大面板原定 66，首轮因 NC808 混合编码准备超时排除该新增题后为 65（CrossVid19/CVBench30/MVU16），不补抽。开发面板不能当作独立 Test 或全量 benchmark 成绩。

## 耗时与执行

- 媒体 metadata 记录 `preprocessing_seconds`。
- `requests.jsonl` 记录每次模型请求的实际输入/输出和 HTTP 耗时；服务审计记录处理耗时与完整 token。
- `result.json` 记录 Agent 内部耗时；VAM 另记录索引与查询耗时。
- `execution.json` 记录整题墙钟；`progress.json` 记录整批墙钟、逐题均值/中位数/最大值。
- 模型启动单独计时，不混入逐题推理时间；完整评测还应单列评分时间。HTTP 请求有重叠时，不把耗时之和当作墙钟。

所有重负载经 `mvagent-environment` skill 和 `modal-gpu` dev box 放到 Modal。`freeze.py` 保存不可变源码、配置与适配补丁；`run_batch.py rsi|vam` 必须连接上述外部方法专用服务。模型与数据、原始请求和结果只保存在 runs volume；Lightsail 仅保存源码和 Markdown 报告。

此前 2048 对照 `devbox/rsi_budget_20261015_r2` 已因随机 seek 故障及错误路径进入 prompt 被标记无效并停止，未完成准确率评测；随后用户又明确恢复原项目预算。该目录与历史速度实验保留为证据，不能混入本次按原参数测试的结果。

代码备份分支为 `codex/external-methods-prompts-20261014`。共享工作区其他推理/runtime 改动不属于此分支；精确恢复实验以 Modal 冻结快照为准。
