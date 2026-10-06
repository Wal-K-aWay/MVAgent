# 交替优化

`global/adaptor/` 保留已实现的 SkillAdaptor-inspired Global 优化；`global/cluster/` 已实现并注册 `global-cluster-v1` 簇内批量优化流程。见 [目录说明](global/README.md)。
`video/` 暂未实现。总体仍为 Global/Video 轮流优化，当前入口只运行 Global，不自动交接。
共享基础设施位于 ../../infra/；角色内部的流程、Prompt 和候选策略归各自目录。

`global/cluster_v2/` 注册 `global-cluster-v2`，实现独立 Cal 搜索和正式 Gate，见其 README。
