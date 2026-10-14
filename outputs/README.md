# 本地结果与报告

正式运行仅使用[固定评测配置](../configs/inference/README.md#固定评测方案)。历史报告以实际设置区分实验；
原始结果、冻结源码、路径及实验组 ID 保留原值，用于追溯，不作为可选配置。

- [恢复固定配置方案](fixed_profile_validation_20261014/README.md)：关闭prefix cache，六个入口统一固定配置；参数与原冻结固定配置一致，13项契约和9B E2E/MVAgent小规模冒烟通过。
- [TP8、prefix cache与16题并发的完整MVAgent测试](tp8_cache_20261014/README.md)：35B、80条轨迹；TP8能运行但更慢且重复失败，TP1 开启 prefix cache 的实验配置小测通过。
- [三模型完整 MVAgent 与 E2E 同题比较](mvagent_full_20261013/README.md)：尚未完成，目标15963条可测轨迹；沿用启动时冻结的固定配置，原始结果留Modal。
- [采样与重复惩罚对 MVAgent 循环的影响](sampling_20261013/README.md)：三种新参数完成23冻结请求及6完整轨迹；部分循环缩短，但仍有标点理由和答案格式退步，正式默认不变。
- [Global 决策 System：冲突取证与简洁表达](decision_system_20261013/README.md)：只改决策 System，冻结检查点与完整 Agent 对照，保留无效候选和未解决的问题。
- [presence_penalty 小规模重复性](presence_repro_20261013/README.md)：0.5/1.5共12次同卡或跨卡比较，0差异；格式与准确率不能由此保证。
- [reason 边界前后的推进与循环](reason_boundary_20261013/README.md)：23条历史理由判读＋7次受控续写，两类机制均存在；正式配置不变。
- [输出稳定性候选与理由整理](output_stability_20261013/README.md)：字段顺序/短理由小测有正例，仍有格式和理由问题；正式默认不变。
- [三模型最终 E2E 数据与分数表](e2e_final_20261013/README.md)
- [扩大 E2E / MVAgent 一致性验收](repro_expanded_20261012/README.md)
- [MVAgent 66题效果与可靠性测试](validation_history.md#mvagent_pilot_20261013-readme)
- [终答 reason 字符限制对照](reason_relaxation_20261013/README.md)
- [输出预算放宽对照](output_budget_20261013/README.md)

历史记录：

- [旧硬件与旧协议基线](historical_baselines.md)
- [验收、提示诊断与清理历史](validation_history.md)
- [最终 E2E 的启动与超时恢复历史](e2e_final_20261013/reports/run_history.md)

过时目录与巡检文件已清理；必要结论、负结果和来源保留在历史记录中。Modal 原始数据未改动。
