# 冻结数据清单

已有清单一律按原字节使用，不因为新默认seed=0重新抽样。以下研究清单由原Modal文件迁移，19份库/清单总计222742 bytes，资源SHA均与远端一致。

| 清单 | 样本与用途 | SHA256 |
|---|---|---|
| [research_train80_cal40_gate176.json](research_train80_cal40_gate176.json) | Train80 / Cal40 / Gate176；已复用开发面板 | `794a66996f1e12fceea9e6c7f12fcd6416fb4704c6a96e573e715ae7a35b1a21` |
| [research_confirmation365.json](research_confirmation365.json) | 365题只报告确认；96声明来源组，不是最终Test | `7a8a83c1f5a3d205131b3a537d4e9c1ac7758f4df18de1bc66e1c5120d9e8b69` |
| [research_confirmation400.json](research_confirmation400.json) | 400题计划开发确认；未启动，题号隔离但来源重叠 | `8853fb235a9f6a71f4c88becccc53ee017a49d9aef92daa13dd330d5d3ef9598` |

三个清单的`eval`只是分区名称：原296中用于Gate，365/400用于只报告开发确认，不能自动解释为最终Test。
400题与原661题及Lite2500题号不重合，但339/400与原661共享声明来源组，296/400与Lite2500共享来源组。
不要将只有eval分区的365/400清单交给要求train/cal/eval各覆盖十任务的rolewise入口。
原始清单保留其旧抽样seed；推理seed统一0，两者含义不同。
新十任务划分见[服务器手册](../../../docs/server-runbook.md)，历史研究边界见[研究交接](../../../docs/research-handoff.md)。
