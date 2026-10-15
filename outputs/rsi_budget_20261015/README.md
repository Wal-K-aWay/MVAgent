# Video-RSI 视觉描述预算对照（2026-10-15）

用户已决定将默认视觉描述上限改成 2048 token；规划器仍为 8192 token。本次比较旧视觉上限 8192 与新上限 2048。

面板共 66 题：CrossVid 20、CVBench 30、MVU-Eval 16，每个原生任务两题。保留原有 33 题，再按 seed=0 每类新增一题；属于开发样本，不是独立 Test。每题两组各跑一次，共 132 条轨迹。同题固定同卡，先后顺序交替，8 卡动态领取整对题目。

两组均用当前原尺寸、原帧时间拼接和已经验证的并行抽帧；输入问题、帧限制、11 步预算与技能库相同。Actor 为 Qwen3.5-35B-A3B，8×H100、独立 TP1/C1、BF16、seed=0、temperature=0、thinking/prefix cache 关闭。开放问答采用固定 Qwen3-30B-A3B-Instruct-2507 Judge；相同 Judge 输入共享缓存。

官方逐题评分和分层聚合：CrossVid 十类 macro（CCQA 按评分点加权），CVBench/MVU 按全集任务占比估计；另外报告面板原始均分、答案变化、升降题数、成功/失败覆盖。耗时报告同题配对时间、模型服务耗时、输出 token、截断与无效视觉观察。调度方案使用实测耗时进行模拟，模拟收益与真实测量分开标注。

运行目录：Modal runs volume `devbox/rsi_budget_20261015/`。冻结源码、私有标签、拼接视频、原始请求/token、逐题结果与评分留在该 volume。独立 GPU sandbox：`sb-2hPetsLlITj6IAaVwoHP0R`，`DEVBOX_NAME=mvagent-rsi-budget-20261015`。

当前为准备/提交阶段，尚无本次准确率或耗时结论。代码入口为 `eval/external_methods/experiments/20261015/rsi_budget_{panel,run,analysis}.py`。正式运行与评分结束后补充实测结果；小样本不支持宣称准确率无损。
