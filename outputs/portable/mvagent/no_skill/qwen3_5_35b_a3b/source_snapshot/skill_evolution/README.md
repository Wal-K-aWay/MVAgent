# Skill 自进化：公共设施与运行方法

本目录把**执行问答的公共设施**和**决定如何更新 Skill 的算法**分开。MVAgent 本身只负责回答问题，不知道训练集、标准答案或优化器。

本文描述已实现流程。按用户最新要求，保留现有交替反思/merge/ranking/joint，最小接入
SkillOpt 的 slow update 和 optimizer meta skill；候选池/新搜索架构暂不实施。
默认关闭两项新增机制，测试配置显式开启。唯一测试计划见
[当前方案](../../analysis/skill_evolution/next_steps.md)。

## 1. 代码在哪里

| 路径 | 职责 |
|---|---|
| `infra/data.py` | 固定样本清单、分批、媒体分组、划分审计、执行身份 |
| `infra/rollout.py` | 候选 Skill 配置、逐题缓存、公共 BatchExecutor 的薄适配 |
| `../mvagent/batch.py` | 共用题目 worker、动态队列、超时与重试 |
| `../models/pool.py` | GPU 请求分配、服务限流、媒体准备上限和故障隔离 |
| `infra/trajectory.py` | Global 公开视图、Video 本地视图、决策状态、调用关系 |
| `infra/evaluation.py` | 独立评分、聚合、逐题比较与执行指标 |
| `infra/skills.py` | 两角色 Skill 文本、增删改、全文设置、diff |
| `infra/store.py` | 原子文件、内容摘要、缓存文件 |
| `infra/benchmarks/` | 复用现有 CrossVid、CVBench、MVU-Eval 适配器和 scorer |
| `algorithms/alternating/trainer.py` | 原有短步 Video／Global 更新和 epoch 末联合检查 |
| `algorithms/alternating/gate.py` | 三次完整系统配对重复的接受规则 |
| `algorithms/alternating/longitudinal.py` | SkillOpt 保护区、纵向对照与 meta memory 展示 |
| `runner.py` | 装配公共设施，启动算法；不决定候选是否接受 |

旧的 Beam、Patcher、归因器、Reviewer、Planner replay 实现及重复入口已删除。历史实验通过各自 `outputs/.../src/` 冻结源码追溯，不迁移旧 checkpoint。

当前只保留自有 `alternating` 算法，其角色顺序、反思／merge 和预算沿用原实现；Gate 使用三次 fresh 配对重复。独立的上游 SkillOpt Trainer 适配已删除；本算法使用的 SkillOpt／GEPA Prompt、来源与许可证仍完整保留，原文没有改写。轨迹恢复原有角色视图，保留原本已有的 Observe 区间与有效 FPS；不附加专项异常诊断字段。

算法代码和 Prompt 集中在一个目录：

```text
skill_evolution/
  algorithms/
    alternating/
      trainer.py
      gate.py            # 三次完整系统配对重复的共享接受判定
      prompts/           # 本算法使用的 SkillOpt/GEPA 模板、接入文本、来源与许可证
  infra/
    benchmarks/
      open_qa.py         # 与其他数据适配器、评分器放在一起
      prompts/
        open_qa_judge.md
    ...                  # rollout、轨迹、Skill 文本、存储等公共模块
  runner.py
```

alternating 直接读取自己的 Prompt 文件，不导入或依赖安装包 `skillopt`。公共 Judge 与具体优化算法无关，归 `infra/benchmarks` 管理。

## 2. 完整运行流程

```text
读取配置、固定源码和划分，审计共享媒体
    ↓
建立 rollout worker、评分线程、轨迹与 Skill 接口
    ↓
算法指定：SkillSet + 样本 ID
    ↓
缓存命中 → 直接读原始问答
缓存未命中 → 空闲 worker 领取一题 → 完整运行 MVAgent
    ↓
每完成一题，立即原子保存，再提交给评分线程
worker 随即领取下一题；不等待该题 Judge
    ↓
所有题完成并评分后，返回总分、逐题结果和轨迹
    ↓
算法选择证据、反思、修改、评估候选、接受或拒绝
    ↓
保存算法 checkpoint；进入下一次算法操作
```

