# AgentCVR 公开8B适配评测：最终结果

完成时间：2026-10-16 20:21:53 UTC / 北京时间2026-10-17 04:21:53。最终恢复批次完成2821/2821题，8张H100已退出释放。

| Benchmark | 正确 / 评测题数 | 官方准确率 | 整题基础设施失败 | 未终答（计0） |
|---|---:|---:|---:|---:|
| CVBench | 567 / 997 | **56.87%** | 0 | 0 |
| MVU-Eval | 803 / 1824 | **44.02%** | 0 | 1 |

CVBench官方共1000题，其中64–66的已知损坏媒体继续排除；不能称完整1000题成绩。MVU-Eval全部1824题均进入分母，包括一题正常未终答的负结果。CVBench使用官方正则评分，MVU使用官方首字符规则，按题平均；未使用Judge。

唯一未终答题为`mvu_eval:RAG:873`：10次模型调用、6次工具调用，末尾三次生成均触及输出上限并重复推理，最终返回`Error: Loop ended unexpectedly.`。这是模型未交付答案的负结果，保留原轨迹并按0计入，不以重复测到正确为目标重跑。

## 方法口径

这是**作者公开权重及代码默认参数的跨benchmark适配基线**，不是已证明的论文原设置复现。Master为作者`xiaohua616/qwen8b_crossvidRL`（实际Qwen3-8B纯文本），视觉为Qwen3-VL-8B-Thinking，音频Whisper large-v3启用；与仅视觉方法比较时必须披露音频权限。

采用CVBench/MVU官方题面文本、选项和指令顺序；Agent System沿用已披露的CC模板适配。temperature=0.5、每次最多8192输出token、20轮、最长边360、seed=0，8×H100独立TP1执行。论文与公开版本的模型身份、温度及长度表述存在差异，详见[设置核对](official_settings_audit.md)。未取得训练集，不能证明完全无数据污染。

生产冻结代码53a04a4；恢复时只降低Master显存预留，为视觉峰值留空间，并把作者工具错误对象封装为合法OpenAI文本消息。185条正常H100结果经SHA核验继承，其余在恢复批次完成。旧失败记录、320帧OOM及恢复回归原件保留；H200的124条历史结果没有混入本成绩。

## 最终CPU审计

2821条记录全部通过检查：ID覆盖与去重、原始回答和记录SHA256、185条继承结果hash、冻结源码/配置hash、官方题面重建、逐题官方评分与汇总、每次Master请求中的题面及System、推理参数、完整输入/输出token数组长度均一致。

最终轨迹包含21,259次模型调用（Master16,808、Vision4,451），0 HTTP/传输错误，0 token长度不匹配；21,041次正常停止、218次输出触顶。输出触顶不等于整题失败，大部分题目随后仍终答；唯一未终答题如上。现有格式诊断标记CV 2题、MVU 29题不符合格式，主成绩仍按官方规则，没有替换为宽松解析分。

CPU app `ap-13Z2ymvJj76rJg64gfPZXO`正常完成且容器列表为空，`final_audit.json`已从外部Volume核验`phase=passed`。仅离线读取/复算，没有新增模型或Judge调用。

## 耗时与留档

逐题累计时间为CVBench86,661.87秒（均值86.92秒），MVU221,577.67秒（均值121.48秒）。这些是并行题目的耗时之和，不是墙钟时长或账单金额；不包含失败启动、未落盘中断及重复回归的全部成本。

全部原始数据仍在Modal runs volume `wxu-evolve-agent-runs-20261006`，最终目录`devbox/agentcvr_eval_h100_20261016_r2/`：

- `manifest.json`、`frozen_source.tar.gz`：源码、模型和运行配置。
- `items.json`、`private_labels.json`：官方输入与隔离标签。
- `raw/`、`records/`：完整轨迹、响应及token/输入hash，逐题完成记录。
- `scores.json`、`progress.json`：最终官方评分及completed状态。
- `recovery_manifest.json`、`recovery_audit.json`：继承来源与恢复验证。
- `final_audit.json`：最终2821条核验、分题型统计、调用/截断/格式诊断及关键文件SHA。

本地只保存源码和Markdown报告，未迁出原始结果、媒体或权重。
