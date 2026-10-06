# SkillAdaptor 源码运算流程与复现说明

本文依据本仓库 `SkillAdaptor/skill-adaptor/` 当前源码（而不是论文图或 README 的概括）整理。目标是让实现者能够从零搭出同等的**训练无关（training-free）技能演化**管线，并知道哪些行为是当前实现的真实语义、哪些只是保留代码。所有给 LLM 的固定模板都移至文末索引所列的独立 `*.md`；正文只引用文件名。运行时由任务、轨迹、技能库等填入的占位数据在各 Prompt 文件中以 `{...}` 标记。

## 1. 一句话模型

维护可版本化的技能库 `B`。每轮用当前 `B` 执行训练任务 `Q`；对失败或低分成功轨迹，定位第一个根因步骤 `t*`，决定应改旧技能还是生新技能；将每个候选单独注入验证集 `Q'` 重跑，只有验证指标严格达到门槛且没有回归才写回 `B`。最后才在从未参与上述决策的 `Q_test` 上报告。

这里的“无训练”意为不更新模型权重；Localizer、Linker、Generator、Reviser、可选 reranker 和某些逐步归因都仍会调用同一个/兼容的聊天模型，检索还会调用 embedding API。

## 2. 组件、数据与不可省略的接口

```text
run_plugin.py / run_skill_adaptor.py
  → 环境 executor（workspace / PinchBench / Claw-Eval / WebShop）
  → SkillAdaptorOrchestrator
      B0 validation → execute Q → Localize → Link → Revise | Generate
      → candidate A/B validation → adopt/reject → export/inject
```

核心 DTO 定义在 `core/types.py`：

| 对象 | 最小字段与含义 |
|---|---|
| `Skill` | `id,title,description,body,when_to_apply,version,created_from,domain_category`；创建及修订会计算 `body_sha256`，修订版本递增。 |
| `Step` | `index, observation, action, reward, done, skills_used`；没有可解析 tool action 的轨迹不合格。 |
| `Trajectory` | `task_id, task_description, steps, success, total_reward`。 |
| `LocalizedFault` | `task_id, step_index, fault_type, observation, wrong_action, skills_at_fault, improvement_principle`，以及 `fault_chain`、交付物/rubric 辅助字段。 |
| `ValidationResult` | 候选的两类指标增量、回归布尔值、样本量及基线/候选原始 metrics。 |

`fault_type` 只有 `skill_wrong`、`skill_missing`、`reasoning_wrong`。三种输入分区必须显式固定：`input_tasks`（训练）、`validation_tasks`（采用门）、`test_tasks`（最终只读）。入口检测到训练/验证交集时默认报错，只有 manifest 的 `allow_train_val_overlap=true` 才放行；严谨复现不要打开它。

## 3. 启动、配置和任务执行

### 3.1 两个入口

推荐插件入口是 `run_plugin.py`：`init` 建立工作区、manifest、锁和目录；默认运行命令取项目配置或参数，拿到全局 evolution lock 与工作区 lock 后转入 `PluginHost.run_evolution`。成功后导出 `skills/<id>/SKILL.md`，按 harness 再同步到 Claude/Codex/Hermes 路径，并写运行摘要。

底层入口 `run_skill_adaptor.py` 直接按 `--env` 分发：

| 环境 | 真正执行/评分 |
|---|---|
| `workspace` | `WorkspaceExecutor` 把 task markdown 的 Prompt（和内联技能）交给 harness；解析 tool trace，用 `grade_workspace_task` 评分。 |
| `pinchbench`、`claw-eval` | executor 调 benchmark/harness；`PinchBenchPolicyAdapter` 负责检索、技能组装与约束。Claw-Eval 还锁官方 Judge 配置。 |
| `webshop` | `WebShopEnvWrapper` 运行最大 50 step 的购物 episode，`WebShopEvaluator` 评分。 |

聊天 API 的 key/base/model 与 embedding API 的 key/base/model 分开；缺 embedding 配置会回退聊天凭据。关键默认值来自 `SkillAdaptorConfig`：`max_iterations=10`、`min_sample_size=5`、成功率和平均分采用阈值均为 `0.05`、容忍 aggregate 回归阈值 `-0.05`、技能匹配阈值 `0.5`、跨任务阈值 `0.55`。需把完整 env、模型名、随机种子 42、任务 manifest 和代码 commit 保存，才能复现一次运行。

### 3.2 每次 agent rollout 前的检索与注入

对 PinchBench/Claw-Eval/workspace，`configure_pinchbench_skill_injection` 的顺序是：

