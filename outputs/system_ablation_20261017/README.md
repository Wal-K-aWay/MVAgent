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

状态（2026-10-17 11:36 UTC）：CPU `ap-rhAeHltojgdDFBYORpgkf9` 完整compileall、13接口测试和System替换自检通过；CPU `ap-sUJ8ieXKVGv0f17PoBzzuA` 完成提交前控制器修正归档，均rc0。首版准备源码与manifest保留在 `preparation_attempts/initial`，题目清单未变。最终冻结提交 `519c6984a7a6ca4a136753b71414c890aa88ed54`，归档SHA `209cc39a79fa2a265e62d6f6b377fcb3aefbfcd16cd2e983d922c63a001f6e48`。

两个候选已申请独立8×H100：Global `sb-33cmVnrutj7rIEiCadGwU7`，Video `sb-dL95bKvQlYPNUFoldBXUTL`，开始9B加载；尚无准确率结论。host控制器PID3147193，日志 `~/wxu-evolve-agent/devbox/watch-system_ablation_20261017.log`；两候选依次9B→27B→35B→固定Judge，完成后自动释放本实验GPU并汇总。服务启动前检查实际manifest/profile/8个GPU身份，正式逐题保留输入哈希和token日志。

基于所选同题旧耗时，单臂9B/27B/35B总GPU秒为5643.52/10916.93/9082.70，按8卡加25%波动及27分钟加载/评分预留，预计约1.56小时；非保证。11:38健康检查：共享项目app有3任务（含无关任务），近5分钟Traceback为0；Global八卡已加载约19GB/卡，处于服务预热。


## 阶段结果（2026-10-17 12:23 UTC，尚未完成全矩阵）

两候选9B与27B均102/102有效、整题工程失败0；35B当前Global27/102、Video47/102落盘。尚未执行本轮CCQA Judge，不报告Cross十类总分。以下各CV/MVU单元都是同30题、按既有task人口权重估计的开发子集，不能与前4500面板的500题单元直接相减。

| 模型 | Benchmark | 当前基线 | 简洁Global | Video通用要求＋身份 | 同题E2E |
|---|---|---:|---:|---:|---:|
| 9B | CVBench | 66.60 | 74.70 | 64.00 | 70.30 |
| 9B | MVU | 34.49 | 50.96 | 37.49 | 29.98 |
| 27B | CVBench | 77.55 | 78.40 | 79.85 | 70.85 |
| 27B | MVU | 57.90 | 54.02 | 57.57 | 36.44 |

每模型87道闭式题：9B基线格式失败2，Global2，Video1；27B基线0，Global0，Video1。四个新模型/候选单元均空答案0、仅右花括号0。9B基线两个格式失败均在MVU，因此Global的CV增益发生在两边格式都合格的题上；Global的格式失败总数虽持平，失败题已变成PEA784和Counting127，不能声称原合格题全部保持合格。Video的9B新失败为CV774，27B为FSA2115（No equivalent step found）。

闭式翻转：9B Global CV5胜3负、MVU6胜1负；Video CV0胜1负、MVU1胜0负。27B Global CV2胜2负、MVU1胜2负；Video CV1胜0负、MVU1胜1负。权重不同，翻转个数不能直接当官方百分点。

案例保存在Global/9B/closed_cases.json并核对基线原件SHA：CV154从C错到D对，两版都3调用，候选区分场地中的标牌与教学活动；CV199从B对到A错，候选从联合观看改为分视频取证、3→24调用，依赖单视频推断跨视频方位。Counting136虽然改答正确，理由仍包含对不确定墙数的猜测；Counting155从F对到E错，候选把未量化的multiple与明确3幅比较，缺少有效复核。没有人工重新观看视频，不将这些文本轨迹当作完整视觉根因证明。

首批实际请求核验：每臂8记录，共133响应（Global76、Video57），seed0/T0/2048、输入hash、实际token计数、cache0和整题单卡全部通过；实际Global System分别为短版SHA e04f4c1c26b17d87ff1c73ab1442969e88e5b9fff4171dc56de715d097ee8320和原版SHA acb36637f9288ad5a5ec6703abeed55d7d46ac253fb4fcf3fd8355ce0cb8b4a3，Video臂19次普通Planner请求已核验新规则与对应video_id。没有额外双遍生成。文件为各臂9B/startup_calls_audit.json；阶段闭式分和格式分别为closed_preliminary.json、format_preliminary.json。

Git冻结另提供固定标签 baseline/mvagent-direct-20261017 → 1b711bf6a466c6dee70c273d24fbd98bd4f0c80d，已推送并核验远端解引用SHA。它保留已验收的直接回答实现；共享工作区快照d565790另存，两个用途不可混为完整研究工作区都已验证。
