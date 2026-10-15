# evidence.py 中文镜像

仅供阅读，不被 Runtime 加载。

统一 User 标题：`## Development evidence (offline feedback is not observation)`，后接结构化 JSON；阶段模板中的 {context} 只替换一次。

- analyzer：原始输入、公开步骤、最终答案、离线反馈；不含 used_skill、bank_hash、source_sample_id、routing、selected、injected 或卡目录/正文。
- planner：上述完整案例与实际 routing/selected/injected，issue、library_catalog（id/when_to_use）、related_cards。
- generator/reviser：增加 plan 和 target_skill；variant 为候选序号，earlier_edits 为同计划已有候选，max_card_words 为组装整卡预算。
- 超过 max_context_chars 时按整条案例省略并保存 omitted_case_ids；优先保留 issue/plan 引用案例，关键引用不可整体容纳则明确失败。

阶段数据仅来自 Train/Cal；程序不从 Gate/Test 组装 optimizer 输入。

缺失请求时注入仍为 unknown。