worker 是独立进程，每个进程顺序复用一个 Engine。达到单题 deadline 后回收该进程，释放本地请求槽并按配置重试该题；不关闭共享 vLLM 服务。重试耗尽则本批明确失败，已完成题目仍在缓存，恢复时只补未完成题。

同一次 `analyze_videos` 内，不同 VideoAgent 可并行运行。每个 VideoAgent 仍只有自己的 Memory；Global 等待本轮全部返回，并按原始视频顺序得到 report。同一 Video 的多个请求没有被并行拆开。

### 当前交替算法的内部流程

实现位于 [trainer.py](algorithms/alternating/trainer.py)，与 [后续方案](../../analysis/skill_evolution/next_steps.md) 中尚未实施的改进分开。

```text
先评估初始 SkillSet，作为基线
每个 epoch：
    打乱 Train，按 batch_size 分批
    每批依次优化 Video、Global；另一角色冻结：
        用当前 SkillSet 跑这一批完整问答（已有相同结果则读缓存）
        提取目标角色轨迹，按系统成败分组
        每组按 minibatch_size 反思，分别逐层 merge
        将成败两路建议最终 merge；编辑数超过 top_l 时才 ranking
        应用编辑并检查字符预算；不合格则结束本步
        候选与父版本做三次完整 Eval fresh 配对；中间一次反转执行顺序
        至少两次宏分差为正、三次平均分差为正、均无逐题新增 fatal/invalid 才接受
    做一次 joint 提案，修改两角色并走相同 Eval Gate
以独立于训练 Gate 的三次配对重复确认初态/终态；通过则选用终态，否则选回初态，并保留终态候选与实际复测分数
```

快速更新仍无逐候选 Train 前后对照；可选 slow/meta 增加相邻 epoch 同题执行对照。Gate 的 repeat_id 绑定输出运行、完整父/候选 pair 和协议；不同重复生成新轨迹，
同一已拒绝 pair 不追加抽样，恢复只补缺失记录。`majority-positive-mean-v1` 规则标识进入训练和 Gate 缓存身份；历史三次全正规则的判定不作为新规则缓存恢复。`gates/<key>/` 保存逐次比较与汇总，`attempts/`
保存所有槽位（pending、静态失败、无改动、无证据、模型输出非法、接受、拒绝）；近期反馈按角色分别取四条，
只有 Eval 汇总进入 optimizer。终态确认使用独立身份，其结果仍是选择集证据，不是 Test。
旧单次缓存 Gate 的限制及实验结果见 [失败原因分析](../../analysis/skill_evolution/failure_analysis.md)。
`batch_size` 是一次角色更新使用的题数，`minibatch_size` 是一次反思调用读取的轨迹数；它们不控制 GPU 并发。

固定候选校准入口为 `scripts/analysis/run_gate_calibration.py prepare --output <新目录>`；之后使用输出目录的
`run.py smoke|run|analyze --output <同目录>`。每组 200 Eval × 3，五组共 3,000 问答；它不调用 optimizer，
不训练或推广 Skill。源码/配置/候选冻结，后台状态见 progress.json，完成后写 report.json。

### 可选 SkillOpt slow update / meta skill

2026-09-12 接口修正：fast 编辑正文的 H1/H2、中文限制进入既有 Schema 单次修复；
移除未核实的逐编辑 support_count，发送 merge 模板时同步删除计数要求；空起点说明
已有 Runtime 基础策略，并要求每项编辑自包含。slow/meta 额外读取本 epoch 按角色筛选的
接受/拒绝清单，区分冻结对照前后发生的尝试；meta 能看到本角色刚完成的 slow Gate。
只给聚合 Eval 反馈，不增加 Video 局部 GT。Gate、Runtime、提议机会和搜索流程不变。

`training.use_slow_update` 和 `training.use_meta_skill` 为独立布尔开关（默认 false），
`training.slow_update_samples` 默认 20。每 epoch 原有 Video/Global/joint 完成后增加一个
slow_meta 槽位：第一轮只保存末尾 Skill pair，第二轮起在同一随机 Train 面板比较相邻
末尾 pair；默认采样 seed 为 seed + epoch_number × 2000。两侧各自运行完整 MVAgent，
再用现有角色视图给 Global/Video 分别提供对照，整题结果不被解释为 Video 局部 GT。

