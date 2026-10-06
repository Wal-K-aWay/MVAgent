# 当前已实现流程

Train 原始输入聚类 → 按 epoch/簇/批次遍历 → 完整库自然选卡或无卡运行 → 批量反思 → Generator/Reviser编写完整卡 → 程序校验 → Train Selector 回放 → 完整库 Gate → 严格提升才接受 → 每批原子提交。

Train 和 Gate 均使用完整 Global 库与固定 Video 卡，Selector 可不选；整题使用固定选择。簇只组织 batch，不绑定卡。
reflect 返回 generate、revise_metadata、revise_body 或 skip；正文修订要求非满分锚点实际使用目标完整版本。每批最多一个候选，失败修订不替换旧卡。反思 skip 或无有效候选不运行候选 Gate。
新建调用Generator；正文或元信息修订调用Reviser，各一次返回完整三字段。元信息修订冻结正文和meta，由程序检查。Train Selector 回放只记录选卡变化，不是适用性金标或接受门槛。
候选修改仅接收 Train 公开材料。Gate 是选择集，不是独立 Test，最终收益需要未参与优化的测试评估。
配置、恢复、验证边界和产物见 [README.md](README.md)。
