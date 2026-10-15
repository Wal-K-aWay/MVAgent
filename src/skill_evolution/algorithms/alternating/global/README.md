# Global Skill 自进化

- [adaptor/](adaptor/README.md)：原有 SkillAdaptor-inspired 实现，包含原代码、Prompt、中文镜像、流程和参考材料。现有 `global-skilladaptor-v1` 训练入口指向此目录。
- [cluster/](cluster/README.md)：`global-cluster-v1`，固定 Train 聚类、每簇一卡槽、批量反思→原作者→完整库 Gate；已有训练入口与独立配置。

聚类已完成实现与诊断，但同簇不保证共享完整解题方法。簇内共用 Skill 的有效性仍需实验验证。

修改模型可见 Prompt 时，同步各自目录下的 chinese_prompts/。现有实验通过各自冻结源码恢复，不能把本次目录调整当成相同源码身份继续训练。

- [cluster_v2/](cluster_v2/README.md)：`global-cluster-v2`，Train/Cal 固定分组、analyzer/planner、独立作者、完整 Cal 搜索池与定期 Gate；独立配置与检查点，不改变 cluster v1。