两份原始模板文件按字节保留；slow 发送版本将“没有长度限制”替换为动态正文长度、英文 H3/H4 标题与原 diff 预算说明，meta 仍原字节发送。保护区、对照展示、meta 包装采用上游纯函数。slow
为对应 Agent 生成受保护指导，使用上游支持的 selection-gated 模式接入现有三次
Eval Gate 和 2,000 changed / 6,000 total 字符约束。通过才更改角色 Skill；fast/joint
不能增删改该保护区。首轮不插入空占位，避免仅为标记而改变初始策略；首次实际接受才创建。
meta 使用同一冻结对照（不包含本次尚未执行的 slow guidance），更新每角色 optimizer
记忆；只在下一轮该角色 analyst/merge/ranking User Prompt 前注入，不写入任何在线 Skill。
joint 保留原流程，不新增 meta 输入。

slow 的 JSON Schema 按剩余总长度、已有正文和编辑预算限制正文长度，首次创建扣除保护标记/分隔符。标题和标记也在 Schema 校验，失败复用现有一次修复。已有正文替换仍需通过原新增+删除量检查；Schema 长度只是上界，不替代 diff。Gate 不变。

`slow_meta/epoch_NN/` 保存完整前后角色对照和阶段摘要，`attempts/` 保存 slow Gate/meta
结果。checkpoint 包含前一 epoch 末尾 pair 与两份 meta memory。epoch 边界中断时回放
已经缓存的调用/Gate，完成整个边界后原子提交，不能让半轮记忆或伙伴状态丢失。

本接入不等于完整上游 Trainer：保留本项目交替与 joint；不采用固定代码默认的
force-accept slow guidance；不增加候选池、局部奖励或新 Gate。默认 API profile 仍用
GLM-5.3-Flash，Runtime/Observer/Judge 不变。测试必须至少三个 epoch，才能检查第
二轮 meta 是否确实影响第三轮提议。

测试配置：`configs/skill_evolution/seed_v001_slow_meta_smoke_glm53_flash.yaml`（8/4）与
`seed_v001_slow_meta_train300_eval200_glm53_flash.yaml`（300/200）。两者均为三轮，启动时
必须显式 `--skills` 指向冻结 seed-v001 pair；文件名不自动加载 seed。沿用四卡执行配置。

## 3. 一个入口：训练或独立评测

在仓库根目录运行：

```bash
PYTHON=/home/kww/miniconda3/envs/MVAgent/bin/python

# 现有 130 Train / 70 Eval，短步交替算法；用新的输出目录。
$PYTHON scripts/run_skill_evolution.py \
  --config configs/skill_evolution/alternating_multibench_train130_eval70_qwen38_gpu4_7.yaml \
  --execution-config configs/execution/gpu5_7.yaml \
  --output-dir outputs/skill_evolution/infra_train130_eval70

# 独立评测：省略 --skills 表示两角色均无 Skill，不创建 optimizer。
$PYTHON scripts/run_skill_evolution.py \
  --config configs/skill_evolution/alternating_multibench_train130_eval70_qwen38_gpu4_7.yaml \
  --execution-config configs/execution/gpu5_7.yaml \
  --output-dir outputs/skill_evolution/infra_eval \
  --mode evaluate --split eval --limit 4

# 同一实验恢复：保留原命令及参数，追加 --resume。
# 真正重新生成轨迹：换输出目录，设置新的 --repeat-id，例如 --repeat-id repeat-1。
```

评测指定完整 SkillSet JSON：

```json
{"global_skill": "### Policy\nUse the available evidence.\n", "video_skill": ""}
```

通过 `--skills /path/to/skill_set.json` 加载。也可以使用算法输出中的 `skill_set.json`，不能把审计 summary 当成此文件。

训练固定使用 alternating，不再提供 `--algorithm` 选项。完整项目依赖见根目录 `requirements.txt`，不需要安装上游 SkillOpt。配置中的 `optimizer` 指定模型，`training` 指定本算法参数。