1. 对 task markdown 建任务描述（任务标题/类别/正文）。`SemanticSkillMatcher` 调 embedding，余弦排序最多 10 个技能。
2. `SkillRetrievalGate` 先检查来源同 task（直接通过）；否则要求类别相同且相似度至少 `same_category_embed_min`，跨 task 至少 `cross_task_embed_min`。跨类别默认拒绝。
3. 默认 `SkillAdaptor_LLM_RERANK` 开启时，聊天模型用 [p05_skill_rerank.md](prompts/p05_skill_rerank.md) 将经过门控的候选重排，取前 `top_k=3`；任何调用/JSON 失败直接失败，不做静默规则回退。
4. `PinchBenchPolicyAdapter.build_combined_skill_text` 组装最高三个技能、可选全局 prior `π`、交付物 banner 和模型专属约束，最多 5000 chars。对 `command.txt` 类任务还会从技能或 task 推得一条 canonical command，作为首条行动前缀（见 [p09_injection_wrappers.md](prompts/p09_injection_wrappers.md)）。
5. executor 将技能写入 harness 可发现的位置并 read-back 验证；workspace 同时把 [p09_injection_wrappers.md](prompts/p09_injection_wrappers.md) 的 inline block 置于用户任务之前。WebShop 在 episode 开始按任务检索至多三个技能，并把 [p06_webshop_actor.md](prompts/p06_webshop_actor.md) 发送给 actor。

不要把“被检索”与“在某 step 实际遵循”混淆：WebShop 主路径用 `StepSkillRetriever` 以 step 文本 embedding 标注；PinchBench/Claw-Eval 可以用 LLM 逐步追踪器（[p07_step_attribution.md](prompts/p07_step_attribution.md)）。`skills_used` 是随后 Linker 的直接证据。

## 4. 主循环的精确顺序

`SkillAdaptorOrchestrator.run(Q,Q',eval,B_init)`：

1. 将 `B_init` 加入 `SkillBankManager`；初始化 rejection history 和可选 `global_prior.txt`。
2. **B0 锚点**：以初始 `B0` 对完整 `Q'` 调 `eval_func`，缓存结果和每 task `success/score`，写 `baseline_metrics.json`。这不是最终 test。
3. 对第 `i=1..max_iterations` 轮：以当前技能库执行所有 `Q`，获得 tool-level 轨迹。issue 集合是 `success=False` **或** `success=True 且 total_reward<0.6`。
4. 对每个 issue 调 Localizer；再以同一 `fault_type`、`fault_type + observation[:150] + wrong_action` 的 embedding cosine 去重，阈值 `0.85`，仅保留先到的故障代表。
5. 对每个代表按 `fault_chain`（最多前三个、去重后的 1-based step；缺省即 `t*`）依次尝试候选。某一 step 一旦有被采用技能，停止该 fault 的后续 chain。
6. 每个候选单独经过验证/采用（第 6 节）。若同一次返回多个已采用技能，再做一次“把它们一起放入原 bank”的 holistic validation；aggregate success 或 avg 低于 `regression_threshold` 就按逆序 rollback。
7. 若本轮有 Localizer principle，则另行尝试更新全局 prior `π`：取第一个去重 principle，评估同一 bank 的无 π / 有 π；样本量足、无负增量并且任一指标严格大于 `0.05` 才写 `global_prior.txt` 并清 baseline cache。
8. 连续 `k_reject_threshold`（配置默认 3）轮无技能采用即停止；issue 为空也停止。最终写 `skill_bank_final.json`、迭代报告、拒绝史和检查点；外层才可跑 `Q_test`。

`reasoning_wrong` 的代码默认**仍然**允许产生软技能补丁；只有环境变量 `SKILLADAPTOR_SKIP_REASONING_WRONG_EVOLVE=1` 才记录到日志而不演化。这是源码与“只修 skill fault”的简化论文叙述之间的重要差异。

## 5. L → Link → R/G 的局部计算

### 5.1 Localizer（L）

输入为完整工具轨迹、压缩摘要、末尾五步、任务 brief 和动态 adapter hints。它发送 [p01_localizer.md](prompts/p01_localizer.md)，temperature 0.2。输出按行解析而非 JSON：`fault_chain`、`t_star`、交付物、`improvement_principle`、三选一 `fault_type`。`t_star` 越界或 principle 为空会抛错；随后 `refine_localized_fault` 根据任务 markdown/真实 step 继续规范交付物相关字段。

