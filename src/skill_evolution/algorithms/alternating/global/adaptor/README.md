# Global SkillAdaptor 适配

当前实现以 [flow.md](flow.md) 为完整流程和模块输入输出说明：
固定全部Train原始输入embedding＋Louvain；每轮Train轨迹入跨batch池 → Localizer → 同簇最多4条成败参考 → 本题唯一 Skill 的 Linker 归因（无卡直接生成）→
Reviser/Generator → 候选程序校验和完全重复检查 → 每候选完整 Gate → 总体严格增益才接受。
只优化 Global；Video 卡冻结，不自动启动 Video 优化、交替调度或 Test。
原始输入聚类与跨batch素材池已接入；额外噪声过滤、Merge及其专用Gate规则仍待实现。

| 文件 | 职责 |
|---|---|
| `trainer.py` | GlobalConfig、采样、故障链预算、库变化后的刷新、Gate、轮末原子提交及恢复 |
| `stages.py` | 模型调用持久化、阶段校验、无卡分流、模型提案转换和完整候选库构造 |
| `evidence.py` | 公开案例、选择/实际注入核实、模型正文渲染、Skill 版本关系及成败素材渲染 |
| `question_groups.py` | Train原始输入embedding、mutual-kNN Louvain及有限同簇近邻选择 |
| `prompts/common.py` | 共享背景、卡片契约和假设内容示例 |
| `prompts/<stage>/prompts.py`、`schema.py` | 各阶段 System TASK、User 文本及输出约束；包级 `__init__.py` 拼接 |
| `chinese_prompts/` | 与 Prompt/Schema 对齐的中文文档镜像，Runtime 不加载 |
| `skilladaptor-reference/` | 上游导读和原 Prompt，仅供参考，运行时不 import |

## 运行

```bash
PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python scripts/run_skill_evolution.py \
  --mode train --config configs/skill_evolution/global_skilladaptor_35b.yaml \
  --execution-config configs/inference/execution/gpu2_7_single.yaml \
  --split-manifest /absolute/path/to/split.json \
  --output-dir /absolute/path/to/new_run
```

不传 `--skills` 从空库开始。Global 要求 `selection_scope: task` 和 Embedding。
GLM 凭据由 BIGMODEL_API_KEY 提供；有开放题时还需要配置的固定 Judge。普通闭式题不创建 Judge。
复用已有 Actor/Embedding 服务和池身份验证，不自动部署服务。`--limit` 仅供 evaluate，不用于训练采样。

训练参数为 rounds、batch_size、patience、seed、issue_score_threshold、max_card_words。
默认分析健康非满分题；Localizer 每链最多三个不同的可编辑步骤，实际尝试预算为初始链长度。
每个步骤最多一个修改/新建操作，接受后有预算的案例可在新库下重新推理与定位继续处理。

## 模型契约

- 各阶段 System 包含 TASK + BACKGROUND；作者阶段再加入 含两字段正反例的 CARD_CONTRACT。
- Localizer User 分为 Input、selected skill、steps、output、ground truth；只定位公开行动/参数/执行缺陷，
  输出 status/reason/fault_chain，每项含 step/fault_type/evidence_reason/improvement_principle。
- Linker 只接收本题固定使用的一张卡，输出 status=revise/generate 与 reason，没有卡列表、权重或 skip。
- Reviser 输出 update_mode、target_skill_id、revision_summary、完整 skill_profile；skip 时 profile=null。
- 公开案例删除 Global 决策/最终答案 reason，主案例不渲染 score 或评分解释；参考案例显示成功/未完全成功及定位状态；原始轨迹与审计数据保留。
- 单次阶段请求先持久化再校验，无阶段级纠错；候选两字段总长度由程序限制。

中文入口：[chinese_prompts/README.md](chinese_prompts/README.md)。文档修改不改变 Prompt；
修改模型可见英文文本或 Schema 时同步对应中文镜像。

## 分组、接受与恢复

正式分组只编码完整题目/选项和逐视频ID/时长，采用32互近邻、cosine阈值0.55、Louvain resolution2、固定seed，不预设簇数。
全部Train输入统一分组，轨迹按batch到达；每题最新健康轨迹参与跨batch检索，优先成功/未完全成功各2条、最多4条。
无边单例保留，可独立进化；额外噪声规则未实现。故障定位只触发进化，不影响分组。
同组相关案例保留实际卡快照和各自证据边界，成功不证明Skill因果，只有有依据的同版卡失败可支持当前卡缺陷。
Generator不输入整库，Reviser只保留目标卡；拒绝候选和修订历史仍提供参考。

候选只做 Schema/完整库构造/完全相同内容检查，没有独立语义 Validator 或语义去重。
通过后直接执行完整 Gate，总体严格增加才接受；持平拒绝。分任务和健康差异只记录，Gate 细节不进入优化器。

`global_evolution/state.json` 为轮末提交点，`versions/` 保存不可变库；`rounds/` 保存阶段、分组、尝试和验证；
`evaluations/` 保存 compact report，原始推理/评分由共享缓存保存；`question_groups.json` 保存固定输入分组，`embeddings/` 保存输入向量；
`rounds/NNN/materials.json` 保存本轮每题最新素材更新，state引用路径与哈希，恢复时严格校验并重建最新案例池；
`final_bank.json`、`summary.json` 保存终态。

`--resume` 必须使用运行自己的冻结源码及一致配置/数据/库/模型/Prompt 身份。
未提交轮重放可以复用已持久化阶段响应和评估缓存，接受单个候选不等于立刻提交恢复游标。
非阻塞训练锁拒绝并发写同一输出；无效模型输出记录并跳过，实际抛出的传输/身份/评分错误中止。

当前默认max_card_words=1200，与Runtime单卡总文本/渲染正文上限一致。

当前 Skill 长度规则：两个文本字段合计最多 **1200 words**，when_to_use无独立硬上限；渲染正文（含标题）最多1200 words。统一由 `count_words` 统计字母/数字/下划线组成的词，词内撇号和连字符不拆分，独立标点不计数；cat、analyze_videos、segment_1 各计1 word，1->2 计2 words。这是英文词计数，不是 tokenizer 或中文分词。Prompt 要求简洁英文，通常900–1100 words或更少，上限不是写作目标。配置改为 max_card_words/max_skill_words；旧字符配置不再支持。JSON Schema 仅保留非空和结构检查，单词上限由程序统一校验。冻结实验仍保留原字符口径，不能混用新源码恢复。

2026-10-05 当前规范：新卡引用编号由程序分配顺序数字字符串，Generator只返回四个内容字段，不生成命名ID；修订保持已有引用。引用字段仍用于选卡、归因和版本关联，不承载语义。CARD_CONTRACT使用客观字段规范，Design requirements说明各字段作用、内容细节和样例；无独立字段上限提示。整卡及渲染正文总预算保留。历史冻结源与卡库不改写。