支持 `--dataset-root`、`--split-manifest` 覆盖配置。独立评测可以选 `--split test`，其 version-2 manifest 可仅包含 Test。训练必须有 Train 和 Eval，且不加载 Test 记录。Eval 用于候选选择，不是独立 Test。

原始 130/70 清单保持不变，其共享视频问题写入 `data_audit.json`。

### 固定 500 题开发集：300 Train / 200 Val

清单位于 `configs/skill_evolution/splits/multibench_train300_val200_seed20260908.json`。
文档中的 Val 对应现有代码和命令中的 `eval`，不另加 split 名称。

历史 Qwen3.5 9B / 27B / 35B-A3B 在相同 500 题上的直接端到端基线见 [统计报告](../../outputs/analysis/20260908_e2e_baseline_train300_val200/report.md)，包含逐题结果、300/200 分项和来源哈希；这不是 MVAgent 无 Skill 的基线。

| 数据集 | Train | Val | 每个原生题型的配额 |
| --- | ---: | ---: | --- |
| CrossVid | 120 | 80 | 10 个题型，各 12 Train / 8 Val |
| MVU-Eval | 96 | 64 | 8 个题型，各 12 Train / 8 Val |
| CVBench | 84 | 56 | 单一汇总题型 |
| 合计 | 300 | 200 | 500 题 |

按用户最终要求固定为 300/200，兼顾 Skill 训练样本与验证规模；判断小幅变化时仍需重复验证。原来的 500 道题完全保留，以 250/250 为父清单，将 Val 中 40 个完整来源组、共 50 题移入 Train；原 Train 全部保留，旧 250/250 和中间 350/150 清单及审计不覆盖。调整只使用固定 seed、题型配额和素材关系，不按模型得分、是否答对或历史失败挑题。Train 用于反思和修改 Skill；Val 用于候选选择与开发回归，不能当作未参与调参的独立 Test。需要最终泛化结论时另设 Test。

混合数据准备脚本交替选取两边的题目，把相同输入视频、内容相同的副本，以及已知的原始素材限定在同一集合。PEA/PI/PSS 检查裁剪前的原视频；MOC/MSR 检查同一 UAV 序列，避免不同 bbox 渲染文件掩盖同源关系。同源题可以位于同一集合，实际来源组数见伴随 `.audit.json`。传递分组只计算入选题目，不让未入选的组合题连接两组本来不重叠的素材。素材检查不改动题目、Prompt、片段或 bbox。

本清单包含 Train 268 个、Val 181 个来源组，跨集合共享为 0；500 个题目与视频的完整输入均不同。素材与输入未变，沿用父清单对 1,649 个实际输入视频的元信息及首帧读取检查。与旧 130/70 仍有 11 个样本 ID 重叠，不能声称它们都是从未使用过的题目。新审计记录包含父清单 SHA256、完整转移 ID 和来源组，能够精确还原这次调整。

在本节现有训练或独立评测命令上加下面的参数即可使用新清单：

```bash
--split-manifest configs/skill_evolution/splits/multibench_train300_val200_seed20260908.json
```

训练会读取两个集合；独立评测分别使用 `--mode evaluate --split train` 和 `--mode evaluate --split eval`，每次使用新的输出目录。模型、Judge、batch/minibatch 和 GPU 配置仍由实验配置指定，清单不改变这些设置。

原始 500 题的生成命令（生成父清单 250/250；不要覆盖已使用的清单）：

```bash
$PYTHON scripts/prepare_multibench_skill_evolution_split.py \
  --dataset-root /home/kww/datasets/Multi-Video \
  --output /tmp/multibench_train250_val250_seed20260908.json \
  --seed 20260908 \
  --crossvid-choice-train-per-task 10 --crossvid-choice-eval-per-task 10 \
  --crossvid-nonchoice-train-per-task 10 --crossvid-nonchoice-eval-per-task 10 \
  --mvu-train-per-task 10 --mvu-eval-per-task 10 \
  --cvbench-train 70 --cvbench-eval 70
```

