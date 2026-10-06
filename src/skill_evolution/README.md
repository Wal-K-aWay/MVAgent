# Skill 离线进化

当前有三个 Global 训练入口。`global-cluster-v1` 使用固定聚类组织 batch、完整库自然选卡、编辑类型反思、独立正文/选择字段作者和完整库 Gate；见 [cluster README](algorithms/alternating/global/cluster/README.md)。

`global-skilladaptor-v1` 实现：Train原始输入embedding＋Louvain、跨batch成功/失败素材、故障定位及Linker的
revise/generate分流、候选生成、完整 Gate 验证、严格总体增益接受。Video Skill 冻结。
实现及命令见 [Global README](algorithms/alternating/global/README.md)，流程见
[flow.md](algorithms/alternating/global/adaptor/flow.md)。Video 阶段和交替调度尚未实现。

runner 负责共享模型、数据、评分和角色算法组装；algorithms/ 管理优化流程；infra/ 管理
数据划分、完整 rollout、评分、角色证据、不可变 Skill 库和持久化。Runtime 不依赖优化器。
历史 build_candidate/paired_gate 为保留审计合同，新流程使用自己的单来源候选与总体增益规则。

`scripts/run_skill_evolution.py --mode train` 使用
`configs/skill_evolution/global_skilladaptor_35b.yaml`，必须给出 Train/Gate split。
默认 `--mode evaluate` 独立评估，不创建 optimizer。`--split test` 仅在独立评估时读取 Test。
新运行冻结源码；恢复通过原入口 --resume 使用所属冻结版本，不用当前源码接续旧算法。
英文 Skill 规范见 [global_skill_specification.md](infra/global_skill_specification.md)。

Cluster v1：`global-cluster-v1`；配置 `configs/skill_evolution/global_cluster_35b.yaml`；流程见 `src/skill_evolution/algorithms/alternating/global/cluster/README.md`；CPU 测试 `tests/test_global_cluster.py`。

当前 Skill 长度规则：四个文本字段合计最多 **1200 words**，when_to_use无独立硬上限；渲染正文（含标题）最多1200 words。统一由 `count_words` 统计字母/数字/下划线组成的词，词内撇号和连字符不拆分，独立标点不计数；cat、analyze_videos、segment_1 各计1 word，1->2 计2 words。这是英文词计数，不是 tokenizer 或中文分词。Prompt 要求简洁英文，通常900–1100 words或更少，上限不是写作目标。配置改为 max_card_words/max_skill_words；旧字符配置不再支持。JSON Schema 仅保留非空和结构检查，单词上限由程序统一校验。冻结实验仍保留原字符口径，不能混用新源码恢复。

Evaluation mode also saves `routing_audit.json`: per-decision selection, actual Actor
body injection, actions/parameters and outcome. Missing Actor requests remain unknown;
selection or injection does not itself establish semantic applicability or usefulness.

Cluster v2：`global-cluster-v2`；见 [cluster_v2 README](algorithms/alternating/global/cluster_v2/README.md)。使用显式 Train/Cal/Gate 分区，四阶段 optimizer、完整 Cal 搜索池及隔离的正式 Gate。配置 `configs/skill_evolution/global_cluster_v2_35b.yaml`，训练不加载 Test；独立评估可选 `--split cal` 或 `--split test`。
