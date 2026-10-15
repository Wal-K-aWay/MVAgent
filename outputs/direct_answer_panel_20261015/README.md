# 当前直接回答与历史独立回答器：完整MVAgent小样本对照

2026-10-15。用户要求三模型、三个benchmark小规模完整Agent测试，比较格式错误、空答案与同题准确率，不影响正在运行的全量任务。

## 协议

- 当前源码运行完整MVAgent，每题一遍；Global直接在decision.parameters.answer提交，全部取证路径由当前Agent自然选择。保留seed0、temperature0、BF16、每卡TP1/DP1/C1、FlashInfer GDN、原生GemmaRMSNorm、关闭prefix/MM cache、2048输出token、512帧及Global/Video各5步。
- 在独立8×H100 Sandbox依次加载9B、27B、35B-A3B，使用公开eval/agent_eval/run.py入口和整题固定副本。生产全量的冻结源码、端点、结果均不变。
- 从2026-10-15已有同题分析快照的三模型已完成题交集按32个闭式原生题型各随机抽1题（seed0）：CVBench15、MVU-Eval8、CrossVid9。此随机面板三个模型共用。
- 各模型另纳入该快照中全部空答案，以及每benchmark至多2个随机非空格式失败，单独报告诊断面板。不同模型诊断补充题可不同，始终与该模型历史同题比较；不混入随机面板声称总体收益。
- CrossVid CCQA需要独立Judge，本轮不纳入；NC506参考歧义题排除。CrossVid只报九任务macro；CV/MVU同时报告样本均分与按原生题型总体题数加权分。小样本不能作为全量成绩。
- 历史完整轨迹只读复制到本实验目录，保存来源和SHA256。新旧用同一现有官方评分器重算，并与原保存分数核对；同时报告明确答案提取后的保守分数。空答案、非空格式错误、结构化失败、截断、服务错误分别计数。
- 这是完整Agent协议比较，不是固定证据的单次终答消融；新取证路径可能不同，不能把变化仅归因于某一个prompt或字段。

## 产物与进度

实验驱动：scripts/compare_direct_answer.py。所有原始选择清单、旧轨迹副本、新轨迹、输入hash/token日志、服务manifest、评分与配对结果只写Modal runs volume：devbox/direct_answer_panel_20261015。

本地只保留代码与Markdown。准备和实测结果待补，不把提交或准备完成视为实验完成。
