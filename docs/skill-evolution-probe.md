# 首轮 Skill 自进化闭环：实测与限制

2026-10-21。**流程完成，未获得通过接受规则的新库，最终保留空库。**
这是一轮接入和方向诊断，不是算法有效性或无效性的统计结论。

## 配置与来源

- Actor：固定Qwen3.5-35B-A3B；7个独立H100单卡副本，原固定profile、seed=0、temperature=0、thinking关闭、512帧、2048输出token、Global/Video各5步，prefix cache关闭。
- Judge：第8张H100上的Qwen3-30B-A3B-Instruct-2507与原官方Prompt；成本不参与接受。
- 优化器：DeepSeek-Flash，沿用一次生成的API配置，2个角色轮次、每轮2个提案；4次提案全部结构有效，未手工改卡或按Cal/Gate逐题信息改Prompt。
- 数据：CrossVid 10 Train / 10 Cal / 10 Gate，30道不同题，每分区每task一题。三分区声明源组互斥，seed=0；来自80/40/40母面板。母面板142/160与历史开发数据源组重叠，不能视为新盲测。
- 首测split SHA：`85f56ba07892c689e71382e6ae09d92769ad945680782ec004a0f1a650a1978f`。
- 闭环冻结源码：`1d7928e0673e68f8d16fc568f30d8db3486ac59a`，源码归档SHA `f60ded4be08602904e8ad057a005b9e5dba6a9a266b9d61767cdbd9520093f2d`。
- 运行目录：Modal runs volume `wxu-evolve-agent-runs-20261006` 下 `devbox/skill_evolution_20261021/probe/`。原始问答、评分、请求/响应、配置、源码与全部候选均保留；没有将这些数据迁入Git。
- 120次完整问答全部完成评分，分布在12个整库×分区单元。10:59 UTC完成，8张新增H100已由控制器释放；原48卡补测独立继续。

## 官方分数与接受结果

以下均为CrossVid十任务macro百分数，CCQA按评分点加权；每格10题。
`—`表示按预设筛选流程未进入Gate，不是零分。

| 库 | Train | Cal | Gate | 结果 |
|---|---:|---:|---:|---|
| 空库 | 50.00 | 30.00 | 40.00 | 起点与最终保留库 |
| Global第一版 | 56.67 | 50.00 | 40.00 | Cal最优，但Gate持平，拒绝 |
| Global第二版 | 61.67 | 20.00 | — | Cal退化，未进Gate |
| Video第一版 | 50.00 | 30.00 | — | Cal持平，未进Gate |
| Video第二版 | 45.45 | 30.00 | — | Cal持平，未进Gate |

Global轮次拒绝后仍以空库进入Video轮次，两角色没有在本次被同时启用。不能把这张表当作双库协同优化实验。
最终库SHA `1dea07ba6d17ff67eb714db06082a162f76012a28d2c8ecc5ad832ab33f1c184`，`accepted_rounds=0`。

## 已观察到的行为

| 候选/分区 | 自然选中/选卡调用 | 相对空库的逐题得分变化：改善/退化/相同 |
|---|---:|---:|
| Global第一版 / Train | 8/10 | 2/1/7 |
| Global第一版 / Cal | 8/10 | 2/0/8 |
| Global第一版 / Gate | 5/10 | 0/0/10 |
| Global第二版 / Train | 8/10 | 2/0/8 |
| Global第二版 / Cal | 9/10 | 0/1/9 |
| Video第一版 / Train | 18/22 | 2/1/7 |
| Video第一版 / Cal | 11/27 | 0/0/10 |
| Video第二版 / Train | 11/23 | 1/1/8 |
| Video第二版 / Cal | 6/27 | 0/0/10 |

Video分母是请求数，Global分母是题数；两者不能直接横比。表中“相同”是得分相同，不保证答案或轨迹逐字相同。以上选择均无无效Selector输出。

Global第一版把Train的`analyze_videos/watch_videos`调用从9/2变为6/4；Gate从11/1变为6/5，Gate逐题得分仍全部持平。因此当前观察只支持“skill能够改变取证行为”，没有证明“更多watch必然改善正确率”。

第一版Global的`when_to_use`含选择时不可见的History条件；第二版不再包含这个条件，却同时改了strategy与其他入口文字。因此不能从两版分差估计这个条件本身的影响。

Video第一版Cal的11/27次选中与逐题得分全部持平，既可能是选错适用范围，也可能是策略未改变关键证据、原有证据已足够或下游未利用新报告。**仅凭选中率与终答总分不能区分这些解释**；需要设计文档中的固定strategy/固定入口与诊断强选对照。

## 工程问题与修复验证

冻结版先抽Train题，再跳过没有Video调用的题。已观察到7道有Video轨迹的题中只送出3个例子，而配置上限为6。该实验没有热更新或重跑来隐藏这个问题。

源码 `bcc045272f7b746b6435870601f2ee04c727c29a` 已改成先筛选角色可用轨迹，再抽样；完全没有该角色轨迹时记录跳过并继续其他角色。Modal CPU `ap-m5sr4EBtYJ47BnEvtBZ43R` 完成11个进化用例、完整compileall与真实API冒烟；加既有一次生成9、评估适配2、冻结恢复2，共24个不同回归用例通过。迁移前后一次生成Prompt逐字一致的检查已通过。

修复后真实API输出摘要：

```json
{"valid":true,"role":"video","eligible_questions":7,"examples_sent":6,"operation":"add","evaluated":false}
```

这次额外提案只验证采样与API接入，未做准确率评估、不参加上述4候选搜索或接受。原始记录在 `devbox/skill_evolution_20261021/checks4/role_sampling_smoke/`；不能把冻结版成绩归给修复后的源码。

## 下一步与可声称范围

1. 先用修复后的实现和80/40/40开发面板扩大测量，记录每轮修复与退化；不因为本次全部拒绝而降低Gate标准。
2. 优先补Global的“自然选择/诊断强选/不用卡”对照，分开估计卡片价值与选卡损失，再决定先优化入口还是策略正文。
3. Video先保证有效角色例子充足，再做相同instruction与先前Memory条件下的局部干预诊断；最终接受仍是完整问答的整库分数。
4. 不从每task一题的面板计算稳定提升或置信区间。本轮没有复现历史47%救回率，也没有运行CVBench/MVU最终Test、跨模型迁移、联合角色修改或长期候选池搜索。

最终分析CPU `ap-hIahSX1IpqeHbK2krUe1Ad` 成功；`probe/analysis.json`与`analysis.md`包含全表及决策，重核了120份原始记录SHA。客户端尾部日志等待超时不影响函数成功及已保存分析。
