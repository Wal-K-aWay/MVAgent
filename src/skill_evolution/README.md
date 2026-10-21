# Skill 方法

固定MVAgent和模型权重，分别提供无反馈的一次生成基线与角色轮换的反馈优化闭环。
方法依据、数据边界、实验取舍见[设计文档](../../docs/skill-evolution-design.md)。

```text
skill_evolution/
├── configs/                 # EvolutionConfig；复用已有API模型配置/客户端
├── infra/                   # 卡库编辑/冻结、公开轨迹投影、调用留存、角色契约、评估结果接口
├── algorithms/
│   ├── one_shot/             # 每角色一次生成，原Prompt与公开入口保留
│   └── rolewise/             # 一次改单角色一张卡，Train反馈，整库Cal/Gate
└── skill_specification.md    # 写卡规范，不自动加载进模型上下文
```

Python配置解析在`configs/`，实验YAML在仓库根`configs/skill_evolution/`。
`infra`不选择算法、不包含benchmark/数据加载/评分；这些能力复用`eval/`。
原子保存/哈希直接复用`mvagent.utils.io`，没有恢复旧store或另写一套Judge/批处理器。
公开轨迹投影参考`de28149`的算法无关思路，改为复用当前Global/Video Memory渲染器。
旧adaptor/cluster/scope训练器未恢复，不作为本方法前提。

## 一次生成

```bash
python scripts/generate_skills.py --role both --output-dir /runs/one-shot/new-run
```

默认DeepSeek-Flash，每角色由LLM自主生成1–8张；`--max-cards N`是上限而非配额。
只读任务/角色/基础System/动作契约，不读题目、轨迹或反馈。输出和中文Prompt镜像见
[生成说明](../../docs/llm-skill-generation.md)。现有DeepSeek冻结对比库见
[`skill_sets/`](../mvagent/skills/skill_sets/README.md)，不是进化初始化。

## 角色轮换优化

先准备独立的Actor服务与固定本地CCQA Judge，再运行：

```bash
python scripts/evolve_skills.py \
  --config configs/skill_evolution/evolution.yaml \
  --optimizer-config configs/skill_evolution/llm_generation.yaml \
  --runtime-config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --execution-config /runs/my-run/execution.json \
  --split-manifest /runs/my-run/split.json \
  --dataset-root /assets --judge-endpoints http://127.0.0.1:8207/v1 \
  --output /runs/my-run/evolution
```

默认优化器密钥仅由`DEEPSEEK_API_KEY`环境变量/Modal Secret提供。入口不分配GPU；本地服务沿用已有模型池管理。
清单沿用`eval.data.DataSplitManifest` v2：train=Train、cal=Cal、eval=Gate；每组覆盖CrossVid十任务、题目和声明源组互斥。
CVBench/MVU不进入优化。入口先冻结源码/评测代码/配置，再从冻结入口运行；原始rollout先保存，再按官方评分。
两库初始为空；每轮只改一个角色的一张卡，最多8张/角色。候选在完整Train、Cal上自然选卡运行，Cal严格增益最高者进入Gate，Gate严格正增益才接受。
取Train例子前先筛出含目标角色轨迹的题；完全没有该角色经验时记录跳过并继续其他角色。
Cal/Gate只向算法返回总分及身份，不向优化器提供逐题数据；视频局部反馈不冒充局部正确性标签。

```bash
python scripts/evolve_skills.py --output /runs/my-run/evolution --resume
```

resume只接受输出目录，使用原冻结配置，拒绝被改写的源码或配置。完成的API响应和整库评估可复用；缺响应的中断API尝试不自动重复。所有拒绝、格式失败及候选保留。
产物包含`manifest.json`、`frozen/`、`banks/`、`evaluations/`、`rounds/`、`judge_cache/`和`summary.json`。
接受的库可能仍为空库；运行成功与准确率提高分别报告。Prompt中文镜像见
[角色轮换Prompt](../../docs/skill-evolution-prompts.md)。

首轮完整接入实验和采样修复的证据见[实测报告](../../docs/skill-evolution-probe.md)。该轮0次接受。手工设计卡片与路由/指导诊断已实现，方案与实际测量状态见[机制检验](../../docs/manual-skill-diagnostics.md)。

