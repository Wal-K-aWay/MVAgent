# 冻结数据清单

已有清单一律按原字节使用，不因为新默认seed=0重新抽样。继续历史比较时使用下面对应的原清单。
固定库评测入口`eval/agent_eval/run.py --split-manifest`只读取`eval`分区；
进化入口`scripts/evolve_skills.py`要求`train/cal/eval`三组各覆盖CrossVid十任务。

以下三份研究清单由原Modal文件迁移，与16份研究库合计222742 bytes，资源SHA均与远端一致。

| 清单 | 样本与用途 | SHA256 |
|---|---|---|
| [research_train80_cal40_gate176.json](research_train80_cal40_gate176.json) | Train80 / Cal40 / Gate176；已复用开发面板 | `794a66996f1e12fceea9e6c7f12fcd6416fb4704c6a96e573e715ae7a35b1a21` |
| [research_confirmation365.json](research_confirmation365.json) | 365题只报告确认；96声明来源组，不是最终Test | `7a8a83c1f5a3d205131b3a537d4e9c1ac7758f4df18de1bc66e1c5120d9e8b69` |
| [research_confirmation400.json](research_confirmation400.json) | 400题计划开发确认；未启动，题号隔离但来源重叠 | `8853fb235a9f6a71f4c88becccc53ee017a49d9aef92daa13dd330d5d3ef9598` |

三个清单的`eval`只是分区名称：原296中用于Gate，365/400用于只报告开发确认，不能自动解释为最终Test。
400题与原661题及Lite2500题号不重合，但339/400与原661共享声明来源组，296/400与Lite2500共享来源组。
不要将只有eval分区的365/400清单交给要求train/cal/eval各覆盖十任务的rolewise入口。
原始清单保留其旧抽样seed；推理seed统一0，两者含义不同。

同目录还保留以下评测或历史材料，不能将它们混作当前进化输入：

| 文件 | 内容与用途 | 可否用于当前rolewise |
|---|---|---|
| [crossvid_lite2500_eval_seed20260919.json](crossvid_lite2500_eval_seed20260919.json) | 固定Lite2500评测manifest，仅`eval`；新划分脚本也用它排除题号 | 否，缺少Train/Cal |
| [crossvid_lite2500_eval_seed20260919.audit.json](crossvid_lite2500_eval_seed20260919.audit.json) | 上述面板的来源与构造审计，不是样本manifest | 否 |
| [crossvid_closed_t72_c36_g36_seed20261006.json](crossvid_closed_t72_c36_g36_seed20261006.json) | 历史九任务72/36/36清单，不含CCQA；仅供历史对照追溯 | 否，缺少第十任务 |
| [crossvid_clean_pool.json](crossvid_clean_pool.json) | 1734个题号的数组，没有分区；不是来源完全独立的证明 | 否，不是split manifest |

新十任务划分见[服务器手册](../../../docs/server-runbook.md)，历史研究边界见[研究交接](../../../docs/research-handoff.md)。
