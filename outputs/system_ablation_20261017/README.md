# Global简洁System与Video通用要求：隔离对照

2026-10-17，用户先授权冻结代码，再测试两个提示候选，目标约两小时取得开发面板结果。

共享工作区快照已推送 `codex/current-code-freeze-20261017`，`d56579030c7f400a2379d822cd976986d136e9ca`，恢复说明在该分支 `docs/frozen_evaluation_20261017.md`。本实验从已完成4500条直接回答分支 `1b711bf` 派生，保留已验收的极短视频采样修复。主工作区不热更新，其他实验不改动。

| 对照臂 | Global | Video |
|---|---|---|
| baseline | 已测通用System | 已测System；复用4500条中的同题结果及评分 |
| global_short | 仅替换为PRO6000的简短角色/证据边界System | 不变 |
| video_rules | 保留baseline Global System | 普通Planner System增加任务定义传递、具体证据与不确定性保留、简洁但完整；显式写入当前video_id |

Video没有新增完整原题、其他视频报告或内部跨角色轨迹。加入完整原题会改变既有信息边界，此轮先检验在现有局部instruction下能否改善。video_id以前存在于对象/日志和视觉请求，普通Planner User没有显式身份行；此臂仅在其System显示已有身份。步数耗尽的Video终止性总结沿用原来的空System，不能声称该调用也接受新规则。Video臂合并了通用要求与身份显示，若有效再拆分其贡献。

Video新增文字：

> Preserve the active instruction's definitions and distinctions in each observation request. Report the concrete observed evidence needed to resolve that instruction, retaining relevant identities, quantities, relations, and uncertainty. Keep explanations concise without omitting required information. Use only evidence from your assigned video; do not infer facts about other videos or select the global answer.

三模型使用相同102题：CV30、MVU30、Cross42（九闭式任务各3题，CCQA15题）；每个候选306次完整Agent，两个候选共612次新推理，另复用306基线。选择seed0，不按得分筛题；这是反复使用的开发池，不是独立Test，也不是scope优化器的Train/Gate流程。小面板只作筛选，不证明九格稳定提升。

固定H100/BF16、8独立TP1/C1、seed0/temperature0、FlashInfer/native norm、prefix/MM cache关闭、2048token、512帧、Global/Video各5步、直接answer与answer_only收尾。User、schema、接口与正式评分不改。两个独立8卡Sandbox各负责一个候选，三模型依次加载，模型切换使用独立端口避免残留租约。CCQA使用同一固定本地Judge，失败单列，不记零。

预留加载、Judge与汇总时间，使用历史同题耗时估计预算，实际可能受GPU排队和长尾影响。控制器有墙钟上限；到时报告实际有效样本及缺失，不把未完成写成完成。源码存单个不可变tar归档，实际每模型source_snapshot及服务身份保留，结果只在Modal runs `devbox/system_ablation_20261017`。完成后释放本实验GPU。

验收报告逐模型×benchmark的官方分、对当前baseline及E2E同题差值、格式/空答案/右花括号、翻转数、调用与耗时；Cross报十task macro，CCQA按点评分。保留负结果。改变提示后答案可以变化，固定数值配置已验收的重复性不重新做双遍矩阵。

状态：准备中，尚无本轮模型结果。