### 本地优化器

角色轮换入口支持将上面的 `--optimizer-config` 换成
[`configs/skill_evolution/local_optimizer.yaml`](../../configs/skill_evolution/local_optimizer.yaml)，
配合 `configs/inference/modal_qwen35_9b_no_skill.yaml` 和对应 execution 配置。
配置使用 `api_vlm/openai_compatible` 发送纯文本，模型名为 `qwen3_5_9b_local`，
temperature=0、top_p=1、最多4096输出token；固定 `qwen35-bf16-flashinfer-sync` 服务关闭thinking。
`LOCAL_OPTIMIZER_API_KEY` 必须在运行环境中设置为非空值，不在YAML或日志中保存实际值。
无需鉴权的本地服务也应使用唯一的长随机占位值；不要使用`local`等普通词，以免通用日志脱敏替换Prompt中的同名文字。

`runtime.models` 必须含同名 `local_vllm` 模型；`execution.model_pools` 中该模型必须包含
优化器 `api_base` 对应的端口，且该模型必须已被运行时角色引用。本接入只支持复用已有角色的模型池，
不支持添加独立的optimizer专用池：原批量执行器会为每道题占用execution中的全部池，额外的小池会限制并发。
入口先复用 `prepare_model_pools` 验证并注册已有配置的全部池，
再构造优化器客户端，避免向固定服务发送不支持的 `response_format`。模型池负责既有服务检查和必要的服务启动，
因此只在已分配GPU的远端环境运行。端口不匹配、没有健康副本或缺少固定profile身份会直接报错。

本地调用复用已有grammar、seed=0、实际token和输入哈希记录；服务身份留在 `optimizer_pools.json`，
逐次请求仍在 `rounds/*/proposal-*/events.jsonl`。退出仅清理父进程的池注册，不停止服务。
商业API路径不准备本地池。本接入仅覆盖角色轮换入口，不扩展一次生成入口。

配置仍遵循现有 `max_retries: 1` 校验；现有API VLM和API LLM客户端都将它解释为首次请求后最多一次瞬时错误重试，
因此不能称为严格单次HTTP尝试。本次不改变其语义；正常成功请求只调用一次，缺响应的中断提案仍不自动重放。
远端无模型契约测试为 `PYTHONPATH=src:. python tests/test_local_optimizer.py`；真实提案还需独立验证，
这些接入检查不代表skill收益。

## 手工设计的对照卡片

`configs/manual_{global,video}.json` 保存方法、正文和适用描述三个因子；`configs/manual.py` 校验后构造运行时 `SkillBank`。正文有简短/步骤两版，适用描述有宽泛/关系/排除条件三版。`infra.banks.runtime_with_forced_card` 仅用于诊断，复用静态注入，不改变 Actor。正式整库比较继续使用自然选卡。

`eval/skill_eval/selector_probe.py` 复用真实 Selector，只测描述和编号的敏感性：

```bash
python eval/skill_eval/selector_probe.py \
  --runtime-config configs/inference/modal_qwen35_35b_a3b_no_skill.yaml \
  --execution-config /runs/my-run/execution.json \
  --cases /runs/my-run/selector_cases.json \
  --definitions src/skill_evolution/configs/manual_global.json src/skill_evolution/configs/manual_video.json \
  --output /runs/my-run/selector
```

输入数组每项为 `id/role/task/state/has_evidence`；Global 的 `task` 是问题，`state` 仅含空 `history` 与 `videos={video_id:{duration_sec:...}}`；Video 的 `task` 是本次 instruction，`state` 只能含空 `history`。不得向 Video Selector 加入 Global 问题、其他视频或私有记忆。输出保留原始请求和选择事件；选中率不能代替最终准确率。

补充的 `configs/manual_watch_first_bank.json` 已是 schema3 单卡库，不属于上面的因子定义格式；它用于单独验证明确 watch-first 行动策略，中文镜像见[联合观看优先](../../docs/manual-watch-first-skills-zh.md)。原矩阵不随它改变。

保留原指令范围的单Video实验卡见[卡片与完整中文镜像](../../docs/manual-video-scope-skill.md)；它是手工控制条件，默认配置不启用，不能作为进化算法的收益证据。
