# Global cluster v2

`global-cluster-v2` 是从 cluster 复制后独立实现的完整库搜索算法。原 cluster v1 保留。
设计依据为 [docs/design.md](docs/design.md)。其中第1.1节“embedding驱动的迭代分组”为待实现方案；当前运行时仍采用初始化一次的固定分组。

## 流程

1. 对冻结的 Train + Cal 原始问题、选项、视频 ID/时长做一次 embedding/Louvain；分组组织取样，不绑定卡。
2. scheduler 优先展开次数少的完整库，同次数优先 Cal 高分、再按创建顺序。簇轮换取 Train batch，每四轮优先抽取已观察到的 Train 错误。
3. 使用完整父库正常选卡、运行 Train。补充最多四条相关 Cal 成功/失败：均在当前父库核实，旧版本记录不会直接成为修改依据。
4. analyzer 不接收 Skill 正文、用途目录或选卡记录，只诊断公开轨迹；planner 接收 issue、原始案例、用途目录、最多八张相关完整卡及实际路由/注入。
5. planner 返回 ready（NEW/WHEN/STRATEGY）或 skip。依据不足时直接跳过，不调用作者。
6. generator 输出新卡；reviser 只输出修改字段。candidate_builder 在作者调用前校验计划，之后复制冻结字段、分配顺序数字字符串 ID，验证总字数、单卡范围、无变化和完全重复。
7. 每个有效候选完成同一个完整 Cal；父库与候选使用预先固定的 repeat 身份，默认两个重复，按官方总分和逐题分数取均值。
8. 搜索池最多三个完整库：Cal 最优、至少两题且各配对重复均成立的互补分支、有限探索。纯探索后代继承剩余展开额度；总展开和评价预算受 exploration_fraction 限制。
9. 每两轮至多验收一个尚未 Gate 的竞争版本，结束时再验收一次。只有完整 Gate 官方总分严格提高，才替换正式库；搜索池留存不等于正式接受。

## Optimizer Prompt 规范

四阶段沿用 adaptor 的分节风格：任务定义 → 输入及其作用 → 分析/编写要求 → 阶段约束 → 输出格式。planner 增加操作标准，reviser 增加单字段要求。少量示例放在对应规则旁，不替代通用判断要求；共享动作背景与 CARD_CONTRACT 仍统一拼接。

analyzer 区分事实、原因假设和未知项，不做卡库归因；planner 核对真实路由、注入及正文，再决定 NEW/WHEN/STRATEGY 或 skip。generator 落实完整方法，reviser 只落实目标字段。作者可以在无法形成有依据的候选时 skip；通用格式提醒或未遵循现成规则不自动构成新方法。输出字段名和 Schema 不变。

## 数据与入口

使用 version=2 的显式 split manifest：`train`、`cal`、`eval`（Gate），可另含 `test`。
三种开发分区必须非空，ID 和已知媒体来源隔离。训练不读取 Test；独立 Test 通过 evaluate 调用。
不能把旧 Train/Gate 两分区自动拆分或让 Cal/Gate 共用题目。

```bash
PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python scripts/run_skill_evolution.py \
  --mode train --config configs/skill_evolution/global_cluster_v2_35b.yaml \
  --execution-config configs/inference/execution/gpu4_7.yaml \
  --split-manifest /absolute/path/to/frozen_train_cal_gate_test.json \
  --output-dir outputs/mvagent/skill/cluster_v2_run
```

执行池路径须选择机器上经过身份验证的现有配置，示例并不启动或替换模型服务。
恢复沿用同一输出、冻结源码与参数，增加 `--resume`。
独立 Test 使用 `--mode evaluate --split test --skills <run>/final_bank.json` 和相同 split/config。

## 代码结构与阅读顺序

目录根部只保留六个实现文件和包入口。先看主流程，再按调用跳转到相应职责；算法步骤并不一一对应文件。