注意实现只把 Localizer 的**主** `t_star` 用作最初 fault；chain 中每次尝试都构造该 step 的 `observation/action/skills_used`，但保留原 fault type/principle。禁用 `SKILLADAPTOR_ALLOW_FAULT_COERCE` 时（默认）不改模型分类；打开时可对 cold-start/degraded bank 做规则强制分类。

### 5.2 Linker（Link）

若 bank 非空，先以 `skills_at_fault` 精确命中；否则用 observation、wrong action、principle 和 skill 文本的语义匹配筛小候选。它调用 [p02_linker.md](prompts/p02_linker.md)，解析 `attributions[]`，丢掉未知 id/非法权重。`weight >= config.attribution_weight_threshold`（默认 0.55）是高置信 repair。

候选路由是：

```text
高置信归因                 → 对每个归因技能 Reviser
skill_wrong + 低权重归因    → 修最高权重技能
skill_wrong + Link 空 + S_t → 修 S_t 中注入的技能；仍无候选才 Generate
skill_missing / 空 bank     → Generator
skill_wrong 无任何嫌疑      → Generator
reasoning_wrong（默认）     → Generator；若已有高置信归因则 Reviser
```

候选在进入验证前用 `SkillBankManager.deduplicate` 做 Jaccard 词集合相似度去重（默认 0.8）；另外候选 body hash 或标题词重合过高于历史 rejected candidate 也会跳过。

### 5.3 Reviser（R）

每次修订先把 fault 记入该 skill 的 history，然后发送 [p03_reviser.md](prompts/p03_reviser.md)，temperature 0.2。首选返回完整 `skill_profile`：title/principle/when/procedure/qualification/negative example；代码将它格式化成新 body、补充分支/交付物约束、压到 2000 chars，并 `copy_with_revision()`。如没有 profile，则校验 legacy JSON patch，按 `revision_type` 调 handler 修改 Markdown（precondition、negative example、procedure、validation 等）；未知类型也会把 `after` 追加为新 section。`revision_type=none` 不产生候选。

### 5.4 Generator（G）

先用描述文本 Jaccard（默认 0.75）排除与已有技能相似的 principle；再发送 [p04_generator.md](prompts/p04_generator.md)，temperature 0.3。JSON 会经过：shell/artifact task enrichment、拒绝 meta-skill（日志/转录/监控自身）、拒绝过浅技能（少于 3 procedure、body <220、短 principle/trigger 等）、格式化 Markdown、`smart_compact_skill_body(max=1600)`。id 是本进程内的 `gen_<task_id>_<counter>`；重启而不加载原 bank 会影响 id，因此复现需要固定 seed bank/调用顺序。

## 6. 验证、局部重跑和采用门

对一个候选 `s`，构造 `B' = B ∪ {s.id: s}`（同 id 是覆盖修订）。`Validator.validate` 先取同 bank/version + scope 的缓存 baseline；随后 eval `B'`。固定随机种子为 42。

实际 eval 函数有检索优化：先判定 `Q'` 中哪些 task 在 `B'` 会检索到候选技能。若候选只影响集合 `A`：

```text
重跑 A（以 B' 注入）
把 Q'\A 的 B0 task_result 原样复制
adoption delta = metric(B'[A]) - metric(B0[A])
frozen regression = Q'\A 任一 success→failure，或 score 降低
```

若 `A` 为空，不重跑，直接拒绝；若不走该优化则完整重跑 `Q'`。因此“全 Q' 无回归”在局部验证中不是一次真实联合 rollout，而是 rerun 结果与旧基线的拼接；复刻时必须保留这一语义，不能误报成全量 A/B 重跑。

`should_adopt` 的必要条件：

1. 样本数至少 `min_sample_size`；局部 `A` 时为 `max(1,min(min_sample_size,|A|))`。
2. `frozen_regression=false`，同时 aggregate / task-level回归检测为 false，且两项 delta 都不小于 0。
3. `delta_success > 0.05` **或** `delta_avg_score > 0.05`（严格大于）。

回归检测除了 aggregate 不可低于 -0.05，还检查 `critical_success_rate`，以及可比较 task 中 success→failure 或 score 降超过 0.1 的比例不能大于 10%。source task 的单题 evaluation 是 advisory，不参与采用门。候选拒绝时将原因、验证后的 action tail/trace 写 `rejection_history.json`，该历史会反哺 R/G Prompt，避免重复提案。

## 7. 从零复建的最小蓝图

建议先仅实现 workspace executor；它最能隔离 benchmark 依赖。

