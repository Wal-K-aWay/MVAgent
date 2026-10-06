# 当前入口

`global_skilladaptor_35b.yaml`：Global SkillAdaptor 适配阶段，完整 Gate 总体分提高即接受。
使用 --mode train 和显式 --split-manifest；Video 冻结。其余过时配置说明只用于历史追溯。

## 历史配置说明

以下旧算法和配方不适用于当前训练入口；复现使用所属冻结源码与配置。

# Skill自进化配置

- 本层YAML：实验训练/评估方案，包括数据、optimizer、Judge、训练参数和缓存。
- `runtime/`：同时定义Actor、optimizer及可选Judge的MVAgent配置。
- `execution/`：包含本地optimizer服务的专用GPU池。
- `splits/`：固定数据划分及来源审计；保留250/250、350/150等父清单是为了追溯300/200的来源，不是当前推荐实验。

`splits/crossvid_lite2500_eval_seed20260919.json`是已冻结的2500题CrossVid开发评估子集（全部为`eval`），不是训练集或新Gate。配套`.audit.json`记录来源及完整审计位置。使用独立evaluate模式，不自动修改现有训练配方；后续新增Train/Gate须排除其源媒体。详见[子集报告](../../analysis/skill_evolution/crossvid_lite2500.md)。

历史GLM入口是`alternating_multibench_train130_eval70_glm53_flash_gpu5_7.yaml`，
引用`runtime/local_qwen35_35b_a3b_glm53_flash_optimizer_gpu5_7.yaml`；凭据来自
`BIGMODEL_API_KEY`。GPU放置独立于文件名，可传共享的
`configs/inference/execution/gpu2_7_single.yaml`。

历史 YAML 保留其命名的训练参数，但已移除不再支持的 joint_size；不能据此重现旧 joint/三次 Gate。
历史复现使用原输出内冻结源码和配置。当时算法为单次 Gate、无 joint 的 MVAgent 适配版本；当前入口见下节。
2026-09-16 E0–E3 共享协议与精确快照位于 outputs/mvagent/skill/20260916_evolution_redesign/；
当时配置入口为 redesign_train130_gate300_glm.yaml，运行要使用对应快照与冻结配置。

## 2026-09-23 当前入口

以上静态SkillOpt配方属于历史复现，应使用原冻结源码。当前根入口为
`bank_lifecycle_27b.yaml`，引用`runtime/dynamic_27b_embedding.yaml`：27B Actor/Selector/Observer、
8110 Embedding、GLM optimizer。必须传来源隔离的`--split-manifest`；不传`--skills`从空库开始。
`maintenance_ids`是预先从Eval留出的确认题，不是Test；空列表禁用平分维护接受。
完整启动、保护层与恢复合同见[实现说明](../../src/skill_evolution/README.md)。

2026-09-28：GEPA 试验代码与三份 recipe 已移除。历史 GEPA 运行使用原冻结版本。

2026-09-24：当前35B runtime的Global/Video均显式设置`selection_scope: task`。Runtime统一只选一张或空选，已删除`max_selected`配置。
Global每QA选至多一张并保持；Video每个request选至多一张并保持，新request重选。
合法空选择仍允许。task选择器评估完整流程，候选只提供 id/when_to_use。
旧实验用输出中的冻结配置/源码，不能用当前配置续接；此处修改未启动新的进化。

## 2026-09-24 Global-only

`global_targeted_35b.yaml`：独立 `global-targeted-v1`，35B Actor，现有 embedding，GLM optimizer；
每轮一个 Global 提案，Video 冻结；不调用 GEPA，不交替角色。必须提供 Train/Gate 来源隔离 split。
未提供初始库则从空库开始。所有修改接受均要求 Gate 正收益。
Global 模型输出为 SkillClaw 四操作 improve_skill/optimize_description/create_skill/skip；
不再支持合并、删除。exploration_interval 仅调度证据组，不限制组内合法操作。

Global-only经验版默认4轮、batch64；`use_train_memory: true`、
`reflection_minibatch_size: 8`、`exploration_interval: 4`。
记忆只供离线优化器使用；关闭记忆读取、将反思大小/探索间隔置0可做逐项消融。
每轮一个目标，最多两次反思小批次；完整Gate验收合同不变。

`skills/crossvid_global_v001.json`: authored10-card Global-only dynamic bank,
input-grounded CrossVid coverage. Not enabled by default or performance validated.
English cards: `src/mvagent/skills/authored/crossvid-v001/`;60 real input examples and
scope: `analysis/skill_evolution/crossvid_global_library_20260925/`.

`skills/crossvid_global_patterns_v001.json`: alternative8-card Global bank organized
by shared evidence/reasoning workflows; old10-card bank retained. Both are authored
candidates, not validated defaults. See the same report directory, `patterns.md`.

`skills/global_acquisition_v001.json`:4 authored Global acquisition-strategy cards,
with concrete local instructions and illustrative interval examples. Not enabled or
performance validated; see analysis/skill_evolution/acquisition_skills_20260925.md.

`skills/global_acquisition_v002.json`:11-card authored Global library generalizing
acquisition-v001's action/parameter-oriented style across the original60 CrossVid inputs.
No default switch. For initial full-catalog evaluation explicitly set retrieval_top_k=11;
selection remains one or none (do not configure the removed max_selected field).
Report and source-linked hypothesis mappings: analysis/skill_evolution/acquisition_library_v002_20260925/.

2026-09-26：当前动态卡采用结构化 JSON（meta、when_to_use、strategy）。
筛选只看 when_to_use，执行只插入 strategy；大于8张时 BM25+embedding 融合取8张。
优化器 Schema 与输出同步；max_card_words 限制两个文本字段总长度。历史冻结运行不能用新源码恢复。

Cluster v1：`global-cluster-v1`；配置 `configs/skill_evolution/global_cluster_35b.yaml`；流程见 `src/skill_evolution/algorithms/alternating/global/cluster/README.md`；CPU 测试 `tests/test_global_cluster.py`。

当前Skill上限统一1200 words，配置中的max_card_words/max_skill_words已同步；历史冻结实验配置不修改。cluster可通过training.cluster_anchor只优化全Train聚类中的一个原簇。

当前 Skill 长度规则：两个文本字段合计最多 **1200 words**，description 最多60 words，when_to_use 最多120 words；渲染正文（含标题）最多1200 words。统一由 `count_words` 统计字母/数字/下划线组成的词，词内撇号和连字符不拆分，独立标点不计数；cat、analyze_videos、segment_1 各计1 word，1->2 计2 words。这是英文词计数，不是 tokenizer 或中文分词。Prompt 要求简洁英文，通常900–1100 words或更少，上限不是写作目标。配置改为 max_card_words/max_skill_words；旧字符配置不再支持。JSON Schema 仅保留非空和结构检查，单词上限由程序统一校验。冻结实验仍保留原字符口径，不能混用新源码恢复。

Cluster v2：`global_cluster_v2_35b.yaml` 使用 `global-cluster-v2`。必须提供冻结的 version=2 split，包含 train/cal/eval（Gate）；test 仅用于独立 evaluate。默认 30 优化轮、每轮最多2候选、完整评价2重复、池3、互补2题、纯探索2次及25%预算上限、每2轮Gate。参数详见 cluster_v2/README.md；不会自动改旧 split 或启动模型服务。