300/200 是对父清单的分组转移，不是用不同配额重新抽题。要复现它，读取新 `.audit.json` 的 `parent_manifest`，只把 `moved_eval_to_train_ids` 对应行的 `split` 改成 `train`，保留其余字段及行顺序，再通过 `DataSplitManifest.write` 写入新文件。

脚本按需读取候选素材计算摘要，配额无法在隔离约束下满足时直接报错。清单与审计记录一起固定，后续迭代不重新抽样。旧 130/70 只保留作历史对照。

## 4. 并发与缓存设置

题目并发现在由公共 `mvagent.batch.BatchExecutor` 执行。`infra/rollout.py` 只提供候选配置、缓存和结果包装；批量测试使用同一执行器。

资源配置使用单独的 `--execution-config configs/execution/gpu5_7.yaml`：

```yaml
question_workers: auto
max_prepared_requests: auto
question_timeout_sec: 1800
question_retries: 1
media_cache:
  root: .cache/mvagent/media
  max_bytes: 10737418240
model_pools:
  qwen3_5_35b_a3b_local:
    replicas:
      - gpus: [5]
        endpoint: http://127.0.0.1:8102/v1
        max_inflight: 2
      - gpus: [6]
        endpoint: http://127.0.0.1:8100/v1
        max_inflight: 2
      - gpus: [7]
        endpoint: http://127.0.0.1:8001/v1
        max_inflight: 2
```

- `question_workers` 是并发题目数；`auto` 为健康 Agent 服务额度之和，此配置为 6。
- `max_prepared_requests` 限制读取/Base64 后持有媒体的请求数；`auto` 为额度总和的两倍，此配置为 12。
- `max_inflight` 是整个 endpoint 的在途请求额度，跨 worker、跨批量入口共享。
- GPU 编号可不连续，也可用完整 UUID；一个 `gpus` 列表定义一个服务的设备组。
- 不设置 `media_cache` 或设为 null 时关闭媒体缓存；示例明确启用 10 GiB。
- MVAgent 配置里的 `runtime.video_concurrency` 仍控制一道题内部的 VideoAgent 并发。

每道题保留在一个 CPU worker，但每次 decide/observe/watch/收尾请求可以切换服务。CPU 裁剪不占推理名额。超时且服务端完成情况未知时隔离 endpoint，其他服务继续；所有必需服务都不可用时明确结束并保留已完成题目。

`--resume` 保留原输入、模型/Skill/评分配置和源码快照，可更换资源配置里的 GPU、worker 数和请求额度；每次调用记录在 `executions/`。改变整题 timeout/retry 仍要求新实验。真实性能对照使用新 `repeat_id`，并注明媒体缓存冷热状态。

具体流程与代码边界见 [共享执行方案](../../analysis/roadmaps/shared_gpu_request_pool_20260907.md)。算法的 batch/minibatch 是证据批次，不是 worker 并发参数。

## 5. Skill 修改接口

```python
from skill_evolution.infra.skills import SkillSet, apply, set_text, set_pair

parent = SkillSet(global_skill="### Policy\nOld rule.\n", video_skill="")
change = apply(parent, {
    "global": [{"op": "replace", "target": "Old rule.", "content": "New rule."}],
    "video": [{"op": "append", "content": "### Observe\nInspect the requested event."}],
}, expected_parent_hash=parent.skill_set_hash())

candidate = change.skills       # 两角色一起校验；失败时 parent 完全不变。
diff = change.changes           # 每角色 added/deleted/changed 字符数及 unified diff。
cleared = set_text(candidate, role="video", text="").skills
replaced = set_pair(parent, candidate).skills
```

支持 `append`、`insert_after`、`replace`、`delete`。后三者的 `target` 必须在同一父文本中精确出现一次；多个编辑不能覆盖同一范围。`insert_after` 在目标所在行之后插入。删掉整段或通过 `set_text(..., text="")` 可禁用该角色 Skill。

全文候选用 `set_text` 或 `set_pair`，不必伪装成追加。接口负责文本有效性、父版本和 Runtime 长度上限；每步允许修改多少、是否值得接受，由算法决定。

## 6. 轨迹查询和独立重评分