| 文件 | 职责 |
|---|---|
| [trainer.py](trainer.py) | 配置、模块组装、初始化、每轮流程、最终交付 |
| [optimizer.py](optimizer.py) | 四阶段调用、issue/plan 引用校验、作者调度和单卡构建；不执行 Cal/Gate |
| [evaluation.py](evaluation.py) | Evaluator 持有执行/评分依赖，统一正常 rollout、历史核实、完整 Cal 和隔离 Gate；不接收整个 trainer |
| [search.py](search.py) | 选父版本、簇/错误取样、池留存、不可变版本与预算检查点；不调用模型 |
| [evidence.py](evidence.py) | 公开轨迹投影、实际注入核实、analysis/planning/authoring 视图及上下文取舍 |
| [question_groups.py](question_groups.py) | 冻结的原始输入 embedding/Louvain 分组 |

```text
cluster_v2/
├── README.md
├── trainer.py
├── optimizer.py
├── evaluation.py
├── search.py
├── evidence.py
├── question_groups.py
├── __init__.py
├── prompts/                 # common + 四个独立阶段的 Prompt/Schema
├── chinese_prompts/         # 对应中文镜像；拼接说明合入索引
└── docs/design.md           # 详细算法、伪代码与五轮模拟
```

`prompts/<analyzer|planner|generator|reviser>/{prompts,schema}.py` 保留独立，避免把不同模型任务混在一个提示词文件中。
原 scheduler/search_pool/state_store 整合至 search；cal_evaluator/gate 整合至 evaluation；stages/candidate_builder 整合至 optimizer。旧文件直接移除，无转发层。
原 flow.md 与 README 重复，已合并；设计中的概念模块及算法顺序保持不变。

## 持久化契约

`cluster_v2_evolution/state.json` 保存正式库、池、父子版本、展开/探索额度、停止计数、当前 pending 轮及 Gate 接受/拒绝。
`versions/` 保存不可变库，`tasks/` 保存持久化预算预留；同任务恢复不重复扣预算。
`rounds/NNNN/` 保存四阶段输入/响应/校验和 Cal 收益/退化及来源集中度。
`cal/`、`gate/` 保存隔离评价；`routing/`、`evaluations/` 保存正常与诊断运行记录。
最终 `final_bank.json` 只输出 Gate 接受的正式库；`summary.json` 汇总搜索与预算。

`rounds` 在 v2 表示优化轮数，而非 v1 的完整 epoch。默认 30 轮、每轮最多 2 个候选、总候选 60、逻辑题目评价预算 20000。
预算按唯一库/上下文/有序题集任务预留题数计数；重复使用同任务不重复扣除，但不同子集任务即便复用 rollout 也独立记账。它是保守的搜索预算，不是实际新增推理调用数。
最终 Gate 预算始终保留；作者前预算不足则结束搜索，不生成未完成 Cal 的池成员。

完整库与执行身份的现有 rollout 缓存继续复用。**本版没有新增逐模型请求级缓存或跨库的策略等价复用**；改变库会保守地重算正常选卡/运行，保证不会命中过期正文。
同一 repeat 的缓存是既有样本，不是新的独立复测。

## 验证

`tests/test_global_cluster_v2.py` 使用 CPU mock 复现设计文档五轮模拟、互补降分分支后续修复、单字段锁定、正式库/Gate隔离、transport 中断及 Gate 提交中断恢复、探索额度和诊断配置。
这些测试验证流程正确性，不代表真实模型下能够提高回答得分。已完成旧冻结Prompt的小规模真实工程烟测，见 analysis/skill_evolution/cluster_v2_smoke_20261006.md；后续Prompt修改及动态材料提案尚未经过真实端到端验证。

2026-10-06 验证：v2 与现有 cluster/adaptor/bank 基础设施针对性59项 unittest 通过，compileall 通过。全量270项中268项通过，2项失败属于既有 selector 文字断言（旧规则子串、旧候选标题）；这些 Runtime Prompt 本次未改动。
