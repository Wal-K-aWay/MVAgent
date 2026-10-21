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

密钥仅由`DEEPSEEK_API_KEY`环境变量/Modal Secret提供。入口不会分配GPU或启动模型服务。
清单沿用`eval.data.DataSplitManifest` v2：train=Train、cal=Cal、eval=Gate；每组覆盖CrossVid十任务、题目和声明源组互斥。
CVBench/MVU不进入优化。入口先冻结源码/评测代码/配置，再从冻结入口运行；原始rollout先保存，再按官方评分。
两库初始为空；每轮只改一个角色的一张卡，最多8张/角色。候选在完整Train、Cal上自然选卡运行，Cal严格增益最高者进入Gate，Gate严格正增益才接受。
Cal/Gate只向算法返回总分及身份，不向优化器提供逐题数据；视频局部反馈不冒充局部正确性标签。

```bash
python scripts/evolve_skills.py --output /runs/my-run/evolution --resume
```

resume只接受输出目录，使用原冻结配置，拒绝被改写的源码或配置。完成的API响应和整库评估可复用；缺响应的中断API尝试不自动重复。所有拒绝、格式失败及候选保留。
产物包含`manifest.json`、`frozen/`、`banks/`、`evaluations/`、`rounds/`、`judge_cache/`和`summary.json`。
接受的库可能仍为空库；运行成功与准确率提高分别报告。Prompt中文镜像见
[角色轮换Prompt](../../docs/skill-evolution-prompts.md)。