```python
from skill_evolution.infra.trajectory import global_view, video_view, decision_view, dependency_links

public = global_view(episode)
local = video_view(episode, video_id="video_1", request_id="req_1")
state = decision_view(episode, decision_id="video:video_1:req_1:1")
links = dependency_links(episode)
```

`global_view` 返回公开 History；`video_view` 返回指定请求及该视频之前的本地观察；`decision_view` 从原始审计事件返回真实 Planner 请求、Schema、修复与响应。节点 ID 在一道题内唯一，跨候选使用 execution cache key 区分。调用关系用普通列表管理，不引入图数据库，也不自动决定更新哪个角色。

公共 `evaluate_batch` 组合 rollout、score 和 aggregate；`compare` 给出同一批题的分数变化与执行指标，不作候选决策。`CachedScorer.score_results(episodes)` 可直接对已保存的 `RolloutArtifact` 重评分，不调用 Runtime。

## 7. 输出与恢复

```text
<output>/
  src/                    # 本次冻结源码
  manifest.json           # 模型/配置/数据/源码身份；敏感配置脱敏
  runtime_config.json     # 启动时 Runtime 配置的脱敏副本
  split_manifest.json
  data_audit.json
  skills/<pair_hash>/     # 不可变两角色正文、配置和 SkillSet JSON
  rollout_events.jsonl    # 调度、模型、媒体、错误、服务指标及缓存引用
  state/                  # 所选算法的 checkpoint
  current_skill_set/      # 最后接受的搜索版本；不是历史最佳或最终确认结论
  selected_skill_set/     # 仅在最终确认完成后写入；通过选 current，否则选 initial
  summary.json

<cache>/
  rollouts/<key>.json     # 完整单题原始记录，不含标准答案
  scores/<key>.json       # 独立 scorer 结果
  open_qa_judge/          # 原有固定 Judge 缓存
  media/                 # 内容寻址、带租约的媒体缓存
```

训练 summary 的 `evolution_status` 为 `confirmed_improvement`、`unconfirmed` 或 `unchanged`；
只有不同于初态且通过最终确认的终态才标记为确认收益。`selected_source` 指明 `current` 或 `initial`。
`current_confirmation_score` 与 `current_skill_set_hash` 始终描述末态候选，
`selected_confirmation_score` 与 `selected_skill_set_hash` 描述实际选用版本；
`final_confirmation` 保留原始父子分差和失败事实。回退不算进化成功，同一 Eval 上的新执行也不是独立 Test。
`output_selection_rule=confirmed-current-or-initial-v1` 进入训练身份；不提供旧输出字段或目录的兼容层。

执行 key 包含 Runtime 源码、运行配置、输入视频内容／顺序、问题、两角色 Skill 和 repeat_id。改变 optimizer 或训练策略不要求重跑相同问答；改变 scorer／参考答案只重评分；改变聚合方式只重聚合。

源码每次新实验冻结一次；配置在建立 Executor 时复制，后续候选不会再次读取被编辑的 YAML。`--resume` 要求原始输入、配置和参考信息与运行清单一致，否则使用新输出目录。凭据不写进候选 YAML，worker 从父进程内存接收有效配置。

## 8. 验证

```bash
PYTHONPATH=src /home/kww/miniconda3/envs/MVAgent/bin/python -m unittest discover -s tests
```

覆盖真实子进程卡住后的回收、逐题保存、缓存恢复、重复实验身份、评分失败与重评分、四种编辑和联合原子性、跨视频 Memory 隔离与有序返回、媒体缓存复用、自有交替算法、上游 Prompt 原文校验和冻结源码加载。

2026-09-07 的小规模实测记录在 `outputs/analysis/20260907_infra_validation/`：使用 GPU6–7 的 Qwen3.5-35B-A3B 和 GPU4 的 Qwen3.8-27B Judge，涵盖 choice、OpenQA、temporal、ordering。它用于验证基础设施，不用于判断 Skill 进化收益。GPU5 当时的服务探测不稳定，因此此次四题检查没有使用它，也没有重启共享服务。

公共 GPU 请求池的验收见 [验证报告](../../analysis/reports/2026-09-07_shared_gpu_pool_validation.md)。
