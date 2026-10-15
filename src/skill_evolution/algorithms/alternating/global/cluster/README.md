# Global 簇内组织、完整库优化

入口 `global-cluster-v1`；配置 `configs/skill_evolution/global_cluster_35b.yaml`。只优化 Global，Video 始终冻结。Train/Gate 非空、ID 无交集、来源审计；训练不加载 Test。初始库可为空或显式提供完整库。

1. 全部 Train 的完整问题、选项、视频 ID/时长做 embedding + Louvain。簇仅组织 batch，不绑定 Skill；cluster_anchor 可只调度一个簇。
2. 每 epoch 遍历簇内打乱题目。每道 Train 题从当前完整库自然选一张卡或不选，整题固定。保存公开轨迹、评分及真实选择/注入。
3. 健康成功和非满分案例进入 reflect；无健康非满分案例跳过。输出 generate、revise_metadata、revise_body 或 skip，及依据、目标卡和本地 case 标签。正文修订锚点必须实际使用完整目标版本；未选卡不自动新建、未遵循明确规则不自动改正文。
4. 新建由 Generator 一次返回 when_to_use、strategy，程序分配顺序编号；修订由 Reviser 一次返回两字段和说明，也可 skip。revise_metadata仍经Reviser，但程序要求正文/meta不变。无独立metadata作者。
5. 作者读取全部 Global 卡的元信息、相关实际用卡完整内容及相关拒绝历史；GT 只作差异反馈。Prompt 用 case_1 等局部标签和 correct/partially correct/incorrect，不显示原始题 ID、数值 Train score、私有 Video 轨迹或 Gate 细节。
6. 检查格式/ID/角色/阶段、配置的整卡总 word 预算、无变化与完全重复；没有独立字段上限。有效候选在固定 Train 输入上回放真实 Selector：每个原簇前4题，比较完整父库/候选库的选择，记录变化但不视作适用性金标准。最多20条变化反馈给下一批作者；按原子状态恢复。
7. 完整候选库跑全部 Gate，自然选卡。官方总体严格提高才接受；持平/下降拒绝。后续作者只见拒绝状态及 Train 反馈，不见 Gate 分数/题目/轨迹。每批最多一个候选，簇 patience/epoch 终止，原子保存。

`cluster_evolution/state.json` 保存库/游标/决策；`versions/` 不可变版本；`batches/NNNN/` 保存 materials、reflect、proposal/generator或proposal/reviser、train_routing、validation/change；final_bank.json、selection_statistics.json、summary.json 为最终输出。没有 cluster_slots.json 或固定簇卡映射。

仍无跨 batch 原始素材池、多级 merge/ranking/slow/meta、强制注入、语义审查或超长自动改写。Train 回放是选卡行为诊断，不是独立适用性验证。独立迁移/Test 评估另行运行。

恢复必须使用原冻结源码、配置和身份；新源码不能恢复历史簇槽实验。真实 transport 错误中止，结构/长度错误记录跳过；底层模型有限 JSON 修复不变。

验证：`PYTHONPATH=src:tests /home/kww/miniconda3/envs/MVAgent/bin/python -m unittest test_global_cluster -v`。受控 CPU 测试验证跨簇完整库、分开作者、字段冻结、目标真实使用、公开边界、断点恢复及 Selector 回放缓存，不作为收益证据。

2026-10-05：已合并完整卡作者；旧拆分作者checkpoint只能使用原冻结源码恢复，新源码不兼容旧阶段响应。

Prompt目录统一为reflect/generator/reviser各自的prompts.py与schema.py；包__init__.py仅说明用途。reflect/schema.py还负责锚点及目标版本证据校验，反思行为和输入输出保持不变。

2026-10-05 当前规范：新卡引用编号由程序分配顺序数字字符串，Generator只返回 when_to_use、strategy 两个内容字段，不生成命名ID；修订保持已有引用。引用字段仍用于选卡、归因和版本关联，不承载语义。CARD_CONTRACT使用客观字段规范，Design requirements说明各字段作用、内容细节和样例；无独立字段上限提示。整卡及渲染正文总预算保留。历史冻结源与卡库不改写。