1. 定义第 2 节 DTO，保存原始 task、agent 请求/响应、每一步工具 action、评分和 skill ids；无 step 的失败必须 fail closed，调试才允许合成一步轨迹。
2. 固定 manifest，预先跑/缓存 B0 的 `Q'`；实现能够接收任意 bank 的 `execute(task)` 与 `evaluate(tasks,bank)`。
3. 实现 embedding `encode`、cosine ranking、类别 gate；需要与本实现一致时加入 LLM rerank 和 top-3 注入。将 Markdown 前置并验证磁盘注入，且对能直接传 prompt 的 harness 再做 inline 注入。
4. 按第 5 节依次实现 Localizer、Linker、Reviser、Generator，使用文末模板，严格验证响应格式、t* 范围与候选质量。
5. 按第 6 节实现 evaluator/validator、baseline 缓存、候选逐个验证、rejection history、checkpoint 和 holistic rollback。
6. 最后接入 plugin lock、skill export、具体 benchmark executor 和 final `Q_test`。不要用 test 分数影响任何上述分支。

复现实验至少记录：源码 commit 与所有 Prompt 文件 hash、完整 env（去除密钥）、chat/embedding/Judge 模型与参数、manifest 内容、初始 bank JSON hash、每个任务 prompt hash、rollout seed、所有原始 trajectory、检索/rerank 结果、candidate/rejection/adoption 决定及 B0/B' task metrics。当前实现没有统一的 API retry/deterministic completion 保证，故“相同设置”并不保证 token 完全一致。

## 8. 当前源码中的边界与容易误读处

- `core/prompts.py` 的 `SkillPrompts` 虽被 Reviser 实例化，但当前 Reviser/Generator 实际各自拼 prompt；它不是主路径。保留模板见 [p10_legacy_prompt_builder.md](prompts/p10_legacy_prompt_builder.md)，不要在复刻主路径时重复叠加。
- Localizer 使用一个长的、WebShop 倾向的 synthetic examples 常量，即使目标为 workspace/PinchBench；adapter hint 只是补充，无法移除这些 examples。
- `PromptProfile.constraints_block('localizer')` 被 Localizer 插入；Generator 当前只插模型 block，Reviser 仅插模型 block，故不要假设 shared constraints 对所有阶段都实际生效。见 [p08_profile_and_hints.md](prompts/p08_profile_and_hints.md)。
- `global_prior π` 是额外的字符串注入通道，不是 bank 中的 `Skill`，也不走 Linker/Generator；它可在每轮后独立被采用。
- WebShop 使用独立 actor Prompt 和 episode-level retrieval，且其 evaluator 的验证集可能是固定随机 50 子集；不要把它和 task-manifest executor 的 protocol 当成同一个实验。
- 对 `command.txt` 任务，代码可由任务文本派生 canonical `grep` 命令后强制首行动。这是 task-specific prompt shaping，不是普适技能演化算法，应在论文复现中单列 ablation。

## 9. Prompt 索引（固定文本已独立提取）

| 文件 | 调用点 | 用途 |
|---|---|---|
| [p01_localizer.md](prompts/p01_localizer.md) | `core/localizer.py` | 失败轨迹 → `LocalizedFault`。 |
| [p02_linker.md](prompts/p02_linker.md) | `core/linker.py` | fault → skill attribution weights。 |
| [p03_reviser.md](prompts/p03_reviser.md) | `core/reviser.py` | 旧技能 + fault → profile/patch JSON。 |
| [p04_generator.md](prompts/p04_generator.md) | `core/generator.py` | fault → 新技能 JSON。 |
| [p05_skill_rerank.md](prompts/p05_skill_rerank.md) | `core/skill_rerank.py` | embedding 候选重排。 |
| [p06_webshop_actor.md](prompts/p06_webshop_actor.md) | `adapters/webshop_adapter/llm_policy.py` | WebShop 单 step ReAct actor。 |
| [p07_step_attribution.md](prompts/p07_step_attribution.md) | `adapters/pinchbench_adapter/skill_tracker.py` | 逐 step `skills_used` 归因。 |
| [p08_profile_and_hints.md](prompts/p08_profile_and_hints.md) | `core/prompt_profile.py`, `adapter_hints.py` | 动态附加的约束/模型/环境片段。 |
| [p09_injection_wrappers.md](prompts/p09_injection_wrappers.md) | `runtime/skill_inject.py`, `skill_body_utils.py` | agent 实际看见的技能包装及命令前缀。 |
| [p10_legacy_prompt_builder.md](prompts/p10_legacy_prompt_builder.md) | `core/prompts.py` | 保留、当前主循环未调用的旧 builder。 |
