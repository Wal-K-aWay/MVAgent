# planner/prompts.py 中文镜像

仅供阅读，不被 Runtime 加载。

## TASK

# Skill 修改规划

判断 issue 是否支持对当前父库进行一次一致的修改。输出有依据的 NEW、WHEN、STRATEGY 计划或 skip；发现执行问题不自动证明 Skill 存在缺陷。

## 输入及其作用

- **issue**：analyzer 的发现、引用、假设和未确定项；须用案例核对，它不是新观察证据。
- **cases**：原始输入、公开步骤、最终答案和离线反馈，以及实际路由与注入记录。用动作之前可用的信息评估决策。
- **library_catalog**：Global 卡 ID 和 when_to_use，说明选卡范围，不说明完整方法。
- **related_cards**：提供完整正文的相关卡，用于方法比较；只有目录条目不能证明策略覆盖任务。
- **used_skill / routing / injected**：已记录的选择与核实的注入。区分 eligible、recalled、selected 和实际 injected；缺失核实仍为未知。
- **omitted_case_ids**：不可见案例，不能引用其未提供细节。

## 规划要求

1. 根据原始案例核对任务、失败与可编辑决策。区分未召回、误选/拒选、指导未遵循、策略内容缺陷和观察不足。
2. 将所需方法与相关卡正文比较。覆盖要求支持输入关系、决定性证据依赖和答案内容；共享词语或通用分析动作不足以说明覆盖。
3. 指出具体内容修改如何影响记录中的选择或可用 Global 决策。答案错误、候选为空、通用提醒都不是充分理由。若输入或现有指导已包含相关规则，最终答案的执行缺陷不证明策略缺少该规则。
4. 按下述标准选择操作，保留成功行为与任务差异；依据不足时 skip，不强行归因或生成。

## 操作标准

- **WHEN**：when_to_use 有明确缺陷且与选择/未选择相关，strategy 已支持目标任务。只修 when_to_use，冻结 strategy。扩大用途不能创造缺失的方法；未进入候选与展示后被 selector 拒绝不同。
- **STRATEGY**：具体正文缺陷与实际接收该精确目标策略的可编辑决策相关。只修 strategy，冻结 when_to_use。已有明确规则未遵循不是规则缺失；注入未知不足以支持本操作。
- **NEW**：存在有依据的方法需求，所提供相关卡不能合理覆盖。检查所有完整相关卡，说明实质方法缺口；不同题材或同簇分组不自动要求新卡。

例如，全视频计数方法被用于指定时刻的对象计数，可能是用途过宽；已注入策略明确要求只看开头来统计全视频总数，是策略缺陷；计数方法与片段排序都使用视频报告，不代表前者覆盖后者。

## 阶段约束

- 选卡只读取 when_to_use，选定后只注入 strategy，区分选择与执行缺陷。
- 用途由原始输入识别；引用和反馈是离线证据，不是求解时已观察事实。case_id 使用案例的 sample_id。
- 核对各案例的卡及注入关系。成功不证明 Skill 因果关系，曾被拒绝不说明原因。
- Gate/Test 明细不可用；接受由后续评估决定。

## 输出格式

仅返回符合 Schema 的 JSON 对象，不加 Markdown 围栏或额外文字；返回全部字段：
- **status**：ready 或 skip。
- **reason**：操作依据，或修改不受支持的理由；区分事实与预期作用。
- **operation**：ready 时 WHEN/STRATEGY/NEW；skip 时 null。
- **target_skill_id**：WHEN/STRATEGY 的目标 ID；NEW/skip 为 null。
- **evidence_refs**：case_id 和真实 step 或 null。ready 包含非满分依据；STRATEGY 的引用步骤须核实目标注入且可编辑；路由修改可 step=null。
- **checked_skill_ids**：实际检查的完整相关卡 ID；NEW 包含所有所提供相关卡。
- **goal**：作者要实现的具体修改。
- **expected_benefit**：有依据的收益假设，不保证提升。
- **preserved_behavior**：须保留的有效规则和任务区别。
- **frozen_fields**：WHEN 为 ["strategy"]，STRATEGY 为 ["when_to_use"]，NEW/skip 为 []。

skip 在 reason 说明证据限制，不适用字段为空字符串/数组，不指定编辑操作或目标。

## TEMPLATE

{context}
